#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""OpenAI Speech-to-Text service implementation using OpenAI's transcription API."""

from typing import Optional

from loguru import logger
from openai import AsyncOpenAI
from openai.types.audio import Transcription

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt


# Language mapping for Whisper API
def language_to_whisper_language(language: Language) -> Optional[str]:
    """Maps pipecat Language enum to Whisper API language codes."""
    LANGUAGE_MAP = {
        Language.AF: "af",
        Language.AR: "ar",
        Language.HY: "hy",
        Language.AZ: "az",
        Language.BE: "be",
        Language.BS: "bs",
        Language.BG: "bg",
        Language.CA: "ca",
        Language.ZH: "zh",
        Language.HR: "hr",
        Language.CS: "cs",
        Language.DA: "da",
        Language.NL: "nl",
        Language.EN: "en",
        Language.ET: "et",
        Language.FI: "fi",
        Language.FR: "fr",
        Language.GL: "gl",
        Language.DE: "de",
        Language.EL: "el",
        Language.HE: "he",
        Language.HI: "hi",
        Language.HU: "hu",
        Language.IS: "is",
        Language.ID: "id",
        Language.IT: "it",
        Language.JA: "ja",
        Language.KN: "kn",
        Language.KK: "kk",
        Language.KO: "ko",
        Language.LV: "lv",
        Language.LT: "lt",
        Language.MK: "mk",
        Language.MS: "ms",
        Language.MR: "mr",
        Language.MI: "mi",
        Language.NE: "ne",
        Language.NO: "no",
        Language.FA: "fa",
        Language.PL: "pl",
        Language.PT: "pt",
        Language.RO: "ro",
        Language.RU: "ru",
        Language.SR: "sr",
        Language.SK: "sk",
        Language.SL: "sl",
        Language.ES: "es",
        Language.SW: "sw",
        Language.SV: "sv",
        Language.TL: "tl",
        Language.TA: "ta",
        Language.TH: "th",
        Language.TR: "tr",
        Language.UK: "uk",
        Language.UR: "ur",
        Language.VI: "vi",
        Language.CY: "cy",
    }
    return LANGUAGE_MAP.get(language)


class OpenAISTTService(SegmentedSTTService):
    """OpenAI Speech-to-Text service that generates text from audio.

    Uses OpenAI's transcription API to convert audio to text. Requires an OpenAI API key
    set via the api_key parameter or OPENAI_API_KEY environment variable.
    
    Set language=None for automatic language detection (multilingual support).
    """

    def __init__(
        self,
        *,
        model: str = "gpt-4o-transcribe",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        language: Optional[Language] = None,  # None = auto-detect for multilingual
        prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ):
        """Initialize OpenAI STT service.

        Args:
            model: Model to use — either gpt-4o or Whisper. Defaults to "gpt-4o-transcribe".
            api_key: OpenAI API key. Defaults to None.
            base_url: API base URL. Defaults to None.
            language: Language of the audio input. None = auto-detect (multilingual).
            prompt: Optional text to guide the model's style or continue a previous segment.
            temperature: Optional sampling temperature between 0 and 1. Defaults to 0.0.
            **kwargs: Additional arguments passed to SegmentedSTTService.
        """
        super().__init__(**kwargs)
        self.set_model_name(model)
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        
        # Convert language enum to Whisper language code, or None for auto-detect
        self._language = language_to_whisper_language(language) if language else None
        self._prompt = prompt
        self._temperature = temperature
        self._include_prob_metrics = False

        self._settings = {
            "base_url": base_url,
            "language": self._language or "auto-detect",
            "prompt": self._prompt,
            "temperature": self._temperature,
        }
        
        logger.info(f"OpenAI STT initialized with language: {self._language or 'auto-detect (multilingual)'}")

    def can_generate_metrics(self) -> bool:
        """Check if this service can generate performance metrics."""
        return True

    def language_to_service_language(self, language: Language) -> Optional[str]:
        """Convert Language enum to Whisper language code."""
        return language_to_whisper_language(language)

    @traced_stt
    async def run_stt(self, audio: bytes):
        """Run speech-to-text on audio data."""
        try:
            result = await self._transcribe(audio)
            if result and result.text:
                yield TranscriptionFrame(
                    text=result.text,
                    user_id="",
                    timestamp=time_now_iso8601(),
                )
        except Exception as e:
            logger.exception(f"OpenAI STT error: {e}")
            yield ErrorFrame(f"OpenAI STT error: {e}")

    async def _transcribe(self, audio: bytes) -> Transcription:
        # Build kwargs dict with only set parameters
        kwargs = {
            "file": ("audio.wav", audio, "audio/wav"),
            "model": self.model_name,
        }
        
        # Only pass language if explicitly set (not None)
        # When language is None, Whisper auto-detects the language
        if self._language is not None:
            kwargs["language"] = self._language

        if self._include_prob_metrics:
            # GPT-4o-transcribe models only support logprobs (not verbose_json)
            if self.model_name in ("gpt-4o-transcribe", "gpt-4o-mini-transcribe"):
                kwargs["response_format"] = "json"
                kwargs["include"] = ["logprobs"]
            else:
                # Whisper models support verbose_json
                kwargs["response_format"] = "verbose_json"

        if self._prompt is not None:
            kwargs["prompt"] = self._prompt

        if self._temperature is not None:
            kwargs["temperature"] = self._temperature

        return await self._client.audio.transcriptions.create(**kwargs)
