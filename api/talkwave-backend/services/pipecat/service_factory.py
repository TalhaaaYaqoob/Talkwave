from typing import TYPE_CHECKING, Optional, Dict, List
import os
import re

from fastapi import HTTPException
from loguru import logger

from api.constants import MPS_API_URL
from api.services.configuration.registry import GeminiVoice, ServiceProviders


# =====================================================================
# DEEPGRAM CONFIGURATION - Intelligent STT Setup
# =====================================================================

# Language code mappings for workflow configuration
# Maps workflow language names to Deepgram language codes
LANGUAGE_TO_DEEPGRAM_CODE: Dict[str, str] = {
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
    "Dutch": "nl",
    "Russian": "ru",
    "Turkish": "tr",
    "Polish": "pl",
    "Swedish": "sv",
    "Norwegian": "no",
    "Danish": "da",
    "Finnish": "fi",
    "Indonesian": "id",
    "Malay": "ms",
    "Vietnamese": "vi",
    "Thai": "th",
    "Ukrainian": "uk",
    "Romanian": "ro",
    "Czech": "cs",
    "Greek": "el",
    "Hebrew": "he",
    "Tamil": "ta",
    "Telugu": "te",
    "Bengali": "bn",
    "Urdu": "ur",
}

# Maps workflow language names to OpenAI locale names
LANGUAGE_TO_OPENAI_LOCALE: Dict[str, str] = {
    "English": "English",
    "Arabic": "Arabic",
    "Hindi": "Hindi",
    "French": "French",
    "German": "German",
    "Korean": "Korean",
    "Spanish": "Spanish",
    "Portuguese": "Portuguese",
    "Italian": "Italian",
    "Japanese": "Japanese",
    "Chinese": "Chinese (Mandarin)",
}

# =====================================================================
# DEEPGRAM MODEL SELECTION - SMART LANGUAGE-AWARE CONFIGURATION
# =====================================================================
# 
# This configuration maps:
# 1. Use cases → Specialized models
# 2. Models → Supported languages (from official Deepgram docs)
#
# Logic: If specialized model supports the workflow language, use it.
#        Otherwise, fall back to nova-3 (best multilingual model).
# =====================================================================

# Mapping: Model → List of supported Deepgram language codes
# From official Deepgram docs: https://developers.deepgram.com/docs/models-languages-overview
DEEPGRAM_MODEL_LANGUAGES: Dict[str, List[str]] = {
    # Flux - English only, conversational voice agents with native turn detection
    "flux-general-en": [
        "en", "en-US", "en-AU", "en-CA", "en-GB", "en-IE", "en-IN", "en-NZ",
    ],
    
    # Flux Multilingual - 10 languages with same turn-aware intelligence as flux-general-en
    "flux-general-multi": [
        "en", "en-US", "en-AU", "en-CA", "en-GB", "en-IE", "en-IN", "en-NZ",
        "es", "es-419", "es-ES",
        "fr", "fr-CA", "fr-FR",
        "de", "de-DE",
        "hi", "hi-Latn",
        "ru",
        "pt", "pt-BR", "pt-PT",
        "ja",
        "it",
        "nl",
    ],
    
    # Nova-3 General - Multilingual (10 languages + Arabic dialects)
    "nova-3": [
        "multi",  # Auto-detect multilingual
        "en", "en-US", "en-AU", "en-CA", "en-GB", "en-IE", "en-IN", "en-NZ",  # English
        "ar", "ar-AE", "ar-SA", "ar-QA", "ar-KW", "ar-SY", "ar-LB", "ar-PS", "ar-JO", "ar-EG",  # Arabic
        "es", "es-419", "es-ES",  # Spanish
        "fr", "fr-CA", "fr-FR",  # French
        "de", "de-DE",  # German
        "hi", "hi-Latn",  # Hindi
        "ru",  # Russian
        "pt", "pt-BR", "pt-PT",  # Portuguese
        "ja",  # Japanese
        "it",  # Italian
        "nl",  # Dutch
    ],
    
    # Nova-3 Medical - English only (but best for medical terminology)
    "nova-3-medical": [
        "en", "en-US", "en-AU", "en-CA", "en-GB", "en-IE", "en-IN", "en-NZ",
    ],
    
    # Nova-2 General - Multilingual (30+ languages)
    "nova-2": [
        "multi",  # Spanish + English auto-detect
        "en", "en-US", "en-AU", "en-CA", "en-GB", "en-IE", "en-IN", "en-NZ",
        "ar",  # Arabic (limited support compared to Nova-3)
        "es", "es-419", "es-ES",
        "fr", "fr-CA", "fr-FR",
        "de", "de-DE",
        "hi", "hi-Latn",
        "pt", "pt-BR", "pt-PT",
        "ja", "ko", "zh", "zh-CN", "zh-TW",  # Asian languages
        "it", "nl", "pl", "ru", "sv", "tr", "uk",  # European languages
    ],
    
    # Nova-2 Specialized - English only
    "nova-2-medical": ["en", "en-US"],
    "nova-2-finance": ["en", "en-US"],
    "nova-2-phonecall": ["en", "en-US"],
    "nova-2-meeting": ["en", "en-US"],
    "nova-2-conversationalai": ["en", "en-US"],
    "nova-2-voicemail": ["en", "en-US"],
    "nova-2-video": ["en", "en-US"],
    "nova-2-drivethru": ["en", "en-US"],
    "nova-2-automotive": ["en", "en-US"],
    "nova-2-atc": ["en", "en-US"],
}

# Mapping: Use case keywords → Best specialized model for that use case
# NOTE: All use cases now map to nova-3 (recommended by Deepgram for most use cases).
# Nova-2 specialized models (nova-2-conversationalai, nova-2-phonecall, etc.) 
# can return HTTP 400 on some Deepgram plans and are superseded by Nova-3.
# Only nova-3-medical is kept as a specialized model (officially supported).
DEEPGRAM_USE_CASE_MODELS: Dict[str, str] = {
    # Medical - nova-3-medical is an officially supported specialized model
    "medical": "nova-3-medical",
    "healthcare": "nova-3-medical",
    "health": "nova-3-medical",
    "hospital": "nova-3-medical",
    "clinic": "nova-3-medical",
    "doctor": "nova-3-medical",
    "patient": "nova-3-medical",
    "pharmacy": "nova-3-medical",
    # Finance - use nova-3 (nova-2-finance is deprecated/restricted)
    "finance": "nova-3",
    "banking": "nova-3",
    "investment": "nova-3",
    "trading": "nova-3",
    "insurance": "nova-3",
    "loan": "nova-3",
    # Phone/Call Center - use nova-3 (nova-2-phonecall is deprecated/restricted)
    "phonecall": "nova-3",
    "phone": "nova-3",
    "call_center": "nova-3",
    "customer_service": "nova-3",
    "support": "nova-3",
    # Meeting/Conference - use nova-3 (nova-2-meeting is deprecated/restricted)
    "meeting": "nova-3",
    "conference": "nova-3",
    # Conversational AI - use nova-3 (nova-2-conversationalai is deprecated/restricted)
    "conversational": "nova-3",
    "assistant": "nova-3",
    "chatbot": "nova-3",
    "voicebot": "nova-3",
}

