"""
Generic telephony routes that work with any telephony provider.
"""

import json
import random
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket
from loguru import logger
from pydantic import BaseModel
from starlette.responses import HTMLResponse, Response

from api.db import db_client
from api.db.models import UserModel
from api.enums import WorkflowRunState
from api.services.auth.depends import get_user
from api.services.campaign.call_dispatcher import campaign_call_dispatcher
from api.services.campaign.campaign_event_publisher import get_campaign_event_publisher
from api.services.security.rate_limiter import limiter, RateLimitTiers
from api.services.subscription.subscription_service import SubscriptionService
from api.services.telephony.base import TelephonyError
from api.services.telephony.factory import get_telephony_provider
from api.utils.tunnel import TunnelURLProvider
from pipecat.utils.context import set_current_run_id

router = APIRouter(prefix="/telephony")

# NOTE: A previous implementation cached inbound-call setup data in Redis using
# Python ``pickle``. Unpickling attacker-controlled bytes is a remote-code-
# execution risk if Redis is ever compromised or reachable, so that cache has
# been removed. The WebSocket handler now always re-fetches the (small) setup
# data from the database using the trusted primary keys in the URL.

# Subscription service for usage checks
_sub_service = SubscriptionService()


async def _verify_twilio_signature(
    request: Request, provider, signature: Optional[str], form_dict: dict
) -> bool:
    """Verify a Twilio webhook signature for the current request.

    Returns False (fail closed) when the signature header is missing or the
    provider cannot validate it.
    """
    if not signature:
        return False
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    full_url = f"{proto}://{host}{request.url.path}"
    if request.url.query:
        full_url += f"?{request.url.query}"
    try:
        return await provider.verify_webhook_signature(
            url=full_url, params=form_dict, signature=signature
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[TELEPHONY] Signature verification error: {e}")
        return False


_UNAUTHORIZED_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response><Say>Unauthorized request.</Say><Hangup/></Response>"
)

GEMINI_DEFAULT_VOICE_ID = "Kore"
CARTESIA_DEFAULT_VOICE_ID = "f786b574-daa5-4673-aa0c-cbe3e8534c02"  # Katie

import time as _time

# Pre-built TwiML cache: workflow_run_id → (XML string, timestamp).
# Entries older than _TWIML_TTL seconds are cleaned up periodically
# to prevent leaks from calls that never reach the /twiml callback.
_PREBUILT_TWIML: dict[int, tuple[str, float]] = {}
_TWIML_TTL = 300  # 5 minutes


def _twiml_put(workflow_run_id: int, twiml: str) -> None:
    _PREBUILT_TWIML[workflow_run_id] = (twiml, _time.time())


def _twiml_pop(workflow_run_id: int) -> str | None:
    entry = _PREBUILT_TWIML.pop(workflow_run_id, None)
    if entry is None:
        return None
    return entry[0]


def _twiml_cleanup() -> None:
    """Remove stale TwiML entries older than _TWIML_TTL."""
    now = _time.time()
    stale_keys = [k for k, (_, ts) in _PREBUILT_TWIML.items() if now - ts > _TWIML_TTL]
    for k in stale_keys:
        _PREBUILT_TWIML.pop(k, None)


def _extract_spoken_greeting(prompt_text: str) -> str:
    """Extract the spoken greeting from a start-node prompt.

    Prompts typically start with a greeting paragraph followed by system
    instructions separated by blank lines.  We take the first paragraph
    (up to the first ``\\n\\n``) and cap it at 150 chars for a short greeting.
    """
    first_paragraph = prompt_text.split("\n\n")[0].strip()
    if len(first_paragraph) > 150:
        last_space = first_paragraph[:150].rfind(" ")
        if last_space > 80:
            first_paragraph = first_paragraph[:last_space] + "..."
        else:
            first_paragraph = first_paragraph[:147] + "..."
    return first_paragraph


def _extract_greeting_and_voice(workflow) -> tuple[str | None, str | None, str, str, str | None, str]:
    """Return greeting metadata for the configured TTS provider.

    Returns a tuple of
    ``(connection_greeting, tts_voice_id, voice_mode, tts_provider,
       workflow_language, cartesia_model)``.

    ``tts_provider`` is Gemini for every language, so the pre-rendered greeting
    matches the accent the agent speaks with. Cartesia is used only when the
    workflow explicitly asks for it.
    """
    connection_greeting = None
    tts_voice_id = None
    voice_mode = "standard"
    tts_provider = "gemini"
    workflow_language = "English"
    cartesia_model = "sonic-3.5"

    if workflow is None:
        return (
            connection_greeting, tts_voice_id, voice_mode,
            tts_provider, workflow_language, cartesia_model,
        )

    if workflow.workflow_configurations:
        cfg = workflow.workflow_configurations
        tts_voice_id = cfg.get("tts_voice_id")
        voice_mode = cfg.get("voice_mode", "standard")
        workflow_language = cfg.get("workflow_language", "English")
        cartesia_model = cfg.get("tts_cartesia_model", "sonic-3.5")

        # Legacy configs may still say "elevenlabs"; those fall through to Gemini.
        tts_provider = "cartesia" if cfg.get("tts_provider") == "cartesia" else "gemini"

    if not tts_voice_id:
        tts_voice_id = (
            CARTESIA_DEFAULT_VOICE_ID
            if tts_provider == "cartesia"
            else GEMINI_DEFAULT_VOICE_ID
        )

    try:
        wf_def = workflow.workflow_definition
        if isinstance(wf_def, str):
            wf_def = json.loads(wf_def)
        if wf_def:
            for node in wf_def.get("nodes", []):
                nd = node.get("data", {})
                if nd.get("is_start") or node.get("type") == "startCall":
                    raw_prompt = (nd.get("prompt") or "").strip()
                    if raw_prompt:
                        connection_greeting = _extract_spoken_greeting(raw_prompt)
                    break
    except Exception as e:
        logger.warning(f"Could not extract greeting prompt from workflow: {e}")

    return (
        connection_greeting, tts_voice_id, voice_mode,
        tts_provider, workflow_language, cartesia_model,
    )


