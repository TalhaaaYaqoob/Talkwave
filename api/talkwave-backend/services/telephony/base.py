"""
Base telephony provider interface for abstracting telephony services.
This allows easy switching between different providers (Twilio, Vonage, etc.)
while keeping business logic decoupled from specific implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import aiohttp
from loguru import logger

if TYPE_CHECKING:
    from fastapi import WebSocket


class SharedHTTPSession:
    """Process-wide shared aiohttp session with connection pooling.

    Using a single session across all telephony API calls avoids the overhead
    of creating a new TCP connection (and TLS handshake) for every request.
    The connector limits total connections to ``limit`` to prevent exhaustion.
    """

    _session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def get(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            connector = aiohttp.TCPConnector(
                limit=200,
                limit_per_host=50,
                ttl_dns_cache=300,
                keepalive_timeout=30,
            )
            cls._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return cls._session

    @classmethod
    async def close(cls) -> None:
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None
            logger.info("Shared HTTP session closed")


# Mapping of Twilio error codes to user-friendly messages
TWILIO_ERROR_MESSAGES = {
    21215: "Your Twilio account is not authorized to call this country. Please enable international permissions in your Twilio Console under Voice → Settings → Geo Permissions.",
    21214: "Invalid destination phone number. Please check the number format.",
    21211: "Invalid 'To' phone number format.",
    21212: "Invalid 'From' phone number. The number is not a valid Twilio phone number.",
    21217: "Phone number is not verified. Please verify this number in your Twilio Console.",
    21219: "The 'To' phone number is not currently reachable.",
    21401: "Invalid phone number. Please check if the number exists.",
    21407: "This phone number is not owned by your Twilio account.",
    21606: "The 'From' phone number is not enabled for SMS or Voice.",
    21608: "Unverified phone number. Add and verify this number in Twilio Console.",
    21614: "'To' number is not a valid mobile number.",
    21610: "Message cannot be sent to this number (blacklisted or blocked).",
    20003: "Twilio authentication failed. Please check your Account SID and Auth Token.",
    20404: "The requested resource was not found.",
    20429: "Too many requests. Please try again later.",
}


class TelephonyError(Exception):
    """Custom exception for telephony-related errors with user-friendly messages."""
    
    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        user_message: Optional[str] = None,
        provider: str = "unknown",
        raw_error: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.provider = provider
        self.raw_error = raw_error or {}
        
        # Get user-friendly message based on error code
        if user_message:
            self.user_message = user_message
        elif code and code in TWILIO_ERROR_MESSAGES:
            self.user_message = TWILIO_ERROR_MESSAGES[code]
        else:
            self.user_message = message
        
        super().__init__(self.user_message)
    
    @classmethod
    def from_twilio_error(cls, error_data: Dict[str, Any]) -> "TelephonyError":
        """Create a TelephonyError from Twilio API error response."""
        code = error_data.get("code")
        message = error_data.get("message", "Unknown Twilio error")
        
        return cls(
            message=message,
            code=code,
            provider="twilio",
            raw_error=error_data,
        )


@dataclass
class CallInitiationResult:
    """Standardized response from initiate_call across all providers."""

    call_id: str  # Provider's call identifier (SID for Twilio, UUID for Vonage)
    status: str  # Initial status (e.g., "queued", "initiated", "started")
    provider_metadata: Dict[str, Any] = field(
        default_factory=dict
    )  # Data that needs to be persisted
    raw_response: Dict[str, Any] = field(
        default_factory=dict
    )  # Full provider response for debugging


class TelephonyProvider(ABC):
    """
    Abstract base class for telephony providers.
    All telephony providers must implement these core methods.
    """

    PROVIDER_NAME = None
    WEBHOOK_ENDPOINT = None

    @abstractmethod
    async def initiate_call(
        self,
        to_number: str,
        webhook_url: str,
        workflow_run_id: Optional[int] = None,
        **kwargs: Any,
    ) -> CallInitiationResult:
        """
        Initiate an outbound call.

        Args:
            to_number: The destination phone number
            webhook_url: The URL to receive call events
            workflow_run_id: Optional workflow run ID for tracking
            **kwargs: Provider-specific additional parameters

        Returns:
            CallInitiationResult with standardized call details
        """
        pass

    @abstractmethod
    async def get_call_status(self, call_id: str) -> Dict[str, Any]:
        """
        Get the current status of a call.

        Args:
            call_id: The provider-specific call identifier

        Returns:
            Dict containing call status information
        """
        pass

    @abstractmethod
    async def get_available_phone_numbers(self) -> List[str]:
        """
        Get list of available phone numbers for this provider.

        Returns:
            List of phone numbers that can be used for outbound calls
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """
        Validate that the provider is properly configured.

        Returns:
            True if configuration is valid, False otherwise
        """
        pass

    @abstractmethod
    async def verify_webhook_signature(
        self, url: str, params: Dict[str, Any], signature: str
    ) -> bool:
        """
        Verify webhook signature for security.

        Args:
            url: The webhook URL
            params: The webhook parameters
            signature: The signature to verify

        Returns:
            True if signature is valid, False otherwise
        """
        pass

    @abstractmethod
    async def get_webhook_response(
        self,
        workflow_id: int,
        user_id: int,
        workflow_run_id: int,
        connection_greeting: str | None = None,
        greeting_audio_url: str | None = None,
    ) -> str:
        """
        Generate the initial webhook response for starting a call session.

        Args:
            workflow_id: The workflow ID
            user_id: The user ID
            workflow_run_id: The workflow run ID
            connection_greeting: Optional brief text played instantly at call
                connection (before the WebSocket pipeline starts).
                Used as ``<Say>`` fallback when *greeting_audio_url* is absent.
            greeting_audio_url: Optional URL to a pre-generated TTS audio
                file (MP3).  When provided the TwiML uses ``<Play>`` instead
                of ``<Say>`` so the greeting matches the configured AI voice.

        Returns:
            Provider-specific response (e.g., TwiML for Twilio)
        """
        pass

    @abstractmethod
    async def get_call_cost(self, call_id: str) -> Dict[str, Any]:
        """
        Get cost information for a completed call.

        Args:
            call_id: Provider-specific call identifier (SID for Twilio, UUID for Vonage)

        Returns:
            Dict containing:
                - cost_usd: The cost in USD as float
                - duration: Call duration in seconds
                - status: Call completion status
                - raw_response: Full provider response for debugging
        """
        pass

    @abstractmethod
    def parse_status_callback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse provider-specific status callback data into generic format.

        Args:
            data: Raw callback data from the provider

        Returns:
            Dict with standardized fields:
                - call_id: Provider's call identifier
                - status: Standardized status (completed, failed, busy, etc.)
                - from_number: Optional caller number
                - to_number: Optional recipient number
                - duration: Optional call duration
                - extra: Provider-specific additional data
        """
        pass

    @abstractmethod
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
        Handle provider-specific WebSocket connection for real-time call audio.

        This method encapsulates all provider-specific WebSocket handshake and
        message routing logic, keeping the main websocket endpoint clean.

        Args:
            websocket: The WebSocket connection
            workflow_id: The workflow ID
            user_id: The user ID
            workflow_run_id: The workflow run ID
            workflow: Pre-fetched workflow object (optional, avoids re-fetch)
            workflow_run: Pre-fetched workflow run object (optional, avoids re-fetch)
        """
        pass