# Default model - Nova-3 is best for multilingual, multi-speaker, noisy audio
DEEPGRAM_DEFAULT_MODEL = "nova-3"

# Languages supported by flux-general-multi (base codes for quick lookup)
FLUX_MULTI_BASE_LANGUAGES = {"en", "es", "fr", "de", "hi", "ru", "pt", "ja", "it", "nl"}
# Endpointing: 200ms detects end-of-speech faster while still safe for
# natural pauses (which are 100-300ms).  300ms was adding ~100ms of
# unnecessary latency per turn.  25ms was too aggressive and broke words.
DEEPGRAM_ENDPOINTING_MS = 200
# Utterance end: fires after 1000ms of silence following the last finalized
# word.  Acts as a reliable "user is done" signal for the pipeline aggregator.
DEEPGRAM_UTTERANCE_END_MS = 1000


def model_supports_language(model: str, language_code: str) -> bool:
    """
    Check if a Deepgram model supports a specific language code.
    
    Args:
        model: Deepgram model name (e.g., "nova-3-medical")
        language_code: Deepgram language code (e.g., "ar", "en", "multi")
        
    Returns:
        True if model supports the language, False otherwise
    """
    if model not in DEEPGRAM_MODEL_LANGUAGES:
        return False
    
    supported_languages = DEEPGRAM_MODEL_LANGUAGES[model]
    
    # Check exact match
    if language_code in supported_languages:
        return True
    
    # Check base language (e.g., "en" for "en-US")
    base_lang = language_code.split("-")[0] if "-" in language_code else language_code
    if base_lang in supported_languages:
        return True
    
    return False

# Keywords to boost recognition for specific domains
DEEPGRAM_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "medical": [
        "appointment", "prescription", "diagnosis", "symptoms", "medication",
        "doctor", "nurse", "hospital", "clinic", "patient", "treatment",
        "blood pressure", "heart rate", "temperature", "allergy", "insurance"
    ],
    "finance": [
        "account", "balance", "transaction", "transfer", "deposit", "withdrawal",
        "interest rate", "loan", "mortgage", "credit", "debit", "investment",
        "portfolio", "stocks", "bonds", "dividend", "statement"
    ],
    "restaurant": [
        "reservation", "booking", "table", "menu", "order", "delivery",
        "takeout", "cuisine", "appetizer", "entree", "dessert", "beverage"
    ],
    "hotel": [
        "reservation", "booking", "check-in", "checkout", "room", "suite",
        "amenities", "concierge", "housekeeping", "breakfast"
    ],
    "retail": [
        "order", "shipping", "delivery", "return", "refund", "exchange",
        "inventory", "product", "price", "discount", "coupon"
    ],
}


def detect_use_case_from_workflow(
    workflow_name: str = "", 
    use_case: str = "", 
    global_prompt: str = "",
    language: str = "",
    language_code: str = ""
) -> str:
    """
    Detect the use case/domain from workflow metadata and select optimal Deepgram model.
    
    SMART MODEL SELECTION LOGIC:
    1. Detect use case from workflow (medical, finance, etc.)
    2. Find the best specialized model for that use case
    3. Check if that specialized model supports the workflow language
       - If YES → Use the specialized model
       - If NO → Fall back to nova-3 (best multilingual model)
    
    Args:
        workflow_name: Name of the workflow
        use_case: Use case description from workflow
        global_prompt: Global prompt from workflow
        language: Workflow language name (e.g., "Arabic", "English")
        language_code: Deepgram language code (e.g., "ar", "en", "multi")
        
    Returns:
        Deepgram model name optimized for the detected use case and language
    """
    # Combine all text for analysis
    combined_text = f"{workflow_name} {use_case} {global_prompt}".lower()
    
    logger.info("=" * 60)
    logger.info("[DEEPGRAM STT] SMART MODEL SELECTION")
    logger.info("=" * 60)
    logger.info(f"[DEEPGRAM STT] Workflow name: {workflow_name}")
    logger.info(f"[DEEPGRAM STT] Use case: {use_case}")
    logger.info(f"[DEEPGRAM STT] Language: {language} (code: {language_code})")
    logger.info(f"[DEEPGRAM STT] Global prompt (first 100 chars): {global_prompt[:100]}..." if global_prompt else "[DEEPGRAM STT] Global prompt: None")
    
    # Step 1: Detect use case keywords and find best specialized model
    detected_keywords = []
    detected_model = None
    
    for keyword, model in DEEPGRAM_USE_CASE_MODELS.items():
        if keyword in combined_text:
            detected_keywords.append(keyword)
            if detected_model is None:
                detected_model = model
    
    if detected_keywords:
        logger.info(f"[DEEPGRAM STT] ✓ Detected use case keywords: {detected_keywords}")
        logger.info(f"[DEEPGRAM STT] ✓ Best specialized model for use case: {detected_model}")
        
        # Step 2: Check if specialized model supports the workflow language
        if model_supports_language(detected_model, language_code):
            logger.info(f"[DEEPGRAM STT] ✓ Model '{detected_model}' SUPPORTS language '{language_code}'")
            logger.info(f"[DEEPGRAM STT] ✓ USING SPECIALIZED MODEL: {detected_model}")
            return detected_model
        else:
            logger.info(f"[DEEPGRAM STT] ⚠️ Model '{detected_model}' does NOT support language '{language_code}'")
            logger.info(f"[DEEPGRAM STT] ⚠️ Supported languages for {detected_model}: {DEEPGRAM_MODEL_LANGUAGES.get(detected_model, [])}")
            logger.info(f"[DEEPGRAM STT] ✓ Falling back to nova-3 (best multilingual model)")
            return DEEPGRAM_DEFAULT_MODEL
    
    # Step 3: No specific use case detected - use default model
    logger.info(f"[DEEPGRAM STT] ✗ No specific use case keywords detected")
    logger.info(f"[DEEPGRAM STT] ✓ Using default model: {DEEPGRAM_DEFAULT_MODEL} (best multilingual)")
    return DEEPGRAM_DEFAULT_MODEL


