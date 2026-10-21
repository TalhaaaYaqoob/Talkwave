"""Generate, persist, and serve TTS greeting audio for telephony.

Audio is generated with the same provider that speaks the rest of the call —
Gemini TTS, including its accent prompt, with Cartesia Sonic-3.5 as the
fallback — then stored in **Supabase Storage** (the same ``voice-audio`` bucket
used for recordings). A lightweight in-memory metadata cache avoids repeated
storage lookups on every call while keeping memory usage negligible (only
URLs are cached, not audio bytes).
"""

import asyncio
import hashlib
import io
import json
import os
import time
from typing import Literal, Optional, Tuple

import aiohttp
from loguru import logger

TTSProvider = Literal["gemini", "cartesia"]

# ---------------------------------------------------------------------------
# Lightweight metadata cache
# Maps workflow_id → (voice_id, text_hash, public_url, monotonic_ts)
# Only stores short strings – safe even for thousands of workflows.
# ---------------------------------------------------------------------------
_META_CACHE: dict[int, Tuple[str, str, str, float]] = {}
_META_CACHE_TTL = 3600.0  # 1 hour


def text_hash(text: str) -> str:
    """Short deterministic hash of greeting text for staleness checks."""
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]


def _storage_path(workflow_id: int) -> str:
    return f"greeting-audio/{workflow_id}.mp3"


def _get_storage():
    """Lazy import to avoid circular imports at module load."""
    from api.services.storage import storage_fs
    return storage_fs


# ---------------------------------------------------------------------------
# Gemini generation
# ---------------------------------------------------------------------------

async def _generate_from_gemini(
    text: str,
    voice_id: str,
    *,
    workflow_language: Optional[str] = None,
    accent_id: Optional[str] = None,
    model: Optional[str] = None,
) -> bytes:
    """Synthesise the greeting with Gemini TTS and return raw MP3 bytes.

    Uses the same voice, accent prompt and locale as the live call, so the
    pre-generated greeting is indistinguishable from the speech that follows it.
    Gemini's unary synthesize endpoint (unlike its streaming one) can emit MP3
    directly, which is the format this module stores.
    """
    # Imported lazily: pulling in the service factory at module load would drag
    # the whole pipecat stack into every process that touches telephony.
    from api.services.pipecat.service_factory import (
        GEMINI_DEFAULT_MODEL,
        GEMINI_DEFAULT_VOICE_ID,
        GEMINI_VALID_VOICE_IDS,
        LANGUAGE_TO_PIPECAT_LANGUAGE,
        resolve_google_tts_credentials,
    )
    from api.services.pipecat.tts_accents import resolve_accent
    from google.cloud import texttospeech_v1
    from google.oauth2 import service_account
    from pipecat.services.google.tts import language_to_gemini_tts_language
    from pipecat.transcriptions.language import Language

    credentials, credentials_path = resolve_google_tts_credentials()

    if not voice_id or voice_id not in GEMINI_VALID_VOICE_IDS:
        logger.warning(
            f"[GREETING-AUDIO] Invalid Gemini voice '{voice_id}', "
            f"using default: {GEMINI_DEFAULT_VOICE_ID}"
        )
        voice_id = GEMINI_DEFAULT_VOICE_ID

    accent = resolve_accent(workflow_language, accent_id)
    language = accent.language or LANGUAGE_TO_PIPECAT_LANGUAGE.get(
        workflow_language, Language.EN
    )
    language_code = language_to_gemini_tts_language(language) or "en-US"

    creds = None
    if credentials:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(credentials)
        )
    elif credentials_path:
        creds = service_account.Credentials.from_service_account_file(credentials_path)

    client = texttospeech_v1.TextToSpeechAsyncClient(credentials=creds)

    t0 = time.perf_counter()
    response = await client.synthesize_speech(
        input=texttospeech_v1.SynthesisInput(text=text.strip(), prompt=accent.prompt),
        voice=texttospeech_v1.VoiceSelectionParams(
            language_code=language_code,
            name=voice_id,
            model_name=model or GEMINI_DEFAULT_MODEL,
        ),
        audio_config=texttospeech_v1.AudioConfig(
            audio_encoding=texttospeech_v1.AudioEncoding.MP3,
            sample_rate_hertz=22050,
        ),
        timeout=10.0,
    )
    audio_bytes = response.audio_content

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        f"[GREETING-AUDIO] Gemini generated | voice={voice_id}, "
        f"accent={accent.id}, language={language_code}, "
        f"size={len(audio_bytes)}, elapsed={elapsed_ms:.0f}ms"
    )
    return audio_bytes


