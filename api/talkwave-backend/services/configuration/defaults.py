from __future__ import annotations

"""Utilities for building default service configurations for a new user.

Default TTS strategy:
    - Gemini TTS is the primary provider for every supported language. It is the
      only provider that can render a specific regional accent on request
      (Qatari, Saudi or Egyptian Arabic, for example), which it does by taking
      direction through a style prompt alongside the text.
    - Cartesia Sonic-3.5 is the fallback, used when Gemini cannot be reached or
      its Google Cloud credentials are not configured.

ElevenLabs has been retired as a TTS provider for all languages, including
Arabic and Chinese, which Gemini now handles.

These defaults can be overridden per workflow in Settings → Service Configuration.
Runtime selection lives in ``api.services.pipecat.service_factory``; this module
only declares the *baseline* provider mapping that the UI and onboarding flows
use to render their initial defaults.
"""


from api.services.configuration.registry import (
    DeepgramSTTConfiguration,
    GeminiTTSConfiguration,
    OpenAILLMService,
    ServiceProviders,
)


# Retired. ElevenLabs no longer serves any language, so this is empty rather than
# removed: it was part of this module's public API, and callers that still test
# membership against it now correctly find that no language requires ElevenLabs.
LANGUAGES_REQUIRING_ELEVENLABS: frozenset[str] = frozenset()


def get_default_tts_provider_for_language(workflow_language: str | None) -> ServiceProviders:
    """Resolve the default TTS provider for a given workflow language.

    Gemini covers every supported language, so the language no longer changes
    the provider. The parameter is kept so callers don't have to change.
    """
    return ServiceProviders.GOOGLE


# Mapping of service to (default provider enum, default configuration class).
_DEFAULTS = {
    "llm": (ServiceProviders.OPENAI, OpenAILLMService),
    "tts": (ServiceProviders.GOOGLE, GeminiTTSConfiguration),
    "stt": (ServiceProviders.DEEPGRAM, DeepgramSTTConfiguration),
}

# Public mapping of service name -> default provider
DEFAULT_SERVICE_PROVIDERS = {
    field: provider for field, (provider, _) in _DEFAULTS.items()
}

__all__ = [
    "DEFAULT_SERVICE_PROVIDERS",
    "LANGUAGES_REQUIRING_ELEVENLABS",
    "get_default_tts_provider_for_language",
]