def get_domain_keywords(workflow_name: str = "", use_case: str = "", global_prompt: str = "") -> List[str]:
    """
    Get domain-specific keywords to boost Deepgram recognition accuracy.
    
    Args:
        workflow_name: Name of the workflow
        use_case: Use case description from workflow
        global_prompt: Global prompt from workflow
        
    Returns:
        List of keywords to boost recognition
    """
    combined_text = f"{workflow_name} {use_case} {global_prompt}".lower()
    keywords = []
    matched_domains = []
    
    for domain, domain_keywords in DEEPGRAM_DOMAIN_KEYWORDS.items():
        if domain in combined_text:
            keywords.extend(domain_keywords)
            matched_domains.append(domain)
    
    # Remove duplicates
    unique_keywords = list(set(keywords))
    
    if matched_domains:
        logger.info(f"[DEEPGRAM STT] ✓ Matched domains: {matched_domains}")
        logger.info(f"[DEEPGRAM STT] ✓ Adding {len(unique_keywords)} domain keywords for better recognition")
    else:
        logger.info("[DEEPGRAM STT] ✗ No domain keywords matched")
    
    return unique_keywords
from pipecat.services.azure.llm import AzureLLMService
from pipecat.services.cartesia.stt import CartesiaSTTService
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.cerebras.llm import CerebrasLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService, LiveOptions
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.dograh.llm import DograhLLMService
from pipecat.services.dograh.stt import DograhSTTService
from pipecat.services.dograh.tts import DograhTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.google.tts import GeminiTTSService
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.text.xml_function_tag_filter import XMLFunctionTagFilter

from api.services.pipecat.guardrails import MarkdownTextFilter
from api.services.pipecat.tts_accents import resolve_accent
from api.services.pipecat.voice_text_filter import VoiceTextFilter

if TYPE_CHECKING:
    from api.services.pipecat.audio_config import AudioConfig


def create_stt_service(
    user_config,
    workflow_language: Optional[str] = None,
    workflow_name: str = "",
    use_case: str = "",
    global_prompt: str = "",
    audio_config: "AudioConfig | None" = None,
):
    """
    Create and return appropriate STT service based on user configuration.
    
    Intelligently configures Deepgram based on:
    - Workflow language (uses specific language code or multilingual)
    - Use case detection (medical, finance, etc. for specialized models)
    - Domain keywords (boosts recognition of industry-specific terms)
    
    Args:
        user_config: User service configuration
        workflow_language: Language configured in workflow (e.g., "Arabic", "English")
        workflow_name: Name of the workflow for use case detection
        use_case: Use case description for model selection
        global_prompt: Global prompt for context analysis
    """
    if user_config.stt is None:
        raise HTTPException(
            status_code=400,
            detail="STT (Speech-to-Text) service not configured. Please go to Settings > Service Configuration to set up your STT provider (e.g., Deepgram, OpenAI, Cartesia)."
        )
    if user_config.stt.provider == ServiceProviders.DEEPGRAM.value:
        # =====================================================================
        # INTELLIGENT DEEPGRAM CONFIGURATION
        # =====================================================================
        
        # CONFIGURE LANGUAGE FIRST (needed for model selection)
        if workflow_language and workflow_language in LANGUAGE_TO_DEEPGRAM_CODE:
            language_code = LANGUAGE_TO_DEEPGRAM_CODE[workflow_language]
            logger.info(f"Using specific language: {workflow_language} ({language_code})")
        else:
            language_code = "multi"
            logger.info("Using multilingual auto-detection (language=multi)")
        
        language = language_code
        is_english = language.startswith("en")
        
        stt_sample_rate = audio_config.pipeline_sample_rate if audio_config else 16000

        # =====================================================================
        # MODEL SELECTION STRATEGY:
        #   1. English         → flux-general-en  (best English accuracy)
        #   2. Flux-supported  → flux-general-multi + language_hint
        #                        (native turn detection for es/fr/de/hi/ru/pt/ja/it/nl)
        #   3. Unsupported     → nova-3  (Arabic, Chinese, etc.)
        # =====================================================================
        base_lang = language_code.split("-")[0] if "-" in language_code else language_code
        use_flux_multi = (not is_english) and (base_lang in FLUX_MULTI_BASE_LANGUAGES)

        if is_english or use_flux_multi:
            flux_model = "flux-general-en" if is_english else "flux-general-multi"
            keywords = get_domain_keywords(workflow_name, use_case, global_prompt)
            keyterm_list = keywords[:20] if keywords else []

            hint_list = [base_lang] if use_flux_multi else []
            
            # Flux turn-taking tuning:
            #   - eot_threshold=0.7  → declare turn-end at 70% confidence
            #     (was 0.9 — too conservative, the model would wait until it
            #     was almost certain, adding 1–2s of dead air).
            #   - eager_eot_threshold=0.3 → start LLM prefetch as soon as a
            #     turn boundary seems possible. The LLM response is discarded
            #     if the user keeps talking; this hides ~400ms of TTFT.
            #   - eot_timeout_ms=1500 → hard cap forced end-of-turn at 1.5s
            #     of post-speech silence (was 5000ms which is the dominant
            #     cause of "the agent feels slow / laggy" perception).
            flux_params = DeepgramFluxSTTService.InputParams(
                eot_threshold=0.7,
                eager_eot_threshold=0.3,
                eot_timeout_ms=1500,
                keyterm=keyterm_list,
                language_hint=hint_list,
            )
            
            logger.info("=" * 60)
            logger.info(f"[DEEPGRAM STT] FINAL CONFIGURATION (User Config) — FLUX {'MULTI' if use_flux_multi else 'EN'}")
            logger.info("=" * 60)
            logger.info(f"[DEEPGRAM STT] Model: {flux_model}")
            logger.info(f"[DEEPGRAM STT] Endpoint: /v2/listen")
            logger.info(f"[DEEPGRAM STT] Language: {language}")
            if hint_list:
                logger.info(f"[DEEPGRAM STT] Language Hints: {hint_list}")
            logger.info(f"[DEEPGRAM STT] Sample Rate: {stt_sample_rate}")
            logger.info(f"[DEEPGRAM STT] Workflow Language Input: {workflow_language}")
            logger.info(f"[DEEPGRAM STT] Encoding: linear16")
            logger.info(f"[DEEPGRAM STT] EOT Threshold: {flux_params.eot_threshold}")
            logger.info(f"[DEEPGRAM STT] Eager EOT Threshold: {flux_params.eager_eot_threshold}")
            logger.info(f"[DEEPGRAM STT] EOT Timeout: {flux_params.eot_timeout_ms}ms")
            logger.info(f"[DEEPGRAM STT] Turn Detection: Native (Flux)")
            if keyterm_list:
                logger.info(f"[DEEPGRAM STT] Keyterms: {len(keyterm_list)} terms")
                logger.info(f"[DEEPGRAM STT] Keyterms Sample: {keyterm_list[:5]}...")
            logger.info("=" * 60)
            
            return DeepgramFluxSTTService(
                api_key=user_config.stt.api_key,
                sample_rate=stt_sample_rate,
                model=flux_model,
                params=flux_params,
            )
        
        # UNSUPPORTED BY FLUX (Arabic, Chinese, etc.): Use Nova-3
        model = detect_use_case_from_workflow(
            workflow_name=workflow_name, 
            use_case=use_case, 
            global_prompt=global_prompt, 
            language=workflow_language or "",
            language_code=language_code
        )
        
        live_options = LiveOptions(
            model=model,
            language=language,
            encoding="linear16",
            sample_rate=stt_sample_rate,
            channels=1,
            profanity_filter=False,
            endpointing=DEEPGRAM_ENDPOINTING_MS,
            utterance_end_ms=DEEPGRAM_UTTERANCE_END_MS,
            interim_results=True,
            smart_format=True,
            punctuate=True,
            diarize=False,
        )
        
        logger.info("=" * 60)
        logger.info("[DEEPGRAM STT] FINAL CONFIGURATION (User Config) — Nova-3 (Flux unsupported language)")
        logger.info("=" * 60)
        logger.info(f"[DEEPGRAM STT] Model: {model}")
        logger.info(f"[DEEPGRAM STT] Language: {language}")
        logger.info(f"[DEEPGRAM STT] Sample Rate: {stt_sample_rate}")
        logger.info(f"[DEEPGRAM STT] Workflow Language Input: {workflow_language}")
        logger.info(f"[DEEPGRAM STT] Encoding: linear16")
        logger.info(f"[DEEPGRAM STT] Channels: 1")
        logger.info(f"[DEEPGRAM STT] Smart Format: True")
        logger.info(f"[DEEPGRAM STT] Punctuate: True")
        logger.info(f"[DEEPGRAM STT] Endpointing: {DEEPGRAM_ENDPOINTING_MS}ms")
        logger.info(f"[DEEPGRAM STT] Utterance End: {DEEPGRAM_UTTERANCE_END_MS}ms")
        logger.info(f"[DEEPGRAM STT] Keyterms: DISABLED (non-English language)")
        logger.info("=" * 60)
        
        return DeepgramSTTService(
            live_options=live_options,
            api_key=user_config.stt.api_key,
            audio_passthrough=False,
        )
    elif user_config.stt.provider == ServiceProviders.OPENAI.value:
        return OpenAISTTService(
            api_key=user_config.stt.api_key,
            model=user_config.stt.model.value,
            language=None,  # Auto-detect language for multilingual support
            audio_passthrough=False,  # Disable passthrough since audio is buffered separately
        )
    elif user_config.stt.provider == ServiceProviders.CARTESIA.value:
        return CartesiaSTTService(
            api_key=user_config.stt.api_key,
            audio_passthrough=False,  # Disable passthrough since audio is buffered separately
        )
    elif user_config.stt.provider == ServiceProviders.DOGRAH.value:
        base_url = MPS_API_URL.replace("http://", "ws://").replace("https://", "wss://")
        return DograhSTTService(
            base_url=base_url,
            api_key=user_config.stt.api_key,
            model=user_config.stt.model.value,
            audio_passthrough=False,  # Disable passthrough since audio is buffered separately
        )
    else:
        raise HTTPException(
            status_code=400, detail=f"Invalid STT provider {user_config.stt.provider}"
        )


