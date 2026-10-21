import { NodeProps, NodeToolbar, Position } from "@xyflow/react";
import { Edit, OctagonX } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { ExtractionVariable, FlowNodeData } from "@/components/flow/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { AIExtractionPrompt, AIExtractionVariables, AIPromptField, AITextField } from "./common/AIHelpers";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface EndCallEditFormProps {
    nodeId: string;
    nodeData: FlowNodeData;
    prompt: string;
    setPrompt: (value: string) => void;
    promptRef?: React.RefObject<HTMLTextAreaElement | null>;
    nameRef?: React.RefObject<HTMLInputElement | null>;
    name: string;
    setName: (value: string) => void;
    extractionEnabled: boolean;
    setExtractionEnabled: (value: boolean) => void;
    extractionPrompt: string;
    setExtractionPrompt: (value: string) => void;
    variables: ExtractionVariable[];
    setVariables: (vars: ExtractionVariable[]) => void;
    addGlobalPrompt: boolean;
    setAddGlobalPrompt: (value: boolean) => void;
    invalidField?: string | null;
    validationMessage?: string | null;
}

interface EndCallNodeProps extends NodeProps {
    data: FlowNodeData;
}

export const EndCall = memo(({ data, selected, id }: EndCallNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleClearValidation, handleRestoreValidation } = useNodeHandlers({
        id,
        additionalData: { is_end: true }
    });
    const { saveWorkflow } = useWorkflow();
    const promptRef = useRef<HTMLTextAreaElement>(null);
    const nameRef = useRef<HTMLInputElement>(null);

    // Form state
    const [prompt, setPrompt] = useState(data.prompt ?? "");
    const [name, setName] = useState(data.name);

    // Variable Extraction state
    const [extractionEnabled, setExtractionEnabled] = useState(data.extraction_enabled ?? false);
    const [extractionPrompt, setExtractionPrompt] = useState(data.extraction_prompt ?? "");
    const [variables, setVariables] = useState<ExtractionVariable[]>(data.extraction_variables ?? []);
    const [addGlobalPrompt, setAddGlobalPrompt] = useState(data.add_global_prompt ?? true);

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
            is_static: false, // Static nodes are not supported
            allow_interrupt: false,  // Always set to false for end nodes
            extraction_enabled: extractionEnabled,
            extraction_prompt: extractionPrompt,
            extraction_variables: variables,
            add_global_prompt: addGlobalPrompt,
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
            setExtractionEnabled(data.extraction_enabled ?? false);
            setExtractionPrompt(data.extraction_prompt ?? "");
            setVariables(data.extraction_variables ?? []);
            setAddGlobalPrompt(data.add_global_prompt ?? true);
        }
        setOpen(newOpen);
    };

    // Update form state when data changes (e.g., from undo/redo)
    useEffect(() => {
        if (open) {
            setPrompt(data.prompt ?? "");
            setName(data.name);
            setExtractionEnabled(data.extraction_enabled ?? false);
            setExtractionPrompt(data.extraction_prompt ?? "");
            setVariables(data.extraction_variables ?? []);
            setAddGlobalPrompt(data.add_global_prompt ?? true);
        }
    }, [data, open]);

    const hasChanges = useMemo(() => {
        if (name !== data.name) return true;
        if (prompt !== (data.prompt ?? "")) return true;
        if (extractionEnabled !== (data.extraction_enabled ?? false)) return true;
        if (extractionPrompt !== (data.extraction_prompt ?? "")) return true;
        if (addGlobalPrompt !== (data.add_global_prompt ?? true)) return true;
        if (JSON.stringify(variables) !== JSON.stringify(data.extraction_variables ?? [])) return true;
        return false;
    }, [name, prompt, extractionEnabled, extractionPrompt, addGlobalPrompt, variables, data]);

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title="End Call"
                icon={<OctagonX />}
                nodeType="end"
                hasSourceHandle={true}
                hasTargetHandle={true}
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
                title="End Call"
                onSave={handleSave}
                hasChanges={hasChanges}
                onNavigateToField={handleNavigateToField}
            >
                {open && (
                    <EndCallEditForm
                        nodeId={id}
                        nodeData={data}
                        prompt={prompt}
                        setPrompt={(v: string) => handleFieldChange('prompt', v)}
                        promptRef={promptRef}
                        nameRef={nameRef}
                        name={name}
                        setName={(v: string) => handleFieldChange('name', v)}
                        extractionEnabled={extractionEnabled}
                        setExtractionEnabled={setExtractionEnabled}
                        extractionPrompt={extractionPrompt}
                        setExtractionPrompt={setExtractionPrompt}
                        variables={variables}
                        setVariables={setVariables}
                        addGlobalPrompt={addGlobalPrompt}
                        setAddGlobalPrompt={setAddGlobalPrompt}
                        invalidField={data.invalidField}
                        validationMessage={data.validationMessage}
                    />
                )}
            </NodeEditDialog>
        </>
    );
});