async def _build_greeting_audio_url(
    workflow_id: int,
    connection_greeting: str,
    tts_voice_id: str,
    tts_provider: str = "gemini",
    workflow_language: str | None = None,
    cartesia_model: str = "sonic-3.5",
    accent_id: str | None = None,
) -> str | None:
    """Ensure greeting audio exists in Supabase Storage and return its public URL.

    The returned URL points directly to the Supabase CDN so Twilio can
    fetch the audio without hitting our backend.  Falls back to our own
    ``/greeting-audio/`` endpoint if Supabase upload fails.

    Returns ``None`` if both paths fail (no greeting will be played).
    """
    from api.services.telephony.greeting_audio import ensure_greeting_audio

    try:
        url = await ensure_greeting_audio(
            workflow_id,
            connection_greeting,
            tts_voice_id,
            provider=tts_provider,  # type: ignore[arg-type]
            workflow_language=workflow_language,
            cartesia_model=cartesia_model,
            accent_id=accent_id,
        )
        if url:
            return url
    except Exception as e:
        logger.warning(f"[GREETING-AUDIO] ensure_greeting_audio failed: {e}")

    # Fallback: point Twilio at our own endpoint which generates on the fly.
    try:
        backend_endpoint = await TunnelURLProvider.get_tunnel_url()
        if not backend_endpoint.startswith("http"):
            backend_endpoint = f"https://{backend_endpoint}"
        return f"{backend_endpoint}/api/v1/telephony/greeting-audio/{workflow_id}"
    except Exception:
        return None


def _prebuild_twiml_for_outbound(
    backend_host: str,
    workflow_id: int,
    user_id: int,
    workflow_run_id: int,
    greeting_audio_url: str | None = None,
) -> None:
    """Pre-build TwiML XML and cache it by *workflow_run_id*.

    Called during ``initiate_call`` so the ``/twiml`` callback from Twilio
    can return a pure in-memory lookup with **zero** DB queries.

    When *greeting_audio_url* is provided the TwiML plays the pre-recorded
    greeting via ``<Play>`` before opening the ``<Stream>``.  Twilio finishes
    the audio first, giving the pipeline time to warm up in the background.
    """
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<Response>']

    if greeting_audio_url:
        parts.append(f'    <Play>{greeting_audio_url}</Play>')

    from api.services.security.ws_ticket import generate_ws_ticket

    ticket = generate_ws_ticket(workflow_id, user_id, workflow_run_id)
    parts.append(
        f'    <Connect>\n'
        f'        <Stream url="wss://{backend_host}/api/v1/telephony/ws/'
        f'{workflow_id}/{user_id}/{workflow_run_id}?ticket={ticket}"></Stream>\n'
        f'    </Connect>'
    )
    parts.append('    <Pause length="40"/>')
    parts.append("</Response>")

    twiml = "\n".join(parts)
    _twiml_put(workflow_run_id, twiml)
    logger.info(
        f"[OUTBOUND] Pre-built TwiML cached | "
        f"run_id={workflow_run_id}, greeting_audio={bool(greeting_audio_url)}, "
        f"twiml_size={len(twiml)}"
    )


class InitiateCallRequest(BaseModel):
    workflow_id: int
    workflow_run_id: int | None = None
    phone_number: str | None = None


class StatusCallbackRequest(BaseModel):
    """Generic status callback that can handle different providers"""

    # Common fields
    call_id: str
    status: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    direction: Optional[str] = None
    duration: Optional[str] = None

    # Provider-specific fields stored as extra
    extra: dict = {}

    @classmethod
    def from_twilio(cls, data: dict):
        """Convert Twilio callback to generic format"""
        return cls(
            call_id=data.get("CallSid", ""),
            status=data.get("CallStatus", ""),
            from_number=data.get("From"),
            to_number=data.get("To"),
            direction=data.get("Direction"),
            duration=data.get("CallDuration") or data.get("Duration"),
            extra=data,
        )

    @classmethod
    def from_vonage(cls, data: dict):
        """Convert Vonage event to generic format"""
        # Map Vonage status to common format
        status_map = {
            "started": "initiated",
            "ringing": "ringing",
            "answered": "answered",
            "complete": "completed",
            "failed": "failed",
            "busy": "busy",
            "timeout": "no-answer",
            "rejected": "busy",
        }

        return cls(
            call_id=data.get("uuid", ""),
            status=status_map.get(data.get("status", ""), data.get("status", "")),
            from_number=data.get("from"),
            to_number=data.get("to"),
            direction=data.get("direction"),
            duration=data.get("duration"),
            extra=data,
        )


