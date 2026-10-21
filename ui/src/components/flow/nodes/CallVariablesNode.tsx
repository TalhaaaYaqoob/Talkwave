'use client';

import { NodeProps, NodeToolbar, Position, useNodes } from "@xyflow/react";
import { Braces, Edit, PlusIcon, Trash2Icon, X } from "lucide-react";
import { memo, useMemo, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { useWorkflowStore } from "@/app/workflow/[workflowId]/stores/workflowStore";
import { ExtractionVariable, FlowNodeData } from "@/components/flow/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

interface CallVariablesNodeProps extends NodeProps {
    data: FlowNodeData;
}

type HubVar = { name: string; required: boolean; custom?: boolean };

const sanitizeVarName = (raw: string) =>
    raw.trim().replace(/[^a-zA-Z0-9_]/g, '_').replace(/_{2,}/g, '_');

/**
 * Post-call data hub. It sits after the End node and surfaces EVERY variable
 * the call collected (extraction variables on any node, exit-condition
 * required variables, and pre-call template context). Users attach Action
 * nodes to it to run post-call integrations referencing {{variable_name}}.
 *
 * Auto-collected variables are aggregated live from the reactive node list.
 * Users can also open the edit dialog to rename the hub and declare custom
 * variables (e.g. template-context values passed in at dial time) which are
 * persisted on the node itself.
 */
export const CallVariablesNode = memo(({ data, selected, id }: CallVariablesNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleDeleteNode } = useNodeHandlers({ id });
    const { saveWorkflow } = useWorkflow();
    const allNodes = useNodes();
    const templateContextVariables = useWorkflowStore((s) => s.templateContextVariables);

    const [name, setName] = useState(data.name);
    const [customVars, setCustomVars] = useState<ExtractionVariable[]>(
        data.extraction_variables ?? []
    );
    const [newVarName, setNewVarName] = useState('');

    // Variables aggregated live from the rest of the workflow (read-only here;
    // they are edited on their source nodes).
    const aggregatedVariables = useMemo(() => {
        const map = new Map<string, HubVar>();
        const add = (name?: string, required?: boolean) => {
            const clean = (name || '').trim();
            if (!clean) return;
            const existing = map.get(clean);
            // Once required, stays required (most restrictive wins for display).
            map.set(clean, { name: clean, required: (existing?.required ?? false) || required !== false });
        };

        for (const node of allNodes) {
            // The hub's own persisted variables are handled separately as
            // custom variables (editable in the dialog).
            if (node.id === id) continue;
            const nodeData = (node.data || {}) as Record<string, unknown>;

            const extractionVars = nodeData?.extraction_variables as
                | Array<{ name?: string; required?: boolean }>
                | undefined;
            if (Array.isArray(extractionVars)) {
                for (const v of extractionVars) add(v?.name, v?.required);
            }

            const exitConditions = nodeData?.exit_conditions as
                | Array<{ required_variables?: Array<{ name?: string }> }>
                | undefined;
            if (Array.isArray(exitConditions)) {
                for (const ec of exitConditions) {
                    if (Array.isArray(ec?.required_variables)) {
                        for (const rv of ec.required_variables) add(rv?.name, true);
                    }
                }
            }
        }

        if (templateContextVariables) {
            for (const key of Object.keys(templateContextVariables)) add(key, false);
        }

        return Array.from(map.values());
    }, [allNodes, templateContextVariables, id]);

    // Combined list for the node card: aggregated + persisted custom vars,
    // deduped by name (aggregated wins so display flags stay accurate).
    const variables = useMemo(() => {
        const map = new Map<string, HubVar>();
        for (const v of data.extraction_variables ?? []) {
            const clean = (v.name || '').trim();
            if (clean) map.set(clean, { name: clean, required: v.required !== false, custom: true });
        }
        for (const v of aggregatedVariables) map.set(v.name, v);
        return Array.from(map.values());
    }, [aggregatedVariables, data.extraction_variables]);

    const handleOpenChange = (newOpen: boolean) => {
        if (newOpen) {
            setName(data.name);
            setCustomVars(data.extraction_variables ?? []);
            setNewVarName('');
        }
        setOpen(newOpen);
    };

    const handleAddCustomVar = () => {
        const clean = sanitizeVarName(newVarName);
        if (!clean) return;
        if (customVars.some((v) => v.name === clean)) {
            setNewVarName('');
            return;
        }
        setCustomVars((vars) => [...vars, { name: clean, type: 'string', required: false }]);
        setNewVarName('');
    };

    const handleRemoveCustomVar = (varName: string) => {
        setCustomVars((vars) => vars.filter((v) => v.name !== varName));
    };

    const handleToggleRequired = (varName: string, required: boolean) => {
        setCustomVars((vars) =>
            vars.map((v) => (v.name === varName ? { ...v, required } : v))
        );
    };

    const handleSave = async () => {
        handleSaveNodeData({
            ...data,
            name,
            extraction_variables: customVars,
        });
        setOpen(false);
        setTimeout(async () => {
            await saveWorkflow();
        }, 100);
    };

    const hasChanges = useMemo(() => {
        if (name !== data.name) return true;
        const saved = data.extraction_variables ?? [];
        if (saved.length !== customVars.length) return true;
        return customVars.some((v, i) =>
            v.name !== saved[i]?.name || (v.required !== false) !== (saved[i]?.required !== false)
        );
    }, [name, customVars, data]);

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title={data.name || 'Call Variables'}
                icon={<Braces />}
                nodeType="callVariables"
                hasSourceHandle={true}
                hasTargetHandle={true}
                onDoubleClick={() => handleOpenChange(true)}
                onEdit={() => handleOpenChange(true)}
                nodeId={id}
            >
                {variables.length === 0 ? (
                    <p className="text-sm text-muted-foreground line-clamp-3 leading-relaxed">
                        No variables collected yet. Enable variable extraction on an agent node
                        (or add custom variables here), then attach an Action node for post-call
                        integrations.
                    </p>
                ) : (
                    <div className="space-y-2">
                        <p className="text-xs text-muted-foreground">
                            {variables.length} variable{variables.length > 1 ? 's' : ''} available for
                            post-call actions:
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                            {variables.slice(0, 12).map((v) => (
                                <Badge
                                    key={v.name}
                                    variant="secondary"
                                    className="text-[10px] font-mono"
                                >
                                    {`{{${v.name}}}`}
                                    {!v.required && (
                                        <span className="ml-1 text-muted-foreground/60">opt</span>
                                    )}
                                </Badge>
                            ))}
                            {variables.length > 12 && (
                                <span className="text-[10px] text-muted-foreground self-center">
                                    +{variables.length - 12} more
                                </span>
                            )}
                        </div>
                    </div>
                )}
            </NodeContent>

            <NodeToolbar isVisible={selected} position={Position.Right}>
                <div className="flex flex-col gap-1">
                    <Button onClick={() => handleOpenChange(true)} variant="outline" size="icon">
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
                title="Edit Call Variables"
                onSave={handleSave}
                hasChanges={hasChanges}
                dialogClassName="max-w-2xl"
            >
                <div className="grid gap-6 max-h-[60vh] overflow-y-auto pr-2 custom-scrollbar">
                    <div className="space-y-2" data-field="name">
                        <Label className="text-sm font-medium">Name</Label>
                        <Input
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Call Variables"
                            className="bg-background/50 border-white/10"
                        />
                    </div>

                    <div className="space-y-2" data-field="extraction_variables">
                        <Label className="text-sm font-medium">Custom variables</Label>
                        <p className="text-xs text-muted-foreground">
                            Declare extra variables you know will be available at call time (e.g.
                            values passed via campaign columns or the API). Reference them in Action
                            nodes as <span className="font-mono">{'{{variable_name}}'}</span>.
                        </p>

                        <div className="space-y-2">
                            {customVars.length === 0 && (
                                <p className="text-xs text-muted-foreground/70 italic">
                                    No custom variables yet.
                                </p>
                            )}
                            {customVars.map((v) => (
                                <div
                                    key={v.name}
                                    className="flex items-center gap-3 rounded-lg border border-white/10 bg-background/50 px-3 py-2"
                                >
                                    <span className="font-mono text-xs flex-1 truncate">{`{{${v.name}}}`}</span>
                                    <div className="flex items-center gap-1.5">
                                        <Switch
                                            checked={v.required !== false}
                                            onCheckedChange={(checked) => handleToggleRequired(v.name, checked)}
                                        />
                                        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
                                            Required
                                        </span>
                                    </div>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="h-6 w-6 text-muted-foreground hover:text-destructive"
                                        onClick={() => handleRemoveCustomVar(v.name)}
                                    >
                                        <X className="h-3.5 w-3.5" />
                                    </Button>
                                </div>
                            ))}
                        </div>

                        <div className="flex items-center gap-2">
                            <Input
                                value={newVarName}
                                onChange={(e) => setNewVarName(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        e.preventDefault();
                                        handleAddCustomVar();
                                    }
                                }}
                                placeholder="e.g. customer_id"
                                className="bg-background/50 border-white/10 font-mono text-xs"
                            />
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={handleAddCustomVar}
                                disabled={!newVarName.trim()}
                                className="gap-1.5 shrink-0"
                            >
                                <PlusIcon className="h-3.5 w-3.5" /> Add
                            </Button>
                        </div>
                    </div>

                    {aggregatedVariables.length > 0 && (
                        <div className="space-y-2">
                            <Label className="text-sm font-medium">
                                Auto-collected variables ({aggregatedVariables.length})
                            </Label>
                            <p className="text-xs text-muted-foreground">
                                Aggregated live from extraction variables, exit conditions and
                                template context across the workflow. Edit them on their source
                                nodes.
                            </p>
                            <div className="flex flex-wrap gap-1.5">
                                {aggregatedVariables.map((v) => (
                                    <Badge key={v.name} variant="secondary" className="text-[10px] font-mono">
                                        {`{{${v.name}}}`}
                                        {!v.required && (
                                            <span className="ml-1 text-muted-foreground/60">opt</span>
                                        )}
                                    </Badge>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </NodeEditDialog>
        </>
    );
});

CallVariablesNode.displayName = "CallVariablesNode";
