export interface VADConfiguration {
    confidence: number;
    start_seconds: number;
    stop_seconds: number;
    minimum_volume: number;
}

export interface AmbientNoiseConfiguration {
    enabled: boolean;
    volume: number;
}

/**
 * Voice processing mode for the workflow
 * - "standard": Uses separate LLM + STT + TTS services (default)
 * - "realtime": Uses Gemini Live API for ultra-low latency native audio processing
 */
export type VoiceMode = "standard" | "realtime";

/**
 * Available Gemini Live voices
 */
export const GEMINI_VOICES = [
    "Achernar",
    "Achird",
    "Algenib",
    "Algieba",
    "Alnilam",
    "Aoede",
    "Autonoe",
    "Callirhoe",
    "Charon",
    "Despina",
    "Enceladus",
    "Erinome",
    "Fenrir",
    "Gacrux",
    "Iapetus",
    "Kore",
    "Laomedeia",
    "Leda",
    "Orus",
    "Puck",
    "Pulcherrima",
    "Rasalgethi",
    "Sadachbia",
    "Sadaltager",
    "Schedar",
    "Sulafar",
    "Umbriel",
    "Vindemiatrix",
    "Zephyr",
    "Zubenelgenubi",
] as const;

export type GeminiVoice = typeof GEMINI_VOICES[number];

/**
 * Supported workflow languages with mappings to all services
 */
export const WORKFLOW_LANGUAGES = [
    "English",
    "Arabic",
    "Hindi", 
    "French",
    "German",
    "Korean",
    "Spanish",
    "Portuguese",
    "Italian",
    "Japanese",
    "Chinese",
] as const;

export type WorkflowLanguage = typeof WORKFLOW_LANGUAGES[number];

/**
 * Language configuration for display and services
 */
export interface LanguageConfig {
    displayName: string;
    openaiLocale: string;  // For OpenAI/LLM system prompts
}

/**
 * Language mappings for display and LLM prompts
 * Note: Speech recognition (Nova-3) automatically detects language
 */
export const LANGUAGE_CONFIG: Record<WorkflowLanguage, LanguageConfig> = {
    "English": {
        displayName: "English",
        openaiLocale: "English",
    },
    "Arabic": {
        displayName: "العربية (Arabic)",
        openaiLocale: "Arabic",
    },
    "Hindi": {
        displayName: "हिन्दी (Hindi)",
        openaiLocale: "Hindi",
    },
    "French": {
        displayName: "Français (French)",
        openaiLocale: "French",
    },
    "German": {
        displayName: "Deutsch (German)",
        openaiLocale: "German",
    },
    "Korean": {
        displayName: "한국어 (Korean)",
        openaiLocale: "Korean",
    },
    "Spanish": {
        displayName: "Español (Spanish)",
        openaiLocale: "Spanish",
    },
    "Portuguese": {
        displayName: "Português (Portuguese)",
        openaiLocale: "Portuguese",
    },
    "Italian": {
        displayName: "Italiano (Italian)",
        openaiLocale: "Italian",
    },
    "Japanese": {
        displayName: "日本語 (Japanese)",
        openaiLocale: "Japanese",
    },
    "Chinese": {
        displayName: "中文 (Chinese)",
        openaiLocale: "Chinese (Mandarin)",
    },
};

/**
 * A regional accent the agent can speak in.
 *
 * The `id` is stored on the workflow and expanded by the backend into the
 * accent line of the Gemini director's notes, so these IDs must stay in sync
 * with ACCENTS_BY_LANGUAGE in api/services/pipecat/tts_accents.py.
 */
export interface Accent {
    id: string;
    label: string;
    /** Shown as a hint beneath the picker. */
    description: string;
}

/**
 * Three accents per language. Accent is applied on top of the chosen voice:
 * any voice can speak any of its language's accents.
 */