def create_tts_service(
    user_config,
    audio_config: "AudioConfig",
    workflow_language: Optional[str] = None,
    accent_id: Optional[str] = None,
):
    """Create and return appropriate TTS service based on user configuration

    Args:
        user_config: User configuration containing TTS settings
        audio_config: Pipeline audio configuration
        workflow_language: Workflow language, so Gemini renders the right locale
        accent_id: Workflow accent selection, passed through to Gemini's style
            prompt. Without it Gemini falls back to the language's default accent.
    """
    if user_config.tts is None:
        raise HTTPException(
            status_code=400,
            detail="TTS (Text-to-Speech) service not configured. Please go to Settings > Service Configuration to set up your TTS provider (e.g., Gemini, Cartesia, Deepgram)."
        )
    # Create function call filter to prevent TTS from speaking function call tags.
    # Includes JSON patterns for smaller models (e.g. llama3.1-8b) that emit
    # function calls as raw JSON text instead of proper tool calls.
    xml_function_tag_filter = XMLFunctionTagFilter(
        custom_patterns=[
            r'\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\}',
            r'\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*"[^"]*"\}',
        ]
    )
    if user_config.tts.provider == ServiceProviders.DEEPGRAM.value:
        # Pass sample_rate so pre-warming can connect before StartFrame sets it.
        # Without this, prewarm sends sample_rate=None → HTTP 400.
        tts_sample_rate = audio_config.pipeline_sample_rate if audio_config else 16000
        return DeepgramTTSService(
            api_key=user_config.tts.api_key,
            voice=user_config.tts.voice.value,
            sample_rate=tts_sample_rate,
            text_filters=[VoiceTextFilter(), MarkdownTextFilter(), xml_function_tag_filter],
        )
    elif user_config.tts.provider == ServiceProviders.OPENAI.value:
        return OpenAITTSService(
            api_key=user_config.tts.api_key,
            model=user_config.tts.model.value,
            text_filters=[VoiceTextFilter(), MarkdownTextFilter(), xml_function_tag_filter],
        )
    elif user_config.tts.provider == ServiceProviders.GOOGLE.value:
        # Gemini TTS voices are plain voice names ("Kore"), optionally stored as
        # "Name - voice_id" by the settings UI.
        voice_raw = user_config.tts.voice if isinstance(user_config.tts.voice, str) else str(user_config.tts.voice)
        voice_id = voice_raw.split(" - ")[1] if " - " in voice_raw else voice_raw
        return create_gemini_tts_from_workflow(
            voice_id=voice_id,
            accent_id=accent_id,
            workflow_language=workflow_language,
            user_config=user_config,
            audio_config=audio_config,
        )
    elif user_config.tts.provider == ServiceProviders.ELEVENLABS.value:
        # ElevenLabs has been retired as a TTS provider. Workflows whose saved
        # settings still name it are served by Gemini instead of failing.
        logger.warning(
            "[TTS] Stored config requests ElevenLabs, which is no longer supported — using Gemini TTS"
        )
        return create_gemini_tts_from_workflow(
            accent_id=accent_id,
            workflow_language=workflow_language,
            audio_config=audio_config,
        )
    elif user_config.tts.provider == ServiceProviders.CARTESIA.value:
        # Cartesia Sonic-3.5 voice IDs are stored as "Name - <uuid>" or just "<uuid>"
        voice_raw = user_config.tts.voice if isinstance(user_config.tts.voice, str) else str(user_config.tts.voice)
        voice_id = voice_raw.split(" - ")[1] if " - " in voice_raw else voice_raw
        tts_sample_rate = audio_config.pipeline_sample_rate if audio_config else 16000
        model_value = user_config.tts.model.value if hasattr(user_config.tts.model, "value") else str(user_config.tts.model)
        speed_value = getattr(user_config.tts, "speed", 1.0)
        return CartesiaTTSService(
            api_key=user_config.tts.api_key,
            voice_id=voice_id,
            model=model_value,
            sample_rate=tts_sample_rate,
            params=CartesiaTTSService.InputParams(
                language=Language.EN,
                generation_config=GenerationConfig(speed=speed_value),
            ),
            text_filters=[VoiceTextFilter(), MarkdownTextFilter(), xml_function_tag_filter],
        )
    elif user_config.tts.provider == ServiceProviders.DOGRAH.value:
        # Convert HTTP URL to WebSocket URL for TTS
        base_url = MPS_API_URL.replace("http://", "ws://").replace("https://", "wss://")
        # Handle both enum and string values for model and voice
        return DograhTTSService(
            base_url=base_url,
            api_key=user_config.tts.api_key,
            model=user_config.tts.model.value,
            voice=user_config.tts.voice.value,
            text_filters=[VoiceTextFilter(), MarkdownTextFilter(), xml_function_tag_filter],
        )
    else:
        raise HTTPException(
            status_code=400, detail=f"Invalid TTS provider {user_config.tts.provider}"
        )


