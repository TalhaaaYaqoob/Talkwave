from typing import Dict, Optional, TypedDict

import openai
from deepgram import (
    DeepgramClient,
    LiveOptions,
)
from groq import Groq

# try:
#     from pyneuphonic import Neuphonic
# except ImportError:
#     Neuphonic = None
from api.schemas.user_configuration import (
    UserConfiguration,
)
from api.services.configuration.registry import ServiceConfig, ServiceProviders


class APIKeyStatus(TypedDict):
    model: str
    message: str


class APIKeyStatusResponse(TypedDict):
    status: list[APIKeyStatus]


class UserConfigurationValidator:
    def __init__(self):
        self._provider_api_key_validity_status: Dict[str, bool] = {}
        self._validator_map = {
            ServiceProviders.OPENAI.value: self._check_openai_api_key,
            ServiceProviders.DEEPGRAM.value: self._check_deepgram_api_key,
            ServiceProviders.GROQ.value: self._check_groq_api_key,
            ServiceProviders.ELEVENLABS.value: self._validate_elevenlabs_api_key,
            ServiceProviders.GOOGLE.value: self._check_google_api_key,
            ServiceProviders.AZURE.value: self._check_azure_api_key,
            ServiceProviders.CARTESIA.value: self._check_cartesia_api_key,
            ServiceProviders.DOGRAH.value: self._check_dograh_api_key,
        }

    async def validate(self, configuration: UserConfiguration) -> APIKeyStatusResponse:
        status_list = []

        status_list.extend(self._validate_service(configuration.llm, "llm"))
        status_list.extend(self._validate_service(configuration.stt, "stt"))
        status_list.extend(self._validate_service(configuration.tts, "tts"))

        if status_list:
            raise ValueError(status_list)

        return {"status": [{"model": "all", "message": "ok"}]}

    _ENV_FALLBACKS = {
        "llm": ["OPENAI_API_KEY", "GROQ_API_KEY"],
        "stt": ["DEEPGRAM_API_KEY", "GOOGLE_API_KEY"],
        # Cartesia is checked first because it's the platform's default TTS
        # provider (Sonic-3.5, 42 languages, ~3x cheaper than ElevenLabs).
        # ElevenLabs is kept as a strong fallback for Arabic / Chinese.
        "tts": ["CARTESIA_API_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY"],
    }

    def _validate_service(
        self, service_config: Optional[ServiceConfig], service_name: str
    ) -> list[APIKeyStatus]:
        """Validate a service configuration and return any error statuses."""
        if not service_config:
            import os
            for env_key in self._ENV_FALLBACKS.get(service_name, []):
                if os.getenv(env_key):
                    return []
            return [{"model": service_name, "message": "API key is missing"}]

        provider = service_config.provider
        api_key = service_config.api_key

        if not self._check_api_key(provider, api_key):
            return [{"model": service_name, "message": f"Invalid {provider} API key"}]

        return []

    def _check_api_key(self, provider: str, api_key: str) -> bool:
        """Check if an API key for a provider is valid."""
        validator = self._validator_map.get(provider)
        if not validator:
            return False

        return validator(provider, api_key)

    def _check_openai_api_key(self, model: str, api_key: str) -> bool:
        if model in self._provider_api_key_validity_status:
            return self._provider_api_key_validity_status[model]

        client = openai.OpenAI(api_key=api_key)
        try:
            client.models.list()
            self._provider_api_key_validity_status[model] = True
        except openai.AuthenticationError:
            self._provider_api_key_validity_status[model] = False
        return self._provider_api_key_validity_status[model]

    def _check_deepgram_api_key(self, model: str, api_key: str) -> bool:
        if model in self._provider_api_key_validity_status:
            return self._provider_api_key_validity_status[model]

        deepgram = DeepgramClient(api_key)
        dg_connection = deepgram.listen.websocket.v("1")

        try:
            options = LiveOptions(
                model="nova-2",
                language="en-US",
                smart_format=True,
            )

            connected = dg_connection.start(options)
            self._provider_api_key_validity_status[model] = connected
        finally:
            dg_connection.finish()
        return self._provider_api_key_validity_status[model]

    def _check_groq_api_key(self, model: str, api_key: str) -> bool:
        if model in self._provider_api_key_validity_status:
            return self._provider_api_key_validity_status[model]

        client = Groq(api_key=api_key)
        try:
            client.models.list()
            self._provider_api_key_validity_status[model] = True
        except Exception:
            self._provider_api_key_validity_status[model] = False
        return self._provider_api_key_validity_status[model]

    def _validate_elevenlabs_api_key(self, model: str, api_key: str) -> bool:
        return True

    def _check_google_api_key(self, model: str, api_key: str) -> bool:
        return True

    def _check_azure_api_key(self, model: str, api_key: str) -> bool:
        return True

    def _check_cartesia_api_key(self, model: str, api_key: str) -> bool:
        return True

    def _check_dograh_api_key(self, model: str, api_key: str) -> bool:
        return True

    # def _check_neuphonic_api_key(self, model: str, api_key: str) -> bool:
    #     if not Neuphonic:
    #         self._provider_api_key_validity_status[model] = False
    #         return self._provider_api_key_validity_status[model]

    #     if model in self._provider_api_key_validity_status:
    #         return self._provider_api_key_validity_status[model]

    #     client = Neuphonic(api_key=api_key)
    #     try:
    #         response = client.voices.list()  # get's all available voices
    #         voices = response.data["voices"]
    #         self._provider_api_key_validity_status[model] = True
    #     except Exception:
    #         self._provider_api_key_validity_status[model] = False

    #     return self._provider_api_key_validity_status[model]
