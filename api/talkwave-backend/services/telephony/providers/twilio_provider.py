"""
Twilio implementation of the TelephonyProvider interface.
"""

import json
import random
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from loguru import logger
from twilio.request_validator import RequestValidator

from api.enums import WorkflowRunMode
from api.services.telephony.base import CallInitiationResult, SharedHTTPSession, TelephonyError, TelephonyProvider
from api.utils.tunnel import TunnelURLProvider

if TYPE_CHECKING:
    from fastapi import WebSocket


class TwilioProvider(TelephonyProvider):
    """
    Twilio implementation of TelephonyProvider.
    Accepts configuration and works the same regardless of OSS/SaaS mode.
    """

    PROVIDER_NAME = WorkflowRunMode.TWILIO.value
    WEBHOOK_ENDPOINT = "twiml"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize TwilioProvider with configuration.

        Args:
            config: Dictionary containing:
                - account_sid: Twilio Account SID
                - auth_token: Twilio Auth Token
                - from_numbers: List of phone numbers to use
        """
        self.config = config  # Store full config for passing to transport
        self.account_sid = config.get("account_sid")
        self.auth_token = config.get("auth_token")
        self.from_numbers = config.get("from_numbers", [])

        # Handle both single number (string) and multiple numbers (list)
        if isinstance(self.from_numbers, str):
            self.from_numbers = [self.from_numbers]

        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"

    async def initiate_call(
        self,
        to_number: str,
        webhook_url: str,
        workflow_run_id: Optional[int] = None,
        **kwargs: Any,
    ) -> CallInitiationResult:
        """
        Initiate an outbound call via Twilio.
        """
        if not self.validate_config():
            raise ValueError("Twilio provider not properly configured")

        endpoint = f"{self.base_url}/Calls.json"

        # Select a random phone number
        from_number = random.choice(self.from_numbers)
        logger.info(f"Selected phone number {from_number} for outbound call")

        # Prepare call data
        data = {"To": to_number, "From": from_number, "Url": webhook_url}

        # Add status callback if workflow_run_id provided
        if workflow_run_id:
            backend_endpoint = await TunnelURLProvider.get_tunnel_url()
            callback_url = f"https://{backend_endpoint}/api/v1/telephony/twilio/status-callback/{workflow_run_id}"
            data.update(
                {
                    "StatusCallback": callback_url,
                    "StatusCallbackEvent": [
                        "initiated",
                        "ringing",
                        "answered",
                        "completed",
                    ],
                    "StatusCallbackMethod": "POST",
                }
            )

        data.update(kwargs)

        import aiohttp
        session = SharedHTTPSession.get()
        auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
        async with session.post(endpoint, data=data, auth=auth) as response:
            if response.status != 201:
                error_data = await response.json()
                raise TelephonyError.from_twilio_error(error_data)

            response_data = await response.json()

            return CallInitiationResult(
                call_id=response_data["sid"],
                status=response_data.get("status", "queued"),
                provider_metadata={},
                raw_response=response_data,
            )

    async def get_call_status(self, call_id: str) -> Dict[str, Any]:
        """
        Get the current status of a Twilio call.
        """
        if not self.validate_config():
            raise ValueError("Twilio provider not properly configured")

        endpoint = f"{self.base_url}/Calls/{call_id}.json"

        import aiohttp
        session = SharedHTTPSession.get()
        auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
        async with session.get(endpoint, auth=auth) as response:
            if response.status != 200:
                error_data = await response.json()
                raise Exception(f"Failed to get call status: {error_data}")

            return await response.json()

    async def get_available_phone_numbers(self) -> List[str]:
        """
        Get list of available Twilio phone numbers.
        """
        return self.from_numbers

    def validate_config(self) -> bool:
        """
        Validate Twilio configuration.
        """
        return bool(self.account_sid and self.auth_token and self.from_numbers)

    async def verify_webhook_signature(
        self, url: str, params: Dict[str, Any], signature: str
    ) -> bool:
        """
        Verify Twilio webhook signature for security.
        """
        if not self.auth_token:
            logger.error("No auth token available for webhook signature verification")
            return False

        validator = RequestValidator(self.auth_token)
        return validator.validate(url, params, signature)

    async def get_webhook_response(
        self,
        workflow_id: int,
        user_id: int,
        workflow_run_id: int,
        connection_greeting: str | None = None,
        greeting_audio_url: str | None = None,
    ) -> str:
        """Generate TwiML response for starting a call session.

        If a greeting audio URL is provided the greeting is played via
        ``<Play>`` *before* the ``<Connect><Stream>`` — no ``<Gather>``
        wrapper so Twilio won't cut the audio on background noise.
        Interruption is handled natively by the Pipecat pipeline once the
        stream connects.
        """
        backend_endpoint = await TunnelURLProvider.get_tunnel_url()

        if backend_endpoint.startswith("https://"):
            backend_endpoint = backend_endpoint[len("https://"):]
        elif backend_endpoint.startswith("http://"):
            backend_endpoint = backend_endpoint[len("http://"):]

        parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<Response>']

        if greeting_audio_url:
            safe_url = xml_escape(greeting_audio_url)
            parts.append(f"    <Play>{safe_url}</Play>")

        from api.services.security.ws_ticket import generate_ws_ticket

        ticket = generate_ws_ticket(workflow_id, user_id, workflow_run_id)
        parts.append(
            f'    <Connect>\n'
            f'        <Stream url="wss://{backend_endpoint}/api/v1/telephony/ws/'
            f'{workflow_id}/{user_id}/{workflow_run_id}?ticket={ticket}"></Stream>\n'
            f'    </Connect>'
        )
        parts.append('    <Pause length="40"/>')
        parts.append("</Response>")

        return "\n".join(parts)

    async def get_call_cost(self, call_id: str) -> Dict[str, Any]:
        """
        Get cost information for a completed Twilio call.

        Args:
            call_id: The Twilio Call SID

        Returns:
            Dict containing cost information
        """
        endpoint = f"{self.base_url}/Calls/{call_id}.json"

        try:
            import aiohttp
            session = SharedHTTPSession.get()
            auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
            async with session.get(endpoint, auth=auth) as response:
                if response.status != 200:
                    error_data = await response.json()
                    logger.error(f"Failed to get Twilio call cost: {error_data}")
                    return {
                        "cost_usd": 0.0,
                        "duration": 0,
                        "status": "error",
                        "error": str(error_data),
                    }

                call_data = await response.json()

                price_str = call_data.get("price", "0")
                cost_usd = abs(float(price_str)) if price_str else 0.0

                duration = int(call_data.get("duration", "0"))

                return {
                    "cost_usd": cost_usd,
                    "duration": duration,
                    "status": call_data.get("status", "unknown"),
                    "price_unit": call_data.get("price_unit", "USD"),
                    "raw_response": call_data,
                }

        except Exception as e:
            logger.error(f"Exception fetching Twilio call cost: {e}")
            return {"cost_usd": 0.0, "duration": 0, "status": "error", "error": str(e)}

    def parse_status_callback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Twilio status callback data into generic format.
        """
        return {
            "call_id": data.get("CallSid", ""),
            "status": data.get("CallStatus", ""),
            "from_number": data.get("From"),
            "to_number": data.get("To"),
            "direction": data.get("Direction"),
            "duration": data.get("CallDuration") or data.get("Duration"),
            "extra": data,  # Include all original data
        }

    async def handle_websocket(
        self,
        websocket: "WebSocket",
        workflow_id: int,
        user_id: int,
        workflow_run_id: int,
        workflow=None,
        workflow_run=None,
        user_config=None,
    ) -> None:
        """
        Handle Twilio-specific WebSocket connection.

        Twilio sends:
        1. "connected" event first
        2. "start" event with streamSid and callSid
        3. Then audio messages
        """
        import time as _time
        from api.services.pipecat.run_pipeline import run_pipeline_twilio

        _twilio_t0 = _time.perf_counter()
        try:
            first_msg = await websocket.receive_text()
            msg = json.loads(first_msg)

            if msg.get("event") != "connected":
                logger.error(f"Expected 'connected' event, got: {msg.get('event')}")
                await websocket.close(code=4400, reason="Expected connected event")
                return

            _twilio_t_connected = _time.perf_counter()
            logger.info(
                f"⏱ [LATENCY] Twilio 'connected' event | run_id={workflow_run_id} | "
                f"wait={(_twilio_t_connected - _twilio_t0)*1000:.0f}ms"
            )

            start_msg = await websocket.receive_text()
            start_msg = json.loads(start_msg)
            if start_msg.get("event") != "start":
                logger.error("Expected 'start' event second")
                await websocket.close(code=4400, reason="Expected start event")
                return

            _twilio_t_start = _time.perf_counter()
            logger.info(
                f"⏱ [LATENCY] Twilio 'start' event | run_id={workflow_run_id} | "
                f"wait={(_twilio_t_start - _twilio_t_connected)*1000:.0f}ms | "
                f"total_handshake={(_twilio_t_start - _twilio_t0)*1000:.0f}ms"
            )

            try:
                stream_sid = start_msg["start"]["streamSid"]
                call_sid = start_msg["start"]["callSid"]
            except KeyError:
                logger.error("Missing streamSid or callSid in start message")
                await websocket.close(code=4400, reason="Missing stream identifiers")
                return

            logger.info(
                f"⏱ [LATENCY] Starting pipeline | run_id={workflow_run_id} | "
                f"since_twilio_handler={(_time.perf_counter() - _twilio_t0)*1000:.0f}ms"
            )
            await run_pipeline_twilio(
                websocket, stream_sid, call_sid, workflow_id, workflow_run_id, user_id,
                workflow=workflow, workflow_run=workflow_run,
                telephony_config=self.config,
                user_config=user_config,
            )

        except Exception as e:
            logger.error(f"Error in Twilio WebSocket handler: {e}")
            raise
