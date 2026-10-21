import { NodeProps, NodeToolbar, Position } from "@xyflow/react";
import { Edit, Play } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { FlowNodeData } from "@/components/flow/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn, isOSSMode } from "@/lib/utils";

import { AIPromptField, AITextField } from "./common/AIHelpers";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface StartCallEditFormProps {
    nodeId: string;
    nodeData: FlowNodeData;
    prompt: string;
    setPrompt: (value: string) => void;
    promptRef?: React.RefObject<HTMLTextAreaElement | null>;
    nameRef?: React.RefObject<HTMLInputElement | null>;
    name: string;
    setName: (value: string) => void;
    allowInterrupt: boolean;
    setAllowInterrupt: (value: boolean) => void;
    addGlobalPrompt: boolean;
    setAddGlobalPrompt: (value: boolean) => void;
    detectVoicemail: boolean;
    setDetectVoicemail: (value: boolean) => void;
    delayedStart: boolean;
    setDelayedStart: (value: boolean) => void;
    delayedStartDuration: number;
    setDelayedStartDuration: (value: number) => void;
    invalidField?: string | null;
    validationMessage?: string | null;
}

interface StartCallNodeProps extends NodeProps {
    data: FlowNodeData;
}

export const StartCall = memo(({ data, selected, id }: StartCallNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleClearValidation, handleRestoreValidation } = useNodeHandlers({
        id,
        additionalData: { is_start: true }
    });
    const { saveWorkflow } = useWorkflow();
    const promptRef = useRef<HTMLTextAreaElement>(null);
    const nameRef = useRef<HTMLInputElement>(null);

    // Form state
    const [prompt, setPrompt] = useState(data.prompt ?? "");
    const [name, setName] = useState(data.name);
    const [allowInterrupt, setAllowInterrupt] = useState(data.allow_interrupt ?? true);
    const [addGlobalPrompt, setAddGlobalPrompt] = useState(data.add_global_prompt ?? true);
    const [detectVoicemail, setDetectVoicemail] = useState(data.detect_voicemail ?? true);
    const [delayedStart, setDelayedStart] = useState(data.delayed_start ?? false);
    const [delayedStartDuration, setDelayedStartDuration] = useState(data.delayed_start_duration ?? 2);

    const savedValidation = useRef<{ field: string; message: string } | null>(null);

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

    const handleNavigateToField = useCallback((fieldName: string) => {
        if (fieldName === "prompt" && promptRef.current) {
            promptRef.current.focus();
            promptRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else if (fieldName === "name" && nameRef.current) {
            nameRef.current.focus();
            nameRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, []);

    const handleSave = async () => {
        handleSaveNodeData({
            ...data,
            prompt,
            name,
            is_static: false,
            allow_interrupt: allowInterrupt,
            add_global_prompt: addGlobalPrompt,
            detect_voicemail: detectVoicemail,
            delayed_start: delayedStart,
            delayed_start_duration: delayedStart ? delayedStartDuration : undefined
        });
        setOpen(false);
        // Save the workflow after updating node data with a small delay to ensure state is updated
        setTimeout(async () => {
            await saveWorkflow();
        }, 100);
    };

    // Reset form state when dialog opens
    const handleOpenChange = (newOpen: boolean) => {
        if (newOpen) {
            setPrompt(data.prompt ?? "");
            setName(data.name);
            setAllowInterrupt(data.allow_interrupt ?? true);
            setAddGlobalPrompt(data.add_global_prompt ?? true);
            setDetectVoicemail(data.detect_voicemail ?? true);
            setDelayedStart(data.delayed_start ?? false);
            setDelayedStartDuration(data.delayed_start_duration ?? 3);
        }
        setOpen(newOpen);
    };

    // Update form state when data changes (e.g., from undo/redo)
    useEffect(() => {
        if (open) {
            setPrompt(data.prompt ?? "");
            setName(data.name);
            setAllowInterrupt(data.allow_interrupt ?? true);
            setAddGlobalPrompt(data.add_global_prompt ?? true);
            setDetectVoicemail(data.detect_voicemail ?? true);
            setDelayedStart(data.delayed_start ?? false);
            setDelayedStartDuration(data.delayed_start_duration ?? 3);
        }
    }, [data, open]);

    const hasChanges = useMemo(() => {
        if (name !== data.name) return true;
        if (prompt !== (data.prompt ?? "")) return true;
        if (allowInterrupt !== (data.allow_interrupt ?? true)) return true;
        if (addGlobalPrompt !== (data.add_global_prompt ?? true)) return true;
        if (detectVoicemail !== (data.detect_voicemail ?? true)) return true;
        if (delayedStart !== (data.delayed_start ?? false)) return true;
        if (delayedStart && delayedStartDuration !== (data.delayed_start_duration ?? 2)) return true;
        return false;
    }, [name, prompt, allowInterrupt, addGlobalPrompt, detectVoicemail, delayedStart, delayedStartDuration, data]);

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title="Start Call"
                icon={<Play />}
                nodeType="start"
                hasSourceHandle={true}
                onDoubleClick={() => setOpen(true)}
                onEdit={() => setOpen(true)}
                nodeId={id}
            >
                <p className="text-sm text-muted-foreground line-clamp-5 leading-relaxed">
                    {data.prompt || 'No prompt configured'}
                </p>
            </NodeContent>

            <NodeToolbar isVisible={selected} position={Position.Right}>
                <Button onClick={() => setOpen(true)} variant="outline" size="icon">
                    <Edit />
                </Button>
            </NodeToolbar>

            <NodeEditDialog
                open={open}
                onOpenChange={handleOpenChange}
                nodeData={data}
                title="Start Call"
                onSave={handleSave}
                hasChanges={hasChanges}
                onNavigateToField={handleNavigateToField}
            >
                {open && (
                    <StartCallEditForm
                        nodeId={id}
                        nodeData={data}
                        prompt={prompt}
                        setPrompt={(v: string) => handleFieldChange('prompt', v)}
                        promptRef={promptRef}
                        nameRef={nameRef}
                        name={name}
                        setName={(v: string) => handleFieldChange('name', v)}
                        allowInterrupt={allowInterrupt}
                        setAllowInterrupt={setAllowInterrupt}
                        addGlobalPrompt={addGlobalPrompt}
                        setAddGlobalPrompt={setAddGlobalPrompt}
                        detectVoicemail={detectVoicemail}
                        setDetectVoicemail={setDetectVoicemail}
                        delayedStart={delayedStart}
                        setDelayedStart={setDelayedStart}
                        delayedStartDuration={delayedStartDuration}
                        setDelayedStartDuration={setDelayedStartDuration}
                        invalidField={data.invalidField}
                        validationMessage={data.validationMessage}
                    />
                )}
            </NodeEditDialog>
        </>
    );
});

const StartCallEditForm = ({
    nodeId,
    prompt,
    setPrompt,
    promptRef,
    nameRef,
    name,
    setName,
    allowInterrupt,
    setAllowInterrupt,
    addGlobalPrompt,
    setAddGlobalPrompt,
    detectVoicemail,
    setDetectVoicemail,
    delayedStart,
    setDelayedStart,
    delayedStartDuration,
    setDelayedStartDuration,
    invalidField,
    validationMessage,
}: StartCallEditFormProps) => {
    const normalizedField = invalidField?.startsWith("data.") ? invalidField.slice(5) : invalidField;
    const isNameInvalid = normalizedField === "name";
    const isPromptInvalid = normalizedField === "prompt";

    return (
        <div className="grid gap-6">
            <AITextField
                nodeId={nodeId}
                value={name}
                onChange={setName}
                fieldName="name"
                label="Name"
                placeholder="e.g., Greeting Agent, Reservation Handler"
                description="Short name to identify this step in call logs."
                inputRef={nameRef}
                isInvalid={isNameInvalid}
                required
            />

            <AIPromptField
                nodeId={nodeId}
                prompt={prompt}
                setPrompt={setPrompt}
                setName={setName}
                label="Prompt"
                placeholder={"e.g., Hi there! Welcome to [Business Name]. How can I help you today?\n\nYou are a friendly assistant for [Business Name]. Help callers with reservations, inquiries, and general questions. Be concise — this is a real-time voice call."}
                description="The agent's opening greeting — spoken instantly when the call connects using your configured voice. Also serves as the system prompt that guides the agent's behaviour. The caller can interrupt this greeting by speaking."
                promptRef={promptRef}
                isInvalid={isPromptInvalid}
                validationMessage={validationMessage}
                minHeight="160px"
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex items-start space-x-4 p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group" onClick={() => setAllowInterrupt(!allowInterrupt)}>
                    <Switch id="allow-interrupt" checked={allowInterrupt} onCheckedChange={setAllowInterrupt} className="mt-1 data-[state=checked]:bg-primary" />
                    <div className="space-y-1">
                        <Label htmlFor="allow-interrupt" className="text-sm font-medium cursor-pointer group-hover:text-primary transition-colors">Allow Interruption</Label>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                            Whether you would like user to be able to interrupt the bot.
                        </p>
                    </div>
                </div>

                <div className="flex items-start space-x-4 p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group" onClick={() => setAddGlobalPrompt(!addGlobalPrompt)}>
                    <Switch
                        id="add-global-prompt"
                        checked={addGlobalPrompt}
                        onCheckedChange={setAddGlobalPrompt}
                        className="mt-1 data-[state=checked]:bg-primary"
                    />
                    <div className="space-y-1">
                        <Label htmlFor="add-global-prompt" className="text-sm font-medium cursor-pointer group-hover:text-primary transition-colors">
                            Add Global Prompt
                        </Label>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                            Include global prompt with this node
                        </p>
                    </div>
                </div>

                {!isOSSMode() && (
                    <div className="flex items-start space-x-4 p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group" onClick={() => setDetectVoicemail(!detectVoicemail)}>
                        <Switch
                            id="detect-voicemail"
                            checked={detectVoicemail}
                            onCheckedChange={setDetectVoicemail}
                            className="mt-1 data-[state=checked]:bg-primary"
                        />
                        <div className="space-y-1">
                            <Label htmlFor="detect-voicemail" className="text-sm font-medium cursor-pointer group-hover:text-primary transition-colors">
                                Detect Voicemail
                            </Label>
                            <p className="text-xs text-muted-foreground leading-relaxed">
                                Automatically detect and end call if voicemail is reached.
                            </p>
                        </div>
                    </div>
                )}
            </div>

            <div className={cn(
                "flex flex-col space-y-4 p-5 rounded-xl border border-white/5 bg-white/5 transition-all duration-300",
                delayedStart && "bg-primary/5 border-primary/20"
            )}>
                <div className="flex items-start space-x-4 cursor-pointer group" onClick={() => setDelayedStart(!delayedStart)}>
                    <Switch
                        id="delayed-start"
                        checked={delayedStart}
                        onCheckedChange={setDelayedStart}
                        className="mt-1 data-[state=checked]:bg-primary"
                    />
                    <div className="space-y-1">
                        <Label htmlFor="delayed-start" className="text-sm font-medium cursor-pointer group-hover:text-primary transition-colors">
                            Delayed Start
                        </Label>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                            Introduce a delay before the agent starts speaking.
                        </p>
                    </div>
                </div>

                {delayedStart && (
                    <div className="pl-14 pt-2 animate-in slide-in-from-top-2 fade-in duration-200">
                        <div className="flex items-center gap-4">
                            <Label htmlFor="delay-duration" className="text-sm font-medium whitespace-nowrap">
                                Delay (seconds)
                            </Label>
                            <div className="relative max-w-[120px]">
                                <Input
                                    id="delay-duration"
                                    type="number"
                                    step="0.1"
                                    min="0.1"
                                    max="10"
                                    value={delayedStartDuration}
                                    onChange={(e) => setDelayedStartDuration(parseFloat(e.target.value) || 3)}
                                    className="bg-black/20 border-white/10 pr-8"
                                />
                                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">s</span>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

StartCall.displayName = "StartCall";