@router.post("/initiate-call")
@limiter.limit(RateLimitTiers.CRITICAL)  # Critical for calling operations
async def initiate_call(
    request: Request,
    call_request: InitiateCallRequest,
    user: UserModel = Depends(get_user),
):
    """Initiate a call using the configured telephony provider."""

    logger.info(
        f"[OUTBOUND] initiate_call started | user_id={user.id}, org_id={user.selected_organization_id}, "
        f"workflow_id={call_request.workflow_id}, phone={call_request.phone_number}, "
        f"existing_run_id={call_request.workflow_run_id}"
    )

    # Check subscription allows making calls
    can_call = await _sub_service.check_can_make_call(user.selected_organization_id)
    logger.debug(f"[OUTBOUND] Subscription check result: {can_call}")
    if not can_call["allowed"]:
        logger.warning(
            f"[OUTBOUND] Subscription limit blocked call | org_id={user.selected_organization_id}, "
            f"reason={can_call['reason']}"
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_call["reason"],
                "message": can_call.get("message", "Subscription limit reached"),
            },
        )

    # Get the telephony provider for the organization
    provider = await get_telephony_provider(user.selected_organization_id)
    logger.info(
        f"[OUTBOUND] Provider loaded | provider={provider.PROVIDER_NAME}, "
        f"webhook_endpoint={provider.WEBHOOK_ENDPOINT}, config_valid={provider.validate_config()}"
    )

    # Validate provider is configured
    if not provider.validate_config():
        logger.error(
            f"[OUTBOUND] Provider not configured | org_id={user.selected_organization_id}, "
            f"provider={provider.PROVIDER_NAME}"
        )
        raise HTTPException(
            status_code=400,
            detail="telephony_not_configured",
        )

    # Determine the workflow run mode based on provider type
    workflow_run_mode = provider.PROVIDER_NAME

    user_configuration = await db_client.get_user_configurations(user.id)

    phone_number = call_request.phone_number or user_configuration.test_phone_number

    if not phone_number:
        logger.error(f"[OUTBOUND] No phone number provided and none in user config | user_id={user.id}")
        raise HTTPException(
            status_code=400,
            detail="Phone number must be provided in request or set in user configuration",
        )

    logger.debug(f"[OUTBOUND] Target phone: {phone_number}")

    workflow_run_id = call_request.workflow_run_id

    if not workflow_run_id:
        workflow_run_name = f"WR-TEL-{random.randint(1000, 9999)}"
        workflow_run = await db_client.create_workflow_run(
            workflow_run_name,
            call_request.workflow_id,
            workflow_run_mode,
            initial_context={
                "phone_number": phone_number,
            },
            user_id=user.id,
        )
        workflow_run_id = workflow_run.id
        logger.info(
            f"[OUTBOUND] Created new workflow run | run_id={workflow_run_id}, "
            f"name={workflow_run_name}, mode={workflow_run_mode}"
        )
    else:
        workflow_run = await db_client.get_workflow_run(workflow_run_id, user.id)
        if not workflow_run:
            logger.error(f"[OUTBOUND] Existing workflow run not found | run_id={workflow_run_id}")
            raise HTTPException(status_code=400, detail="Workflow run not found")
        workflow_run_name = workflow_run.name
        logger.info(f"[OUTBOUND] Using existing workflow run | run_id={workflow_run_id}, name={workflow_run_name}")

    # Construct webhook URL based on provider type
    backend_endpoint = await TunnelURLProvider.get_tunnel_url()
    logger.debug(f"[OUTBOUND] Backend tunnel URL: {backend_endpoint}")
    
    # Remove protocol if present (we'll add it ourselves)
    if backend_endpoint.startswith("https://"):
        backend_endpoint = backend_endpoint[8:]
    elif backend_endpoint.startswith("http://"):
        backend_endpoint = backend_endpoint[7:]

    webhook_endpoint = provider.WEBHOOK_ENDPOINT

    # Fetch workflow to extract greeting audio for <Play>.
    workflow = await db_client.get_workflow_by_id(call_request.workflow_id)
    greeting_audio_url: str | None = None
    if workflow:
        (
            connection_greeting,
            tts_voice_id,
            _voice_mode,
            tts_provider,
            workflow_language,
            cartesia_model,
        ) = _extract_greeting_and_voice(workflow)
        # Verify subscription allows Gemini S2S before trusting the voice_mode config
        if _voice_mode == "realtime":
            try:
                from api.services.subscription import shared_subscription_service
                from api.services.subscription.plans import get_plan
                _sub = await shared_subscription_service.get_or_create_subscription(user.selected_organization_id)
                _plan_features = get_plan(_sub.plan)
                if not _plan_features.gemini_s2s_enabled:
                    logger.warning(
                        f"[OUTBOUND] voice_mode=realtime but plan '{_sub.plan}' does NOT include "
                        f"Gemini S2S — treating as standard mode | workflow_id={call_request.workflow_id}"
                    )
                    _voice_mode = "standard"
                else:
                    logger.info(
                        f"[OUTBOUND] plan '{_sub.plan}' confirmed Gemini S2S ✓ | "
                        f"workflow_id={call_request.workflow_id}"
                    )
            except Exception as e:
                logger.warning(f"[OUTBOUND] Subscription check failed, treating as standard: {e}")
                _voice_mode = "standard"
        if _voice_mode == "realtime":
            logger.info(
                f"[OUTBOUND] Realtime (Gemini Live) mode - skipping TwiML greeting audio. "
                f"Gemini will handle greeting natively | workflow_id={call_request.workflow_id}"
            )
        elif connection_greeting and tts_voice_id:
            try:
                greeting_audio_url = await _build_greeting_audio_url(
                    call_request.workflow_id,
                    connection_greeting,
                    tts_voice_id,
                    tts_provider=tts_provider,
                    workflow_language=workflow_language,
                    cartesia_model=cartesia_model,
                    accent_id=(workflow.workflow_configurations or {}).get("tts_accent") or None,
                )
            except Exception as e:
                logger.warning(f"[OUTBOUND] Greeting audio build failed (non-fatal): {e}")

    from urllib.parse import quote

    webhook_url = (
        f"https://{backend_endpoint}/api/v1/telephony/{webhook_endpoint}"
        f"?workflow_id={call_request.workflow_id}"
        f"&user_id={user.id}"
        f"&workflow_run_id={workflow_run_id}"
        f"&organization_id={user.selected_organization_id}"
    )
    if greeting_audio_url:
        webhook_url += f"&greeting_audio_url={quote(greeting_audio_url, safe='')}"

    logger.info(f"[OUTBOUND] Webhook URL constructed: {webhook_url}")

    try:
        _prebuild_twiml_for_outbound(
            backend_endpoint,
            call_request.workflow_id,
            user.id,
            workflow_run_id,
            greeting_audio_url=greeting_audio_url,
        )
    except Exception as e:
        logger.warning(f"[OUTBOUND] TwiML pre-build failed (non-fatal): {e}")

    # Initiate call via provider
    try:
        logger.info(
            f"[OUTBOUND] Calling provider.initiate_call | to={phone_number}, "
            f"provider={provider.PROVIDER_NAME}, run_id={workflow_run_id}"
        )
        result = await provider.initiate_call(
            to_number=phone_number,
            webhook_url=webhook_url,
            workflow_run_id=workflow_run_id,
        )
        logger.info(
            f"[OUTBOUND] Call initiated successfully | call_id={result.call_id}, "
            f"status={result.status}, run_id={workflow_run_id}"
        )
        
    except TelephonyError as e:
        logger.error(
            f"[OUTBOUND] Telephony error | message={e.message}, code={e.code}, "
            f"provider={e.provider}, user_message={e.user_message}"
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "call_initiation_failed",
                "message": e.user_message,
                "code": e.code,
                "provider": e.provider,
            },
        )
    except Exception as e:
        logger.error(f"[OUTBOUND] Unexpected error initiating call: {type(e).__name__}: {e}")
        raise

    # Store provider type and any provider-specific metadata in workflow run context
    gathered_context = {
        "provider": provider.PROVIDER_NAME,
        "call_direction": "outbound",
        "greeting_played_by_provider": bool(greeting_audio_url),
        **(result.provider_metadata or {}),
    }
    await db_client.update_workflow_run(
        run_id=workflow_run_id, gathered_context=gathered_context
    )
    logger.info(
        f"[OUTBOUND] Stored gathered_context | run_id={workflow_run_id}, "
        f"provider={provider.PROVIDER_NAME}, call_id={result.call_id}, "
        f"greeting_played={bool(greeting_audio_url)}"
    )

    return {"message": f"Call initiated successfully with run name {workflow_run_name}"}