export const ACCENTS_BY_LANGUAGE: Record<WorkflowLanguage, Accent[]> = {
    "English": [
        { id: "en-us-general", label: "American", description: "General American, as heard on US national news" },
        { id: "en-gb-london", label: "British", description: "Standard Southern British, central London" },
        { id: "en-au-sydney", label: "Australian", description: "Broad and relaxed, as heard in Sydney" },
    ],
    "Arabic": [
        { id: "ar-qatari", label: "Qatari (Gulf)", description: "Khaleeji Arabic as spoken in Doha" },
        { id: "ar-saudi", label: "Saudi (Najdi)", description: "Riyadh Arabic, firm and unhurried" },
        { id: "ar-egyptian", label: "Egyptian", description: "Cairo Arabic, lively and expressive" },
    ],
    "Hindi": [
        { id: "hi-delhi", label: "Delhi", description: "Standard Khari Boli, neutral newsreader delivery" },
        { id: "hi-mumbai", label: "Mumbai", description: "Quick and clipped, with a Bambaiya lilt" },
        { id: "hi-hyderabadi", label: "Hyderabadi", description: "Dakhni Hindi, softer with a Deccani melody" },
    ],
    "French": [
        { id: "fr-paris", label: "Parisian", description: "Metropolitan French, standard placement" },
        { id: "fr-quebec", label: "Québécois", description: "Montréal French, diphthongised vowels" },
        { id: "fr-marseille", label: "Southern", description: "Marseille French, sung and open" },
    ],
    "German": [
        { id: "de-hanover", label: "Standard", description: "Hochdeutsch as spoken in Hanover" },
        { id: "de-munich", label: "Bavarian", description: "Munich German, warm and darker vowels" },
        { id: "de-vienna", label: "Austrian", description: "Viennese German, melodic and gentle" },
    ],
    "Korean": [
        { id: "ko-seoul", label: "Seoul", description: "The broadcast standard, even in pitch" },
        { id: "ko-busan", label: "Busan", description: "Gyeongsang accent, punchy with strong pitch swings" },
        { id: "ko-gwangju", label: "Gwangju", description: "Jeolla accent, warm with drawn-out endings" },
    ],
    "Spanish": [
        { id: "es-madrid", label: "Castilian", description: "Madrid Spanish, with distinción" },
        { id: "es-mexico", label: "Mexican", description: "Mexico City Spanish, clear and neutral" },
        { id: "es-buenos-aires", label: "Rioplatense", description: "Buenos Aires Spanish, Italian-tinged" },
    ],
    "Portuguese": [
        { id: "pt-lisbon", label: "European", description: "Lisbon Portuguese, closed and reduced vowels" },
        { id: "pt-sao-paulo", label: "Brazilian", description: "São Paulo Portuguese, clear and neutral" },
        { id: "pt-rio", label: "Carioca", description: "Rio Portuguese, musical and laid-back" },
    ],
    "Italian": [
        { id: "it-standard", label: "Standard", description: "Florence-based standard used by RAI" },
        { id: "it-rome", label: "Roman", description: "Rome Italian, relaxed and conversational" },
        { id: "it-naples", label: "Neapolitan", description: "Naples Italian, expressive and warm" },
    ],
    "Japanese": [
        { id: "ja-tokyo", label: "Tokyo", description: "The NHK broadcast standard, level and polite" },
        { id: "ja-osaka", label: "Kansai", description: "Osaka Japanese, bouncy and friendly" },
        { id: "ja-kyoto", label: "Kyoto", description: "Softer and unhurried, refined politeness" },
    ],
    "Chinese": [
        { id: "zh-beijing", label: "Standard", description: "Beijing Putonghua, full retroflex and erhua" },
        { id: "zh-taipei", label: "Taiwanese", description: "Taipei Mandarin, gentle and polite" },
        { id: "zh-guangzhou", label: "Cantonese-accented", description: "Guangzhou and Hong Kong Mandarin" },
    ],
};

export function getDefaultAccentForLanguage(language: WorkflowLanguage): Accent {
    return ACCENTS_BY_LANGUAGE[language]?.[0] ?? ACCENTS_BY_LANGUAGE["English"][0];
}

/** Resolve a saved accent ID within a language, or null if it doesn't belong. */
export function findAccent(
    language: WorkflowLanguage | undefined,
    accentId: string | undefined,
): Accent | null {
    if (!language || !accentId) return null;
    return ACCENTS_BY_LANGUAGE[language]?.find((a) => a.id === accentId) ?? null;
}