const EndCallEditForm = ({
    nodeId,
    prompt,
    setPrompt,
    promptRef,
    nameRef,
    name,
    setName,
    extractionEnabled,
    setExtractionEnabled,
    extractionPrompt,
    setExtractionPrompt,
    variables,
    setVariables,
    addGlobalPrompt,
    setAddGlobalPrompt,
    invalidField,
    validationMessage,
}: EndCallEditFormProps) => {
    const handleVariableNameChange = (idx: number, value: string) => {
        const newVars = [...variables];
        newVars[idx] = { ...newVars[idx], name: value };
        setVariables(newVars);
    };

    const handleVariableTypeChange = (idx: number, value: 'string' | 'number' | 'boolean') => {
        const newVars = [...variables];
        newVars[idx] = { ...newVars[idx], type: value };
        setVariables(newVars);
    };

    const handleVariableRequiredChange = (idx: number, value: boolean) => {
        const newVars = [...variables];
        newVars[idx] = { ...newVars[idx], required: value };
        setVariables(newVars);
    };

    const handleVariablePromptChange = (idx: number, value: string) => {
        const newVars = [...variables];
        newVars[idx] = { ...newVars[idx], prompt: value };
        setVariables(newVars);
    };

    const handleRemoveVariable = (idx: number) => {
        const newVars = variables.filter((_, i) => i !== idx);
        setVariables(newVars);
    };

    const handleAddVariable = () => {
        setVariables([...variables, { name: '', type: 'string', prompt: '' }]);
    };

    const normalizedField = invalidField?.startsWith("data.") ? invalidField.slice(5) : invalidField;
    const isNameInvalid = normalizedField === "name";
    const isPromptInvalid = normalizedField === "prompt";

    return (
        <div className="grid gap-3">
            <AITextField
                nodeId={nodeId}
                value={name}
                onChange={setName}
                fieldName="name"
                label="Name"
                placeholder="e.g., End Call, Goodbye"
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
                placeholder="Enter the end call prompt..."
                description="Enter the prompt for the end call agent."
                promptRef={promptRef}
                isInvalid={isPromptInvalid}
                validationMessage={validationMessage}
                minHeight="100px"
            />

            <div className="flex items-center space-x-2">
                <Switch id="add-global-prompt" checked={addGlobalPrompt} onCheckedChange={setAddGlobalPrompt} />
                <Label htmlFor="add-global-prompt">Add Global Prompt</Label>
                <Label className="text-xs text-muted-foreground">
                    Whether you want to add global prompt with this node&apos;s prompt.
                </Label>
            </div>

            {/* Variable Extraction Section */}
            <div className="flex items-center space-x-2 pt-2">
                <Switch id="enable-extraction" checked={extractionEnabled} onCheckedChange={setExtractionEnabled} />
                <Label htmlFor="enable-extraction">Enable Variable Extraction</Label>
                <Label className="text-xs text-muted-foreground ml-2">
                    Extract variables from the conversation at the end of the call.
                </Label>
            </div>

            {extractionEnabled && (
                <div className="border rounded-lg p-4 space-y-3 bg-muted/20">
                    <AIExtractionPrompt
                        nodeId={nodeId}
                        extractionPrompt={extractionPrompt}
                        setExtractionPrompt={setExtractionPrompt}
                        prompt={prompt}
                        extractionVariables={variables}
                    />

                    <AIExtractionVariables
                        nodeId={nodeId}
                        prompt={prompt}
                        extractionPrompt={extractionPrompt}
                        setExtractionPrompt={setExtractionPrompt}
                        extractionVariables={variables}
                        setExtractionVariables={setVariables}
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
    );
};

EndCall.displayName = "EndCall";