def create_llm_service(user_config):
    """Create and return appropriate LLM service based on user configuration"""
    if user_config.llm is None:
        raise HTTPException(
            status_code=400,
            detail="LLM (Language Model) service not configured. Please go to Settings > Service Configuration to set up your LLM provider (e.g., OpenAI, Groq, Google, Azure)."
        )
    if user_config.llm.provider == ServiceProviders.OPENAI.value:
        if "gpt-5" in user_config.llm.model.value:
            return OpenAILLMService(
                api_key=user_config.llm.api_key,
                model=user_config.llm.model.value,
                params=OpenAILLMService.InputParams(
                    reasoning_effort="minimal", verbosity="low"
                ),
            )
        else:
            return OpenAILLMService(
                api_key=user_config.llm.api_key,
                model=user_config.llm.model.value,
                params=OpenAILLMService.InputParams(temperature=0.1),
            )
    elif user_config.llm.provider == ServiceProviders.GROQ.value:
        print(
            f"Creating Groq LLM service with API key: {user_config.llm.api_key} and model: {user_config.llm.model.value}"
        )
        return GroqLLMService(
            api_key=user_config.llm.api_key,
            model=user_config.llm.model.value,
            params=OpenAILLMService.InputParams(temperature=0.1),
        )
    elif user_config.llm.provider == ServiceProviders.GOOGLE.value:
        # Use the correct InputParams class for Google to avoid propagating OpenAI-specific
        # NOT_GIVEN sentinels that break Pydantic validation in GoogleLLMService.
        return GoogleLLMService(
            api_key=user_config.llm.api_key,
            model=user_config.llm.model.value,
            params=GoogleLLMService.InputParams(temperature=0.1),
        )
    elif user_config.llm.provider == ServiceProviders.AZURE.value:
        return AzureLLMService(
            api_key=user_config.llm.api_key,
            endpoint=user_config.llm.endpoint,
            model=user_config.llm.model.value,  # Azure uses deployment name as model
            params=AzureLLMService.InputParams(temperature=0.1),
        )
    elif user_config.llm.provider == ServiceProviders.CEREBRAS.value:
        cerebras_model = user_config.llm.model.value
        # gpt-oss models are reasoning models that use OpenAI's "harmony" format
        # with a separate analysis channel. Without a strict cap + reasoning_effort=low,
        # the analysis channel can leak into the spoken output (chain-of-thought
        # narration like "We need to ask..."), and the model can run into the
        # multi-thousand-token range — disastrous for a voice call.
        is_reasoning_model = "gpt-oss" in cerebras_model.lower()
        extra: dict = {}
        if is_reasoning_model:
            extra["reasoning_effort"] = "low"
        return CerebrasLLMService(
            api_key=user_config.llm.api_key,
            model=cerebras_model,
            params=CerebrasLLMService.InputParams(
                temperature=0.1,
                max_completion_tokens=180,
                max_tokens=180,
                extra=extra,
            ),
        )
    elif user_config.llm.provider == ServiceProviders.DOGRAH.value:
        return DograhLLMService(
            base_url=f"{MPS_API_URL}/api/v1/llm",
            api_key=user_config.llm.api_key,
            model=user_config.llm.model.value,
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid LLM provider")


# Gemini TTS prebuilt voices. Every voice speaks every supported language, so a
# single catalog serves all workflow languages — the accent is applied on top of
# the voice through the style prompt (see api.services.pipecat.tts_accents).
#
# GeminiVoice is the single source of truth and must match GEMINI_TTS_VOICES in
# ui/src/types/workflow-configurations.ts, otherwise a voice picked in the editor
# is rejected here and silently replaced by the default.
GEMINI_VALID_VOICE_IDS = {voice.value for voice in GeminiVoice}

GEMINI_DEFAULT_VOICE_ID = "Kore"  # Firm, neutral — safe default for any language

# Gemini 3.1 gives the strongest accent and style steering. Set GEMINI_TTS_MODEL
# to pin a different model, e.g. gemini-2.5-flash-tts for the GA release.
GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_TTS_MODEL") or "gemini-3.1-flash-tts-preview"


def resolve_google_tts_credentials() -> tuple[Optional[str], Optional[str]]:
    """Resolve Google Cloud credentials for Gemini TTS as (inline_json, path).

    Raises RuntimeError when nothing is configured, so the caller can fall back
    to Cartesia immediately.

    This deliberately refuses to let the Google client fall through to
    Application Default Credentials discovery. Off GCP there is no metadata
    server, and that lookup blocks the event loop for seconds before failing —
    which stalls pipeline startup and leaves the agent silent instead of
    failing over. Set GOOGLE_TTS_USE_ADC=true to allow ADC when running on GCP,
    where the metadata server answers immediately.
    """
    credentials = os.getenv("GOOGLE_TTS_CREDENTIALS")
    credentials_path = os.getenv("GOOGLE_TTS_CREDENTIALS_PATH") or os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )

    if credentials or credentials_path:
        return credentials, credentials_path

    if os.getenv("GOOGLE_TTS_USE_ADC", "").lower() in ("1", "true", "yes"):
        return None, None

    raise RuntimeError(
        "Gemini TTS has no Google Cloud credentials. Set GOOGLE_TTS_CREDENTIALS "
        "(inline service account JSON) or GOOGLE_TTS_CREDENTIALS_PATH."
    )