@router.post("/twiml", include_in_schema=False)
async def handle_twiml_webhook(
    request: Request,
    workflow_id: int,
    user_id: int,
    workflow_run_id: int,
    organization_id: int,
    greeting_audio_url: str | None = None,
    x_twilio_signature: Optional[str] = Header(None),
):
    """
    Handle initial webhook from telephony provider (outbound calls).
    Returns provider-specific response (e.g., TwiML for Twilio).
    """

    logger.info(
        f"[OUTBOUND-TWIML] TwiML webhook hit | workflow_id={workflow_id}, user_id={user_id}, "
        f"run_id={workflow_run_id}, org_id={organization_id}, "
        f"greeting_audio_url={'yes' if greeting_audio_url else 'no'}"
    )

    provider = await get_telephony_provider(organization_id)

    # This endpoint returns TwiML that includes a signed media ticket, so it
    # must only ever be served to the telephony provider. Verify the Twilio
    # signature and fail closed otherwise.
    form_dict = dict(await request.form())
    if not await _verify_twilio_signature(
        request, provider, x_twilio_signature, form_dict
    ):
        logger.warning(
            f"[OUTBOUND-TWIML] REJECTED - invalid/missing Twilio signature | "
            f"run_id={workflow_run_id}"
        )
        return HTMLResponse(
            content=_UNAUTHORIZED_TWIML, media_type="application/xml", status_code=403
        )

    _twiml_cleanup()

    prebuilt = _twiml_pop(workflow_run_id)
    if prebuilt:
        logger.info(
            f"[OUTBOUND-TWIML] ⚡ Using pre-built TwiML (instant) | "
            f"run_id={workflow_run_id}"
        )
        return HTMLResponse(content=prebuilt, media_type="application/xml")

    logger.warning(
        f"[OUTBOUND-TWIML] Pre-built TwiML miss (cross-process), rebuilding | "
        f"run_id={workflow_run_id}"
    )

    if greeting_audio_url:
        backend_endpoint = await TunnelURLProvider.get_tunnel_url()
        if backend_endpoint.startswith("https://"):
            backend_endpoint = backend_endpoint[8:]
        elif backend_endpoint.startswith("http://"):
            backend_endpoint = backend_endpoint[7:]
        _prebuild_twiml_for_outbound(
            backend_endpoint,
            workflow_id,
            user_id,
            workflow_run_id,
            greeting_audio_url=greeting_audio_url,
        )
        twiml = _twiml_pop(workflow_run_id)
        if twiml:
            logger.info(
                f"[OUTBOUND-TWIML] Rebuilt TwiML with <Play> greeting | "
                f"run_id={workflow_run_id}"
            )
            return HTMLResponse(content=twiml, media_type="application/xml")

    response_content = await provider.get_webhook_response(
        workflow_id, user_id, workflow_run_id,
    )

    logger.info(
        f"[OUTBOUND-TWIML] TwiML response generated (stream-only fallback) | "
        f"run_id={workflow_run_id}, response_length={len(response_content)}"
    )

    return HTMLResponse(content=response_content, media_type="application/xml")


