'use client';

import { type Node, type NodeProps, NodeToolbar, Position, useEdges, useNodes } from "@xyflow/react";
import {
    AlertTriangle,
    Edit,
    Play,
    Plus,
    Trash2Icon,
    Zap,
} from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { useWorkflowStore } from "@/app/workflow/[workflowId]/stores/workflowStore";
import {
    ActionConfig,
    ActionNodeData,
    DEFAULT_ACTION_NODE_DATA,
} from "@/components/flow/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { AITextField } from "./common/AIHelpers";
import { getVisual } from "./common/integrationIcons";
import { findStaleActionRefs } from "./common/variableRefs";

import { ActionsListPanel } from "./action-panels";
import { NodeContent } from "./common/NodeContent";
import { NodeEditDialog } from "./common/NodeEditDialog";
import { useNodeHandlers } from "./common/useNodeHandlers";

type ActionNodeData_ = ActionNodeData & {
    invalid?: boolean;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
} & Record<string, unknown>;

type ActionNodeType = Node<ActionNodeData_, 'actionNode'>;
type ActionNodeProps = NodeProps<ActionNodeType>;

const ACTION_TYPE_TO_VISUAL_KEY: Record<string, string> = {
    send_sms: 'twilio',
    send_email: 'gmail',
    send_whatsapp: 'whatsapp',
    send_slack: 'slack',
    google_sheets: 'googlesheets',
    webhook: 'webhook',
    api_call: 'http_api',
    set_variable: 'set_variable',
    database_query: 'postgresql',
    custom_tool: 'custom_tool',
};

const getActionIcon = (type: ActionConfig['type']) => {
    return getVisual(ACTION_TYPE_TO_VISUAL_KEY[type] || type).icon('w-3 h-3');
};

const getActionColor = (type: ActionConfig['type']) => {
    const v = getVisual(ACTION_TYPE_TO_VISUAL_KEY[type] || type);
    const bg = v.bgColor.replace(/hover:\S+/g, '').trim();
    return `${bg} ${v.color}`;
};

