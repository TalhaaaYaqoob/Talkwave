"""
Batch audio transcription via Deepgram's pre-recorded API.

Accepts raw audio bytes, sends to Deepgram with speaker diarization,
and returns structured transcripts with agent vs. caller separation.
"""

import asyncio
import os
from typing import Optional

import httpx
from loguru import logger

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
TIMEOUT_SECONDS = 120  # Pre-recorded transcription can take a while for long files
MAX_CONCURRENT = 3


def _get_deepgram_key() -> str:
    key = os.getenv("DEEPGRAM_API_KEY", "")
    if not key:
        raise ValueError("DEEPGRAM_API_KEY not set")
    return key


def _format_diarized_transcript(result: dict) -> str:
    """Format Deepgram result into a clean transcript with speaker labels."""
    channels = result.get("results", {}).get("channels", [])
    if not channels:
        return ""

    alternatives = channels[0].get("alternatives", [])
    if not alternatives:
        return ""

    paragraphs = alternatives[0].get("paragraphs", {}).get("paragraphs", [])
    if paragraphs:
        lines = []
        for para in paragraphs:
            speaker = para.get("speaker", 0)
            label = "Agent" if speaker == 0 else "Caller"
            sentences = " ".join(s.get("text", "") for s in para.get("sentences", []))
            if sentences.strip():
                lines.append(f"{label}: {sentences.strip()}")
        return "\n".join(lines)

    words = alternatives[0].get("words", [])
    if not words:
        transcript = alternatives[0].get("transcript", "")
        return f"Agent/Caller: {transcript}" if transcript else ""

    lines = []
    current_speaker = None
    current_text = []
    for w in words:
        speaker = w.get("speaker", 0)
        if speaker != current_speaker:
            if current_text:
                label = "Agent" if current_speaker == 0 else "Caller"
                lines.append(f"{label}: {' '.join(current_text)}")
            current_speaker = speaker
            current_text = [w.get("punctuated_word", w.get("word", ""))]
        else:
            current_text.append(w.get("punctuated_word", w.get("word", "")))
    if current_text:
        label = "Agent" if current_speaker == 0 else "Caller"
        lines.append(f"{label}: {' '.join(current_text)}")

    return "\n".join(lines)


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio",
    content_type: str = "audio/mpeg",
) -> Optional[str]:
    """Transcribe a single audio file using Deepgram's pre-recorded API.
    Returns formatted transcript text, or None on failure."""
    try:
        api_key = _get_deepgram_key()
    except ValueError as e:
        logger.error(f"[AudioTranscriber] {e}")
        return None

    params = {
        "model": "nova-3",
        "smart_format": "true",
        "diarize": "true",
        "paragraphs": "true",
        "utterances": "true",
        "punctuate": "true",
    }

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": content_type,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                DEEPGRAM_API_URL,
                params=params,
                headers=headers,
                content=audio_bytes,
                timeout=TIMEOUT_SECONDS,
            )

        if resp.status_code != 200:
            logger.error(f"[AudioTranscriber] Deepgram returned {resp.status_code} for {filename}: {resp.text[:300]}")
            return None

        data = resp.json()
        transcript = _format_diarized_transcript(data)

        if not transcript or len(transcript.strip()) < 20:
            logger.warning(f"[AudioTranscriber] Very short/empty transcript for {filename}")
            return None

        logger.info(f"[AudioTranscriber] Transcribed {filename}: {len(transcript)} chars")
        return transcript

    except httpx.TimeoutException:
        logger.error(f"[AudioTranscriber] Timeout transcribing {filename}")
        return None
    except Exception as e:
        logger.error(f"[AudioTranscriber] Error transcribing {filename}: {e}")
        return None


async def transcribe_multiple(
    files: list[tuple[str, bytes, str]],
) -> list[Optional[str]]:
    """Transcribe multiple audio files concurrently with rate limiting.

    Args:
        files: list of (filename, audio_bytes, content_type) tuples

    Returns: list of transcript strings (or None for failures), in same order as input
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _transcribe_with_limit(filename: str, audio_bytes: bytes, content_type: str):
        async with semaphore:
            return await transcribe_audio(audio_bytes, filename, content_type)

    tasks = [_transcribe_with_limit(f, b, ct) for f, b, ct in files]
    results = await asyncio.gather(*tasks)

    succeeded = sum(1 for r in results if r is not None)
    logger.info(f"[AudioTranscriber] Batch complete: {succeeded}/{len(files)} succeeded")

    return list(results)