@router.post("/inbound/{identifier}", include_in_schema=False)
async def handle_inbound_call(
    identifier: str,
    request: Request,
):
    """
    Handle INBOUND calls - when someone calls your Twilio number.

    Configure this URL in Twilio Console:
    https://your-backend.railway.app/api/v1/telephony/inbound/{public_id}

    ``identifier`` is the workflow's opaque ``public_id`` token. For backward
    compatibility with numbers configured before the token migration, a legacy
    integer workflow id is also accepted, but new URLs surfaced in the UI always
    use the opaque token so the enumerable sequential id is never exposed.

    When someone calls your Twilio number, Twilio will POST to this endpoint,
    and we'll connect them to the AI agent for the specified workflow.
    """
    import asyncio as _asyncio
    logger.info(f"[INBOUND] ===== Inbound call webhook received | identifier={identifier} =====")

    # Get form data from Twilio
    form_data = await request.form()
    form_dict = dict(form_data)
    caller_number = form_data.get("From", "unknown")
    called_number = form_data.get("To", "unknown")
    call_sid = form_data.get("CallSid", "unknown")
    call_status = form_data.get("CallStatus", "unknown")
    
    logger.info(
        f"[INBOUND] Call details | from={caller_number}, to={called_number}, "
        f"CallSid={call_sid}, CallStatus={call_status}, identifier={identifier}"
    )
    logger.debug(f"[INBOUND] Full Twilio form data: {json.dumps(form_dict, default=str)}")

    # Resolve the workflow by its opaque public token first; fall back to the
    # legacy integer id for numbers configured before the token migration.
    workflow = await db_client.get_workflow_by_public_id(identifier)
    if workflow is None and identifier.isdigit():
        workflow = await db_client.get_workflow_by_id(int(identifier))

    # ── SECURITY: unify the "not found" and "unauthorized" responses ──
    # Returning distinct responses for a missing workflow vs. a workflow that
    # exists but has a bad/absent signature would let an unauthenticated caller
    # enumerate which workflow identifiers exist. Both paths return the exact
    # same generic 403 TwiML.
    if not workflow:
        logger.warning(
            f"[INBOUND] REJECTED - unknown identifier | "
            f"CallSid={call_sid}, from={caller_number}"
        )
        return HTMLResponse(
            content=_UNAUTHORIZED_TWIML,
            media_type="application/xml",
            status_code=403,
        )

    workflow_id = workflow.id
    organization_id = workflow.organization_id
    user_id = workflow.user_id
    logger.info(
        f"[INBOUND] Workflow found | workflow_id={workflow_id}, name={workflow.name}, "
        f"org_id={organization_id}, user_id={user_id}, status={workflow.status}"
    )

    # ── SECURITY: Verify Twilio signature (CPU-only, no DB needed) ──
    # Do this FIRST before any more DB calls to reject spoofed requests early.
    twilio_signature = request.headers.get("X-Twilio-Signature", "")
    if not twilio_signature:
        logger.warning(
            f"[INBOUND] REJECTED - Missing X-Twilio-Signature header | "
            f"workflow_id={workflow_id}, from={caller_number}"
        )
        return HTMLResponse(
            content=_UNAUTHORIZED_TWIML,
            media_type="application/xml",
            status_code=403,
        )

    gathered_ctx = {
        "provider": "twilio",
        "call_direction": "inbound",
        "caller_number": caller_number,
        "called_number": called_number,
    }
    workflow_run_name = f"WR-IN-{random.randint(1000, 9999)}"

    # Run provider + subscription + workflow_run creation ALL in parallel.
    # Subscription check (minutes) is critical but adds zero extra latency
    # because it runs concurrently with the other two DB queries.
    try:
        provider, can_call, workflow_run, user_config = await _asyncio.gather(
            get_telephony_provider(organization_id),
            _sub_service.check_can_make_call(organization_id),
            db_client.create_workflow_run(
                workflow_run_name,
                workflow_id,
                "twilio",
                initial_context={
                    "phone_number": caller_number,
                    "called_number": called_number,
                    "call_direction": "inbound",
                },
                user_id=user_id,
                gathered_context=gathered_ctx,
            ),
            db_client.get_user_configurations(user_id),
        )
        workflow_run_id = workflow_run.id

        logger.info(
            f"[INBOUND] Parallel setup done | run_id={workflow_run_id}, "
            f"provider={provider.PROVIDER_NAME}, plan={can_call.get('plan')}, "
            f"minutes_remaining={can_call.get('minutes_remaining')}"
        )
    except Exception as e:
        logger.error(
            f"[INBOUND] FAILED - parallel setup error | "
            f"error={type(e).__name__}: {e}, workflow_id={workflow_id}"
        )
        return HTMLResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Say>Sorry, we could not process your call.</Say><Hangup/></Response>',
            media_type="application/xml"
        )

    if not can_call["allowed"]:
        logger.warning(
            f"[INBOUND] REJECTED - Subscription limit | org_id={organization_id}, "
            f"reason={can_call['reason']}, plan={can_call.get('plan')}, "
            f"minutes_used={can_call.get('minutes_used')}"
        )
        return HTMLResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Say>Sorry, the service is currently unavailable. Please try again later.</Say><Hangup/></Response>',
            media_type="application/xml"
        )

    if not provider.validate_config():
        logger.error(
            f"[INBOUND] FAILED - Provider config invalid | provider={provider.PROVIDER_NAME}, "
            f"org_id={organization_id}. Check telephony settings."
        )
        return HTMLResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Say>Sorry, telephony is not configured correctly.</Say><Hangup/></Response>',
            media_type="application/xml"
        )

    # Verify Twilio signature (needs provider auth_token, now available)
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    full_url = f"{proto}://{host}{request.url.path}"
    if request.url.query:
        full_url += f"?{request.url.query}"

    is_valid = await provider.verify_webhook_signature(
        url=full_url, params=form_dict, signature=twilio_signature,
    )
    if not is_valid:
        logger.warning(
            f"[INBOUND] REJECTED - Invalid Twilio signature | "
            f"workflow_id={workflow_id}, from={caller_number}"
        )
        return HTMLResponse(
            content=_UNAUTHORIZED_TWIML,
            media_type="application/xml",
            status_code=403,
        )
    logger.info(f"[INBOUND] ✓ Twilio signature verified | workflow_id={workflow_id}")

    try:
        response_content = await provider.get_webhook_response(
            workflow_id, user_id, workflow_run_id,
        )
        logger.info(
            f"[INBOUND] TwiML response generated (stream-only, no <Play>) | "
            f"run_id={workflow_run_id}, response_length={len(response_content)}"
        )
    except Exception as e:
        logger.error(
            f"[INBOUND] FAILED - Could not generate TwiML response | "
            f"error={type(e).__name__}: {e}, run_id={workflow_run_id}"
        )
        return HTMLResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Say>Sorry, we could not connect you.</Say><Hangup/></Response>',
            media_type="application/xml"
        )
    
    logger.info(
        f"[INBOUND] ===== Inbound call setup complete | run_id={workflow_run_id}, "
        f"from={caller_number}, workflow={workflow_id} ====="
    )
    
    return HTMLResponse(content=response_content, media_type="application/xml")


