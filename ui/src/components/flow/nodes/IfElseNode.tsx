import { NodeProps, NodeToolbar, Position } from "@xyflow/react";
import { Edit, GitBranch, Trash2Icon } from "lucide-react";
import { memo, useCallback, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { FlowNodeData } from "@/components/flow/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { AITextField } from "./common/AIHelpers";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface IfElseNodeProps extends NodeProps {
    data: FlowNodeData;
}

export const IfElseNode = memo(({ data, selected, id }: IfElseNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleDeleteNode } = useNodeHandlers({ id });
    const { saveWorkflow } = useWorkflow();

    const [name, setName] = useState(data.name);
    const [conditionText, setConditionText] = useState(data.condition_text ?? "");
    const nameRef = useRef<HTMLInputElement>(null);

    const handleSave = async () => {
        handleSaveNodeData({
            ...data,
            name,
            condition_text: conditionText,
        });
        setOpen(false);
        setTimeout(async () => {
            await saveWorkflow();
        }, 100);
    };

    const handleOpenChange = (newOpen: boolean) => {
        if (newOpen) {
            setName(data.name);
            setConditionText(data.condition_text ?? "");
        }
        setOpen(newOpen);
    };

    const hasChanges = useMemo(() => {
        return name !== data.name || conditionText !== (data.condition_text ?? "");
    }, [name, conditionText, data]);

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title={data.name || 'If / Else'}
                icon={<GitBranch />}
                nodeType="ifelse"
                hasSourceHandle={false}
                hasTargetHandle={true}
                onDoubleClick={() => setOpen(true)}
                onEdit={() => setOpen(true)}
                nodeId={id}
                sourceHandleIds={["true", "false"]}
            >
                <p className="text-sm text-muted-foreground line-clamp-2 leading-relaxed">
                    {data.condition_text || 'No condition configured'}
                </p>
                <div className="flex gap-2 mt-3">
                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider">True</span>
                    </div>
                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-500/15 border border-rose-500/30">
                        <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                        <span className="text-[10px] font-semibold text-rose-400 uppercase tracking-wider">False</span>
                    </div>
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
                title="Edit If / Else"
                onSave={handleSave}
                hasChanges={hasChanges}
                dialogClassName="max-w-2xl"
            >
                <div className="grid gap-6 max-h-[60vh] overflow-y-auto pr-2 custom-scrollbar">
                    <AITextField
                        nodeId={id}
                        value={name}
                        onChange={setName}
                        fieldName="name"
                        label="Name"
                        placeholder="e.g., Check Interest, Qualify Lead"
                        description="Short name to identify this branching point."
                        inputRef={nameRef}
                        required
                    />

                    <div className="space-y-2" data-field="condition_text">
                        <Label className="text-sm font-medium">Condition</Label>
                        <p className="text-xs text-muted-foreground">
                            Describe the condition to evaluate against the conversation so far. The LLM will determine true or false.
                        </p>
                        <Textarea
                            value={conditionText}
                            onChange={(e) => setConditionText(e.target.value)}
                            placeholder='e.g., "Is the user interested in upgrading their plan?"'
                            className="min-h-[100px] resize-y bg-background/50 border-white/10 focus:border-orange-500/50 transition-colors"
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 space-y-1">
                            <div className="flex items-center gap-2">
                                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]" />
                                <span className="text-sm font-semibold text-emerald-400">True Path</span>
                            </div>
                            <p className="text-xs text-muted-foreground">Connect to the node that handles the &quot;yes&quot; case.</p>
                        </div>
                        <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 space-y-1">
                            <div className="flex items-center gap-2">
                                <span className="w-2.5 h-2.5 rounded-full bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.5)]" />
                                <span className="text-sm font-semibold text-rose-400">False Path</span>
                            </div>
                            <p className="text-xs text-muted-foreground">Connect to the node that handles the &quot;no&quot; case.</p>
                        </div>
                    </div>
                </div>
            </NodeEditDialog>
        </>
    );
});

IfElseNode.displayName = "IfElseNode";
