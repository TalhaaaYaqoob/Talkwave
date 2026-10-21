import { NodeProps, NodeToolbar, Position } from "@xyflow/react";
import {
    Book,
    Clock,
    Edit,
    GitFork,
    Globe,
    Headset,
    MessageSquare,
    PlusIcon,
    Repeat,
    Trash2Icon,
    Wrench
} from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import {
    AgentToolReference,
    DEFAULT_KNOWLEDGE_BASE_CONFIG,
    ExitCondition,
    ExtractionVariable,
    FlowNodeData,
    KnowledgeBaseConfig
} from "@/components/flow/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

// Sub-components for each tab
import { ExitConditionsPanel, KnowledgeBasePanel, ToolsPanel } from "./agent-panels";
import { AIExtractionPrompt, AIExtractionVariables, AIPromptField, AITextField } from "./common/AIHelpers";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface AgentNodeProps extends NodeProps {
    data: FlowNodeData;
}

export const AgentNode = memo(({ data, selected, id }: AgentNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleDeleteNode, handleClearValidation, handleRestoreValidation } = useNodeHandlers({ id });
    const { saveWorkflow, workflowId } = useWorkflow();

    // Tab state for navigation
    const [activeTab, setActiveTab] = useState("instructions");
    const promptRef = useRef<HTMLTextAreaElement>(null);
    const nameRef = useRef<HTMLInputElement>(null);

    // Track original validation error so we can restore it if the field is emptied again
    const savedValidation = useRef<{ field: string; message: string } | null>(null);

    // Instructions tab state
    const [prompt, setPrompt] = useState(data.prompt ?? "");
    const [name, setName] = useState(data.name);
    const [allowInterrupt, setAllowInterrupt] = useState(data.allow_interrupt ?? true);
    const [addGlobalPrompt, setAddGlobalPrompt] = useState(data.add_global_prompt ?? true);
    const [webSearchEnabled, setWebSearchEnabled] = useState(data.web_search_enabled ?? false);

    // Conversation constraints (Timer / Burst)
    const [timerDuration, setTimerDuration] = useState<number | undefined>(data.timer_duration);
    const [maxRounds, setMaxRounds] = useState<number | undefined>(data.max_rounds);

    // Variable Extraction state (part of Instructions)
    const [extractionEnabled, setExtractionEnabled] = useState(data.extraction_enabled ?? false);
    const [extractionPrompt, setExtractionPrompt] = useState(data.extraction_prompt ?? "");
    const [extractionVariables, setExtractionVariables] = useState<ExtractionVariable[]>(data.extraction_variables ?? []);

    // Tools tab state
    const [tools, setTools] = useState<AgentToolReference[]>(data.tools ?? []);

    // Exit Conditions tab state
    const [exitConditions, setExitConditions] = useState<ExitCondition[]>(data.exit_conditions ?? []);

    // Knowledge Base tab state
    const [knowledgeBase, setKnowledgeBase] = useState<KnowledgeBaseConfig>(
        data.knowledge_base ?? DEFAULT_KNOWLEDGE_BASE_CONFIG
    );

    // Save original validation error when it first appears
    useEffect(() => {
        if (data.invalid && data.invalidField && data.validationMessage) {
            const field = data.invalidField.startsWith("data.") ? data.invalidField.slice(5) : data.invalidField;
            savedValidation.current = { field, message: data.validationMessage };
        }
    }, [data.invalid, data.invalidField, data.validationMessage]);

    const handleFieldChange = useCallback((field: 'name' | 'prompt', value: string) => {
        if (field === 'name') setName(value);
        else setPrompt(value);

        if (data.invalid && savedValidation.current?.field === field && value.trim().length > 0) {
            handleClearValidation();
        } else if (!data.invalid && savedValidation.current?.field === field && value.trim().length === 0) {
            handleRestoreValidation(savedValidation.current.message, savedValidation.current.field);
        }
    }, [data.invalid, handleClearValidation, handleRestoreValidation]);

    // Navigate to field when clicking on validation error
    const handleNavigateToField = useCallback((fieldName: string) => {
        const fieldToTab: Record<string, string> = {
            prompt: "instructions",
            name: "instructions",
            extraction_prompt: "instructions",
            extraction_variables: "instructions",
            tools: "tools",
            exit_conditions: "exits",
            knowledge_base: "knowledge",
        };

        const targetTab = fieldToTab[fieldName] || "instructions";
        setActiveTab(targetTab);

        setTimeout(() => {
            if (fieldName === "prompt" && promptRef.current) {
                promptRef.current.focus();
                promptRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } else if (fieldName === "name" && nameRef.current) {
                nameRef.current.focus();
                nameRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }, 150);
    }, []);

    const handleSave = async () => {
        handleSaveNodeData({
            ...data,
            prompt,
            name,
            is_static: false,
            allow_interrupt: allowInterrupt,
            add_global_prompt: addGlobalPrompt,
            web_search_enabled: webSearchEnabled,
            timer_duration: timerDuration,
            max_rounds: maxRounds,
            extraction_enabled: extractionEnabled,
            extraction_prompt: extractionPrompt,
            extraction_variables: extractionVariables,
            tools,
            exit_conditions: exitConditions,
            knowledge_base: knowledgeBase,
        });
        setOpen(false);
        // Save the workflow after updating node data with a small delay
        setTimeout(async () => {
            await saveWorkflow();
        }, 100);
    };

    const handleOpenChange = (newOpen: boolean) => {
        if (newOpen) {
            setPrompt(data.prompt ?? "");
            setName(data.name);
            setAllowInterrupt(data.allow_interrupt ?? true);
            setAddGlobalPrompt(data.add_global_prompt ?? true);
            setWebSearchEnabled(data.web_search_enabled ?? false);
            setTimerDuration(data.timer_duration);
            setMaxRounds(data.max_rounds);
            setExtractionEnabled(data.extraction_enabled ?? false);
            setExtractionPrompt(data.extraction_prompt ?? "");
            setExtractionVariables(data.extraction_variables ?? []);
            setTools(data.tools ?? []);
            setExitConditions(data.exit_conditions ?? []);
            setKnowledgeBase(data.knowledge_base ?? DEFAULT_KNOWLEDGE_BASE_CONFIG);
        }
        setOpen(newOpen);
    };

    // Sync form state from node data only when the underlying prompt actually changes
    // (e.g., undo/redo). We track the data.prompt value to avoid resetting during AI edits.
    const lastSyncedPrompt = useRef(data.prompt);
    useEffect(() => {
        if (open && data.prompt !== lastSyncedPrompt.current) {
            lastSyncedPrompt.current = data.prompt;
            setPrompt(data.prompt ?? "");
            setName(data.name);
            setAllowInterrupt(data.allow_interrupt ?? true);
            setAddGlobalPrompt(data.add_global_prompt ?? true);
            setWebSearchEnabled(data.web_search_enabled ?? false);
            setTimerDuration(data.timer_duration);
            setMaxRounds(data.max_rounds);
            setExtractionEnabled(data.extraction_enabled ?? false);
            setExtractionPrompt(data.extraction_prompt ?? "");
            setExtractionVariables(data.extraction_variables ?? []);
            setTools(data.tools ?? []);
            setExitConditions(data.exit_conditions ?? []);
            setKnowledgeBase(data.knowledge_base ?? DEFAULT_KNOWLEDGE_BASE_CONFIG);
        }
    }, [data, open]);

    const hasChanges = useMemo(() => {
        if (name !== data.name) return true;
        if (prompt !== (data.prompt ?? "")) return true;
        if (allowInterrupt !== (data.allow_interrupt ?? true)) return true;
        if (addGlobalPrompt !== (data.add_global_prompt ?? true)) return true;
        if (webSearchEnabled !== (data.web_search_enabled ?? false)) return true;
        if (timerDuration !== data.timer_duration) return true;
        if (maxRounds !== data.max_rounds) return true;
        if (extractionEnabled !== (data.extraction_enabled ?? false)) return true;
        if (extractionPrompt !== (data.extraction_prompt ?? "")) return true;
        if (JSON.stringify(extractionVariables) !== JSON.stringify(data.extraction_variables ?? [])) return true;
        if (JSON.stringify(tools) !== JSON.stringify(data.tools ?? [])) return true;
        if (JSON.stringify(exitConditions) !== JSON.stringify(data.exit_conditions ?? [])) return true;
        if (JSON.stringify(knowledgeBase) !== JSON.stringify(data.knowledge_base ?? DEFAULT_KNOWLEDGE_BASE_CONFIG)) return true;
        return false;
    }, [name, prompt, allowInterrupt, addGlobalPrompt, webSearchEnabled, timerDuration, maxRounds, extractionEnabled, extractionPrompt, extractionVariables, tools, exitConditions, knowledgeBase, data]);

    // Count badges for tabs
    const toolsCount = tools.length;
    const exitConditionsCount = exitConditions.length;

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title={data.name || 'Agent'}
                icon={<Headset />}
                nodeType="agent"
                hasSourceHandle={true}
                hasTargetHandle={true}
                onDoubleClick={() => setOpen(true)}
                onEdit={() => setOpen(true)}
                nodeId={id}
            >
                <p className="text-sm text-muted-foreground line-clamp-3 leading-relaxed">
                    {data.prompt || 'No prompt configured'}
                </p>
                {/* Feature indicators */}
                <div className="flex flex-wrap gap-1 mt-2">
                    {(data.tools?.length ?? 0) > 0 ? (
                        <Badge variant="secondary" className="text-xs">
                            <Wrench className="w-3 h-3 mr-1" />
                            {data.tools?.length} tools
                        </Badge>
                    ) : (
                        <Badge 
                            variant="outline" 
                            className="text-xs text-muted-foreground/60 border-dashed cursor-pointer hover:text-primary hover:border-primary transition-colors"
                            onClick={() => setOpen(true)}
                        >
                            <PlusIcon className="w-3 h-3 mr-1" />
                            Add tools
                        </Badge>
                    )}
                    {(data.exit_conditions?.length ?? 0) > 0 && (
                        <Badge variant="secondary" className="text-xs">
                            <GitFork className="w-3 h-3 mr-1" />
                            {data.exit_conditions?.length} exits
                        </Badge>
                    )}
                    {data.knowledge_base?.enabled && (
                        <Badge variant="secondary" className="text-xs">
                            <Book className="w-3 h-3 mr-1" />
                            KB
                        </Badge>
                    )}
                    {data.web_search_enabled && (
                        <Badge variant="secondary" className="text-xs bg-primary/20 text-primary">
                            <Globe className="w-3 h-3 mr-1" />
                            Web
                        </Badge>
                    )}
                    {data.timer_duration && (
                        <Badge variant="secondary" className="text-xs bg-orange-500/20 text-orange-400">
                            <Clock className="w-3 h-3 mr-1" />
                            {data.timer_duration}s
                        </Badge>
                    )}
                    {data.max_rounds && (
                        <Badge variant="secondary" className="text-xs bg-teal-500/20 text-teal-400">
                            <Repeat className="w-3 h-3 mr-1" />
                            {data.max_rounds} rounds
                        </Badge>
                    )}
                </div>
            </NodeContent>

            <NodeToolbar isVisible={selected} position={Position.Right}>
                <div className="flex flex-col gap-1">
                    <Button onClick={() => setOpen(true)} variant="outline" size="icon">
                        <Edit />
                    </Button>
                    <Button onClick={handleDeleteNode} variant="outline" size="icon">
                        <Trash2Icon />
                    </Button>
                </div>
            </NodeToolbar>

            <NodeEditDialog
                open={open}
                onOpenChange={handleOpenChange}
                nodeData={data}
                title="Edit Agent"
                onSave={handleSave}
                hasChanges={hasChanges}
                dialogClassName="max-w-4xl"
                onNavigateToField={handleNavigateToField}
            >
                {open && (() => {
                    const nf = data.invalidField?.startsWith("data.") ? data.invalidField.slice(5) : data.invalidField;
                    return (
                    <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
                        <TabsList className="w-full justify-start mb-4">
                            <TabsTrigger value="instructions" className="gap-1.5">
                                <MessageSquare className="w-4 h-4" />
                                Instructions
                                {(nf === "prompt" || nf === "name") && (
                                    <span className="ml-1 h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                                )}
                            </TabsTrigger>
                            <TabsTrigger value="tools" className="gap-1.5">
                                <Wrench className="w-4 h-4" />
                                Tools
                                {toolsCount > 0 && (
                                    <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                                        {toolsCount}
                                    </Badge>
                                )}
                                {nf === "tools" && (
                                    <span className="ml-1 h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                                )}
                            </TabsTrigger>
                            <TabsTrigger value="exits" className="gap-1.5">
                                <GitFork className="w-4 h-4" />
                                Exit Conditions
                                {exitConditionsCount > 0 && (
                                    <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                                        {exitConditionsCount}
                                    </Badge>
                                )}
                                {nf === "exit_conditions" && (
                                    <span className="ml-1 h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                                )}
                            </TabsTrigger>
                            <TabsTrigger value="knowledge" className="gap-1.5">
                                <Book className="w-4 h-4" />
                                Knowledge Base
                                {knowledgeBase?.enabled && (
                                    <Badge className="ml-1 h-5 px-1.5 bg-green-500/20 text-green-600">
                                        On
                                    </Badge>
                                )}
                                {nf === "knowledge_base" && (
                                    <span className="ml-1 h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                                )}
                            </TabsTrigger>
                        </TabsList>

                        <TabsContent value="instructions" className="mt-0">
                            <InstructionsTabContent
                                nodeId={id}
                                name={name}
                                setName={(v: string) => handleFieldChange('name', v)}
                                nameRef={nameRef}
                                prompt={prompt}
                                setPrompt={(v: string) => handleFieldChange('prompt', v)}
                                promptRef={promptRef}
                                allowInterrupt={allowInterrupt}
                                setAllowInterrupt={setAllowInterrupt}
                                addGlobalPrompt={addGlobalPrompt}
                                setAddGlobalPrompt={setAddGlobalPrompt}
                                webSearchEnabled={webSearchEnabled}
                                setWebSearchEnabled={setWebSearchEnabled}
                                timerDuration={timerDuration}
                                setTimerDuration={setTimerDuration}
                                maxRounds={maxRounds}
                                setMaxRounds={setMaxRounds}
                                extractionEnabled={extractionEnabled}
                                setExtractionEnabled={setExtractionEnabled}
                                extractionPrompt={extractionPrompt}
                                setExtractionPrompt={setExtractionPrompt}
                                extractionVariables={extractionVariables}
                                setExtractionVariables={setExtractionVariables}
                                invalidField={data.invalidField}
                                validationMessage={data.validationMessage}
                            />
                        </TabsContent>

                        <TabsContent value="tools" className="mt-0">
                            <ToolsPanel
                                tools={tools}
                                setTools={setTools}
                            />
                        </TabsContent>

                        <TabsContent value="exits" className="mt-0">
                            <ExitConditionsPanel
                                exitConditions={exitConditions}
                                setExitConditions={setExitConditions}
                            />
                        </TabsContent>

                        <TabsContent value="knowledge" className="mt-0">
                            <KnowledgeBasePanel
                                config={knowledgeBase}
                                setConfig={setKnowledgeBase}
                                workflowId={workflowId}
                            />
                        </TabsContent>
                    </Tabs>
                    );
                })()}
            </NodeEditDialog>
        </>
    );
});

// =====================
// Instructions Tab Content
// =====================

interface InstructionsTabContentProps {
    nodeId: string;
    name: string;
    setName: (value: string) => void;
    nameRef?: React.RefObject<HTMLInputElement | null>;
    prompt: string;
    setPrompt: (value: string) => void;
    promptRef?: React.RefObject<HTMLTextAreaElement | null>;
    allowInterrupt: boolean;
    setAllowInterrupt: (value: boolean) => void;
    addGlobalPrompt: boolean;
    setAddGlobalPrompt: (value: boolean) => void;
    webSearchEnabled: boolean;
    setWebSearchEnabled: (value: boolean) => void;
    timerDuration?: number;
    setTimerDuration: (value: number | undefined) => void;
    maxRounds?: number;
    setMaxRounds: (value: number | undefined) => void;
    extractionEnabled: boolean;
    setExtractionEnabled: (value: boolean) => void;
    extractionPrompt: string;
    setExtractionPrompt: (value: string) => void;
    extractionVariables: ExtractionVariable[];
    setExtractionVariables: (vars: ExtractionVariable[]) => void;
    invalidField?: string | null;
    validationMessage?: string | null;
}

const InstructionsTabContent = ({
    nodeId,
    name,
    setName,
    nameRef,
    prompt,
    setPrompt,
    promptRef,
    allowInterrupt,
    setAllowInterrupt,
    addGlobalPrompt,
    setAddGlobalPrompt,
    webSearchEnabled,
    setWebSearchEnabled,
    timerDuration,
    setTimerDuration,
    maxRounds,
    setMaxRounds,
    extractionEnabled,
    setExtractionEnabled,
    extractionPrompt,
    setExtractionPrompt,
    extractionVariables,
    setExtractionVariables,
    invalidField,
    validationMessage,
}: InstructionsTabContentProps) => {
    const normalizedField = invalidField?.startsWith("data.") ? invalidField.slice(5) : invalidField;
    const isPromptInvalid = normalizedField === "prompt";
    const isNameInvalid = normalizedField === "name";
    const handleVariableNameChange = (idx: number, value: string) => {
        const newVars = [...extractionVariables];
        newVars[idx] = { ...newVars[idx], name: value };
        setExtractionVariables(newVars);
    };

    const handleVariableTypeChange = (idx: number, value: 'string' | 'number' | 'boolean') => {
        const newVars = [...extractionVariables];
        newVars[idx] = { ...newVars[idx], type: value };
        setExtractionVariables(newVars);
    };

    const handleVariablePromptChange = (idx: number, value: string) => {
        const newVars = [...extractionVariables];
        newVars[idx] = { ...newVars[idx], prompt: value };
        setExtractionVariables(newVars);
    };

    const handleVariableRequiredChange = (idx: number, value: boolean) => {
        const newVars = [...extractionVariables];
        newVars[idx] = { ...newVars[idx], required: value };
        setExtractionVariables(newVars);
    };

    const handleRemoveVariable = (idx: number) => {
        const newVars = extractionVariables.filter((_, i) => i !== idx);
        setExtractionVariables(newVars);
    };

    const handleAddVariable = () => {
        setExtractionVariables([...extractionVariables, { name: '', type: 'string', prompt: '', required: true }]);
    };

    return (
        <div className="grid gap-6 max-h-[60vh] overflow-y-auto pr-2 custom-scrollbar">
            <AITextField
                nodeId={nodeId}
                value={name}
                onChange={setName}
                fieldName="name"
                label="Name"
                placeholder="e.g., Greeting, Order Processing, Support"
                description="Short name to identify this agent step in call logs."
                inputRef={nameRef}
                isInvalid={isNameInvalid}
                required
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex items-start space-x-4 p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group" onClick={() => setAllowInterrupt(!allowInterrupt)}>
                    <Switch id="allow-interrupt" checked={allowInterrupt} onCheckedChange={setAllowInterrupt} className="mt-1 data-[state=checked]:bg-primary" />
                    <div className="space-y-1">
                        <Label htmlFor="allow-interrupt" className="text-sm font-medium cursor-pointer group-hover:text-primary transition-colors">Allow Interruption</Label>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                            User can interrupt the bot while speaking
                        </p>
                    </div>
                </div>

                <div className="flex items-start space-x-4 p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group" onClick={() => setAddGlobalPrompt(!addGlobalPrompt)}>
                    <Switch id="add-global-prompt" checked={addGlobalPrompt} onCheckedChange={setAddGlobalPrompt} className="mt-1 data-[state=checked]:bg-primary" />
                    <div className="space-y-1">
                        <Label htmlFor="add-global-prompt" className="text-sm font-medium cursor-pointer group-hover:text-primary transition-colors">Add Global Prompt</Label>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                            Include global prompt with this node
                        </p>
                    </div>
                </div>

                <div className="flex items-start space-x-4 p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group col-span-1 md:col-span-2" onClick={() => setWebSearchEnabled(!webSearchEnabled)}>
                    <Switch id="web-search-enabled" checked={webSearchEnabled} onCheckedChange={setWebSearchEnabled} className="mt-1 data-[state=checked]:bg-primary" />
                    <div className="flex-1 space-y-1">
                        <div className="flex items-center gap-2">
                            <Globe className="w-4 h-4 text-primary" />
                            <Label htmlFor="web-search-enabled" className="text-sm font-medium cursor-pointer group-hover:text-primary transition-colors">Enable Web Search</Label>
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                            Allow the agent to search the internet for real-time information
                        </p>
                    </div>
                </div>
            </div>

            {/* Conversation Constraints */}
            <div className="border rounded-lg p-4 space-y-4">
                <div className="space-y-1">
                    <h3 className="text-sm font-medium flex items-center gap-2">
                        <Clock className="w-4 h-4 text-orange-400" />
                        Conversation Constraints
                    </h3>
                    <p className="text-xs text-muted-foreground">
                        Optionally limit this step by time or number of exchanges.
                    </p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label className="text-xs font-medium flex items-center gap-1.5">
                            <Clock className="w-3.5 h-3.5 text-orange-400" />
                            Timer Duration (seconds)
                        </Label>
                        <div className="flex items-center gap-2">
                            <input
                                type="number"
                                min={30}
                                max={1800}
                                value={timerDuration ?? ""}
                                onChange={(e) => {
                                    const val = e.target.value;
                                    setTimerDuration(val ? parseInt(val, 10) : undefined);
                                }}
                                placeholder="No limit"
                                className="w-full rounded-md border border-white/10 bg-background/50 px-3 py-2 text-sm focus:border-orange-500/50 focus:outline-none focus:ring-1 focus:ring-orange-500/30 transition-colors"
                            />
                            {timerDuration && (
                                <Button variant="ghost" size="sm" onClick={() => setTimerDuration(undefined)} className="text-xs shrink-0">
                                    Clear
                                </Button>
                            )}
                        </div>
                        <p className="text-[10px] text-muted-foreground">Auto-advances when time expires (30–1800s)</p>
                    </div>
                    <div className="space-y-2">
                        <Label className="text-xs font-medium flex items-center gap-1.5">
                            <Repeat className="w-3.5 h-3.5 text-teal-400" />
                            Max Rounds
                        </Label>
                        <div className="flex items-center gap-2">
                            <input
                                type="number"
                                min={1}
                                max={10}
                                value={maxRounds ?? ""}
                                onChange={(e) => {
                                    const val = e.target.value;
                                    setMaxRounds(val ? parseInt(val, 10) : undefined);
                                }}
                                placeholder="Unlimited"
                                className="w-full rounded-md border border-white/10 bg-background/50 px-3 py-2 text-sm focus:border-teal-500/50 focus:outline-none focus:ring-1 focus:ring-teal-500/30 transition-colors"
                            />
                            {maxRounds && (
                                <Button variant="ghost" size="sm" onClick={() => setMaxRounds(undefined)} className="text-xs shrink-0">
                                    Clear
                                </Button>
                            )}
                        </div>
                        <p className="text-[10px] text-muted-foreground">Auto-advances after N exchanges (1–10)</p>
                    </div>
                </div>
            </div>

            {/* Prompt field with AI improve/generate */}
            <AIPromptField
                nodeId={nodeId}
                prompt={prompt}
                setPrompt={setPrompt}
                setName={setName}
                label="Instructions / Prompt"
                placeholder="You are a helpful customer service agent. Your goal is to..."
                description="Define how the agent should behave, respond, and what its goals are. This is the agent's &quot;brain&quot;."
                promptRef={promptRef}
                isInvalid={isPromptInvalid}
                validationMessage={validationMessage}
                minHeight="200px"
            />

            {/* Variable Extraction Section */}
            <div className="border rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                        <Switch id="enable-extraction" checked={extractionEnabled} onCheckedChange={setExtractionEnabled} />
                        <Label htmlFor="enable-extraction" className="cursor-pointer font-medium">
                            Enable Variable Extraction
                        </Label>
                    </div>
                </div>
                <p className="text-xs text-muted-foreground">
                    Extract specific information from the conversation into variables.
                </p>

                {extractionEnabled && (
                    <div className="space-y-3 pt-2">
                        <AIExtractionPrompt
                            nodeId={nodeId}
                            extractionPrompt={extractionPrompt}
                            setExtractionPrompt={setExtractionPrompt}
                            prompt={prompt}
                            extractionVariables={extractionVariables}
                        />

                        <AIExtractionVariables
                            nodeId={nodeId}
                            prompt={prompt}
                            extractionPrompt={extractionPrompt}
                            setExtractionPrompt={setExtractionPrompt}
                            extractionVariables={extractionVariables}
                            setExtractionVariables={setExtractionVariables}
                            onVariableNameChange={handleVariableNameChange}
                            onVariableTypeChange={handleVariableTypeChange}
                            onVariablePromptChange={handleVariablePromptChange}
                            onVariableRequiredChange={handleVariableRequiredChange}
                            onRemoveVariable={handleRemoveVariable}
                            onAddVariable={handleAddVariable}
                        />
                    </div>
                )}
            </div>
        </div>
    );
};

AgentNode.displayName = "AgentNode";