/**
 * Gemini TTS prebuilt voices. Every voice speaks all of Gemini's supported
 * languages — the model detects the language from the text — so one list serves
 * every workflow language.
 *
 * IDs are the voice names the Gemini API expects, not UUIDs.
 *
 * Source: https://ai.google.dev/gemini-api/docs/speech-generation#voices
 */
export const GEMINI_TTS_VOICES: { id: string; name: string }[] = [
    { id: "Kore", name: "Kore — Firm" },
    { id: "Puck", name: "Puck — Upbeat" },
    { id: "Charon", name: "Charon — Informative" },
    { id: "Zephyr", name: "Zephyr — Bright" },
    { id: "Fenrir", name: "Fenrir — Excitable" },
    { id: "Leda", name: "Leda — Youthful" },
    { id: "Orus", name: "Orus — Firm" },
    { id: "Aoede", name: "Aoede — Breezy" },
    { id: "Callirrhoe", name: "Callirrhoe — Easy-going" },
    { id: "Autonoe", name: "Autonoe — Bright" },
    { id: "Enceladus", name: "Enceladus — Breathy" },
    { id: "Iapetus", name: "Iapetus — Clear" },
    { id: "Umbriel", name: "Umbriel — Easy-going" },
    { id: "Algieba", name: "Algieba — Smooth" },
    { id: "Despina", name: "Despina — Smooth" },
    { id: "Erinome", name: "Erinome — Clear" },
    { id: "Algenib", name: "Algenib — Gravelly" },
    { id: "Rasalgethi", name: "Rasalgethi — Informative" },
    { id: "Laomedeia", name: "Laomedeia — Upbeat" },
    { id: "Achernar", name: "Achernar — Soft" },
    { id: "Alnilam", name: "Alnilam — Firm" },
    { id: "Schedar", name: "Schedar — Even" },
    { id: "Gacrux", name: "Gacrux — Mature" },
    { id: "Pulcherrima", name: "Pulcherrima — Forward" },
    { id: "Achird", name: "Achird — Friendly" },
    { id: "Zubenelgenubi", name: "Zubenelgenubi — Casual" },
    { id: "Vindemiatrix", name: "Vindemiatrix — Gentle" },
    { id: "Sadachbia", name: "Sadachbia — Lively" },
    { id: "Sadaltager", name: "Sadaltager — Knowledgeable" },
    { id: "Sulafat", name: "Sulafat — Warm" },
];

export const GEMINI_TTS_DEFAULT_VOICE_ID = "Kore";

/**
 * Cartesia Sonic-3.5 voice library (cross-lingual — every voice speaks all 42
 * supported languages). Voices use UUID format; the runtime router auto-detects
 * Cartesia from the ID format.
 *
 * Source: https://docs.cartesia.ai/build-with-cartesia/capability-guides/choosing-a-voice
 */
const _CARTESIA_VOICE_LIBRARY: { id: string; name: string }[] = [
    { id: "f786b574-daa5-4673-aa0c-cbe3e8534c02", name: "Katie — Female, Stable" },
    { id: "a5136bf9-224c-4d76-b823-52bd5efcffcc", name: "Jameson — Male, Stable" },
    { id: "6f84f4b8-58a2-430c-8c79-688dad597532", name: "Brooke — Female, Warm" },
    { id: "0418348a-0ca2-4e90-9986-800fb8b3bbc0", name: "Jacqueline — Female, Professional" },
    { id: "7e96d5e8-9d83-4b50-86b6-ba421a86f8c2", name: "Ronald — Male, Calm" },
    { id: "5345cf08-6f37-424d-a5d9-8ae1101b9377", name: "Carson — Male, Professional" },
];

/** Backwards-compatible alias used by older imports. */
export const CARTESIA_VOICES = _CARTESIA_VOICE_LIBRARY;
export const CARTESIA_DEFAULT_VOICE_ID = "f786b574-daa5-4673-aa0c-cbe3e8534c02"; // Katie

export const CARTESIA_MODELS = ["sonic-3.5", "sonic-3"] as const;
export type CartesiaModel = typeof CARTESIA_MODELS[number];