# ---------------------------------------------------------------------------
# Cartesia generation
# ---------------------------------------------------------------------------

# Workflow language → Cartesia BCP-47 language code (used for Sonic-3.5
# multilingual rendering). Kept tiny on purpose: matches the 11 languages
# Talkwave exposes in the UI.
_LANGUAGE_TO_CARTESIA_CODE: dict[str, str] = {
    "English": "en",
    "Arabic": "ar",
    "Hindi": "hi",
    "French": "fr",
    "German": "de",
    "Korean": "ko",
    "Spanish": "es",
    "Portuguese": "pt",
    "Italian": "it",
    "Japanese": "ja",
    "Chinese": "zh",
}


async def _generate_from_cartesia(
    text: str,
    voice_id: str,
    *,
    model: str = "sonic-3.5",
    language: str = "en",
    speed: float = 1.0,
) -> bytes:
    """Call the Cartesia HTTP TTS Bytes endpoint and return raw MP3 bytes.

    Reference: https://docs.cartesia.ai/api-reference/tts/bytes
    """
    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        raise ValueError("CARTESIA_API_KEY not set")

    url = "https://api.cartesia.ai/tts/bytes"
    headers = {
        "X-API-Key": api_key,
        "Cartesia-Version": "2025-04-16",
        "Content-Type": "application/json",
    }
    payload = {
        "model_id": model,
        "transcript": text.strip(),
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {
            "container": "mp3",
            "sample_rate": 22050,
            "bit_rate": 64000,
        },
        "language": language,
    }
    if speed and speed != 1.0:
        payload["generation_config"] = {"speed": speed}

    t0 = time.perf_counter()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(
                    f"[GREETING-AUDIO] Cartesia error {resp.status}: {body[:300]}"
                )
                raise ValueError(f"Cartesia returned {resp.status}")
            audio_bytes = await resp.read()

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        f"[GREETING-AUDIO] Cartesia generated | voice={voice_id}, model={model}, "
        f"language={language}, size={len(audio_bytes)}, elapsed={elapsed_ms:.0f}ms"
    )
    return audio_bytes


def _cartesia_greeting_voice(voice_id: str) -> str:
    """Map a Gemini voice to its closest Cartesia stand-in.

    Mirrors CARTESIA_FALLBACK_BY_GEMINI_VOICE in the UI so a fallback greeting
    sounds as close as possible to the voice the workflow selected.
    """
    from api.services.pipecat.service_factory import (
        CARTESIA_DEFAULT_VOICE_ID,
        CARTESIA_VALID_VOICE_IDS,
    )
    if voice_id in CARTESIA_VALID_VOICE_IDS:
        return voice_id
    return CARTESIA_DEFAULT_VOICE_ID


async def _generate_greeting(
    text: str,
    voice_id: str,
    provider: TTSProvider,
    workflow_language: Optional[str] = None,
    cartesia_model: str = "sonic-3.5",
    accent_id: Optional[str] = None,
) -> bytes:
    """Generate the greeting, preferring Gemini and falling back to Cartesia.

    The fallback mirrors the live pipeline in api.services.pipecat.service_factory,
    so a missing Google credential degrades the greeting rather than dropping it.
    """
    if provider != "cartesia":
        try:
            return await _generate_from_gemini(
                text,
                voice_id,
                workflow_language=workflow_language,
                accent_id=accent_id,
            )
        except Exception as gemini_err:
            logger.warning(
                f"[GREETING-AUDIO] Gemini unavailable ({gemini_err}) — falling back to Cartesia"
            )

    lang_code = _LANGUAGE_TO_CARTESIA_CODE.get(workflow_language or "English", "en")
    return await _generate_from_cartesia(
        text,
        _cartesia_greeting_voice(voice_id),
        model=cartesia_model,
        language=lang_code,
    )


