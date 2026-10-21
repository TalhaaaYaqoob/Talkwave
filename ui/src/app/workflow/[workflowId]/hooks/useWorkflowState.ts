import {
    applyEdgeChanges,
    applyNodeChanges,
    OnConnect,
    OnEdgesChange,
    OnNodesChange,
    ReactFlowInstance,
} from "@xyflow/react";
import { EdgeChange, NodeChange } from "@xyflow/system";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { useWorkflowStore } from "@/app/workflow/[workflowId]/stores/workflowStore";
import {
    createWorkflowRunApiV1WorkflowWorkflowIdRunsPost,
    updateWorkflowApiV1WorkflowWorkflowIdPut
} from "@/client";
import { WorkflowError } from "@/client/types.gen";
import {
    DEFAULT_ACTION_NODE_DATA,
    DEFAULT_CALL_VARIABLES_DATA,
    DEFAULT_CATEGORIZE_DATA,
    DEFAULT_IF_ELSE_DATA,
    DEFAULT_TRANSFER_DATA,
    FlowEdge,
    FlowNode,
    NodeType,
} from "@/components/flow/types";
import { getBackendUrl } from '@/lib/apiClient';
import logger from '@/lib/logger';
import { getNextNodeId, getRandomId } from "@/lib/utils";
import { WorkflowConfigurations } from "@/types/workflow-configurations";

export function getDefaultAllowInterrupt(type: string = NodeType.START_CALL): boolean {
    switch (type) {
        case NodeType.AGENT_NODE:
            return true; // Agents can be interrupted
        case NodeType.START_CALL:
        case NodeType.END_CALL:
            return false; // Start/End messages should not be interrupted
        default:
            return false;
    }
}

const defaultNodes: FlowNode[] = [
    {
        id: "1",
        type: NodeType.START_CALL,
        position: { x: 200, y: 200 },
        data: {
            prompt: "",
            name: "",
            is_static: false, // Static nodes are not supported
            allow_interrupt: getDefaultAllowInterrupt(NodeType.START_CALL),
        },
    },
];

const getNewNode = (type: string, position: { x: number, y: number }, existingNodes: FlowNode[]): Omit<FlowNode, 'selected'> => {
    const id = getNextNodeId(existingNodes);

    if (type === NodeType.ACTION_NODE) {
        return { id, type, position, data: { ...DEFAULT_ACTION_NODE_DATA } };
    }
    if (type === NodeType.IF_ELSE) {
        return { id, type, position, data: { ...DEFAULT_IF_ELSE_DATA } };
    }
    if (type === NodeType.CATEGORIZE) {
        return { id, type, position, data: { ...DEFAULT_CATEGORIZE_DATA } };
    }
    if (type === NodeType.TRANSFER) {
        return { id, type, position, data: { ...DEFAULT_TRANSFER_DATA } };
    }
    if (type === NodeType.CALL_VARIABLES) {
        return { id, type, position, data: { ...DEFAULT_CALL_VARIABLES_DATA } };
    }

    return {
        id,
        type,
        position,
        data: {
            prompt: {
                [NodeType.GLOBAL_NODE]: "You are a helpful assistant whose mode of interaction with the user is voice. So don't use any special characters which can not be pronounced. Use short sentences and simple language.",
            }[type] || "",
            name: {
                [NodeType.GLOBAL_NODE]: "Global Node",
                [NodeType.START_CALL]: "Start Call",
                [NodeType.END_CALL]: "End Call",
            }[type] || "",
            is_static: false,
            allow_interrupt: getDefaultAllowInterrupt(type),
        },
    };
};

interface UseWorkflowStateProps {
    initialWorkflowName: string;
    workflowId: number;
    // Opaque token for user-facing URLs (falls back to workflowId if absent).
    publicId?: string;
    initialFlow?: {
        nodes: FlowNode[];
        edges: FlowEdge[];
        viewport: {
            x: number;
            y: number;
            zoom: number;
        };
    };
    initialTemplateContextVariables?: Record<string, string>;
    initialWorkflowConfigurations?: WorkflowConfigurations;
    user: { id: string; email?: string };  // Minimal user type needed
    getAccessToken: () => Promise<string>;
}