def create_gemini_tts_from_workflow(
    voice_id: str = GEMINI_DEFAULT_VOICE_ID,
    accent_id: Optional[str] = None,
    model: str = GEMINI_DEFAULT_MODEL,
    workflow_language: Optional[str] = None,
    user_config=None,
    audio_config: "AudioConfig | None" = None,
) -> GeminiTTSService:
    """Create the primary Gemini TTS service for workflow execution.

    The workflow's accent selection is expanded into Gemini's style prompt (its
    "director's notes"), which is how Gemini controls regional accent, pace and
    tone. Some accents also pin a more specific locale — Arabic, for instance,
    defaults to ar-EG, so the Gulf and Najdi accents request ar-001 instead.

    Gemini always synthesises at 24kHz. Rather than asking it for the pipeline
    rate (8kHz on telephony), the service runs at its native rate and the output
    transport resamples, which keeps quality high on narrowband calls.

    Authentication uses a Google Cloud service account — see
    resolve_google_tts_credentials(), which raises when none is configured so the
    caller falls back to Cartesia straight away.
    """
    # Resolved before anything else so a credentials gap fails instantly and the
    # caller can fall back, rather than stalling inside the Google client.
    credentials, credentials_path = resolve_google_tts_credentials()

    if not voice_id or voice_id not in GEMINI_VALID_VOICE_IDS:
        logger.warning(f"Invalid Gemini voice_id '{voice_id}', using default: {GEMINI_DEFAULT_VOICE_ID}")
        voice_id = GEMINI_DEFAULT_VOICE_ID

    if user_config and getattr(user_config, "tts", None):
        tts_cfg = user_config.tts
        if getattr(tts_cfg, "provider", None) == ServiceProviders.GOOGLE.value:
            cfg_model = getattr(tts_cfg, "model", None)
            if cfg_model is not None:
                model = cfg_model.value if hasattr(cfg_model, "value") else str(cfg_model)

    accent = resolve_accent(workflow_language, accent_id)
    language = accent.language or LANGUAGE_TO_PIPECAT_LANGUAGE.get(workflow_language, Language.EN)

    xml_function_tag_filter = XMLFunctionTagFilter(
        custom_patterns=[
            r'\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\}',
            r'\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*"[^"]*"\}',
        ]
    )

    logger.info(
        f"Creating Gemini TTS: voice_id={voice_id}, model={model}, "
        f"language={language.value}, accent={accent.id} ({accent.label})"
    )

    return GeminiTTSService(
        credentials=credentials,
        credentials_path=credentials_path,
        model=model,
        voice_id=voice_id,
        sample_rate=GeminiTTSService.GOOGLE_SAMPLE_RATE,
        params=GeminiTTSService.InputParams(
            language=language,
            prompt=accent.prompt,
        ),
        text_filters=[VoiceTextFilter(), MarkdownTextFilter(), xml_function_tag_filter],
    )


# Cartesia Sonic-3.5 stable agent voices (UUIDs from the Cartesia Voice Library).
# Source: https://docs.cartesia.ai/build-with-cartesia/capability-guides/choosing-a-voice
CARTESIA_VALID_VOICE_IDS = {
    "f786b574-daa5-4673-aa0c-cbe3e8534c02",  # Katie — Female, stable (default)
    "a5136bf9-224c-4d76-b823-52bd5efcffcc",  # Jameson — Male, stable
    "6f84f4b8-58a2-430c-8c79-688dad597532",  # Brooke — Female, warm
    "0418348a-0ca2-4e90-9986-800fb8b3bbc0",  # Jacqueline — Female, professional
    "7e96d5e8-9d83-4b50-86b6-ba421a86f8c2",  # Ronald — Male, calm
    "5345cf08-6f37-424d-a5d9-8ae1101b9377",  # Carson — Male, professional
}

CARTESIA_DEFAULT_VOICE_ID = "f786b574-daa5-4673-aa0c-cbe3e8534c02"  # Katie
CARTESIA_DEFAULT_MODEL = "sonic-3.5"

# Workflow language → Pipecat Language enum (used for Cartesia InputParams.language)
LANGUAGE_TO_PIPECAT_LANGUAGE: Dict[str, Language] = {
    "English": Language.EN,
    "Arabic": Language.AR,
    "Hindi": Language.HI,
    "French": Language.FR,
    "German": Language.DE,
    "Korean": Language.KO,
    "Spanish": Language.ES,
    "Portuguese": Language.PT,
    "Italian": Language.IT,
    "Japanese": Language.JA,
    "Chinese": Language.ZH,
}


def create_cartesia_tts_from_workflow(
    voice_id: str = CARTESIA_DEFAULT_VOICE_ID,
    model: str = CARTESIA_DEFAULT_MODEL,
    workflow_language: Optional[str] = None,
    user_config=None,
    audio_config: "AudioConfig | None" = None,
) -> CartesiaTTSService:
    """Create a Cartesia Sonic-3.5 TTS service using workflow + user config.

    Uses the Cartesia API key from the environment by default. If the user has
    Cartesia configured in Settings, their speed / model values take priority
    over the defaults so every tunable the user can touch in Settings is
    respected. The workflow language is passed through to Cartesia so the same
    voice ID renders correctly in the target locale (Sonic-3.5 voices are
    cross-lingual across all 42 supported languages).
    """
    import os

    api_key = (
        user_config.tts.api_key
        if user_config and getattr(user_config, "tts", None) and getattr(user_config.tts, "provider", None) == ServiceProviders.CARTESIA.value
        else os.getenv("CARTESIA_API_KEY")
    )

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Cartesia TTS is not available. CARTESIA_API_KEY not configured in environment."
        )

    if not voice_id or voice_id not in CARTESIA_VALID_VOICE_IDS:
        logger.warning(f"Invalid Cartesia voice_id '{voice_id}', using default: {CARTESIA_DEFAULT_VOICE_ID}")
        voice_id = CARTESIA_DEFAULT_VOICE_ID

    speed = 1.0
    if user_config and getattr(user_config, "tts", None):
        tts_cfg = user_config.tts
        if getattr(tts_cfg, "provider", None) == ServiceProviders.CARTESIA.value:
            cfg_speed = getattr(tts_cfg, "speed", None)
            if cfg_speed is not None:
                speed = cfg_speed
            cfg_model = getattr(tts_cfg, "model", None)
            if cfg_model is not None:
                model = cfg_model.value if hasattr(cfg_model, "value") else str(cfg_model)

    pipecat_language = (
        LANGUAGE_TO_PIPECAT_LANGUAGE.get(workflow_language, Language.EN)
        if workflow_language
        else Language.EN
    )

    xml_function_tag_filter = XMLFunctionTagFilter(
        custom_patterns=[
            r'\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\}',
            r'\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*"[^"]*"\}',
        ]
    )

    tts_sample_rate = audio_config.pipeline_sample_rate if audio_config else 16000

    logger.info(
        f"Creating Cartesia TTS: voice_id={voice_id}, model={model}, "
        f"language={pipecat_language.value}, speed={speed}, sample_rate={tts_sample_rate}"
    )

    return CartesiaTTSService(
        api_key=api_key,
        voice_id=voice_id,
        model=model,
        sample_rate=tts_sample_rate,
        params=CartesiaTTSService.InputParams(
            language=pipecat_language,
            generation_config=GenerationConfig(speed=speed),
        ),
        text_filters=[VoiceTextFilter(), MarkdownTextFilter(), xml_function_tag_filter],
    )