@router.post("/gather-done", include_in_schema=False)
async def handle_gather_done(
    request: Request,
    workflow_id: int,
    user_id: int,
    workflow_run_id: int,
    x_twilio_signature: Optional[str] = Header(None),
):
    """Called when the caller interrupts the connection greeting.

    Twilio ``<Gather>`` detects speech during the ``<Play>``/``<Say>``
    greeting and POSTs here.  We return TwiML that immediately connects
    the WebSocket media stream so the AI pipeline can take over.
    """
    logger.info(
        f"[GATHER-DONE] Caller interrupted greeting | "
        f"workflow_id={workflow_id}, run_id={workflow_run_id}"
    )

    # Returns TwiML containing a signed media ticket -> must be Twilio-signed.
    workflow = await db_client.get_workflow_by_id(workflow_id)
    if not workflow:
        return HTMLResponse(
            content=_UNAUTHORIZED_TWIML, media_type="application/xml", status_code=403
        )
    provider = await get_telephony_provider(workflow.organization_id)
    form_dict = dict(await request.form())
    if not await _verify_twilio_signature(
        request, provider, x_twilio_signature, form_dict
    ):
        logger.warning(
            f"[GATHER-DONE] REJECTED - invalid/missing Twilio signature | "
            f"run_id={workflow_run_id}"
        )
        return HTMLResponse(
            content=_UNAUTHORIZED_TWIML, media_type="application/xml", status_code=403
        )

    backend_endpoint = await TunnelURLProvider.get_tunnel_url()
    if backend_endpoint.startswith("https://"):
        backend_endpoint = backend_endpoint[len("https://"):]
    elif backend_endpoint.startswith("http://"):
        backend_endpoint = backend_endpoint[len("http://"):]

    from api.services.security.ws_ticket import generate_ws_ticket

    ticket = generate_ws_ticket(workflow_id, user_id, workflow_run_id)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "    <Connect>\n"
        f'        <Stream url="wss://{backend_endpoint}/api/v1/telephony/ws/'
        f'{workflow_id}/{user_id}/{workflow_run_id}?ticket={ticket}"></Stream>\n'
        "    </Connect>\n"
        '    <Pause length="40"/>\n'
        "</Response>"
    )
    return HTMLResponse(content=twiml, media_type="application/xml")


@router.get("/greeting-audio/{workflow_id}", include_in_schema=False)
@limiter.limit(RateLimitTiers.PUBLIC)
async def serve_greeting_audio(request: Request, workflow_id: int):
    """Fallback endpoint that serves greeting audio.

    Primary path is the Supabase public URL (returned by
    ``ensure_greeting_audio``).  This endpoint handles the case where
    that upload failed and Twilio was given our backend URL instead.
    It tries Supabase Storage first, then generates fresh from Gemini TTS.

    Rate-limited: it is unauthenticated and can trigger paid TTS generation,
    so it must not be usable as an unbounded cost-amplification vector.
    """
    from api.services.telephony.greeting_audio import get_greeting_audio_bytes

    workflow = await db_client.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    (
        connection_greeting,
        tts_voice_id,
        voice_mode,
        tts_provider,
        workflow_language,
        cartesia_model,
    ) = _extract_greeting_and_voice(workflow)

    if not connection_greeting:
        raise HTTPException(status_code=404, detail="No greeting prompt configured")

    if not tts_voice_id:
        tts_voice_id = (
            CARTESIA_DEFAULT_VOICE_ID
            if tts_provider == "cartesia"
            else GEMINI_DEFAULT_VOICE_ID
        )

    audio_bytes = await get_greeting_audio_bytes(
        workflow_id,
        connection_greeting,
        tts_voice_id,
        provider=tts_provider,  # type: ignore[arg-type]
        workflow_language=workflow_language,
        cartesia_model=cartesia_model,
        accent_id=(workflow.workflow_configurations or {}).get("tts_accent") or None,
    )
    if not audio_bytes:
        raise HTTPException(status_code=503, detail="Could not generate greeting audio")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/ncco", include_in_schema=False)
async def handle_ncco_webhook(
    workflow_id: int,
    user_id: int,
    workflow_run_id: int,
    organization_id: Optional[int] = None,
):
    """Deprecated Vonage webhook endpoint (Twilio-only deployment)."""
    raise HTTPException(
        status_code=410,
        detail="Vonage telephony has been removed. This deployment supports Twilio only.",
    )


