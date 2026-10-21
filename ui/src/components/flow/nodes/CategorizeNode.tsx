import { NodeProps, NodeToolbar, Position } from "@xyflow/react";
import { Edit, LayoutGrid, PlusCircle, Trash2Icon, X } from "lucide-react";
import { memo, useCallback, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { FlowNodeData } from "@/components/flow/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { AITextField } from "./common/AIHelpers";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

const CATEGORY_COLORS = [
    'bg-cyan-500/15 border-cyan-500/30 text-cyan-400',
    'bg-violet-500/15 border-violet-500/30 text-violet-400',
    'bg-amber-500/15 border-amber-500/30 text-amber-400',
    'bg-emerald-500/15 border-emerald-500/30 text-emerald-400',
    'bg-pink-500/15 border-pink-500/30 text-pink-400',
    'bg-blue-500/15 border-blue-500/30 text-blue-400',
    'bg-orange-500/15 border-orange-500/30 text-orange-400',
    'bg-teal-500/15 border-teal-500/30 text-teal-400',
];

interface CategorizeNodeProps extends NodeProps {
    data: FlowNodeData;
}

export const CategorizeNode = memo(({ data, selected, id }: CategorizeNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleDeleteNode } = useNodeHandlers({ id });
    const { saveWorkflow } = useWorkflow();

    const [name, setName] = useState(data.name);
    const [prompt, setPrompt] = useState(data.prompt ?? "");
    const [categories, setCategories] = useState<string[]>(data.categories ?? ['Sales', 'Support']);
    const [newCategory, setNewCategory] = useState("");
    const nameRef = useRef<HTMLInputElement>(null);

    const handleAddCategory = useCallback(() => {
        const trimmed = newCategory.trim();
        if (trimmed && !categories.includes(trimmed)) {
            setCategories([...categories, trimmed]);
            setNewCategory("");
        }
    }, [newCategory, categories]);

    const handleRemoveCategory = useCallback((index: number) => {
        setCategories(categories.filter((_, i) => i !== index));
    }, [categories]);

    const handleSave = async () => {
        handleSaveNodeData({
            ...data,
            name,
            prompt,
            categories,
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
            setCategories(data.categories ?? ['Sales', 'Support']);
            setNewCategory("");
        }
        setOpen(newOpen);
    };

    const hasChanges = useMemo(() => {
        return (
            name !== data.name ||
            prompt !== (data.prompt ?? "") ||
            JSON.stringify(categories) !== JSON.stringify(data.categories ?? ['Sales', 'Support'])
        );
    }, [name, prompt, categories, data]);

    const currentCategories = data.categories ?? ['Sales', 'Support'];

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title={data.name || 'Categorize'}
                icon={<LayoutGrid />}
                nodeType="categorize"
                hasSourceHandle={false}
                hasTargetHandle={true}
                onDoubleClick={() => setOpen(true)}
                onEdit={() => setOpen(true)}
                nodeId={id}
                sourceHandleIds={currentCategories.map((c) => `category-${c}`)}
            >
                <p className="text-sm text-muted-foreground line-clamp-2 leading-relaxed mb-2">
                    {data.prompt || 'Classify the conversation into categories'}
                </p>
                <div className="flex flex-wrap gap-1.5">
                    {currentCategories.map((cat, i) => (
                        <div
                            key={cat}
                            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-semibold uppercase tracking-wider ${CATEGORY_COLORS[i % CATEGORY_COLORS.length]}`}
                        >
                            <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
                            {cat}
                        </div>
                    ))}
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
                title="Edit Categorize"
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
                        placeholder="e.g., Route by Intent, Triage"
                        description="Short name for this classification step."
                        inputRef={nameRef}
                        required
                    />

                    <div className="space-y-2" data-field="prompt">
                        <Label className="text-sm font-medium">Classification Instruction</Label>
                        <p className="text-xs text-muted-foreground">
                            Describe how the LLM should classify the conversation. It will pick the best-matching category.
                        </p>
                        <Textarea
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            placeholder='e.g., "Based on what the user has described, classify their intent."'
                            className="min-h-[80px] resize-y bg-background/50 border-white/10 focus:border-cyan-500/50 transition-colors"
                        />
                    </div>

                    <div className="space-y-3" data-field="categories">
                        <Label className="text-sm font-medium">Categories</Label>
                        <p className="text-xs text-muted-foreground">
                            Each category becomes a separate output path. Connect each to a different next step.
                        </p>
                        <div className="flex flex-wrap gap-2">
                            {categories.map((cat, index) => (
                                <Badge
                                    key={index}
                                    variant="secondary"
                                    className={`text-sm py-1.5 px-3 gap-1.5 ${CATEGORY_COLORS[index % CATEGORY_COLORS.length]}`}
                                >
                                    {cat}
                                    <button
                                        onClick={() => handleRemoveCategory(index)}
                                        className="ml-1 hover:opacity-70 transition-opacity"
                                        disabled={categories.length <= 2}
                                    >
                                        <X className="w-3 h-3" />
                                    </button>
                                </Badge>
                            ))}
                        </div>
                        <div className="flex gap-2">
                            <Input
                                value={newCategory}
                                onChange={(e) => setNewCategory(e.target.value)}
                                placeholder="Add a category..."
                                className="bg-background/50 border-white/10 focus:border-cyan-500/50"
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        e.preventDefault();
                                        handleAddCategory();
                                    }
                                }}
                            />
                            <Button
                                onClick={handleAddCategory}
                                variant="outline"
                                size="sm"
                                disabled={!newCategory.trim() || categories.includes(newCategory.trim())}
                                className="shrink-0"
                            >
                                <PlusCircle className="w-4 h-4 mr-1" />
                                Add
                            </Button>
                        </div>
                    </div>

                    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 space-y-2">
                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Output Handles</p>
                        <div className="flex flex-wrap gap-2">
                            {categories.map((cat, i) => (
                                <div
                                    key={cat}
                                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-semibold uppercase tracking-wider ${CATEGORY_COLORS[i % CATEGORY_COLORS.length]}`}
                                >
                                    <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
                                    {cat}
                                </div>
                            ))}
                        </div>
                        <p className="text-xs text-muted-foreground">Connect each output to a different next step in your workflow.</p>
                    </div>
                </div>
            </NodeEditDialog>
        </>
    );
});

CategorizeNode.displayName = "CategorizeNode";