def create_tts_from_workflow(
    voice_id: Optional[str] = None,
    workflow_language: Optional[str] = None,
    accent_id: Optional[str] = None,
    user_config=None,
    audio_config: "AudioConfig | None" = None,
):
    """TTS factory for workflow execution.

    Gemini TTS is the primary provider for every language — it is the only one
    that can render a specific regional accent on demand (Qatari, Saudi or
    Egyptian Arabic, for example) by taking direction through a style prompt.
    Cartesia Sonic-3.5 is the fallback, used when Gemini cannot be constructed:
    missing Google Cloud credentials, an unreachable API, or a bad voice.

    `voice_id` is interpreted by the resolved provider — a Gemini voice name
    ("Kore") for Gemini, a UUID for Cartesia. A voice that doesn't belong to the
    resolved provider is replaced with that provider's default, so workflows
    still holding a legacy ElevenLabs or Cartesia voice keep working.
    """
    gemini_voice = voice_id if voice_id in GEMINI_VALID_VOICE_IDS else GEMINI_DEFAULT_VOICE_ID

    try:
        tts = create_gemini_tts_from_workflow(
            voice_id=gemini_voice,
            accent_id=accent_id,
            workflow_language=workflow_language,
            user_config=user_config,
            audio_config=audio_config,
        )
        logger.info(
            f"[TTS ROUTER] workflow_language={workflow_language} → Gemini TTS "
            f"(voice_id={gemini_voice}, accent={accent_id or 'default'})"
        )
        return tts
    except Exception as gemini_err:
        logger.warning(
            f"[TTS ROUTER] Gemini TTS unavailable ({gemini_err}) — falling back to Cartesia Sonic-3.5"
        )

    cartesia_voice = voice_id if voice_id in CARTESIA_VALID_VOICE_IDS else CARTESIA_DEFAULT_VOICE_ID
    logger.info(
        f"[TTS ROUTER] workflow_language={workflow_language} → Cartesia Sonic-3.5 "
        f"(fallback, voice_id={cartesia_voice})"
    )
    return create_cartesia_tts_from_workflow(
        voice_id=cartesia_voice,
        workflow_language=workflow_language,
        user_config=user_config,
        audio_config=audio_config,
    )


def create_deepgram_stt_from_workflow(
    workflow_language: Optional[str] = None,
    workflow_name: str = "",
    use_case: str = "",
    global_prompt: str = "",
    audio_config: "AudioConfig | None" = None,
):
    """
    Create Deepgram STT service with intelligent configuration based on workflow context.
    
    Model selection:
    - English:         flux-general-en   (best English-only accuracy)
    - Flux-supported:  flux-general-multi (es/fr/de/hi/ru/pt/ja/it/nl — native turn detection)
    - Unsupported:     nova-3            (Arabic, Chinese, etc. — endpointing-based)
    
    Features:
    - Flux models use v2 endpoint with model-integrated turn detection (~260ms EOT)
    - Flux Multilingual uses language_hint for near-monolingual accuracy
    - Nova-3 fallback for languages not yet supported by Flux
    - Domain keyword boosting for better accuracy
    
    Args:
        workflow_language: Language configured in workflow (e.g., "Arabic", "English")
        workflow_name: Name of the workflow for use case detection
        use_case: Use case description for model selection
        global_prompt: Global prompt for context analysis
    
    Returns:
        DeepgramFluxSTTService for English/Flux-supported, DeepgramSTTService for others
        
    Raises:
        HTTPException: If DEEPGRAM_API_KEY environment variable is not set
    """
    import os
    
    api_key = os.getenv("DEEPGRAM_API_KEY")
    
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Speech recognition is not available. DEEPGRAM_API_KEY not configured in environment."
        )
    
    # =====================================================================
    # INTELLIGENT DEEPGRAM CONFIGURATION
    # =====================================================================
    
    # CONFIGURE LANGUAGE FIRST (needed for model selection)
    if workflow_language and workflow_language in LANGUAGE_TO_DEEPGRAM_CODE:
        language_code = LANGUAGE_TO_DEEPGRAM_CODE[workflow_language]
        logger.info(f"Using specific language: {workflow_language} ({language_code})")
    else:
        language_code = "multi"
        logger.info("Using multilingual auto-detection (language=multi)")
    
    language = language_code
    is_english = language.startswith("en")
    
    stt_sample_rate = audio_config.pipeline_sample_rate if audio_config else 16000

    # =====================================================================
    # MODEL SELECTION STRATEGY:
    #   1. English         → flux-general-en  (best English accuracy)
    #   2. Flux-supported  → flux-general-multi + language_hint
    #                        (native turn detection for es/fr/de/hi/ru/pt/ja/it/nl)
    #   3. Unsupported     → nova-3  (Arabic, Chinese, etc.)
    # =====================================================================
    base_lang = language_code.split("-")[0] if "-" in language_code else language_code
    use_flux_multi = (not is_english) and (base_lang in FLUX_MULTI_BASE_LANGUAGES)

    if is_english or use_flux_multi:
        flux_model = "flux-general-en" if is_english else "flux-general-multi"
        keywords = get_domain_keywords(workflow_name, use_case, global_prompt)
        keyterm_list = keywords[:20] if keywords else []

        hint_list = [base_lang] if use_flux_multi else []
        
        # Same tuning as the user-config path above — fast turn detection
        # with eager LLM prefetch. See that block for parameter rationale.
        flux_params = DeepgramFluxSTTService.InputParams(
            eot_threshold=0.7,
            eager_eot_threshold=0.3,
            eot_timeout_ms=1500,
            keyterm=keyterm_list,
            language_hint=hint_list,
        )
        
        logger.info("=" * 60)
        logger.info(f"[DEEPGRAM STT] FINAL CONFIGURATION (Workflow Config) — FLUX {'MULTI' if use_flux_multi else 'EN'}")
        logger.info("=" * 60)
        logger.info(f"[DEEPGRAM STT] Model: {flux_model}")
        logger.info(f"[DEEPGRAM STT] Endpoint: /v2/listen")
        logger.info(f"[DEEPGRAM STT] Language: {language}")
        if hint_list:
            logger.info(f"[DEEPGRAM STT] Language Hints: {hint_list}")
        logger.info(f"[DEEPGRAM STT] Sample Rate: {stt_sample_rate}")
        logger.info(f"[DEEPGRAM STT] Workflow Language Input: {workflow_language}")
        logger.info(f"[DEEPGRAM STT] Encoding: linear16")
        logger.info(f"[DEEPGRAM STT] EOT Threshold: {flux_params.eot_threshold}")
        logger.info(f"[DEEPGRAM STT] Eager EOT Threshold: {flux_params.eager_eot_threshold}")
        logger.info(f"[DEEPGRAM STT] EOT Timeout: {flux_params.eot_timeout_ms}ms")
        logger.info(f"[DEEPGRAM STT] Turn Detection: Native (Flux)")
        if keyterm_list:
            logger.info(f"[DEEPGRAM STT] Keyterms: {len(keyterm_list)} terms")
            logger.info(f"[DEEPGRAM STT] Keyterms Sample: {keyterm_list[:5]}...")
        logger.info("=" * 60)
        
        return DeepgramFluxSTTService(
            api_key=api_key,
            sample_rate=stt_sample_rate,
            model=flux_model,
            params=flux_params,
        )
    
    # UNSUPPORTED BY FLUX (Arabic, Chinese, etc.): Use Nova-3
    model = detect_use_case_from_workflow(
        workflow_name=workflow_name, 
        use_case=use_case, 
        global_prompt=global_prompt, 
        language=workflow_language or "",
        language_code=language_code
    )
    
    live_options = LiveOptions(
        model=model,
        language=language,
        encoding="linear16",
        sample_rate=stt_sample_rate,
        channels=1,
        profanity_filter=False,
        endpointing=DEEPGRAM_ENDPOINTING_MS,
        utterance_end_ms=DEEPGRAM_UTTERANCE_END_MS,
        interim_results=True,
        smart_format=True,
        punctuate=True,
        diarize=False,
    )
    
    logger.info("=" * 60)
    logger.info("[DEEPGRAM STT] FINAL CONFIGURATION (Workflow Config) — Nova-3 (Flux unsupported language)")
    logger.info("=" * 60)
    logger.info(f"[DEEPGRAM STT] Model: {model}")
    logger.info(f"[DEEPGRAM STT] Language: {language}")
    logger.info(f"[DEEPGRAM STT] Sample Rate: {stt_sample_rate}")
    logger.info(f"[DEEPGRAM STT] Workflow Language Input: {workflow_language}")
    logger.info(f"[DEEPGRAM STT] Encoding: linear16")
    logger.info(f"[DEEPGRAM STT] Channels: 1")
    logger.info(f"[DEEPGRAM STT] Smart Format: True")
    logger.info(f"[DEEPGRAM STT] Punctuate: True")
    logger.info(f"[DEEPGRAM STT] Endpointing: {DEEPGRAM_ENDPOINTING_MS}ms")
    logger.info(f"[DEEPGRAM STT] Utterance End: {DEEPGRAM_UTTERANCE_END_MS}ms")
    logger.info(f"[DEEPGRAM STT] Keyterms: DISABLED (non-English language)")
    logger.info("=" * 60)
    
    return DeepgramSTTService(
        live_options=live_options,
        api_key=api_key,
        audio_passthrough=False,
    )