# ---------------------------------------------------------------------------
# Supabase Storage helpers (sync – called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _upload_to_storage(workflow_id: int, audio_bytes: bytes) -> Optional[str]:
    """Upload (or replace) greeting MP3 in Supabase Storage.

    Returns the public URL on success, ``None`` on failure.
    """
    try:
        fs = _get_storage()
        path = _storage_path(workflow_id)

        # Remove old file first (ignore errors – may not exist yet).
        try:
            fs.delete(path)
        except Exception:
            pass

        public_url = fs.upload(io.BytesIO(audio_bytes), path, content_type="audio/mpeg")
        logger.info(f"[GREETING-AUDIO] Stored in Supabase | path={path}")
        return public_url
    except Exception as e:
        logger.error(f"[GREETING-AUDIO] Storage upload failed: {e}")
        return None


def _download_from_storage(workflow_id: int) -> Optional[bytes]:
    """Download greeting audio bytes from Supabase Storage."""
    try:
        fs = _get_storage()
        return fs.download(_storage_path(workflow_id))
    except Exception:
        return None


def _get_public_url(workflow_id: int) -> Optional[str]:
    """Return the public Supabase URL for the greeting audio file."""
    try:
        fs = _get_storage()
        return fs.get_url(_storage_path(workflow_id))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _voice_key(voice_id: str, accent_id: Optional[str]) -> str:
    """Cache identity of the rendered voice.

    The accent is part of it: switching from Saudi to Egyptian changes the audio
    while the voice and text stay the same, and would otherwise serve a stale
    greeting from cache forever.
    """
    return f"{voice_id}:{accent_id or 'default'}"


async def _background_generate_and_upload(
    workflow_id: int,
    text: str,
    voice_id: str,
    provider: TTSProvider = "gemini",
    workflow_language: Optional[str] = None,
    cartesia_model: str = "sonic-3.5",
    accent_id: Optional[str] = None,
) -> None:
    """Generate audio and upload to Supabase in the background."""
    try:
        audio_bytes = await _generate_greeting(
            text, voice_id, provider,
            workflow_language=workflow_language,
            cartesia_model=cartesia_model,
            accent_id=accent_id,
        )
        public_url = await asyncio.to_thread(
            _upload_to_storage, workflow_id, audio_bytes,
        )
        if public_url:
            t_hash = text_hash(text)
            _META_CACHE[workflow_id] = (
                _voice_key(voice_id, accent_id), t_hash, public_url, time.monotonic(),
            )
            logger.info(
                f"[GREETING-AUDIO] Background generation done | "
                f"workflow={workflow_id}, voice={voice_id}, provider={provider}"
            )
    except Exception as e:
        logger.warning(f"[GREETING-AUDIO] Background generation failed: {e}")