export const ActionNode = memo(({ data, selected, id }: ActionNodeProps) => {
    const { open, setOpen, handleSaveNodeData, handleDeleteNode, handleClearValidation, handleRestoreValidation } = useNodeHandlers({ id });
    const { saveWorkflow } = useWorkflow();
    const edges = useEdges();
    const allNodes = useNodes();
    const nameRef = useRef<HTMLInputElement>(null);
    const savedValidation = useRef<{ field: string; message: string } | null>(null);

    // Action Node state
    const [name, setName] = useState(data.name ?? DEFAULT_ACTION_NODE_DATA.name);
    const [description, setDescription] = useState(data.description ?? DEFAULT_ACTION_NODE_DATA.description);
    const [actions, setActions] = useState<ActionConfig[]>(data.actions ?? DEFAULT_ACTION_NODE_DATA.actions);
    const [executionMode, setExecutionMode] = useState<'sequential' | 'parallel'>(
        data.execution_mode ?? DEFAULT_ACTION_NODE_DATA.execution_mode
    );

    const handleSave = async () => {
        handleSaveNodeData({
            ...data,
            name,
            description,
            actions,
            execution_mode: executionMode,
            is_static: false, // Static nodes are not supported
        } as unknown as import('@/components/flow/types').FlowNodeData);
        setOpen(false);
        // Save the workflow after updating node data with a small delay
        setTimeout(async () => {
            await saveWorkflow();
        }, 100);
    };

    // Reset form state when dialog opens
    const handleOpenChange = (newOpen: boolean) => {
        if (newOpen) {
            setName(data.name ?? DEFAULT_ACTION_NODE_DATA.name);
            setDescription(data.description ?? DEFAULT_ACTION_NODE_DATA.description);
            setActions(data.actions ?? DEFAULT_ACTION_NODE_DATA.actions);
            setExecutionMode(data.execution_mode ?? DEFAULT_ACTION_NODE_DATA.execution_mode);
        }
        setOpen(newOpen);
    };

    // Update form state when data changes (e.g., from undo/redo)
    useEffect(() => {
        if (open) {
            setName(data.name ?? DEFAULT_ACTION_NODE_DATA.name);
            setDescription(data.description ?? DEFAULT_ACTION_NODE_DATA.description);
            setActions(data.actions ?? DEFAULT_ACTION_NODE_DATA.actions);
            setExecutionMode(data.execution_mode ?? DEFAULT_ACTION_NODE_DATA.execution_mode);
        }
    }, [data, open]);

    useEffect(() => {
        if (data.invalid && data.invalidField && data.validationMessage) {
            const field = data.invalidField.startsWith("data.") ? data.invalidField.slice(5) : data.invalidField;
            savedValidation.current = { field, message: data.validationMessage };
        }
    }, [data.invalid, data.invalidField, data.validationMessage]);

    const handleNameChange = useCallback((value: string) => {
        setName(value);
        if (data.invalid && savedValidation.current?.field === 'name' && value.trim().length > 0) {
            handleClearValidation();
        } else if (!data.invalid && savedValidation.current?.field === 'name' && value.trim().length === 0) {
            handleRestoreValidation(savedValidation.current.message, savedValidation.current.field);
        }
    }, [data.invalid, handleClearValidation, handleRestoreValidation]);

    const handleNavigateToField = useCallback((fieldName: string) => {
        if (fieldName === "name" && nameRef.current) {
            nameRef.current.focus();
            nameRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, []);

    // Hide source handle if this action node is terminal: connected directly
    // after an End Call node, or after a Call Variables hub (which itself sits
    // after the End node). In both cases the call is already over.
    const isAfterEndNode = useMemo(() => {
        const incomingEdges = edges.filter(e => e.target === id);
        return incomingEdges.some(edge => {
            const sourceNode = allNodes.find(n => n.id === edge.source);
            return sourceNode?.type === 'endCall' || sourceNode?.type === 'callVariables';
        });
    }, [edges, allNodes, id]);

    const hasChanges = useMemo(() => {
        if (name !== (data.name ?? DEFAULT_ACTION_NODE_DATA.name)) return true;
        if (description !== (data.description ?? DEFAULT_ACTION_NODE_DATA.description)) return true;
        if (executionMode !== (data.execution_mode ?? DEFAULT_ACTION_NODE_DATA.execution_mode)) return true;
        if (JSON.stringify(actions) !== JSON.stringify(data.actions ?? DEFAULT_ACTION_NODE_DATA.actions)) return true;
        return false;
    }, [name, description, executionMode, actions, data]);

    // Count enabled actions
    const enabledActionsCount = actions.filter(a => a.enabled).length;

    const templateContextVariables = useWorkflowStore((state) => state.templateContextVariables);

    const availableVariables = useMemo(() => {
        const vars: string[] = [];
        const push = (name?: string) => {
            const clean = (name || '').trim();
            if (clean && !vars.includes(clean)) {
                vars.push(clean);
            }
        };
        // Use the REACTIVE node list (useNodes) so this recomputes whenever a
        // node — or a node's variables — is added, edited, or removed.
        for (const node of allNodes) {
            const nodeData = (node.data || {}) as Record<string, unknown>;
            // Variables the agent extracts from the conversation.
            const extractionVars = nodeData?.extraction_variables as Array<{ name: string }> | undefined;
            if (Array.isArray(extractionVars)) {
                for (const v of extractionVars) push(v?.name);
            }
            // Variables required to leave a node (declared on exit conditions).
            const exitConditions = nodeData?.exit_conditions as Array<{ required_variables?: Array<{ name: string }> }> | undefined;
            if (Array.isArray(exitConditions)) {
                for (const ec of exitConditions) {
                    if (Array.isArray(ec?.required_variables)) {
                        for (const rv of ec.required_variables) push(rv?.name);
                    }
                }
            }
        }
        // Pre-call template context variables (campaign / lead seed data).
        if (templateContextVariables) {
            for (const key of Object.keys(templateContextVariables)) push(key);
        }
        return vars;
    }, [allNodes, templateContextVariables]);

    // Stale references: {{variables}} used in this node's actions that aren't
    // produced anywhere in the workflow. These silently render empty at runtime,
    // so we surface them right on the node card.
    const staleVariables = useMemo(
        () => findStaleActionRefs(actions, availableVariables).all,
        [actions, availableVariables],
    );

    return (
        <>
            <NodeContent
                selected={selected}
                invalid={data.invalid}
                selected_through_edge={data.selected_through_edge}
                hovered_through_edge={data.hovered_through_edge}
                title={name || 'Action'}
                icon={<Zap />}
                nodeType="action"
                hasSourceHandle={!isAfterEndNode}
                hasTargetHandle={true}
                onDoubleClick={() => setOpen(true)}
                onEdit={() => setOpen(true)}
                nodeId={id}
            >
                {/* Description */}
                {description && (
                    <p className="text-sm text-muted-foreground line-clamp-2 leading-relaxed">
                        {description}
                    </p>
                )}

                {/* Actions Preview */}
                {actions.length > 0 ? (
                    <div className="space-y-1.5 mt-2">
                        {/* Show up to 3 actions */}
                        {actions.slice(0, 3).map((action) => (
                            <div
                                key={action.id}
                                className={`
                                    flex items-center gap-2 px-2 py-1 rounded text-xs
                                    ${action.enabled ? 'opacity-100' : 'opacity-50'}
                                    ${getActionColor(action.type)}
                                `}
                            >
                                {getActionIcon(action.type)}
                                <span className="truncate">{action.name}</span>
                            </div>
                        ))}
                        {actions.length > 3 && (
                            <p className="text-xs text-muted-foreground pl-2">
                                +{actions.length - 3} more actions
                            </p>
                        )}
                    </div>
                ) : (
                    <div 
                        className="flex items-center gap-2 px-2 py-1.5 mt-2 rounded border border-dashed border-muted-foreground/30 text-muted-foreground/60 text-xs cursor-pointer hover:border-primary hover:text-primary transition-colors"
                        onClick={() => setOpen(true)}
                    >
                        <Plus className="w-3 h-3" />
                        <span>Add integrations, tools & actions</span>
                    </div>
                )}

                {/* Feature indicators */}
                <div className="flex flex-wrap gap-1 mt-2">
                    {enabledActionsCount > 0 && (
                        <Badge variant="secondary" className="text-xs">
                            <Play className="w-3 h-3 mr-1" />
                            {enabledActionsCount} action{enabledActionsCount > 1 ? 's' : ''}
                        </Badge>
                    )}
                    {executionMode === 'parallel' && (
                        <Badge variant="secondary" className="text-xs">
                            Parallel
                        </Badge>
                    )}
                    {staleVariables.length > 0 && (
                        <Badge
                            variant="outline"
                            className="text-xs border-amber-500/40 text-amber-500 bg-amber-500/10"
                            title={`Unknown variable${staleVariables.length > 1 ? 's' : ''}: ${staleVariables.map(v => `{{${v}}}`).join(', ')}. ${staleVariables.length > 1 ? 'They are' : 'It is'} not collected anywhere in this workflow.`}
                        >
                            <AlertTriangle className="w-3 h-3 mr-1" />
                            {staleVariables.length} unknown var{staleVariables.length > 1 ? 's' : ''}
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
                nodeData={data as unknown as import('@/components/flow/types').FlowNodeData}
                title="Edit Action Node"
                onSave={handleSave}
                hasChanges={hasChanges}
                onNavigateToField={handleNavigateToField}
                dialogClassName="max-w-4xl"
            >
                {open && (() => {
                    const nf = data.invalidField?.startsWith("data.") ? data.invalidField.slice(5) : data.invalidField;
                    const isNameInvalid = nf === "name";
                    return (
                    <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-2">
                        {/* Basic Info */}
                        <div className="grid grid-cols-1 gap-4">
                            <AITextField
                                nodeId={id}
                                value={name}
                                onChange={handleNameChange}
                                fieldName="name"
                                label="Name"
                                placeholder="e.g., Post-Call Actions, Send Confirmation"
                                inputRef={nameRef}
                                isInvalid={isNameInvalid}
                                required
                            />
                            <AITextField
                                nodeId={id}
                                value={description ?? ''}
                                onChange={setDescription}
                                fieldName="description"
                                label="Description"
                                placeholder="Describe what this action node does..."
                                multiline
                            />
                        </div>

                        {/* Actions List Panel */}
                        <div className="border-t pt-6">
                            <ActionsListPanel
                                actions={actions}
                                setActions={setActions}
                                executionMode={executionMode}
                                setExecutionMode={setExecutionMode}
                                availableVariables={availableVariables}
                            />
                        </div>
                    </div>
                    );
                })()}
            </NodeEditDialog>
        </>
    );
});

ActionNode.displayName = "ActionNode";