@router.websocket("/ws/{workflow_id}/{user_id}/{workflow_run_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    workflow_id: int,
    user_id: int,
    workflow_run_id: int,
    ticket: str = Query(None),
):
    """WebSocket endpoint for real-time call handling - routes to provider-specific handlers."""
    import time as _time
    _ws_t0 = _time.perf_counter()

    logger.info(
        f"[WS] ===== WebSocket connection request | workflow_id={workflow_id}, "
        f"user_id={user_id}, run_id={workflow_run_id} ====="
    )

    # Authorize the connection with a signed, short-lived, run-bound ticket
    # BEFORE accepting the socket. This prevents an attacker who guesses run IDs
    # from attaching to a live call media stream.
    from api.services.security.ws_ticket import verify_ws_ticket

    if not verify_ws_ticket(ticket, workflow_id, user_id, workflow_run_id):
        logger.warning(
            f"[WS] REJECTED - invalid/missing media ticket | "
            f"workflow_id={workflow_id}, user_id={user_id}, run_id={workflow_run_id}"
        )
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await websocket.accept()
    _ws_t_accept = _time.perf_counter()
    logger.info(
        f"⏱ [LATENCY] WS accepted | run_id={workflow_run_id} | "
        f"accept={(_ws_t_accept - _ws_t0)*1000:.0f}ms"
    )

    try:
        import asyncio as _aio
        set_current_run_id(workflow_run_id)

        # Always re-fetch setup data from the database using the trusted
        # primary keys in the (ticket-authorized) URL. No pickle cache.
        workflow_run, workflow, user_config = await _aio.gather(
            db_client.get_workflow_run(workflow_run_id),
            db_client.get_workflow(workflow_id),
            db_client.get_user_configurations(user_id),
        )
        logger.info(
            f"⏱ [LATENCY] WS setup from DB | "
            f"run_id={workflow_run_id} | elapsed={(_time.perf_counter() - _ws_t0)*1000:.0f}ms"
        )

        if not workflow_run:
            logger.error(f"[WS] FAILED - Workflow run {workflow_run_id} not found")
            await websocket.close(code=4404, reason="Workflow run not found")
            return

        if not workflow:
            logger.error(f"[WS] FAILED - Workflow {workflow_id} not found")
            await websocket.close(code=4404, reason="Workflow not found")
            return

        # Defense-in-depth: ensure the run actually belongs to the workflow and
        # user encoded in the (ticket-signed) URL, so a valid ticket for one run
        # can never be replayed against a mismatched run/workflow/user.
        if workflow_run.workflow_id != workflow_id or workflow.user_id != user_id:
            logger.warning(
                f"[WS] REJECTED - run/workflow/user mismatch | run_id={workflow_run_id}, "
                f"run.workflow_id={workflow_run.workflow_id}, url.workflow_id={workflow_id}, "
                f"workflow.user_id={workflow.user_id}, url.user_id={user_id}"
            )
            await websocket.close(code=1008, reason="Unauthorized")
            return

        if workflow_run.state != WorkflowRunState.INITIALIZED.value:
            logger.warning(
                f"[WS] REJECTED - Run {workflow_run_id} state={workflow_run.state}"
            )
            await websocket.close(code=4409, reason="Workflow run not available for connection")
            return

        provider_type = None
        call_direction = "unknown"
        if workflow_run.gathered_context:
            provider_type = workflow_run.gathered_context.get("provider")
            call_direction = workflow_run.gathered_context.get("call_direction", "unknown")

        if not provider_type:
            logger.error(f"[WS] FAILED - No provider in gathered_context | run_id={workflow_run_id}")
            await websocket.close(code=4400, reason="Provider type not found")
            return

        # Fire-and-forget state update
        _aio.create_task(db_client.update_workflow_run(
            run_id=workflow_run_id,
            state=WorkflowRunState.RUNNING.value
        ))

        provider = await get_telephony_provider(workflow.organization_id)

        logger.info(
            f"⏱ [LATENCY] Ready to delegate | run_id={workflow_run_id} | "
            f"elapsed={(_time.perf_counter() - _ws_t0)*1000:.0f}ms | "
            f"provider={provider_type}, direction={call_direction}"
        )

        await provider.handle_websocket(
            websocket, workflow_id, user_id, workflow_run_id,
            workflow=workflow, workflow_run=workflow_run,
            user_config=user_config,
        )

        logger.info(f"[WS] Provider handler returned normally | run_id={workflow_run_id}")

    except Exception as e:
        logger.error(
            f"[WS] EXCEPTION in WebSocket | run_id={workflow_run_id}, "
            f"error={type(e).__name__}: {e}",
            exc_info=True,
        )
        try:
            await websocket.close(1011, "Internal server error")
        except Exception:
            pass  # WebSocket may already be closed


