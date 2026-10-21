import { Lock, Sparkles } from "lucide-react";

import { Spinner } from "@/components/ui/ai-loader";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useUserConfig } from "@/context/UserConfigContext";
import { useAuth } from "@/lib/auth";
import { getBackendUrl } from "@/lib/apiClient";
import { 
    AmbientNoiseConfiguration, 
    VADConfiguration, 
    VoiceMode, 
    WorkflowConfigurations,
    PerformanceConfig,
    DEFAULT_PERFORMANCE_CONFIG,
    GEMINI_VOICES,
    GeminiVoice,
    WORKFLOW_LANGUAGES,
    VOICE_CATALOG_BY_LANGUAGE,
    ACCENTS_BY_LANGUAGE,
    DEFAULT_TTS_PROVIDER,
    findAccent,
    findVoice,
    getDefaultAccentForLanguage,
    getDefaultVoiceForLanguage,
    LANGUAGE_CONFIG,
    WorkflowLanguage,
    COMMON_TIMEZONES,
} from "@/types/workflow-configurations";

interface ConfigurationsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    workflowConfigurations: WorkflowConfigurations | null;
    workflowName: string;
    workflowId: number;
    onSave: (configurations: WorkflowConfigurations, workflowName: string) => Promise<void>;
}

const DEFAULT_VAD_CONFIG: VADConfiguration = {
    confidence: 0.7,
    start_seconds: 0.4,
    stop_seconds: 0.8,
    minimum_volume: 0.6,
};

const DEFAULT_AMBIENT_NOISE_CONFIG: AmbientNoiseConfiguration = {
    enabled: false,
    volume: 0.3,
};

