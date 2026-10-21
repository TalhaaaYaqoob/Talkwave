import { NodeProps, NodeToolbar, Position } from "@xyflow/react";
import { Edit, PhoneForwarded, Trash2Icon } from "lucide-react";
import { memo, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { FlowNodeData } from "@/components/flow/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import { AITextField } from "./common/AIHelpers";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface TransferNodeProps extends NodeProps {
    data: FlowNodeData;
}

export const TransferNode = memo(({ data, selected, id }: TransferNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleDeleteNode } = useNodeHandlers({ id });
    const { saveWorkflow } = useWorkflow();

    const [name, setName] = useState(data.name);
    const [prompt, setPrompt] = useState(data.prompt ?? "");
    const [transferTarget, setTransferTarget] = useState(data.transfer_target ?? "");
    const [isLiteral, setIsLiteral] = useState(data.is_literal ?? true);
    const nameRef = useRef<HTMLInputElement>(null);

    const handleSave = async () => {
        handleSaveNodeData({
            ...data,
            name,
            prompt,
            transfer_target: transferTarget,
            is_literal: isLiteral,
        });
        setOpen(false);
        setTimeout(async () => {
            await saveWorkflow();
        }, 100);
    };

    const handleOpenChange = (newOpen: boolean) => {
        if (newOpen) {
            setName(data.name);
            setPrompt(data.prompt ?? "");
            setTransferTarget(data.transfer_target ?? "");
            setIsLiteral(data.is_literal ?? true);
        }
        setOpen(newOpen);
    };

    const hasChanges = useMemo(() => {
        return (
            name !== data.name ||
            prompt !== (data.prompt ?? "") ||
            transferTarget !== (data.transfer_target ?? "") ||
            isLiteral !== (data.is_literal ?? true)
        );
    }, [name, prompt, transferTarget, isLiteral, data]);

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title={data.name || 'Transfer'}
                icon={<PhoneForwarded />}
                nodeType="transfer"
                hasSourceHandle={false}
                hasTargetHandle={true}
                onDoubleClick={() => setOpen(true)}
                onEdit={() => setOpen(true)}
                nodeId={id}
            >
                <p className="text-sm text-muted-foreground line-clamp-2 leading-relaxed">
                    {data.prompt || 'No transfer message configured'}
                </p>
                {data.transfer_target && (
                    <Badge variant="secondary" className="mt-2 text-xs bg-pink-500/15 text-pink-400 border-pink-500/30">
                        <PhoneForwarded className="w-3 h-3 mr-1" />
                        {data.transfer_target}
                    </Badge>
                )}
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
                title="Edit Transfer"
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
                        placeholder="e.g., Transfer to Sales, Escalate to Human"
                        description="Short name for this transfer step."
                        inputRef={nameRef}
                        required
                    />

                    <div className="space-y-2" data-field="transfer_target">
                        <Label className="text-sm font-medium">Transfer Target</Label>
                        <p className="text-xs text-muted-foreground">
                            Phone number or SIP address to transfer the call to.
                        </p>
                        <Input
                            value={transferTarget}
                            onChange={(e) => setTransferTarget(e.target.value)}
                            placeholder="e.g., +1234567890 or sip:agent@company.com"
                            className="bg-background/50 border-white/10 focus:border-pink-500/50 transition-colors"
                        />
                    </div>

                    <div className="space-y-2" data-field="prompt">
                        <Label className="text-sm font-medium">Transfer Message</Label>
                        <p className="text-xs text-muted-foreground">
                            What the agent says before transferring the call.
                        </p>
                        <Textarea
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            placeholder="e.g., Please hold while I transfer you to a specialist."
                            className="min-h-[80px] resize-y bg-background/50 border-white/10 focus:border-pink-500/50 transition-colors"
                        />
                    </div>

                    <div
                        className="flex items-start space-x-4 p-4 rounded-xl border border-white/5 bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group"
                        onClick={() => setIsLiteral(!isLiteral)}
                    >
                        <Switch
                            id="is-literal"
                            checked={isLiteral}
                            onCheckedChange={setIsLiteral}
                            className="mt-1 data-[state=checked]:bg-pink-500"
                        />
                        <div className="space-y-1">
                            <Label htmlFor="is-literal" className="text-sm font-medium cursor-pointer group-hover:text-pink-400 transition-colors">
                                Speak Verbatim
                            </Label>
                            <p className="text-xs text-muted-foreground leading-relaxed">
                                If enabled, the agent speaks the transfer message word-for-word instead of using it as an instruction.
                            </p>
                        </div>
                    </div>
                </div>
            </NodeEditDialog>
        </>
    );
});

TransferNode.displayName = "TransferNode";
