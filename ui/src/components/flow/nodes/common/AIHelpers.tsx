'use client';

import { useReactFlow } from "@xyflow/react";
import { PlusIcon, Redo2, Sparkles, Trash2Icon, Undo2 } from "lucide-react";

import { Spinner } from "@/components/ui/ai-loader";
import { useCallback, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { ExtractionVariable, FlowEdge, FlowNode } from "@/components/flow/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/lib/auth";
import { getBackendUrl } from '@/lib/apiClient';
import { cn } from "@/lib/utils";

// Shared fetch helper.
// Takes a token *getter* (not a token) and resolves it at call time so the
// Authorization header always carries a fresh, non-expired access token. Clerk
// access tokens are short-lived (~60s); reusing a token captured at page load
// caused "Signature has expired" 401s on AI actions triggered later.
async function aiSuggest(
    baseUrl: string,
    getToken: () => Promise<string>,
    workflowId: number,
    body: Record<string, unknown>,
) {
    const accessToken = await getToken();
    const res = await fetch(`${baseUrl}/api/v1/workflow/${workflowId}/ai-suggest`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`AI suggest failed: ${res.status}`);
    return res.json();
}

// Shared undo/redo buttons
function UndoRedoButtons({
    undoCount, redoCount, onUndo, onRedo,
}: { undoCount: number; redoCount: number; onUndo: () => void; onRedo: () => void }) {
    if (undoCount === 0 && redoCount === 0) return null;
    return (
        <div className="flex items-center gap-0.5 mr-1">
            <Button type="button" variant="ghost" size="sm" onClick={onUndo}
                disabled={undoCount === 0}
                className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                title={`Undo AI change (${undoCount})`}>
                <Undo2 className="h-3.5 w-3.5" />
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={onRedo}
                disabled={redoCount === 0}
                className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                title={`Redo AI change (${redoCount})`}>
                <Redo2 className="h-3.5 w-3.5" />
            </Button>
        </div>
    );
}

// Shared AI action button
function AIButton({ loading, loadingText, idleText, onClick, disabled }: {
    loading: boolean; loadingText: string; idleText: string;
    onClick: () => void; disabled?: boolean;
}) {
    return (
        <Button type="button" variant="outline" size="sm" onClick={onClick}
            disabled={loading || disabled}
            className="gap-1.5 text-xs h-7 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 hover:text-emerald-300">
            {loading ? <Spinner size="sm" /> : <Sparkles className="h-3 w-3" />}
            {loading ? loadingText : idleText}
        </Button>
    );
}

// Shared suggestions feedback
function AISuggestionsFeedback({ suggestions }: { suggestions: string[] }) {
    if (suggestions.length === 0) return null;
    return (
        <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3 space-y-1.5">
            <p className="text-xs font-semibold text-emerald-400 flex items-center gap-1">
                <Sparkles className="h-3 w-3" /> AI Improvements Applied
            </p>
            {suggestions.map((s, i) => (
                <p key={i} className="text-xs text-muted-foreground pl-4">• {s}</p>
            ))}
        </div>
    );
}

// =============================================
// 0. AITextField – Suggest/Improve short text fields (name, description)
// =============================================

export interface AITextFieldProps {
    nodeId: string;
    value: string;
    onChange: (value: string) => void;
    fieldName: string;
    label: string;
    placeholder?: string;
    description?: string;
    inputRef?: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>;
    isInvalid?: boolean;
    required?: boolean;
    multiline?: boolean;
}

export const AITextField = ({
    nodeId, value, onChange, fieldName, label, placeholder, description,
    inputRef, isInvalid = false, required = false, multiline = false,
}: AITextFieldProps) => {
    const { workflowId } = useWorkflow();
    const { getAccessToken } = useAuth();
    const { getNodes, getEdges } = useReactFlow<FlowNode, FlowEdge>();
    const [loading, setLoading] = useState(false);
    const [undoStack, setUndoStack] = useState<string[]>([]);
    const [redoStack, setRedoStack] = useState<string[]>([]);

    const handleUndo = useCallback(() => {
        if (undoStack.length === 0) return;
        setRedoStack(s => [...s, value]);
        onChange(undoStack[undoStack.length - 1]);
        setUndoStack(s => s.slice(0, -1));
    }, [undoStack, value, onChange]);

    const handleRedo = useCallback(() => {
        if (redoStack.length === 0) return;
        setUndoStack(s => [...s, value]);
        onChange(redoStack[redoStack.length - 1]);
        setRedoStack(s => s.slice(0, -1));
    }, [redoStack, value, onChange]);

    const handleAI = async () => {
        if (!workflowId) return;
        setLoading(true);
        try {
            const baseUrl = getBackendUrl();
            const currentNodes = getNodes().map(n => {
                if (n.id === nodeId) {
                    return { id: n.id, type: n.type, data: { ...n.data, [fieldName]: value }, position: n.position };
                }
                return { id: n.id, type: n.type, data: n.data, position: n.position };
            });
            const currentEdges = getEdges().map(e => ({ id: e.id, source: e.source, target: e.target, data: e.data }));
            const data = await aiSuggest(baseUrl, getAccessToken, workflowId, {
                type: 'suggest_field',
                node_id: nodeId,
                field_name: fieldName,
                current_value: value,
                current_nodes: currentNodes,
                current_edges: currentEdges,
            });
            if (data.suggestion?.text) {
                setUndoStack(s => [...s, value]);
                setRedoStack([]);
                onChange(data.suggestion.text);
            }
        } catch (err) {
            console.error('AI field suggestion failed:', err);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div
            className={cn(
                "space-y-2 transition-all duration-300 rounded-lg",
                isInvalid && "ring-2 ring-red-500/50 p-3 bg-red-500/5"
            )}
            data-field={fieldName}
        >
            <div className="flex items-center justify-between">
                <Label className={cn("text-sm font-medium", isInvalid && "text-red-500")}>
                    {label} {required && <span className="text-red-500">*</span>}
                </Label>
                <div className="flex items-center gap-1">
                    <UndoRedoButtons undoCount={undoStack.length} redoCount={redoStack.length}
                        onUndo={handleUndo} onRedo={handleRedo} />
                    <AIButton loading={loading}
                        loadingText={value ? "Improving..." : "Generating..."}
                        idleText={value ? "Improve with AI" : "Generate with AI"}
                        onClick={handleAI} />
                </div>
            </div>
            {multiline ? (
                <Textarea
                    ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={placeholder}
                    className={cn("min-h-[60px] max-h-[120px] resize-none", isInvalid && "border-red-500")}
                />
            ) : (
                <Input
                    ref={inputRef as React.RefObject<HTMLInputElement>}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={placeholder}
                    className={cn(isInvalid && "border-red-500")}
                />
            )}
            {description && (
                <p className="text-xs text-muted-foreground">{description}</p>
            )}
        </div>
    );
};

// =============================================
// 1. AIPromptField – Improve/Generate any node prompt
// =============================================

export interface AIPromptFieldProps {
    nodeId: string;
    prompt: string;
    setPrompt: (value: string) => void;
    setName?: (value: string) => void;
    label?: string;
    placeholder?: string;
    description?: string;
    promptRef?: React.RefObject<HTMLTextAreaElement | null>;
    isInvalid?: boolean;
    validationMessage?: string | null;
    minHeight?: string;
}

export const AIPromptField = ({
    nodeId,
    prompt,
    setPrompt,
    setName,
    label = "Instructions / Prompt",
    placeholder = "You are a helpful customer service agent. Your goal is to...",
    description,
    promptRef,
    isInvalid = false,
    validationMessage,
    minHeight = "160px",
}: AIPromptFieldProps) => {
    const { workflowId } = useWorkflow();
    const { getAccessToken } = useAuth();
    const { getNodes, getEdges } = useReactFlow<FlowNode, FlowEdge>();
    const [loading, setLoading] = useState(false);
    const [action, setAction] = useState<string | null>(null);
    const [suggestions, setSuggestions] = useState<string[]>([]);

    const [undoStack, setUndoStack] = useState<string[]>([]);
    const [redoStack, setRedoStack] = useState<string[]>([]);

    const handleUndo = useCallback(() => {
        if (undoStack.length === 0) return;
        const prev = undoStack[undoStack.length - 1];
        setUndoStack(s => s.slice(0, -1));
        setRedoStack(s => [...s, prompt]);
        setPrompt(prev);
    }, [undoStack, prompt, setPrompt]);

    const handleRedo = useCallback(() => {
        if (redoStack.length === 0) return;
        const next = redoStack[redoStack.length - 1];
        setRedoStack(s => s.slice(0, -1));
        setUndoStack(s => [...s, prompt]);
        setPrompt(next);
    }, [redoStack, prompt, setPrompt]);

    const handleAI = async (type: 'node_prompt' | 'node_improve') => {
        if (!workflowId) return;
        setLoading(true);
        setAction(type);
        setSuggestions([]);
        try {
            const baseUrl = getBackendUrl();
            const currentNodes = getNodes().map(n => {
                if (n.id === nodeId) {
                    return { id: n.id, type: n.type, data: { ...n.data, prompt }, position: n.position };
                }
                return { id: n.id, type: n.type, data: n.data, position: n.position };
            });
            const currentEdges = getEdges().map(e => ({ id: e.id, source: e.source, target: e.target, data: e.data }));

            const data = await aiSuggest(baseUrl, getAccessToken, workflowId, {
                type, node_id: nodeId, current_nodes: currentNodes, current_edges: currentEdges,
            });
            const suggestion = data.suggestion;
            if (type === 'node_prompt' && suggestion.prompt) {
                setUndoStack(s => [...s, prompt]);
                setRedoStack([]);
                setPrompt(suggestion.prompt);
                if (suggestion.name && setName) setName(suggestion.name);
            } else if (type === 'node_improve' && suggestion.improved_prompt) {
                setUndoStack(s => [...s, prompt]);
                setRedoStack([]);
                setPrompt(suggestion.improved_prompt);
                if (suggestion.suggestions) setSuggestions(suggestion.suggestions);
            }
        } catch (err) {
            console.error('AI suggestion failed:', err);
        } finally {
            setLoading(false);
            setAction(null);
        }
    };

    return (
        <div
            className={cn(
                "space-y-3 transition-all duration-300 rounded-xl",
                isInvalid && "ring-2 ring-red-500/50 p-1 bg-red-500/5"
            )}
            data-field="prompt"
        >
            <div className="flex items-center justify-between">
                <Label className={cn("text-sm font-semibold text-foreground/90", isInvalid && "text-red-500")}>
                    {label} <span className="text-red-500">*</span>
                </Label>
                <div className="flex items-center gap-1.5">
                    {isInvalid && (
                        <span className="text-xs text-red-500 font-medium animate-pulse px-2 py-1 rounded-full bg-red-500/10 border border-red-500/20">
                            Required
                        </span>
                    )}
                    <UndoRedoButtons undoCount={undoStack.length} redoCount={redoStack.length}
                        onUndo={handleUndo} onRedo={handleRedo} />
                    {prompt ? (
                        <AIButton loading={loading && action === 'node_improve'}
                            loadingText="Improving..." idleText="Improve with AI"
                            onClick={() => handleAI('node_improve')} disabled={loading} />
                    ) : (
                        <AIButton loading={loading && action === 'node_prompt'}
                            loadingText="Generating..." idleText="Generate with AI"
                            onClick={() => handleAI('node_prompt')} disabled={loading} />
                    )}
                </div>
            </div>

            <div className="p-1 rounded-xl border border-white/5 bg-black/20 backdrop-blur-sm group focus-within:ring-1 focus-within:ring-primary/30 transition-all">
                <Textarea
                    ref={promptRef}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    className={cn(
                        "resize-none font-mono text-sm leading-relaxed bg-transparent border-none focus-visible:ring-0",
                        isInvalid && "text-red-300 placeholder:text-red-400/50"
                    )}
                    style={{ minHeight, maxHeight: '500px', overflowY: 'auto' }}
                    placeholder={placeholder}
                />
            </div>

            <AISuggestionsFeedback suggestions={suggestions} />

            {(description || (isInvalid && validationMessage)) && (
                <div className="flex items-start justify-between gap-4 px-1">
                    {description && (
                        <p className="text-xs text-muted-foreground/80 leading-relaxed max-w-[80%]">{description}</p>
                    )}
                    {isInvalid && validationMessage && (
                        <p className="text-xs text-red-400 flex items-center gap-1.5 font-medium bg-red-500/10 px-2 py-1 rounded-md border border-red-500/10">
                            <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
                            {validationMessage}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
};

// =============================================
// 2. AIExtractionPrompt – Improve extraction prompt
// =============================================

export interface AIExtractionPromptProps {
    nodeId: string;
    extractionPrompt: string;
    setExtractionPrompt: (value: string) => void;
    prompt: string;
    extractionVariables: ExtractionVariable[];
}

export const AIExtractionPrompt = ({
    nodeId, extractionPrompt, setExtractionPrompt, prompt, extractionVariables,
}: AIExtractionPromptProps) => {
    const { workflowId } = useWorkflow();
    const { getAccessToken } = useAuth();
    const { getNodes, getEdges } = useReactFlow<FlowNode, FlowEdge>();
    const [loading, setLoading] = useState(false);
    const [suggestions, setSuggestions] = useState<string[]>([]);
    const [undoStack, setUndoStack] = useState<string[]>([]);
    const [redoStack, setRedoStack] = useState<string[]>([]);

    const handleUndo = useCallback(() => {
        if (undoStack.length === 0) return;
        setRedoStack(s => [...s, extractionPrompt]);
        setExtractionPrompt(undoStack[undoStack.length - 1]);
        setUndoStack(s => s.slice(0, -1));
    }, [undoStack, extractionPrompt, setExtractionPrompt]);

    const handleRedo = useCallback(() => {
        if (redoStack.length === 0) return;
        setUndoStack(s => [...s, extractionPrompt]);
        setExtractionPrompt(redoStack[redoStack.length - 1]);
        setRedoStack(s => s.slice(0, -1));
    }, [redoStack, extractionPrompt, setExtractionPrompt]);

    const handleImprove = async () => {
        if (!workflowId) return;
        setLoading(true);
        setSuggestions([]);
        try {
            const baseUrl = getBackendUrl();
            const currentNodes = getNodes().map(n =>
                n.id === nodeId
                    ? { id: n.id, type: n.type, position: n.position, data: { ...n.data, prompt, extraction_prompt: extractionPrompt, extraction_variables: extractionVariables } }
                    : { id: n.id, type: n.type, data: n.data, position: n.position }
            );
            const currentEdges = getEdges().map(e => ({ id: e.id, source: e.source, target: e.target, data: e.data }));
            const data = await aiSuggest(baseUrl, getAccessToken, workflowId, {
                type: 'extraction_improve', node_id: nodeId,
                current_nodes: currentNodes, current_edges: currentEdges,
            });
            if (data.suggestion?.improved_prompt) {
                setUndoStack(s => [...s, extractionPrompt]);
                setRedoStack([]);
                setExtractionPrompt(data.suggestion.improved_prompt);
            }
            if (data.suggestion?.suggestions) setSuggestions(data.suggestion.suggestions);
        } catch (err) {
            console.error('AI extraction suggestion failed:', err);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">Extraction Prompt</Label>
                <div className="flex items-center gap-1.5">
                    <UndoRedoButtons undoCount={undoStack.length} redoCount={redoStack.length}
                        onUndo={handleUndo} onRedo={handleRedo} />
                    <AIButton loading={loading} loadingText="Improving..." idleText="Improve with AI"
                        onClick={handleImprove} />
                </div>
            </div>
            <Textarea value={extractionPrompt} onChange={(e) => setExtractionPrompt(e.target.value)}
                className="min-h-[80px] max-h-[150px] resize-none"
                placeholder="Extract the following information from the conversation..." />
            <AISuggestionsFeedback suggestions={suggestions} />
        </div>
    );
};

// =============================================
// 3. AIExtractionVariables – Generate variables with AI
// =============================================

export interface AIExtractionVariablesProps {
    nodeId: string;
    prompt: string;
    extractionPrompt: string;
    setExtractionPrompt: (value: string) => void;
    extractionVariables: ExtractionVariable[];
    setExtractionVariables: (vars: ExtractionVariable[]) => void;
    onVariableNameChange: (idx: number, value: string) => void;
    onVariableTypeChange: (idx: number, value: 'string' | 'number' | 'boolean') => void;
    onVariablePromptChange: (idx: number, value: string) => void;
    onVariableRequiredChange: (idx: number, value: boolean) => void;
    onRemoveVariable: (idx: number) => void;
    onAddVariable: () => void;
}

export const AIExtractionVariables = ({
    nodeId, prompt, extractionPrompt, setExtractionPrompt,
    extractionVariables, setExtractionVariables,
    onVariableNameChange, onVariableTypeChange, onVariablePromptChange,
    onVariableRequiredChange, onRemoveVariable, onAddVariable,
}: AIExtractionVariablesProps) => {
    const { workflowId } = useWorkflow();
    const { getAccessToken } = useAuth();
    const { getNodes, getEdges } = useReactFlow<FlowNode, FlowEdge>();
    const [loading, setLoading] = useState(false);
    const [undoStack, setUndoStack] = useState<{ vars: ExtractionVariable[]; prompt: string }[]>([]);
    const [redoStack, setRedoStack] = useState<{ vars: ExtractionVariable[]; prompt: string }[]>([]);

    const handleUndo = useCallback(() => {
        if (undoStack.length === 0) return;
        const prev = undoStack[undoStack.length - 1];
        setUndoStack(s => s.slice(0, -1));
        setRedoStack(s => [...s, { vars: extractionVariables, prompt: extractionPrompt }]);
        setExtractionVariables(prev.vars);
        setExtractionPrompt(prev.prompt);
    }, [undoStack, extractionVariables, extractionPrompt, setExtractionVariables, setExtractionPrompt]);

    const handleRedo = useCallback(() => {
        if (redoStack.length === 0) return;
        const next = redoStack[redoStack.length - 1];
        setRedoStack(s => s.slice(0, -1));
        setUndoStack(s => [...s, { vars: extractionVariables, prompt: extractionPrompt }]);
        setExtractionVariables(next.vars);
        setExtractionPrompt(next.prompt);
    }, [redoStack, extractionVariables, extractionPrompt, setExtractionVariables, setExtractionPrompt]);

    const handleGenerate = async () => {
        if (!workflowId) return;
        setLoading(true);
        try {
            const baseUrl = getBackendUrl();
            const currentNodes = getNodes().map(n =>
                n.id === nodeId
                    ? { id: n.id, type: n.type, position: n.position, data: { ...n.data, prompt, extraction_prompt: extractionPrompt, extraction_variables: extractionVariables } }
                    : { id: n.id, type: n.type, data: n.data, position: n.position }
            );
            const currentEdges = getEdges().map(e => ({ id: e.id, source: e.source, target: e.target, data: e.data }));
            const data = await aiSuggest(baseUrl, getAccessToken, workflowId, {
                type: 'suggest_variables', node_id: nodeId,
                current_nodes: currentNodes, current_edges: currentEdges,
            });
            const suggestion = data.suggestion;
            if (suggestion?.variables?.length > 0) {
                setUndoStack(s => [...s, { vars: extractionVariables, prompt: extractionPrompt }]);
                setRedoStack([]);
                setExtractionVariables(suggestion.variables);
                if (suggestion.extraction_prompt) setExtractionPrompt(suggestion.extraction_prompt);
            }
        } catch (err) {
            console.error('AI variable suggestion failed:', err);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">Variables to Extract</Label>
                <div className="flex items-center gap-1.5">
                    <UndoRedoButtons undoCount={undoStack.length} redoCount={redoStack.length}
                        onUndo={handleUndo} onRedo={handleRedo} />
                    <AIButton loading={loading} loadingText="Generating..." idleText="Generate with AI"
                        onClick={handleGenerate} />
                </div>
            </div>

            {extractionVariables.map((v, idx) => (
                <div key={idx} className="space-y-2 border rounded-md p-3 bg-background">
                    <div className="flex items-center gap-2">
                        <Input placeholder="Variable name" value={v.name}
                            onChange={(e) => onVariableNameChange(idx, e.target.value)} className="flex-1" />
                        <select className="border rounded-md p-2 text-sm bg-background h-9" value={v.type}
                            onChange={(e) => onVariableTypeChange(idx, e.target.value as 'string' | 'number' | 'boolean')}>
                            <option value="string">String</option>
                            <option value="number">Number</option>
                            <option value="boolean">Boolean</option>
                        </select>
                        <Button variant="ghost" size="icon" onClick={() => onRemoveVariable(idx)}>
                            <Trash2Icon className="w-4 h-4 text-muted-foreground" />
                        </Button>
                    </div>
                    <Textarea placeholder="Description of what to extract for this variable"
                        value={v.prompt ?? ''} onChange={(e) => onVariablePromptChange(idx, e.target.value)}
                        className="min-h-[50px] resize-none text-sm" />
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <Switch
                                id={`var-required-${nodeId}-${idx}`}
                                checked={v.required !== false}
                                onCheckedChange={(checked) => onVariableRequiredChange(idx, checked)}
                            />
                            <Label htmlFor={`var-required-${nodeId}-${idx}`} className="cursor-pointer text-xs">
                                {v.required !== false ? 'Required (critical)' : 'Optional'}
                            </Label>
                        </div>
                        <span className="text-[11px] text-muted-foreground">
                            {v.required !== false
                                ? 'Agent must collect this before moving on'
                                : "Captured if mentioned, won't block the call"}
                        </span>
                    </div>
                </div>
            ))}

            <Button variant="outline" size="sm" onClick={onAddVariable}>
                <PlusIcon className="w-4 h-4 mr-1" /> Add Variable
            </Button>
        </div>
    );
};