/**
 * Internal TTS provider tag. The user never sees this string in the UI — it
 * travels with each voice entry so the runtime knows which backend to call.
 *
 * Gemini serves every language. Cartesia is the backup the runtime switches to
 * when Gemini fails, so no voice in the picker is ever Cartesia-only.
 */
export type TTSProvider = "gemini" | "cartesia";

export const DEFAULT_TTS_PROVIDER: TTSProvider = "gemini";
export const FALLBACK_TTS_PROVIDER: TTSProvider = "cartesia";

const CARTESIA_KATIE = CARTESIA_DEFAULT_VOICE_ID;
const CARTESIA_JAMESON = "a5136bf9-224c-4d76-b823-52bd5efcffcc";
const CARTESIA_BROOKE = "6f84f4b8-58a2-430c-8c79-688dad597532";
const CARTESIA_JACQUELINE = "0418348a-0ca2-4e90-9986-800fb8b3bbc0";
const CARTESIA_RONALD = "7e96d5e8-9d83-4b50-86b6-ba421a86f8c2";
const CARTESIA_CARSON = "5345cf08-6f37-424d-a5d9-8ae1101b9377";

/**
 * Cartesia stand-in for each Gemini voice, matched on gender and character so a
 * call that falls back mid-conversation shifts voice as little as possible.
 */
export const CARTESIA_FALLBACK_BY_GEMINI_VOICE: Record<string, string> = {
    Achernar: CARTESIA_BROOKE,
    Achird: CARTESIA_JAMESON,
    Algenib: CARTESIA_RONALD,
    Algieba: CARTESIA_CARSON,
    Alnilam: CARTESIA_JAMESON,
    Aoede: CARTESIA_BROOKE,
    Autonoe: CARTESIA_KATIE,
    Callirrhoe: CARTESIA_BROOKE,
    Charon: CARTESIA_CARSON,
    Despina: CARTESIA_KATIE,
    Enceladus: CARTESIA_RONALD,
    Erinome: CARTESIA_JACQUELINE,
    Fenrir: CARTESIA_JAMESON,
    Gacrux: CARTESIA_JACQUELINE,
    Iapetus: CARTESIA_CARSON,
    Kore: CARTESIA_KATIE,
    Laomedeia: CARTESIA_BROOKE,
    Leda: CARTESIA_BROOKE,
    Orus: CARTESIA_JAMESON,
    Puck: CARTESIA_JAMESON,
    Pulcherrima: CARTESIA_JACQUELINE,
    Rasalgethi: CARTESIA_CARSON,
    Sadachbia: CARTESIA_JAMESON,
    Sadaltager: CARTESIA_CARSON,
    Schedar: CARTESIA_RONALD,
    Sulafat: CARTESIA_BROOKE,
    Umbriel: CARTESIA_RONALD,
    Vindemiatrix: CARTESIA_BROOKE,
    Zephyr: CARTESIA_KATIE,
    Zubenelgenubi: CARTESIA_RONALD,
};

export function getCartesiaFallbackVoiceId(geminiVoiceId: string): string {
    return CARTESIA_FALLBACK_BY_GEMINI_VOICE[geminiVoiceId] ?? CARTESIA_DEFAULT_VOICE_ID;
}

/**
 * Unified voice catalog — single source of truth used by the UI.
 *
 * Every language offers the same voices: Gemini infers the spoken language from
 * the text rather than from the voice, so there is nothing to curate per
 * locale. The Cartesia voice used if Gemini fails mid-call is derived from the
 * selection by getCartesiaFallbackVoiceId(), not chosen by the user.
 */
export interface UnifiedVoice {
    id: string;
    name: string;
    /** Internal — never rendered in UI. */
    provider: TTSProvider;
}

const GEMINI_VOICE_CATALOG: UnifiedVoice[] = GEMINI_TTS_VOICES.map((v) => ({
    ...v,
    provider: "gemini" as TTSProvider,
}));

export const VOICE_CATALOG_BY_LANGUAGE: Record<WorkflowLanguage, UnifiedVoice[]> =
    Object.fromEntries(
        WORKFLOW_LANGUAGES.map((language) => [language, GEMINI_VOICE_CATALOG]),
    ) as Record<WorkflowLanguage, UnifiedVoice[]>;