export const useWorkflowState = ({
    initialWorkflowName,
    workflowId,
    publicId,
    initialFlow,
    initialTemplateContextVariables,
    initialWorkflowConfigurations,
    user,
    getAccessToken
}: UseWorkflowStateProps) => {
    const router = useRouter();
    const rfInstance = useRef<ReactFlowInstance<FlowNode, FlowEdge> | null>(null);

    // Get state and actions from the store
    const {
        nodes,
        edges,
        workflowName,
        isDirty,
        isAddNodePanelOpen,
        workflowValidationErrors,
        templateContextVariables,
        workflowConfigurations,
        initializeWorkflow,
        setNodes,
        setEdges,
        setWorkflowName,
        setIsDirty,
        setIsAddNodePanelOpen,
        setWorkflowValidationErrors,
        setTemplateContextVariables,
        setWorkflowConfigurations,
        clearValidationErrors,
        markNodeAsInvalid,
        markEdgeAsInvalid,
        setRfInstance,
        resetLocallyClearedNodes,
    } = useWorkflowStore();

    // Get undo/redo functions from the store
    const undo = useWorkflowStore((state) => state.undo);
    const redo = useWorkflowStore((state) => state.redo);
    const canUndo = useWorkflowStore((state) => state.canUndo());
    const canRedo = useWorkflowStore((state) => state.canRedo());

    // Initialize workflow on mount
    useEffect(() => {
        const initialNodes = initialFlow?.nodes?.length
            ? initialFlow.nodes.map(node => ({
                ...node,
                data: {
                    ...node.data,
                    invalid: false,
                    is_static: false, // Static nodes are not supported - always override to false
                    allow_interrupt: node.data.allow_interrupt !== undefined
                        ? node.data.allow_interrupt
                        : getDefaultAllowInterrupt(node.type),
                }
            }))
            : defaultNodes;

        // Get valid node IDs to filter orphan edges
        const validNodeIds = new Set(initialNodes.map(n => n.id));
        
        // Clean up edges thoroughly
        const seenEdges = new Set<string>();
        const initialEdges = (initialFlow?.edges ?? [])
            .filter(edge => {
                // Must have valid source and target
                if (!edge.source || !edge.target) {
                    return false;
                }
                
                if (!validNodeIds.has(edge.source) || !validNodeIds.has(edge.target)) {
                    return false;
                }
                
                const edgeKey = `${edge.source}->${edge.target}`;
                if (seenEdges.has(edgeKey)) {
                    return false;
                }
                seenEdges.add(edgeKey);
                
                return true;
            })
            .map(edge => ({
                // Ensure edge has proper structure
                id: edge.id || `edge-${edge.source}-${edge.target}`,
                source: edge.source,
                target: edge.target,
                type: edge.type || 'custom',
                animated: edge.animated !== false,
                data: {
                    condition: typeof edge.data?.condition === 'string' ? edge.data.condition : '',
                    label: typeof edge.data?.label === 'string' ? edge.data.label : '',
                },
                // Remove any invalid handles that might cause floating edges
                sourceHandle: undefined,
                targetHandle: undefined,
            }));

        initializeWorkflow(
            workflowId,
            initialWorkflowName,
            initialNodes,
            initialEdges,
            initialTemplateContextVariables,
            initialWorkflowConfigurations
        );
    }, []);

    // Set up keyboard shortcuts for undo/redo
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            // Check if we're in an input field
            const target = e.target as HTMLElement;
            if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
                return;
            }

            // Undo: Cmd/Ctrl + Z
            if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) {
                e.preventDefault();
                if (canUndo) {
                    undo();
                }
            }
            // Redo: Cmd/Ctrl + Shift + Z or Cmd/Ctrl + Y
            else if (
                ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'z') ||
                ((e.metaKey || e.ctrlKey) && e.key === 'y')
            ) {
                e.preventDefault();
                if (canRedo) {
                    redo();
                }
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [undo, redo, canUndo, canRedo]);

    const handleNodeSelect = useCallback((nodeType: string) => {
        if (!rfInstance.current) return;

        // Get the center position of the viewport
        const centerPosition = rfInstance.current.screenToFlowPosition({
            x: window.innerWidth / 2,
            y: window.innerHeight / 2,
        });

        // Find the lowest Y position among existing nodes to place new node below
        const existingNodes = rfInstance.current.getNodes();
        let maxY = centerPosition.y;

        if (existingNodes.length > 0) {
            // Find the node with the highest Y position (lowest on screen)
            existingNodes.forEach(node => {
                const nodeBottom = node.position.y + (node.measured?.height || 150);
                if (nodeBottom > maxY) {
                    maxY = nodeBottom;
                }
            });
            // Add spacing below the lowest node (enough room for edge labels between nodes)
            maxY += 180;
        }

        const position = {
            x: centerPosition.x - 160, // Center horizontally (node width is ~320px)
            y: maxY,
        };

        const newNode = {
            ...getNewNode(nodeType, position, nodes),
            selected: true, // Mark the new node as selected
        };

        // Deselect all existing nodes before adding new one
        rfInstance.current.setNodes((nds) =>
            nds.map((n) => ({ ...n, selected: false }))
        );

        // Use addNodes from ReactFlow instance
        rfInstance.current.addNodes([newNode]);
        setIsAddNodePanelOpen(false);
    }, [nodes, setIsAddNodePanelOpen]);

    const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setWorkflowName(e.target.value);
        setIsDirty(true);
    };

    // Validate workflow function. Sends the LIVE (possibly unsaved) flow so the
    // error indicator reflects in-progress edits — fixing an error clears it
    // immediately, without requiring a save.
    const validateWorkflow = useCallback(async () => {
        if (!user) return;
        try {
            const accessToken = await getAccessToken();
            const liveFlow = rfInstance.current?.toObject() ?? null;

            const res = await fetch(
                `${getBackendUrl()}/api/v1/workflow/${workflowId}/validate`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${accessToken}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ workflow_definition: liveFlow }),
                }
            );

            // Get the set of nodes that were locally cleared by the user
            const clearedNodes = useWorkflowStore.getState().locallyClearedNodes;

            const applyErrors = (errors: WorkflowError[]) => {
                // Filter out errors for nodes the user has already fixed locally
                const filtered = errors.filter((e) => !(e.kind === 'node' && e.id && clearedNodes.has(e.id)));

                if (filtered.length > 0) {
                    filtered.forEach((error) => {
                        if (error.kind === 'node' && error.id) {
                            markNodeAsInvalid(error.id, error.message, error.field);
                        } else if (error.kind === 'edge' && error.id) {
                            markEdgeAsInvalid(error.id, error.message);
                        }
                    });
                    setWorkflowValidationErrors(filtered);
                }
            };

            let parsed: {
                is_valid?: boolean;
                errors?: WorkflowError[];
                detail?: { errors?: WorkflowError[] };
            } | null = null;
            try {
                parsed = await res.json();
            } catch {
                parsed = null;
            }

            if (res.ok) {
                // Definitively valid — clear any lingering indicators.
                clearValidationErrors();
                return;
            }

            const errs = parsed?.detail?.errors ?? parsed?.errors;
            if (errs) {
                // Definitive validation failure — reset then re-apply.
                clearValidationErrors();
                applyErrors(errs);
            }
            // Otherwise (transient/non-validation error): leave the current
            // indicator untouched; the next edit re-validates.
        } catch (error) {
            logger.error(`Unexpected validation error: ${error}`);
        }
    }, [workflowId, user, getAccessToken, clearValidationErrors, markNodeAsInvalid, markEdgeAsInvalid, setWorkflowValidationErrors]);

    // Save workflow function
    const saveWorkflow = useCallback(async (updateWorkflowDefinition: boolean = true) => {
        if (!user || !rfInstance.current) return;
        const flow = rfInstance.current.toObject();
        const accessToken = await getAccessToken();
        try {
            await updateWorkflowApiV1WorkflowWorkflowIdPut({
                path: {
                    workflow_id: workflowId,
                },
                body: {
                    name: workflowName,
                    workflow_definition: updateWorkflowDefinition ? flow : null,
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });
            setIsDirty(false);
        } catch (error) {
            logger.error(`Error saving workflow: ${error}`);
        }

        // Reset locally cleared nodes since backend now has fresh data
        resetLocallyClearedNodes();
        // Validate after saving
        await validateWorkflow();
    }, [workflowId, workflowName, setIsDirty, user, getAccessToken, validateWorkflow, resetLocallyClearedNodes]);

    const onConnect: OnConnect = useCallback((connection) => {
        if (!rfInstance.current || !connection.source || !connection.target) return;

        const sourceNode = rfInstance.current.getNode(connection.source) as FlowNode | undefined;
        const targetNode = rfInstance.current.getNode(connection.target) as FlowNode | undefined;
        const currentEdges = rfInstance.current.getEdges();

        if (sourceNode?.type === NodeType.END_CALL) {
            const endOutgoingCount = currentEdges.filter((edge) => edge.source === connection.source).length;
            if (endOutgoingCount >= 1) {
                toast.warning("End Call node can only have one outgoing connection.");
                return;
            }
            if (targetNode?.type !== NodeType.ACTION_NODE && targetNode?.type !== NodeType.CALL_VARIABLES) {
                toast.warning("Invalid connection", {
                    description: "End Call can only connect to a Call Variables or Action node.",
                });
                return;
            }
        }

        // Call Variables hub: fans out only to Action nodes.
        if (sourceNode?.type === NodeType.CALL_VARIABLES) {
            if (targetNode?.type !== NodeType.ACTION_NODE) {
                toast.warning("Invalid connection", {
                    description: "Call Variables can only connect to an Action node.",
                });
                return;
            }
        }

        // If/Else: max 1 edge per handle (true / false)
        if (sourceNode?.type === NodeType.IF_ELSE) {
            const handleEdges = currentEdges.filter(
                (edge) => edge.source === connection.source && (edge as unknown as { sourceHandle?: string }).sourceHandle === connection.sourceHandle
            );
            if (handleEdges.length >= 1) {
                toast.warning(`The ${connection.sourceHandle} handle already has a connection.`);
                return;
            }
        }

        // Categorize: max 1 edge per category handle
        if (sourceNode?.type === NodeType.CATEGORIZE) {
            const handleEdges = currentEdges.filter(
                (edge) => edge.source === connection.source && (edge as unknown as { sourceHandle?: string }).sourceHandle === connection.sourceHandle
            );
            if (handleEdges.length >= 1) {
                toast.warning("This category handle already has a connection.");
                return;
            }
        }

        // Transfer node: no outgoing connections (terminal)
        if (sourceNode?.type === NodeType.TRANSFER) {
            toast.warning("Transfer is a terminal node and cannot have outgoing connections.");
            return;
        }

        // Avoid duplicate source->target edges.
        if (currentEdges.some((edge) => edge.source === connection.source && edge.target === connection.target)) {
            return;
        }

        // Auto-label edges from If/Else handles
        let edgeLabel = '';
        if (sourceNode?.type === NodeType.IF_ELSE && connection.sourceHandle) {
            edgeLabel = connection.sourceHandle === 'true' ? 'True' : 'False';
        }
        // Auto-label edges from Categorize handles
        if (sourceNode?.type === NodeType.CATEGORIZE && connection.sourceHandle) {
            edgeLabel = connection.sourceHandle.replace('category-', '');
        }

        rfInstance.current.addEdges([{
            ...connection,
            id: `${connection.source}-${connection.target}`,
            data: {
                label: edgeLabel,
                condition: edgeLabel,
            }
        }]);
    }, []);

    const onEdgesChange: OnEdgesChange = useCallback(
        (changes) => {
            const currentEdges = useWorkflowStore.getState().edges;
            const newEdges = applyEdgeChanges(changes, currentEdges) as FlowEdge[];
            // Cast changes to FlowEdge type - safe because setEdges only uses the type field
            // to determine history tracking, not the actual item data
            setEdges(newEdges, changes as EdgeChange<FlowEdge>[]);
        },
        [setEdges],
    );

    const onNodesChange: OnNodesChange = useCallback(
        (changes) => {
            const currentNodes = useWorkflowStore.getState().nodes;
            const newNodes = applyNodeChanges(changes, currentNodes) as FlowNode[];
            // Cast changes to FlowNode type - safe because setNodes only uses the type field
            // to determine history tracking, not the actual item data
            setNodes(newNodes, changes as NodeChange<FlowNode>[]);
        },
        [setNodes],
    );

    const [isStartingRun, setIsStartingRun] = useState(false);

    const onRun = async (mode: string) => {
        if (!user) return;
        setIsStartingRun(true);
        try {
            const workflowRunName = `WR-${getRandomId()}`;
            const accessToken = await getAccessToken();
            const response = await createWorkflowRunApiV1WorkflowWorkflowIdRunsPost({
                path: {
                    workflow_id: workflowId,
                },
                body: {
                    mode,
                    name: workflowRunName
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });

            // Handle subscription limit errors
            if (response.error) {
                setIsStartingRun(false);
                const errorDetail = response.error as { detail?: { error?: string; message?: string; reason?: string } };
                if (errorDetail?.detail?.error === 'subscription_limit') {
                    const message = errorDetail.detail.message || 'Subscription limit reached';
                    const reason = errorDetail.detail.reason || '';
                    if (reason === 'trial_expired' || reason === 'minutes_exhausted') {
                        toast.error(message, {
                            description: "Visit the Pricing page to upgrade your plan.",
                        });
                        router.push('/usage');
                    } else {
                        toast.error(message);
                    }
                    return;
                }
                // Generic error
                const msg = errorDetail?.detail?.message || 'Failed to create workflow run';
                toast.error(msg);
                return;
            }

            // Navigation will unmount, so no need to reset isStartingRun
            router.push(`/workflow/${publicId ?? workflowId}/run/${response.data?.id}`);
        } catch (error) {
            setIsStartingRun(false);
            logger.error(`Error starting workflow run: ${error}`);
            toast.error('Failed to start workflow run. Please try again.');
        }
    };

    // Save template context variables
    const saveTemplateContextVariables = useCallback(async (variables: Record<string, string>) => {
        if (!user) return;
        const accessToken = await getAccessToken();
        try {
            await updateWorkflowApiV1WorkflowWorkflowIdPut({
                path: {
                    workflow_id: workflowId,
                },
                body: {
                    name: workflowName,
                    workflow_definition: null,
                    template_context_variables: variables,
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });
            setTemplateContextVariables(variables);
            logger.info('Template context variables saved successfully');
        } catch (error) {
            logger.error(`Error saving template context variables: ${error}`);
            throw error;
        }
    }, [workflowId, workflowName, user, getAccessToken, setTemplateContextVariables]);

    // Save workflow configurations
    const saveWorkflowConfigurations = useCallback(async (configurations: WorkflowConfigurations, newWorkflowName: string) => {
        if (!user) return;
        const accessToken = await getAccessToken();
        try {
            await updateWorkflowApiV1WorkflowWorkflowIdPut({
                path: {
                    workflow_id: workflowId,
                },
                body: {
                    name: newWorkflowName,
                    workflow_definition: null,
                    workflow_configurations: configurations as Record<string, unknown>,
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });
            setWorkflowConfigurations(configurations);
            setWorkflowName(newWorkflowName);
            logger.info('Workflow configurations saved successfully');
        } catch (error) {
            logger.error(`Error saving workflow configurations: ${error}`);
            throw error;
        }
    }, [workflowId, user, getAccessToken, setWorkflowConfigurations, setWorkflowName]);

    // Update rfInstance when it changes
    useEffect(() => {
        if (rfInstance.current) {
            setRfInstance(rfInstance.current);
        }
    }, [setRfInstance]);

    // Validate workflow on mount
    useEffect(() => {
        validateWorkflow();
    }, []);

    // A signature of everything that affects validation (node/edge structure +
    // the data fields the validator checks), but NOT positions — so dragging a
    // node around doesn't trigger a re-validate.
    const validationSignature = useMemo(() => {
        try {
            return JSON.stringify({
                n: nodes.map((n) => ({ id: n.id, type: n.type, data: n.data })),
                e: edges.map((e) => ({ source: e.source, target: e.target, sourceHandle: (e as unknown as { sourceHandle?: string }).sourceHandle, data: e.data })),
            });
        } catch {
            return `${nodes.length}:${edges.length}`;
        }
    }, [nodes, edges]);

    // Re-validate (debounced) against the LIVE flow whenever the graph changes,
    // so fixing an issue clears the error indicator immediately without a save.
    const didInitialValidationRef = useRef(false);
    useEffect(() => {
        if (!didInitialValidationRef.current) {
            // Skip the first run — the mount effect above already validates.
            didInitialValidationRef.current = true;
            return;
        }
        const timer = setTimeout(() => {
            validateWorkflow();
        }, 700);
        return () => clearTimeout(timer);
    }, [validationSignature, validateWorkflow]);

    return {
        rfInstance,
        nodes,
        edges,
        isAddNodePanelOpen,
        workflowName,
        isDirty,
        workflowValidationErrors,
        templateContextVariables,
        workflowConfigurations,
        isStartingRun,
        setNodes,
        setEdges,
        setIsDirty,
        setIsAddNodePanelOpen,
        handleNodeSelect,
        handleNameChange,
        saveWorkflow,
        onConnect,
        onEdgesChange,
        onNodesChange,
        onRun,
        saveTemplateContextVariables,
        saveWorkflowConfigurations,
        undo,
        redo,
        canUndo,
        canRedo,
    };
};