@router.post("/twilio/status-callback/{workflow_run_id}")
async def handle_twilio_status_callback(
    workflow_run_id: int,
    request: Request,
    x_webhook_signature: Optional[str] = Header(None),
):
    """Handle Twilio-specific status callbacks."""

    # Parse form data
    form_data = await request.form()
    callback_data = dict(form_data)
    logger.info(
        f"[run {workflow_run_id}] Received status callback: {json.dumps(callback_data)}"
    )

    # Get workflow run to find organization
    workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)
    if not workflow_run:
        logger.warning(f"Workflow run {workflow_run_id} not found for status callback")
        return {"status": "ignored", "reason": "workflow_run_not_found"}

    # Get workflow and provider
    workflow = await db_client.get_workflow_by_id(workflow_run.workflow_id)
    if not workflow:
        logger.warning(f"Workflow {workflow_run.workflow_id} not found")
        return {"status": "ignored", "reason": "workflow_not_found"}

    provider = await get_telephony_provider(workflow.organization_id)

    # Status callbacks mutate run state and billing, so the Twilio signature is
    # mandatory. Reject (fail closed) when it is missing or invalid.
    if not x_webhook_signature:
        logger.warning(
            f"Missing webhook signature for workflow run {workflow_run_id}"
        )
        return Response(status_code=403)

    backend_endpoint = await TunnelURLProvider.get_tunnel_url()
    full_url = f"https://{backend_endpoint}/api/v1/telephony/twilio/status-callback/{workflow_run_id}"

    is_valid = await provider.verify_webhook_signature(
        full_url, callback_data, x_webhook_signature
    )

    if not is_valid:
        logger.warning(
            f"Invalid webhook signature for workflow run {workflow_run_id}"
        )
        return Response(status_code=403)

    # Parse the callback data into generic format
    parsed_data = provider.parse_status_callback(callback_data)

    # Create StatusCallbackRequest from parsed data
    status_update = StatusCallbackRequest(
        call_id=parsed_data["call_id"],
        status=parsed_data["status"],
        from_number=parsed_data.get("from_number"),
        to_number=parsed_data.get("to_number"),
        direction=parsed_data.get("direction"),
        duration=parsed_data.get("duration"),
        extra=parsed_data.get("extra", {}),
    )

    # Process the status update
    await _process_status_update(workflow_run_id, status_update, workflow_run)

    return {"status": "success"}


async def _process_status_update(
    workflow_run_id: int, status: StatusCallbackRequest, workflow_run: any
):
    """Process status updates from telephony providers."""

    # Log the status callback
    telephony_callback_logs = workflow_run.logs.get("telephony_status_callbacks", [])
    telephony_callback_log = {
        "status": status.status,
        "timestamp": datetime.now(UTC).isoformat(),
        "call_id": status.call_id,
        "duration": status.duration,
        **status.extra,  # Include provider-specific data
    }
    telephony_callback_logs.append(telephony_callback_log)

    # Update workflow run logs
    await db_client.update_workflow_run(
        run_id=workflow_run_id,
        logs={"telephony_status_callbacks": telephony_callback_logs},
    )

    # Handle call completion
    if status.status == "completed":
        logger.info(
            f"[run {workflow_run_id}] Call completed with duration: {status.duration}s"
        )

        # Release concurrent slot if this was a campaign call
        if workflow_run.campaign_id:
            await campaign_call_dispatcher.release_call_slot(workflow_run_id)

        # Mark workflow run as completed
        await db_client.update_workflow_run(
            run_id=workflow_run_id, 
            is_completed=True,
            state=WorkflowRunState.COMPLETED.value
        )

    elif status.status in ["failed", "busy", "no-answer", "canceled"]:
        logger.warning(
            f"[run {workflow_run_id}] Call failed with status: {status.status}"
        )

        # Release concurrent slot for terminal statuses if this was a campaign call
        if workflow_run.campaign_id:
            await campaign_call_dispatcher.release_call_slot(workflow_run_id)

        # Check if retry is needed for campaign calls (busy/no-answer)
        if status.status in ["busy", "no-answer"] and workflow_run.campaign_id:
            publisher = await get_campaign_event_publisher()
            await publisher.publish_retry_needed(
                workflow_run_id=workflow_run_id,
                reason=status.status.replace(
                    "-", "_"
                ),  # Convert no-answer to no_answer
                campaign_id=workflow_run.campaign_id,
                queued_run_id=workflow_run.queued_run_id,
            )

        # Mark workflow run as completed with failure tags
        call_tags = (
            workflow_run.gathered_context.get("call_tags", [])
            if workflow_run.gathered_context
            else []
        )
        call_tags.extend(["not_connected", f"telephony_{status.status.lower()}"])

        await db_client.update_workflow_run(
            run_id=workflow_run_id,
            is_completed=True,
            state=WorkflowRunState.COMPLETED.value,
            gathered_context={"call_tags": call_tags},
        )


@router.post("/vonage/events/{workflow_run_id}", include_in_schema=False)
async def handle_vonage_events(
    request: Request,
    workflow_run_id: int,
):
    """Deprecated Vonage callback endpoint (Twilio-only deployment)."""
    raise HTTPException(
        status_code=410,
        detail="Vonage telephony has been removed. This deployment supports Twilio only.",
    )


@router.post("/vobiz-xml", include_in_schema=False)
async def handle_vobiz_xml_webhook(
    workflow_id: int, user_id: int, workflow_run_id: int, organization_id: int
):
    """Deprecated Vobiz webhook endpoint (Twilio-only deployment)."""
    raise HTTPException(
        status_code=410,
        detail="Vobiz telephony has been removed. This deployment supports Twilio only.",
    )


@router.post("/vobiz/hangup-callback/{workflow_run_id}", include_in_schema=False)
async def handle_vobiz_hangup_callback(
    workflow_run_id: int,
    request: Request,
):
    """Deprecated Vobiz callback endpoint (Twilio-only deployment)."""
    raise HTTPException(
        status_code=410,
        detail="Vobiz telephony has been removed. This deployment supports Twilio only.",
    )


@router.post("/vobiz/ring-callback/{workflow_run_id}", include_in_schema=False)
async def handle_vobiz_ring_callback(
    workflow_run_id: int,
    request: Request,
):
    """Deprecated Vobiz callback endpoint (Twilio-only deployment)."""
    raise HTTPException(
        status_code=410,
        detail="Vobiz telephony has been removed. This deployment supports Twilio only.",
    )