export const ConfigurationsDialog = ({
    open,
    onOpenChange,
    workflowConfigurations,
    workflowName,
    workflowId,
    onSave
}: ConfigurationsDialogProps) => {
    const { subscription } = useUserConfig();
    const { getAccessToken } = useAuth();
    const isProPlan = subscription?.gemini_s2s_enabled === true;
    const [analyzing, setAnalyzing] = useState(false);

    const handleAnalyzeNow = async () => {
        setAnalyzing(true);
        try {
            const token = await getAccessToken();
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/workflow/${workflowId}/improvements/analyze`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) {
                toast.error("Couldn't start the analysis. Please try again.");
                return;
            }
            const data = await res.json().catch(() => ({}));
            if (data?.status === "skipped") {
                toast.info("No calls to analyse yet", {
                    description: "Run a few calls first, then come back and try again.",
                });
                return;
            }
            const calls = data?.total_completed_calls || 0;
            toast.success("Analysing your calls", {
                description:
                    calls > 0
                        ? `Reviewing your ${calls} most recent call${calls === 1 ? "" : "s"}. Suggestions will appear in the Improvements panel in about 30 seconds.`
                        : "Reviewing your recent calls. Suggestions will appear in the Improvements panel shortly.",
            });
        } catch {
            toast.error("Network error. Please try again.");
        } finally {
            setAnalyzing(false);
        }
    };

    // Force voice mode to standard if user doesn't have Pro
    const initialVoiceMode = (!isProPlan && workflowConfigurations?.voice_mode === "realtime")
        ? "standard"
        : (workflowConfigurations?.voice_mode || "standard");

    const [name, setName] = useState<string>(workflowName);
    const [vadConfig, setVadConfig] = useState<VADConfiguration>(
        workflowConfigurations?.vad_configuration || DEFAULT_VAD_CONFIG
    );
    const [ambientNoiseConfig, setAmbientNoiseConfig] = useState<AmbientNoiseConfiguration>(
        workflowConfigurations?.ambient_noise_configuration || DEFAULT_AMBIENT_NOISE_CONFIG
    );
    const [maxCallDuration, setMaxCallDuration] = useState<number>(
        workflowConfigurations?.max_call_duration || 600
    );
    const [maxUserIdleTimeout, setMaxUserIdleTimeout] = useState<number>(
        workflowConfigurations?.max_user_idle_timeout || 10
    );
    const [voiceMode, setVoiceMode] = useState<VoiceMode>(initialVoiceMode as VoiceMode);
    const [geminiVoice, setGeminiVoice] = useState<GeminiVoice>(
        (workflowConfigurations?.gemini_voice as GeminiVoice) || "Charon"
    );
    // Unified language configuration
    const initialLanguage: WorkflowLanguage =
        (workflowConfigurations?.workflow_language as WorkflowLanguage) || "English";
    const [workflowLanguage, setWorkflowLanguage] = useState<WorkflowLanguage>(initialLanguage);
    // Unified voice configuration — provider is internal metadata, never shown
    // to the user. Voices are Gemini's; the backend maps the selection to a
    // Cartesia voice on its own when it has to fall back.
    const initialVoice =
        (workflowConfigurations?.tts_voice_id
            ? findVoice(initialLanguage, workflowConfigurations.tts_voice_id as string)
            : null) ?? getDefaultVoiceForLanguage(initialLanguage);
    const [ttsVoiceId, setTtsVoiceId] = useState<string>(
        (workflowConfigurations?.tts_voice_id as string) || initialVoice.id,
    );
    const [ttsVoiceName, setTtsVoiceName] = useState<string>(
        (workflowConfigurations?.tts_voice_name as string) || initialVoice.name,
    );
    const [ttsAccent, setTtsAccent] = useState<string>(
        findAccent(initialLanguage, workflowConfigurations?.tts_accent as string)?.id
        ?? getDefaultAccentForLanguage(initialLanguage).id,
    );
    const [performanceConfig, setPerformanceConfig] = useState<PerformanceConfig>(
        workflowConfigurations?.performance || DEFAULT_PERFORMANCE_CONFIG
    );
    const [callType, setCallType] = useState<'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING'>(
        (workflowConfigurations?.call_type as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING') || 'INBOUND'
    );
    const [timezone, setTimezone] = useState<string>(
        workflowConfigurations?.timezone || "UTC"
    );
    const [guardrailsEnabled, setGuardrailsEnabled] = useState<boolean>(
        workflowConfigurations?.guardrails_enabled !== false
    );
    const [redactPii, setRedactPii] = useState<boolean>(
        workflowConfigurations?.redact_pii !== false
    );
    const [maxCumulativeSilence, setMaxCumulativeSilence] = useState<number>(
        workflowConfigurations?.max_cumulative_silence || 20
    );
    const [autoImproveEnabled, setAutoImproveEnabled] = useState<boolean>(
        workflowConfigurations?.auto_improve_enabled === true
    );
    const [autoImproveInterval, setAutoImproveInterval] = useState<number>(
        workflowConfigurations?.auto_improve_interval || 10
    );
    const [autoApplyThreshold, setAutoApplyThreshold] = useState<number>(
        workflowConfigurations?.auto_apply_threshold || 0
    );
    const [isSaving, setIsSaving] = useState(false);

    // Single, unified voice list. Gemini reads any supported language in any of
    // its voices, so this list is the same whichever language is selected.
    const availableVoices = VOICE_CATALOG_BY_LANGUAGE[workflowLanguage] || [];
    // Accents, unlike voices, are specific to the language.
    const availableAccents = ACCENTS_BY_LANGUAGE[workflowLanguage] || [];
    const selectedAccent = findAccent(workflowLanguage, ttsAccent);
    const languageConfig = LANGUAGE_CONFIG[workflowLanguage];

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await onSave({
                vad_configuration: vadConfig,
                ambient_noise_configuration: ambientNoiseConfig,
                max_call_duration: maxCallDuration,
                max_user_idle_timeout: maxUserIdleTimeout,
                voice_mode: voiceMode,
                gemini_voice: geminiVoice,
                workflow_language: workflowLanguage,
                timezone,
                // Informational only — the runtime always tries Gemini first and
                // falls back to Cartesia. Persisted for clarity in admin tooling.
                tts_provider:
                    findVoice(workflowLanguage, ttsVoiceId)?.provider ?? DEFAULT_TTS_PROVIDER,
                tts_voice_id: ttsVoiceId,
                tts_voice_name: ttsVoiceName,
                tts_accent: ttsAccent,
                performance: performanceConfig,
                call_type: callType,
                guardrails_enabled: guardrailsEnabled,
                redact_pii: redactPii,
                max_cumulative_silence: maxCumulativeSilence,
                auto_improve_enabled: autoImproveEnabled,
                auto_improve_interval: autoImproveInterval,
                auto_apply_threshold: autoApplyThreshold,
            }, name);
            onOpenChange(false);
        } catch (error) {
            console.error("Failed to save configurations:", error);
        } finally {
            setIsSaving(false);
        }
    };

    // Sync state with props when dialog opens
    useEffect(() => {
        if (open) {
            setName(workflowName);
            setVadConfig(workflowConfigurations?.vad_configuration || DEFAULT_VAD_CONFIG);
            setAmbientNoiseConfig(workflowConfigurations?.ambient_noise_configuration || DEFAULT_AMBIENT_NOISE_CONFIG);
            setMaxCallDuration(workflowConfigurations?.max_call_duration || 600);
            setMaxUserIdleTimeout(workflowConfigurations?.max_user_idle_timeout || 10);
            setVoiceMode(workflowConfigurations?.voice_mode || "standard");
            setGeminiVoice((workflowConfigurations?.gemini_voice as GeminiVoice) || "Charon");
            const lang = (workflowConfigurations?.workflow_language as WorkflowLanguage) || "English";
            setWorkflowLanguage(lang);
            const savedId = workflowConfigurations?.tts_voice_id as string | undefined;
            const resolved = (savedId && findVoice(lang, savedId)) || getDefaultVoiceForLanguage(lang);
            setTtsVoiceId(savedId || resolved.id);
            setTtsVoiceName((workflowConfigurations?.tts_voice_name as string) || resolved.name);
            setTtsAccent(
                findAccent(lang, workflowConfigurations?.tts_accent as string)?.id
                ?? getDefaultAccentForLanguage(lang).id,
            );
            setPerformanceConfig(workflowConfigurations?.performance || DEFAULT_PERFORMANCE_CONFIG);
            setCallType((workflowConfigurations?.call_type as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING') || 'INBOUND');
            setTimezone(workflowConfigurations?.timezone || "UTC");
            setGuardrailsEnabled(workflowConfigurations?.guardrails_enabled !== false);
            setRedactPii(workflowConfigurations?.redact_pii !== false);
            setMaxCumulativeSilence(workflowConfigurations?.max_cumulative_silence || 20);
            setAutoImproveEnabled(workflowConfigurations?.auto_improve_enabled === true);
            setAutoImproveInterval(workflowConfigurations?.auto_improve_interval || 10);
            setAutoApplyThreshold(workflowConfigurations?.auto_apply_threshold || 0);
        }
    }, [open, workflowName, workflowConfigurations]);

    // Every language offers the same voices, so a language switch keeps the
    // chosen voice. Workflows still holding a pre-Gemini voice ID get moved to
    // the default here. Accents belong to a single language, so those always
    // reset.
    const handleLanguageChange = (newLanguage: WorkflowLanguage) => {
        setWorkflowLanguage(newLanguage);
        setTtsAccent(getDefaultAccentForLanguage(newLanguage).id);
        if (findVoice(newLanguage, ttsVoiceId)) return;
        const fallback = getDefaultVoiceForLanguage(newLanguage);
        setTtsVoiceId(fallback.id);
        setTtsVoiceName(fallback.name);
    };

    // Update voice name when voice ID changes
    const handleVoiceChange = (voiceId: string) => {
        setTtsVoiceId(voiceId);
        const voice = availableVoices.find(v => v.id === voiceId);
        if (voice) {
            setTtsVoiceName(voice.name);
        }
    };

    const handleVadChange = (field: keyof VADConfiguration, value: string) => {
        const numValue = parseFloat(value);
        if (!isNaN(numValue)) {
            setVadConfig(prev => ({
                ...prev,
                [field]: numValue
            }));
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
                <DialogHeader className="flex-shrink-0">
                    <DialogTitle>Workflow Configuration</DialogTitle>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto pr-2 space-y-6">
                    {/* Workflow Name Section */}
                    <div className="space-y-3">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Agent Name</h3>
                            <p className="text-xs text-muted-foreground">
                                The name of your voice agent
                            </p>
                        </div>
                        <Input
                            id="workflow_name"
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Enter Agent name"
                        />
                    </div>

                    {/* Call Type */}
                    <div className="space-y-3">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Call Type</h3>
                            <p className="text-xs text-muted-foreground">
                                How this agent interacts — phone calls or website widget
                            </p>
                        </div>
                        <Select value={callType} onValueChange={(v) => setCallType(v as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING')}>
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="INBOUND">Inbound</SelectItem>
                                <SelectItem value="OUTBOUND">Outbound</SelectItem>
                                <SelectItem value="WEBSITE">Website</SelectItem>
                                <SelectItem value="MEETING">Meeting Agent</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>

                    {/* Timezone */}
                    <div className="space-y-3 p-4 bg-gradient-to-br from-amber-500/5 to-orange-500/5 rounded-lg border border-amber-200/50">
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-gradient-to-r from-amber-500 to-orange-500"></div>
                            <h3 className="text-sm font-semibold">Timezone</h3>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            The agent will know the current date and time in this timezone during calls.
                            Critical for appointment scheduling, reminders, and time-sensitive conversations.
                        </p>
                        <Select value={timezone} onValueChange={setTimezone}>
                            <SelectTrigger>
                                <SelectValue placeholder="Select timezone" />
                            </SelectTrigger>
                            <SelectContent className="max-h-[280px]">
                                <SelectItem value="UTC">UTC — Coordinated Universal Time</SelectItem>
                                {COMMON_TIMEZONES.map((tz) => (
                                    <SelectItem key={tz.value} value={tz.value}>
                                        {tz.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {/* Language Selection - Unified for all services */}
                    <div className="space-y-3 p-4 bg-gradient-to-br from-primary/5 to-teal-500/5 rounded-lg border border-primary/20">
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-gradient-to-r from-[#34F5C2] to-teal-400"></div>
                            <h3 className="text-sm font-semibold">Workflow Language</h3>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            Select the primary language for your workflow. All voice processing 
                            (speech recognition, AI responses, and voice synthesis) will work in this language.
                        </p>
                        <Select value={workflowLanguage} onValueChange={(value) => handleLanguageChange(value as WorkflowLanguage)}>
                            <SelectTrigger>
                                <SelectValue placeholder="Select language" />
                            </SelectTrigger>
                            <SelectContent>
                                {WORKFLOW_LANGUAGES.map((lang) => (
                                    <SelectItem key={lang} value={lang}>
                                        {LANGUAGE_CONFIG[lang].displayName}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {/* Voice Mode Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Voice Processing Mode</h3>
                            <p className="text-xs text-muted-foreground">
                                Choose how voice is processed in your workflow.
                            </p>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <button
                                type="button"
                                onClick={() => setVoiceMode("standard")}
                                className={`p-4 rounded-lg border-2 text-left transition-all ${
                                    voiceMode === "standard"
                                        ? "border-primary bg-primary/5"
                                        : "border-border hover:border-primary/50"
                                }`}
                            >
                                <div className="flex items-center gap-2 mb-1">
                                    <span className="text-sm font-medium">Standard Voice</span>
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    Traditional voice processing
                                </p>
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    if (isProPlan) {
                                        setVoiceMode("realtime");
                                    }
                                }}
                                disabled={!isProPlan}
                                className={`p-4 rounded-lg border-2 text-left transition-all ${
                                    voiceMode === "realtime"
                                        ? "border-primary bg-primary/5"
                                        : !isProPlan
                                        ? "border-border opacity-50 cursor-not-allowed"
                                        : "border-border hover:border-primary/50"
                                }`}
                            >
                                <div className="flex items-center gap-2 mb-1">
                                    <span className="text-sm font-medium">Realtime Voice</span>
                                    <span className="px-1.5 py-0.5 text-[10px] font-medium bg-gradient-to-r from-violet-500 to-purple-500 text-white rounded">
                                        PRO
                                    </span>
                                    {!isProPlan && <Lock className="h-3 w-3 text-amber-500" />}
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    {!isProPlan ? "Upgrade to Pro to unlock" : "Ultra-low latency processing"}
                                </p>
                            </button>
                        </div>
                    </div>

                    {/* Voice Configuration based on mode */}
                    {voiceMode === "realtime" ? (
                        // Voice Selection for Realtime mode
                        <div className="space-y-3 p-4 bg-gradient-to-br from-violet-500/5 to-purple-500/5 rounded-lg border border-violet-200/50">
                            <div className="flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full bg-gradient-to-r from-violet-500 to-purple-500"></div>
                                <span className="text-sm font-medium">Agent Voice</span>
                            </div>
                            <Select value={geminiVoice} onValueChange={(value) => setGeminiVoice(value as GeminiVoice)}>
                                <SelectTrigger>
                                    <SelectValue placeholder="Select a voice" />
                                </SelectTrigger>
                                <SelectContent className="max-h-[200px]">
                                    {GEMINI_VOICES.map((voice) => (
                                        <SelectItem key={voice} value={voice}>
                                            {voice}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        <p className="text-xs text-muted-foreground">
                            This voice will speak in {languageConfig?.displayName || workflowLanguage}
                        </p>
                        </div>
                    ) : (
                        // Standard mode — single unified Voice picker.
                        // Provider routing happens silently on the backend.
                        <div className="space-y-3 p-4 bg-muted/30 rounded-lg border">
                            <div className="flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full bg-purple-500"></div>
                                <span className="text-sm font-medium">Agent Voice</span>
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="tts_accent" className="text-xs">Accent</Label>
                                <Select value={ttsAccent} onValueChange={setTtsAccent}>
                                    <SelectTrigger id="tts_accent">
                                        <SelectValue placeholder="Select accent" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {availableAccents.map((accent) => (
                                            <SelectItem key={accent.id} value={accent.id}>
                                                {accent.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                {selectedAccent && (
                                    <p className="text-xs text-muted-foreground">
                                        {selectedAccent.description}
                                    </p>
                                )}
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="tts_voice" className="text-xs">Voice</Label>
                                <Select value={ttsVoiceId} onValueChange={handleVoiceChange}>
                                    <SelectTrigger id="tts_voice">
                                        <SelectValue placeholder="Select voice" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {availableVoices.map((voice) => (
                                            <SelectItem key={voice.id} value={voice.id}>
                                                {voice.name}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>

                            <p className="text-xs text-muted-foreground">
                                {availableVoices.length} voices, each of which speaks {workflowLanguage}
                                {selectedAccent ? ` in a ${selectedAccent.label} accent` : ""}.
                                Speech recognition automatically detects the language.
                            </p>
                        </div>
                    )}

                    {/* Voice Activity Detection Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Voice Activity Detection</h3>
                            <p className="text-xs text-muted-foreground">
                                Fine-tune how the system detects when users start and stop speaking.
                            </p>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label htmlFor="confidence" className="text-xs">
                                    Confidence
                                </Label>
                                <Input
                                    id="confidence"
                                    type="number"
                                    step="0.1"
                                    min="0"
                                    max="1"
                                    value={vadConfig.confidence}
                                    onChange={(e) => handleVadChange('confidence', e.target.value)}
                                />
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="start_seconds" className="text-xs">
                                    Start Seconds
                                </Label>
                                <Input
                                    id="start_seconds"
                                    type="number"
                                    step="0.1"
                                    min="0"
                                    value={vadConfig.start_seconds}
                                    onChange={(e) => handleVadChange('start_seconds', e.target.value)}
                                />
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="stop_seconds" className="text-xs">
                                    Stop Seconds
                                </Label>
                                <Input
                                    id="stop_seconds"
                                    type="number"
                                    step="0.1"
                                    min="0"
                                    value={vadConfig.stop_seconds}
                                    onChange={(e) => handleVadChange('stop_seconds', e.target.value)}
                                />
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="minimum_volume" className="text-xs">
                                    Minimum Volume
                                </Label>
                                <Input
                                    id="minimum_volume"
                                    type="number"
                                    step="0.1"
                                    min="0"
                                    max="1"
                                    value={vadConfig.minimum_volume}
                                    onChange={(e) => handleVadChange('minimum_volume', e.target.value)}
                                />
                            </div>
                        </div>
                    </div>

                    {/* Ambient Noise Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Ambient Noise</h3>
                            <p className="text-xs text-muted-foreground">
                                Add background office ambient noise to make the conversation sound more natural.
                            </p>
                        </div>

                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <Label htmlFor="ambient-noise-enabled" className="text-sm">
                                    Use Ambient Noise
                                </Label>
                                <Switch
                                    id="ambient-noise-enabled"
                                    checked={ambientNoiseConfig.enabled}
                                    onCheckedChange={(checked) =>
                                        setAmbientNoiseConfig(prev => ({ ...prev, enabled: checked }))
                                    }
                                />
                            </div>

                            {ambientNoiseConfig.enabled && (
                                <div className="space-y-2">
                                    <Label htmlFor="ambient-volume" className="text-xs">
                                        Volume
                                    </Label>
                                    <Input
                                        id="ambient-volume"
                                        type="number"
                                        step="0.1"
                                        min="0"
                                        max="1"
                                        value={ambientNoiseConfig.volume}
                                        onChange={(e) => {
                                            const value = parseFloat(e.target.value);
                                            if (!isNaN(value)) {
                                                setAmbientNoiseConfig(prev => ({ ...prev, volume: value }));
                                            }
                                        }}
                                    />
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Call Management Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Call Management</h3>
                            <p className="text-xs text-muted-foreground">
                                Configure call duration limits and idle timeout settings.
                            </p>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label htmlFor="max_call_duration" className="text-xs">
                                    Max Call Duration (seconds)
                                </Label>
                                <Input
                                    id="max_call_duration"
                                    type="number"
                                    step="1"
                                    min="1"
                                    value={maxCallDuration}
                                    onChange={(e) => {
                                        const value = parseInt(e.target.value);
                                        if (!isNaN(value) && value > 0) {
                                            setMaxCallDuration(value);
                                        }
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">Default: 600 (10 minutes)</p>
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="max_user_idle_timeout" className="text-xs">
                                    Max User Idle Timeout (seconds)
                                </Label>
                                <Input
                                    id="max_user_idle_timeout"
                                    type="number"
                                    step="1"
                                    min="1"
                                    value={maxUserIdleTimeout}
                                    onChange={(e) => {
                                        const value = parseInt(e.target.value);
                                        if (!isNaN(value) && value > 0) {
                                            setMaxUserIdleTimeout(value);
                                        }
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">Default: 10 seconds</p>
                            </div>
                        </div>
                    </div>

                    {/* Guardrails & Safety Section */}
                    <div className="space-y-5">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Guardrails &amp; Safety</h3>
                            <p className="text-xs text-muted-foreground">
                                Protect your voice agent from jailbreak attempts, toxic inputs, and PII leakage. Prevent minute waste from silent calls.
                            </p>
                        </div>

                        <div className="flex items-center justify-between">
                            <div className="space-y-0.5">
                                <Label className="text-xs font-medium">Input &amp; Output Guardrails</Label>
                                <p className="text-xs text-muted-foreground">
                                    Block jailbreak attempts, toxic content, and enforce topic boundaries
                                </p>
                            </div>
                            <Switch
                                checked={guardrailsEnabled}
                                onCheckedChange={setGuardrailsEnabled}
                            />
                        </div>

                        <div className="flex items-center justify-between">
                            <div className="space-y-0.5">
                                <Label className="text-xs font-medium">PII Redaction</Label>
                                <p className="text-xs text-muted-foreground">
                                    Automatically redact SSNs, credit card numbers, and emails from speech
                                </p>
                            </div>
                            <Switch
                                checked={redactPii}
                                onCheckedChange={setRedactPii}
                                disabled={!guardrailsEnabled}
                            />
                        </div>

                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label className="text-xs font-medium">Max Cumulative Silence</Label>
                                <span className="text-xs font-mono text-primary">{maxCumulativeSilence}s</span>
                            </div>
                            <input
                                type="range"
                                min={15}
                                max={120}
                                step={5}
                                value={maxCumulativeSilence}
                                onChange={(e) => setMaxCumulativeSilence(parseInt(e.target.value))}
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                            />
                            <p className="text-xs text-muted-foreground">
                                End the call if user is silent for this long (default: 20s)
                            </p>
                        </div>
                    </div>

                    {/* Performance Tuning Section */}
                    <div className="space-y-5">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Performance Tuning</h3>
                            <p className="text-xs text-muted-foreground">
                                Fine-tune the voice agent&apos;s response speed, accuracy, and behavior. These settings directly impact how fast and how well the agent responds.
                            </p>
                        </div>

                        {/* Utterance End (Silence Detection) */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label className="text-xs font-medium">Silence Detection</Label>
                                <span className="text-xs font-mono text-primary">{performanceConfig.utterance_end_ms}ms</span>
                            </div>
                            <input
                                type="range"
                                min={100}
                                max={1500}
                                step={50}
                                value={performanceConfig.utterance_end_ms}
                                onChange={(e) => setPerformanceConfig(prev => ({ ...prev, utterance_end_ms: parseInt(e.target.value) }))}
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                            />
                            <div className="flex justify-between text-[10px] text-muted-foreground">
                                <span>100ms (Fastest)</span>
                                <span>1500ms (Most patient)</span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                How long the agent waits after the user stops speaking before responding. Lower = faster replies but may cut off pauses. Higher = more patient but slower.
                            </p>
                        </div>

                        {/* LLM Temperature */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label className="text-xs font-medium">Response Accuracy</Label>
                                <span className="text-xs font-mono text-primary">{performanceConfig.llm_temperature.toFixed(1)}</span>
                            </div>
                            <input
                                type="range"
                                min={0}
                                max={10}
                                step={1}
                                value={performanceConfig.llm_temperature * 10}
                                onChange={(e) => setPerformanceConfig(prev => ({ ...prev, llm_temperature: parseInt(e.target.value) / 10 }))}
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                            />
                            <div className="flex justify-between text-[10px] text-muted-foreground">
                                <span>0.0 (Precise & Consistent)</span>
                                <span>1.0 (Creative & Varied)</span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                Controls how strictly the agent follows instructions. Low = highly accurate, repeatable answers. High = more creative and varied responses.
                            </p>
                        </div>

                        {/* Max Response Tokens */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label className="text-xs font-medium">Response Length</Label>
                                <span className="text-xs font-mono text-primary">{performanceConfig.max_response_tokens} tokens</span>
                            </div>
                            <input
                                type="range"
                                min={50}
                                max={500}
                                step={25}
                                value={performanceConfig.max_response_tokens}
                                onChange={(e) => setPerformanceConfig(prev => ({ ...prev, max_response_tokens: parseInt(e.target.value) }))}
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                            />
                            <div className="flex justify-between text-[10px] text-muted-foreground">
                                <span>50 (Brief)</span>
                                <span>500 (Detailed)</span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                Maximum length of agent responses. Shorter = faster responses, better for quick Q&amp;A. Longer = more detailed explanations but slower.
                            </p>
                        </div>

                        {/* Frequency Penalty */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label className="text-xs font-medium">Anti-Repetition</Label>
                                <span className="text-xs font-mono text-primary">{performanceConfig.frequency_penalty.toFixed(1)}</span>
                            </div>
                            <input
                                type="range"
                                min={0}
                                max={10}
                                step={1}
                                value={performanceConfig.frequency_penalty * 10}
                                onChange={(e) => setPerformanceConfig(prev => ({ ...prev, frequency_penalty: parseInt(e.target.value) / 10 }))}
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                            />
                            <div className="flex justify-between text-[10px] text-muted-foreground">
                                <span>0.0 (May repeat)</span>
                                <span>1.0 (Never repeats)</span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                Prevents the agent from repeating the same phrases. Higher = more varied language but may occasionally say odd things.
                            </p>
                        </div>
                    </div>

                    {/* Self-Improving Agent Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Self-Improving Agent</h3>
                            <p className="text-xs text-muted-foreground">
                                AI automatically analyzes call transcripts and suggests workflow improvements
                            </p>
                        </div>

                        <div className="flex items-center justify-between">
                            <Label className="text-xs font-medium">Enable Self-Improving</Label>
                            <Switch
                                checked={autoImproveEnabled}
                                onCheckedChange={setAutoImproveEnabled}
                            />
                        </div>

                        {autoImproveEnabled && (
                            <>
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <Label className="text-xs font-medium">Analysis Interval</Label>
                                        <span className="text-xs font-mono text-primary">{autoImproveInterval} calls</span>
                                    </div>
                                    <input
                                        type="range"
                                        min={5}
                                        max={50}
                                        step={5}
                                        value={autoImproveInterval}
                                        onChange={(e) => setAutoImproveInterval(parseInt(e.target.value))}
                                        className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                                    />
                                    <div className="flex justify-between text-[10px] text-muted-foreground">
                                        <span>5 (Frequent)</span>
                                        <span>50 (Conservative)</span>
                                    </div>
                                    <p className="text-xs text-muted-foreground">
                                        How many completed calls between each AI analysis run.
                                    </p>
                                </div>

                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <Label className="text-xs font-medium">Auto-Apply Threshold</Label>
                                        <span className="text-xs font-mono text-primary">
                                            {autoApplyThreshold === 0 ? 'Off (manual)' : `${(autoApplyThreshold * 100).toFixed(0)}%`}
                                        </span>
                                    </div>
                                    <input
                                        type="range"
                                        min={0}
                                        max={10}
                                        step={1}
                                        value={autoApplyThreshold * 10}
                                        onChange={(e) => setAutoApplyThreshold(parseInt(e.target.value) / 10)}
                                        className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                                    />
                                    <div className="flex justify-between text-[10px] text-muted-foreground">
                                        <span>0 (Manual review)</span>
                                        <span>100% (Auto-apply all)</span>
                                    </div>
                                    <p className="text-xs text-muted-foreground">
                                        Suggestions above this confidence level are applied automatically. Set to 0 to require manual approval for all.
                                    </p>
                                </div>
                            </>
                        )}

                        {/* Manual re-analysis trigger — works even when the auto toggle above is OFF. */}
                        <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 space-y-2">
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                    <Label className="text-xs font-medium flex items-center gap-1.5">
                                        <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                                        Re-analyse all calls
                                    </Label>
                                    <p className="text-xs text-muted-foreground mt-1">
                                        Run the AI analysis right now on your recent calls. Bypasses the call-count interval and the cooldown — useful while iterating on your workflow.
                                    </p>
                                </div>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={handleAnalyzeNow}
                                    disabled={analyzing}
                                    className="text-xs gap-1.5 h-8 shrink-0"
                                >
                                    {analyzing ? (
                                        <Spinner size="sm" />
                                    ) : (
                                        <Sparkles className="w-3.5 h-3.5" />
                                    )}
                                    {analyzing ? "Starting…" : "Analyse now"}
                                </Button>
                            </div>
                        </div>
                    </div>
                </div>

                <DialogFooter className="flex-shrink-0 pt-4 border-t">
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button onClick={handleSave} disabled={isSaving}>
                        {isSaving ? "Saving..." : "Save"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
