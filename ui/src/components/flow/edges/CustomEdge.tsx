import { BaseEdge, type Edge, EdgeLabelRenderer, type EdgeProps, getSmoothStepPath, useReactFlow } from '@xyflow/react';
import { AlertCircle, Pencil, Sparkles } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useCallback, useEffect, useState } from 'react';

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { useWorkflowStore } from "@/app/workflow/[workflowId]/stores/workflowStore";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from '@/components/ui/textarea';
import { useAuth } from "@/lib/auth";
import { getBackendUrl } from '@/lib/apiClient';
import { cn } from "@/lib/utils";

import { FlowEdge, FlowEdgeData, FlowNode } from '../types';
type CustomEdge = Edge<{ value: number }, 'custom'>;


interface EdgeDetailsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    data?: FlowEdgeData;
    onSave: (value: FlowEdgeData) => void;
    sourceNodeId?: string;
    targetNodeId?: string;
    workflowId?: number;
}

const EdgeDetailsDialog = ({ open, onOpenChange, data, onSave, sourceNodeId, targetNodeId, workflowId }: EdgeDetailsDialogProps) => {
    const [condition, setCondition] = useState(data?.condition ?? '');
    const [label, setLabel] = useState(data?.label ?? '');
    const [aiLoading, setAiLoading] = useState(false);
    const { getAccessToken } = useAuth();
    const { getNodes, getEdges } = useReactFlow<FlowNode, FlowEdge>();

    // Update form state when data changes (e.g., from undo/redo)
    useEffect(() => {
        if (open) {
            setCondition(data?.condition ?? '');
            setLabel(data?.label ?? '');
        }
    }, [data, open]);

    const handleSave = () => {
        onSave({ condition: condition, label: label });
        onOpenChange(false);
    };

    const handleAISuggest = async () => {
        if (!workflowId || !sourceNodeId || !targetNodeId) return;
        setAiLoading(true);
        try {
            const accessToken = await getAccessToken();
            const baseUrl = getBackendUrl();
            const currentNodes = getNodes().map(n => ({ id: n.id, type: n.type, data: n.data, position: n.position }));
            const currentEdges = getEdges().map(e => ({ id: e.id, source: e.source, target: e.target, data: e.data }));
            const res = await fetch(`${baseUrl}/api/v1/workflow/${workflowId}/ai-suggest`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: 'edge_condition',
                    source_node_id: sourceNodeId,
                    target_node_id: targetNodeId,
                    current_nodes: currentNodes,
                    current_edges: currentEdges,
                }),
            });
            if (res.ok) {
                const data = await res.json();
                const suggestion = data.suggestion;
                if (suggestion.condition) setCondition(suggestion.condition);
                if (suggestion.label) setLabel(suggestion.label);
            }
        } catch (err) {
            console.error('AI suggest failed:', err);
        } finally {
            setAiLoading(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <div className="flex items-center justify-between">
                        <DialogTitle>Edit Condition</DialogTitle>
                        {workflowId && sourceNodeId && targetNodeId && (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={handleAISuggest}
                                disabled={aiLoading}
                                className="gap-1.5 text-xs border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 hover:text-emerald-300"
                            >
                                {aiLoading ? (
                                    <Spinner size="sm" />
                                ) : (
                                    <Sparkles className="h-3 w-3" />
                                )}
                                {aiLoading ? 'Thinking...' : 'AI Suggest'}
                            </Button>
                        )}
                    </div>
                    {data?.invalid && data.validationMessage && (
                        <div className="mt-2 flex items-center gap-2 rounded-md bg-red-50 p-2 text-sm text-red-500 border border-red-200">
                            <AlertCircle className="h-4 w-4" />
                            <span>{data.validationMessage}</span>
                        </div>
                    )}
                </DialogHeader>
                <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                        <Label>Condition Label</Label>
                        <Label className="text-xs text-muted-foreground">
                            Enter a short label which helps identify this pathway in logs
                        </Label>
                        <Input
                            type="text"
                            value={label}
                            maxLength={64}
                            onChange={(e) => setLabel(e.target.value)}
                        />
                        <div className="text-xs text-muted-foreground">
                            {label.length}/64 characters
                        </div>
                    </div>
                    <div className="grid gap-2">
                        <Label>Condition</Label>
                        <Label className="text-xs text-muted-foreground">
                            Describe a condition that will be evaluated to determine if this pathway should be taken
                        </Label>
                        <Textarea
                            value={condition}
                            onChange={(e) => setCondition(e.target.value)}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                        <Button onClick={handleSave}>Save</Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

interface CustomEdgeProps extends EdgeProps {
    data: FlowEdgeData;
}

export default function CustomEdge(props: CustomEdgeProps) {
    const { id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, style, selected } = props;

    const { getEdges, setNodes } = useReactFlow<FlowNode, FlowEdge>();
    const { saveWorkflow, workflowId } = useWorkflow();
    const updateEdge = useWorkflowStore((state) => state.updateEdge);
    const [open, setOpen] = useState(false);
    const [isHovered, setIsHovered] = useState(false);

    const parallel = getEdges().filter(
        (e) =>
            (e.source === source && e.target === target) ||
            (e.source === target && e.target === source)
    );

    // 2) if there are two, sort by id and pick an index
    let offsetX = 0;
    let offsetY = 0;
    if (parallel.length > 1) {
        const sorted = parallel.slice().sort((a, b) => a.id.localeCompare(b.id));
        const idx = sorted.findIndex((e) => e.id === id);

        // first edge (idx 0) moves right & down;
        // second edge (idx 1) moves left & up
        if (idx === 0) {
            offsetX = 100;
            offsetY = 0;
        } else {
            offsetX = 0;
            offsetY = -50;
        }
    }

    // Check if this is a self-loop (source and target are the same node)
    const isSelfLoop = source === target;

    // 3) draw the edge path + get label coords
    // Use custom arc path for self-loops, smoothstep for regular edges
    let edgePath: string;
    let labelX: number;
    let labelY: number;

    if (isSelfLoop) {
        // Create a loop arc that goes out and around the node
        const loopRadius = 50;
        const loopOffsetX = 80;
        // Arc path: start from source, curve out and back to target
        edgePath = `M ${sourceX} ${sourceY}
                    C ${sourceX + loopOffsetX} ${sourceY - loopRadius},
                      ${targetX + loopOffsetX} ${targetY + loopRadius},
                      ${targetX} ${targetY}`;
        labelX = sourceX + loopOffsetX;
        labelY = sourceY;
    } else {
        // Use smoothstep path for orthogonal/elbow edges
        // borderRadius: 16 gives rounder, smoother corners
        // offset: 25 provides better spacing
        const [path, lx, ly] = getSmoothStepPath({
            sourceX,
            sourceY,
            sourcePosition,
            targetX,
            targetY,
            targetPosition,
            borderRadius: 16,
            offset: 25,
        });
        edgePath = path;
        labelX = lx;
        labelY = ly;
    }

    // Update connected nodes when edge is selected or hovered
    useEffect(() => {
        setNodes((nodes) => {
            return nodes.map((node) => {
                if (node.id === source || node.id === target) {
                    // Update both properties based on edge state
                    const shouldSelectThroughEdge = selected || false;
                    const shouldHoverThroughEdge = isHovered || false;

                    // Only update if state actually changed
                    if (
                        node.data.selected_through_edge !== shouldSelectThroughEdge ||
                        node.data.hovered_through_edge !== shouldHoverThroughEdge
                    ) {
                        return {
                            ...node,
                            data: {
                                ...node.data,
                                selected_through_edge: shouldSelectThroughEdge,
                                hovered_through_edge: shouldHoverThroughEdge
                            }
                        };
                    }
                }
                return node;
            });
        });
    }, [selected, isHovered, source, target, setNodes]);

    const handleSaveEdgeData = useCallback(async (updatedData: FlowEdgeData) => {
        // Use the workflow store's updateEdge method to properly track history
        updateEdge(id, { data: updatedData });

        // Save the workflow after updating edge data with a small delay to ensure state is updated
        setTimeout(async () => {
            await saveWorkflow();
        }, 100);
    }, [id, updateEdge, saveWorkflow]);

    return (
        <>
            <g
                onMouseEnter={() => setIsHovered(true)}
                onMouseLeave={() => setIsHovered(false)}
                onDoubleClick={() => setOpen(true)}
            >
                <BaseEdge
                    id={id}
                    path={edgePath}
                    style={{
                        ...style,
                        stroke: selected
                            ? 'oklch(var(--primary))'  // Theme primary color when selected
                            : isHovered
                                ? 'oklch(var(--primary)/0.7)'  // Faded primary when hovered
                                : data?.invalid ? 'oklch(var(--destructive))' : 'rgba(255,255,255,0.2)',
                        strokeWidth: selected ? 3 : isHovered ? 2.5 : 2,
                        filter: selected
                            ? 'drop-shadow(0 0 8px oklch(var(--primary)/0.6))'
                            : isHovered
                                ? 'drop-shadow(0 0 6px oklch(var(--primary)/0.4))'
                                : 'none',
                        transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                    }}
                    interactionWidth={20}
                />
            </g>
            {/* Always show label, expand on select/hover */}
            <EdgeLabelRenderer>
                <div
                    style={{
                        position: 'absolute',
                        pointerEvents: 'all',
                        transformOrigin: 'center',
                        transform: `translate(-50%, -50%) translate(${labelX + offsetX}px, ${labelY + offsetY}px)`,
                        zIndex: 1000,
                    }}
                    className="nodrag nopan"
                    onMouseEnter={() => setIsHovered(true)}
                    onMouseLeave={() => setIsHovered(false)}
                    onDoubleClick={() => setOpen(true)}
                >
                    {/* Show full EdgeLabel when selected or hovered, otherwise show simple label */}
                    {(selected || isHovered) ? (
                        <div className={cn(
                            "flex flex-col gap-2 bg-card/80 backdrop-blur-xl rounded-xl border border-white/10 shadow-2xl min-w-[220px]",
                            "animate-in fade-in zoom-in duration-200 ring-1 ring-white/5",
                            data?.invalid ? "border-destructive/50 shadow-[0_0_20px_rgba(239,68,68,0.2)]" : "border-white/10"
                        )}>
                            {/* Header with label */}
                            <div className={cn(
                                "flex items-center justify-between px-3 py-2 border-b border-white/5",
                                data?.invalid ? "bg-destructive/10" : "bg-white/5"
                            )}>
                                <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                                    Condition
                                </span>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6 p-0 hover:bg-white/10 text-muted-foreground hover:text-foreground rounded-full transition-colors"
                                    onClick={() => setOpen(true)}
                                >
                                    <Pencil className="h-3 w-3" />
                                </Button>
                            </div>
                            {/* Content */}
                            <div className="px-3 pb-3 pt-1">
                                <div className="text-sm font-medium text-foreground/90 break-words leading-relaxed">
                                    {data?.label || data?.condition || 'Always (click to add condition)'}
                                </div>
                            </div>
                        </div>
                    ) : (
                        /* Simple label shown by default */
                        <div className={cn(
                            "px-3 py-1.5 rounded-full text-[11px] font-semibold shadow-lg backdrop-blur-md border border-white/5",
                            "transition-all duration-300 hover:scale-105 cursor-pointer",
                            data?.invalid
                                ? "bg-destructive/20 text-destructive border-destructive/30"
                                : (data?.label || data?.condition)
                                    ? "bg-accent/20 text-accent-foreground border-accent/20"
                                    : "bg-card/40 text-muted-foreground border-white/5 hover:bg-card/60 hover:text-foreground"
                        )}>
                            {data?.label || data?.condition || 'Always'}
                        </div>
                    )}
                </div>
            </EdgeLabelRenderer>
            <EdgeDetailsDialog
                open={open}
                onOpenChange={setOpen}
                data={data}
                onSave={handleSaveEdgeData}
                sourceNodeId={source}
                targetNodeId={target}
                workflowId={workflowId}
            />
        </>
    );
}