async def ensure_greeting_audio(
    workflow_id: int,
    text: str,
    voice_id: str,
    provider: TTSProvider = "gemini",
    workflow_language: Optional[str] = None,
    cartesia_model: str = "sonic-3.5",
    accent_id: Optional[str] = None,
) -> Optional[str]:
    """Return a publicly-accessible URL for the greeting audio.

    Optimised for **speed** — the TwiML response must not block on audio
    generation.  Priority order:

    1. In-memory metadata cache (instant).
    2. Supabase public URL (fast — no download, just URL construction).
       Returned immediately; background task regenerates if stale.
    3. Only blocks on TTS generation for the very first call ever
       (no file in Supabase yet).
    """
    t_hash = text_hash(text)
    v_key = _voice_key(voice_id, accent_id)

    # ── 1. In-memory cache (fastest) ──────────────────────────────────
    cached = _META_CACHE.get(workflow_id)
    if cached:
        c_voice, c_hash, c_url, c_ts = cached
        if (
            c_voice == v_key
            and c_hash == t_hash
            and (time.monotonic() - c_ts) < _META_CACHE_TTL
        ):
            logger.debug(f"[GREETING-AUDIO] Meta-cache hit | workflow={workflow_id}")
            return c_url

    # ── 2. Supabase public URL (instant — just string construction) ───
    try:
        existing_url = _get_public_url(workflow_id)
        if existing_url:
            _META_CACHE[workflow_id] = (
                v_key, t_hash, existing_url, time.monotonic(),
            )
            logger.info(
                f"[GREETING-AUDIO] Using existing Supabase URL | "
                f"workflow={workflow_id}"
            )
            stale = cached and (cached[0] != v_key or cached[1] != t_hash)
            if stale or not cached:
                asyncio.get_running_loop().create_task(
                    _background_generate_and_upload(
                        workflow_id, text, voice_id,
                        provider=provider,
                        workflow_language=workflow_language,
                        cartesia_model=cartesia_model,
                        accent_id=accent_id,
                    )
                )
            return existing_url
    except Exception:
        pass

    # ── 3. First-time generation (blocking — only for very first call) ─
    logger.info(
        f"[GREETING-AUDIO] No cached/stored audio, generating | "
        f"workflow={workflow_id}, provider={provider}"
    )
    try:
        audio_bytes = await _generate_greeting(
            text, voice_id, provider,
            workflow_language=workflow_language,
            cartesia_model=cartesia_model,
            accent_id=accent_id,
        )
    except Exception as e:
        logger.warning(f"[GREETING-AUDIO] Generation failed: {e}")
        if cached:
            return cached[2]
        return None

    public_url = await asyncio.to_thread(
        _upload_to_storage, workflow_id, audio_bytes,
    )

    if public_url:
        _META_CACHE[workflow_id] = (
            v_key, t_hash, public_url, time.monotonic(),
        )
        return public_url

    logger.warning("[GREETING-AUDIO] Storage upload failed; no URL available")
    return None


async def get_greeting_audio_bytes(
    workflow_id: int,
    text: str,
    voice_id: str,
    provider: TTSProvider = "gemini",
    workflow_language: Optional[str] = None,
    cartesia_model: str = "sonic-3.5",
    accent_id: Optional[str] = None,
) -> Optional[bytes]:
    """Return audio bytes for the fallback endpoint.

    Tries Supabase Storage first, then generates fresh from the configured
    TTS provider (Gemini, falling back to Cartesia).
    """
    audio = await asyncio.to_thread(_download_from_storage, workflow_id)
    if audio:
        return audio
    try:
        return await _generate_greeting(
            text, voice_id, provider,
            workflow_language=workflow_language,
            cartesia_model=cartesia_model,
            accent_id=accent_id,
        )
    except Exception:
        return None


def invalidate_cache(workflow_id: int) -> None:
    """Drop metadata cache entry for a workflow.

    Called when the user changes voice settings or greeting text so that
    the next call triggers regeneration.
    """
    _META_CACHE.pop(workflow_id, None)


def _delete_from_storage(workflow_id: int) -> None:
    """Delete greeting audio file from Supabase Storage."""
    try:
        fs = _get_storage()
        fs.delete(_storage_path(workflow_id))
    except Exception:
        pass


async def force_regenerate_greeting_audio(
    workflow_id: int,
    text: str,
    voice_id: str,
    provider: TTSProvider = "gemini",
    workflow_language: Optional[str] = None,
    cartesia_model: str = "sonic-3.5",
    accent_id: Optional[str] = None,
) -> Optional[str]:
    """Delete old audio, generate new, and upload — used on workflow save.

    Unlike ``ensure_greeting_audio`` this never returns a stale URL.
    """
    invalidate_cache(workflow_id)

    await asyncio.to_thread(_delete_from_storage, workflow_id)

    try:
        audio_bytes = await _generate_greeting(
            text, voice_id, provider,
            workflow_language=workflow_language,
            cartesia_model=cartesia_model,
            accent_id=accent_id,
        )
    except Exception as e:
        logger.warning(f"[GREETING-AUDIO] Regeneration failed: {e}")
        return None

    public_url = await asyncio.to_thread(
        _upload_to_storage, workflow_id, audio_bytes,
    )
    if public_url:
        t_hash = text_hash(text)
        _META_CACHE[workflow_id] = (
            _voice_key(voice_id, accent_id), t_hash, public_url, time.monotonic(),
        )
        logger.info(
            f"[GREETING-AUDIO] Force-regenerated | workflow={workflow_id}, "
            f"voice={voice_id}, provider={provider}"
        )
    return public_url