/**
 * Look up the catalog entry for a saved voice ID. Falls back to a search
 * across all languages if the language-specific list doesn't contain it.
 *
 * Workflows saved before the move to Gemini hold a Cartesia or ElevenLabs voice
 * ID, which is no longer in the catalog: those return null so callers land on
 * getDefaultVoiceForLanguage().
 */
export function findVoice(
    language: WorkflowLanguage | undefined,
    voiceId: string,
): UnifiedVoice | null {
    if (!voiceId) return null;

    const langList = (language && VOICE_CATALOG_BY_LANGUAGE[language]) || [];
    const fromLang = langList.find((v) => v.id === voiceId);
    if (fromLang) return fromLang;

    for (const list of Object.values(VOICE_CATALOG_BY_LANGUAGE)) {
        const hit = list.find((v) => v.id === voiceId);
        if (hit) return hit;
    }
    return null;
}

/**
 * Default voice for a language. Every language exposes the same Gemini voices,
 * so this resolves to the same entry throughout.
 */
export function getDefaultVoiceForLanguage(language: WorkflowLanguage): UnifiedVoice {
    const list = VOICE_CATALOG_BY_LANGUAGE[language] || GEMINI_VOICE_CATALOG;
    return (
        list.find((v) => v.id === GEMINI_TTS_DEFAULT_VOICE_ID) ??
        list[0] ?? {
            id: GEMINI_TTS_DEFAULT_VOICE_ID,
            name: "Kore — Firm",
            provider: "gemini",
        }
    );
}

/**
 * Performance tuning configuration for voice agent responsiveness
 */
export interface PerformanceConfig {
    utterance_end_ms: number;     // How long to wait after silence before processing (100-1500ms)
    llm_temperature: number;      // LLM creativity vs accuracy (0-1)
    max_response_tokens: number;  // Max LLM response length (50-500)
    frequency_penalty: number;    // Reduce LLM repetition (0-1)
}

export interface WorkflowConfigurations {
    vad_configuration: VADConfiguration;
    ambient_noise_configuration: AmbientNoiseConfiguration;
    max_call_duration: number;  // Maximum call duration in seconds
    max_user_idle_timeout: number;  // Maximum user idle time in seconds
    voice_mode: VoiceMode;  // Voice processing mode
    gemini_voice?: GeminiVoice;  // Voice for Gemini Live (realtime mode)
    // Language configuration (applies to LLM and TTS)
    workflow_language?: WorkflowLanguage;  // Primary language for the workflow
    // Timezone configuration — the agent uses this to know the current date/time
    timezone?: string;  // IANA timezone (e.g. "America/New_York")
    // TTS configuration
    // Provider routing — when omitted the runtime uses Gemini, falling back to
    // Cartesia if Gemini fails.
    tts_provider?: TTSProvider;
    tts_voice_id?: string;  // Gemini voice name (e.g. "Kore"), or a Cartesia UUID
    tts_voice_name?: string;  // Voice display name
    tts_accent?: string;  // Accent ID from ACCENTS_BY_LANGUAGE, e.g. "ar-egyptian"
    // Cartesia-only: model snapshot used by the fallback ("sonic-3.5" or "sonic-3")
    tts_cartesia_model?: CartesiaModel;
    // Performance tuning
    performance?: PerformanceConfig;
    // Guardrails & safety
    guardrails_enabled?: boolean;
    redact_pii?: boolean;
    max_cumulative_silence?: number;
    // Self-improving agent
    auto_improve_enabled?: boolean;
    auto_improve_interval?: number;
    auto_apply_threshold?: number;
    [key: string]: unknown;
}

export const DEFAULT_PERFORMANCE_CONFIG: PerformanceConfig = {
    utterance_end_ms: 300,       // 300ms — fast but natural
    llm_temperature: 0.1,       // Low = accurate & consistent
    max_response_tokens: 300,   // Short voice-friendly responses
    frequency_penalty: 0.3,     // Slight anti-repetition
};

/**
 * Common IANA timezones grouped by region for the timezone selector.
 */
