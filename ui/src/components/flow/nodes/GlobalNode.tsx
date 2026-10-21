import { NodeProps, NodeToolbar, Position } from "@xyflow/react";
import { Edit, Headset, Trash2Icon } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { FlowNodeData } from "@/components/flow/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { AIPromptField, AITextField } from "./common/AIHelpers";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface GlobalNodeEditFormProps {
    nodeId: string;
    nodeData: FlowNodeData;
    prompt: string;
    setPrompt: (value: string) => void;
    promptRef?: React.RefObject<HTMLTextAreaElement | null>;
    nameRef?: React.RefObject<HTMLInputElement | null>;
    name: string;
    setName: (value: string) => void;
    invalidField?: string | null;
    validationMessage?: string | null;
}

interface GlobalNodeProps extends NodeProps {
    data: FlowNodeData;
}

export const GlobalNode = memo(({ data, selected, id }: GlobalNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleDeleteNode, handleClearValidation, handleRestoreValidation } = useNodeHandlers({ id });
    const { saveWorkflow } = useWorkflow();
    const promptRef = useRef<HTMLTextAreaElement>(null);
    const nameRef = useRef<HTMLInputElement>(null);

    // Form state
    const [prompt, setPrompt] = useState(data.prompt);
    const [name, setName] = useState(data.name);

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
            is_static: false,
            name
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
            setPrompt(data.prompt);
            setName(data.name);
        }
        setOpen(newOpen);
    };

    // Update form state when data changes (e.g., from undo/redo)
    useEffect(() => {
        if (open) {
            setPrompt(data.prompt);
            setName(data.name);
        }
    }, [data, open]);

    const hasChanges = useMemo(() => {
        if (name !== data.name) return true;
        if (prompt !== data.prompt) return true;
        return false;
    }, [name, prompt, data]);

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title={data.name || 'Global'}
                icon={<Headset />}
                nodeType="global"
                onDoubleClick={() => setOpen(true)}
                onEdit={() => setOpen(true)}
                nodeId={id}
            >
                <p className="text-sm text-muted-foreground line-clamp-5 leading-relaxed">
                    {data.prompt || 'No prompt configured'}
                </p>
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
                title="Edit Global Node"
                onSave={handleSave}
                hasChanges={hasChanges}
                onNavigateToField={handleNavigateToField}
            >
                {open && (
                    <GlobalNodeEditForm
                        nodeId={id}
                        nodeData={data}
                        prompt={prompt}
                        setPrompt={(v: string) => handleFieldChange('prompt', v)}
                        promptRef={promptRef}
                        nameRef={nameRef}
                        name={name}
                        setName={(v: string) => handleFieldChange('name', v)}
                        invalidField={data.invalidField}
                        validationMessage={data.validationMessage}
                    />
                )}
            </NodeEditDialog>
        </>
    );
});

const GlobalNodeEditForm = ({
    nodeId,
    prompt,
    setPrompt,
    promptRef,
    nameRef,
    name,
    setName,
    invalidField,
    validationMessage,
}: GlobalNodeEditFormProps) => {
    const normalizedField = invalidField?.startsWith("data.") ? invalidField.slice(5) : invalidField;
    const isNameInvalid = normalizedField === "name";

    return (
        <div className="grid gap-4">
            <AITextField
                nodeId={nodeId}
                value={name}
                onChange={setName}
                fieldName="name"
                label="Name"
                placeholder="e.g., Global Settings"
                description="The name of the global node."
                inputRef={nameRef}
                isInvalid={isNameInvalid}
                required
            />

            <AIPromptField
                nodeId={nodeId}
                prompt={prompt}
                setPrompt={setPrompt}
                setName={setName}
                label="Global Prompt"
                placeholder="Enter the global prompt that applies to all agents..."
                description="This is the global prompt. It will be added to the system prompt of all agents."
                promptRef={promptRef}
                isInvalid={normalizedField === "prompt"}
                validationMessage={validationMessage}
                minHeight="120px"
            />
        </div>
    );
};

GlobalNode.displayName = "GlobalNode";