def create_openai_llm_from_env(user_config=None):
    """Create an LLM service from environment variables.

    Provider priority:
      1) User's configured LLM (from Settings UI)
      2) CEREBRAS_API_KEY  → CerebrasLLMService  (ultra-fast inference)
      3) OPENAI_API_KEY    → OpenAILLMService     (fallback)
    """
    import os

    # 1) User-configured key
    if user_config and user_config.llm and user_config.llm.api_key:
        api_key = user_config.llm.api_key
        model = user_config.llm.model.value if (user_config.llm.model and hasattr(user_config.llm.model, 'value')) else "gpt-4.1-nano"
        logger.info(f"Creating OpenAI LLM service from user config with model: {model}")
        return OpenAILLMService(
            api_key=api_key,
            model=model,
            params=OpenAILLMService.InputParams(temperature=0.1, max_tokens=300),
        )

    # 2) Cerebras from environment (preferred — ultra-fast inference)
    cerebras_key = os.getenv("CEREBRAS_API_KEY")
    if cerebras_key:
        model = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
        # gpt-oss is a reasoning model — cap tokens hard and force low reasoning_effort
        # so the analysis channel does not bleed into the spoken final answer and the
        # model cannot generate multi-thousand-token monologues.
        is_reasoning_model = "gpt-oss" in model.lower()
        extra: dict = {}
        if is_reasoning_model:
            extra["reasoning_effort"] = "low"
        logger.info(
            f"Creating Cerebras LLM service from environment with model: {model} "
            f"(max_completion_tokens=180, reasoning_effort={extra.get('reasoning_effort', 'default')})"
        )
        return CerebrasLLMService(
            api_key=cerebras_key,
            model=model,
            params=CerebrasLLMService.InputParams(
                temperature=0.1,
                max_completion_tokens=180,
                max_tokens=180,
                extra=extra,
            ),
        )

    # 3) OpenAI from environment (fallback)
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        model = "gpt-4.1-nano"
        logger.info(f"Creating OpenAI LLM service from environment with model: {model}")
        return OpenAILLMService(
            api_key=openai_key,
            model=model,
            params=OpenAILLMService.InputParams(temperature=0.1, max_tokens=300),
        )

    raise HTTPException(
        status_code=500,
        detail="No LLM available. Set CEREBRAS_API_KEY or OPENAI_API_KEY in environment, or configure your LLM in Settings → Service Configuration."
    )


def create_gemini_live_service(
    user_config=None, 
    voice_id: str = "Charon",
    workflow_language: str = "English",
) -> GeminiLiveLLMService:
    """
    Create and return a Gemini Live LLM service for realtime voice mode.
    
    The system instruction is NOT set here - it's provided by the pipecat engine
    through LLMContextFrame, which is the single source of truth for the prompt.
    This avoids an expensive disconnect/reconnect cycle that occurs when the
    init-time instruction differs from the engine's context.
    """
    import os
    
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Realtime Voice mode is not available. Server configuration missing."
        )
    
    model = "models/gemini-2.5-flash-native-audio-preview-09-2025"
    
    from google.genai.types import ThinkingConfig, EndSensitivity, StartSensitivity
    from pipecat.services.google.gemini_live.llm import (
        InputParams as GeminiInputParams,
        GeminiVADParams,
    )
    
    params = GeminiInputParams(
        thinking=ThinkingConfig(thinking_budget=0),
        vad=GeminiVADParams(
            end_sensitivity=EndSensitivity.END_SENSITIVITY_HIGH,
            silence_duration_ms=400,
        ),
    )
    
    logger.info(f"Creating Gemini Live service with model: {model}, voice: {voice_id}, language: {workflow_language}")
    
    return GeminiLiveLLMService(
        api_key=api_key,
        model=model,
        voice_id=voice_id,
        inference_on_context_initialization=True,
        params=params,
    )