export const COMMON_TIMEZONES = [
    // Americas
    { value: "America/New_York", label: "Eastern Time (US) — New York" },
    { value: "America/Chicago", label: "Central Time (US) — Chicago" },
    { value: "America/Denver", label: "Mountain Time (US) — Denver" },
    { value: "America/Los_Angeles", label: "Pacific Time (US) — Los Angeles" },
    { value: "America/Anchorage", label: "Alaska Time — Anchorage" },
    { value: "Pacific/Honolulu", label: "Hawaii Time — Honolulu" },
    { value: "America/Toronto", label: "Eastern Time (CA) — Toronto" },
    { value: "America/Vancouver", label: "Pacific Time (CA) — Vancouver" },
    { value: "America/Mexico_City", label: "Central Time — Mexico City" },
    { value: "America/Sao_Paulo", label: "Brasília Time — São Paulo" },
    { value: "America/Argentina/Buenos_Aires", label: "Argentina Time — Buenos Aires" },
    { value: "America/Bogota", label: "Colombia Time — Bogotá" },
    // Europe
    { value: "Europe/London", label: "GMT / BST — London" },
    { value: "Europe/Paris", label: "CET — Paris" },
    { value: "Europe/Berlin", label: "CET — Berlin" },
    { value: "Europe/Madrid", label: "CET — Madrid" },
    { value: "Europe/Rome", label: "CET — Rome" },
    { value: "Europe/Amsterdam", label: "CET — Amsterdam" },
    { value: "Europe/Istanbul", label: "Turkey Time — Istanbul" },
    { value: "Europe/Moscow", label: "Moscow Time — Moscow" },
    // Middle East
    { value: "Asia/Dubai", label: "Gulf Time — Dubai" },
    { value: "Asia/Riyadh", label: "Arabia Time — Riyadh" },
    { value: "Asia/Tehran", label: "Iran Time — Tehran" },
    { value: "Asia/Jerusalem", label: "Israel Time — Jerusalem" },
    // Asia
    { value: "Asia/Kolkata", label: "India Time — Kolkata" },
    { value: "Asia/Shanghai", label: "China Time — Shanghai" },
    { value: "Asia/Tokyo", label: "Japan Time — Tokyo" },
    { value: "Asia/Seoul", label: "Korea Time — Seoul" },
    { value: "Asia/Singapore", label: "Singapore Time" },
    { value: "Asia/Hong_Kong", label: "Hong Kong Time" },
    { value: "Asia/Karachi", label: "Pakistan Time — Karachi" },
    { value: "Asia/Bangkok", label: "Indochina Time — Bangkok" },
    { value: "Asia/Jakarta", label: "West Indonesia Time — Jakarta" },
    // Oceania
    { value: "Australia/Sydney", label: "AEST — Sydney" },
    { value: "Australia/Melbourne", label: "AEST — Melbourne" },
    { value: "Australia/Perth", label: "AWST — Perth" },
    { value: "Pacific/Auckland", label: "NZST — Auckland" },
    // Africa
    { value: "Africa/Cairo", label: "Egypt Time — Cairo" },
    { value: "Africa/Lagos", label: "West Africa Time — Lagos" },
    { value: "Africa/Johannesburg", label: "South Africa Time — Johannesburg" },
    { value: "Africa/Nairobi", label: "East Africa Time — Nairobi" },
] as const;

export const DEFAULT_WORKFLOW_CONFIGURATIONS: WorkflowConfigurations = {
    vad_configuration: {
        confidence: 0.7,
        start_seconds: 0.4,
        stop_seconds: 0.8,
        minimum_volume: 0.6
    },
    ambient_noise_configuration: {
        enabled: false,
        volume: 0.3
    },
    max_call_duration: 600,  // 10 minutes
    max_user_idle_timeout: 10,  // 10 seconds
    voice_mode: "standard",  // Default to standard LLM + STT + TTS
    gemini_voice: "Charon",  // Default Gemini Live voice
    // Language configuration
    workflow_language: "English",
    // Timezone — defaults to UTC, user should set to match their business location
    timezone: "UTC",
    // Default TTS configuration
    tts_provider: DEFAULT_TTS_PROVIDER,
    tts_voice_id: GEMINI_TTS_DEFAULT_VOICE_ID,
    tts_voice_name: "Kore — Firm",
    tts_accent: "en-us-general",
    // Performance tuning
    performance: DEFAULT_PERFORMANCE_CONFIG,
};
