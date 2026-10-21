import '@xyflow/react/dist/style.css';

import { AnimatePresence, motion } from "framer-motion";
import {
    Background,
    BackgroundVariant,
    Panel,
    ReactFlow,
} from "@xyflow/react";
import { Braces, BrushCleaning, Code2, Maximize2, Minus, Plus, Settings, Variable, X } from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { FlowEdge, FlowNode, NodeType } from "@/components/flow/types";
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { WorkflowConfigurations } from '@/types/workflow-configurations';

import AddNodePanel from "../../../components/flow/AddNodePanel";
import AIEditPanel from "../../../components/flow/AIEditPanel";
import CustomEdge from "../../../components/flow/edges/CustomEdge";
import { ActionNode, AgentNode, CallVariablesNode, CategorizeNode, EndCall, GlobalNode, IfElseNode, MeetingSummaryNode, MeetingTriggerNode, StartCall, TransferNode } from "../../../components/flow/nodes";
import { ConfigurationsDialog } from './components/ConfigurationsDialog';
import { EmbedDialog } from '@/app/workflow/[workflowId]/components/embed-dialog';
import { PhoneCallDialog } from './components/PhoneCallDialog';
import { TestCallDialog } from './components/TestCallDialog';
import { TemplateContextVariablesDialog } from './components/TemplateContextVariablesDialog';
import { WorkflowVariablesDialog } from './components/WorkflowVariablesDialog';
import { WorkflowEditorHeader } from "./components/WorkflowEditorHeader";
import { WorkflowProvider } from "./contexts/WorkflowContext";
import { useWorkflowState } from "./hooks/useWorkflowState";
import { layoutNodes } from './utils/layoutNodes';

// Define the node types dynamically based on the onSave prop
const nodeTypes = {
    [NodeType.START_CALL]: StartCall,
    [NodeType.AGENT_NODE]: AgentNode,
    [NodeType.END_CALL]: EndCall,
    [NodeType.GLOBAL_NODE]: GlobalNode,
    [NodeType.ACTION_NODE]: ActionNode,
    [NodeType.CALL_VARIABLES]: CallVariablesNode,
    [NodeType.MEETING_TRIGGER]: MeetingTriggerNode,
    [NodeType.MEETING_SUMMARY]: MeetingSummaryNode,
    [NodeType.IF_ELSE]: IfElseNode,
    [NodeType.CATEGORIZE]: CategorizeNode,
    [NodeType.TRANSFER]: TransferNode,
};

const edgeTypes = {
    custom: CustomEdge,
};

interface RenderWorkflowProps {
    initialWorkflowName: string;
    workflowId: number;
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
    user: { id: string; email?: string };
    getAccessToken: () => Promise<string>;
}

function RenderWorkflow({ initialWorkflowName, workflowId, publicId, initialFlow, initialTemplateContextVariables, initialWorkflowConfigurations, user, getAccessToken }: RenderWorkflowProps) {
    const [isContextVarsDialogOpen, setIsContextVarsDialogOpen] = useState(false);
    const [isVariablesDialogOpen, setIsVariablesDialogOpen] = useState(false);
    const [isConfigurationsDialogOpen, setIsConfigurationsDialogOpen] = useState(false);
    const [isPhoneCallDialogOpen, setIsPhoneCallDialogOpen] = useState(false);
    const [isEmbedDialogOpen, setIsEmbedDialogOpen] = useState(false);
    const [isTestCallOpen, setIsTestCallOpen] = useState(false);
    const [isAIEditOpen, setIsAIEditOpen] = useState(true);
    const [showHelpPanel, setShowHelpPanel] = useState(true);

    const {
        rfInstance,
        nodes,
        edges,
        isAddNodePanelOpen,
        workflowName,
        isDirty,
        workflowValidationErrors,
        templateContextVariables,
        workflowConfigurations,
        setNodes,
        setEdges,
        setIsDirty,
        setIsAddNodePanelOpen,
        handleNodeSelect,
        saveWorkflow,
        onConnect,
        onEdgesChange,
        onNodesChange,
        onRun,
        isStartingRun,
        saveTemplateContextVariables,
        saveWorkflowConfigurations
    } = useWorkflowState({
        initialWorkflowName,
        workflowId,
        publicId,
        initialFlow,
        initialTemplateContextVariables,
        initialWorkflowConfigurations,
        user,
        getAccessToken
    });

    // Memoize defaultEdgeOptions to prevent unnecessary re-renders
    const defaultEdgeOptions = useMemo(() => ({
        animated: true,
        type: "custom"
    }), []);

    // Memoize the context value to prevent unnecessary re-renders
    const workflowContextValue = useMemo(() => ({ saveWorkflow, workflowId }), [saveWorkflow, workflowId]);
    const agentNodes = useMemo(
        () => nodes.filter((node) => node.type === NodeType.AGENT_NODE),
        [nodes]
    );
    const connectedToolsCount = useMemo(
        () => agentNodes.reduce((total, node) => total + (node.data.tools?.length || 0), 0),
        [agentNodes]
    );

    useEffect(() => {
        if (!showHelpPanel) {
            return;
        }

        const timeoutId = window.setTimeout(() => {
            setShowHelpPanel(false);
        }, 8000);

        return () => window.clearTimeout(timeoutId);
    }, [showHelpPanel]);

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                setIsAIEditOpen(prev => !prev);
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, []);

    const handleAIEditApply = useCallback((result: { nodes: any[]; edges: any[]; explanation: string }) => {
        setNodes(result.nodes as FlowNode[]);
        setEdges(result.edges as FlowEdge[]);
        setIsDirty(true);
    }, [setNodes, setEdges, setIsDirty]);

    const focusAgentNode = (agentId: string) => {
        rfInstance.current?.fitView({
            nodes: [{ id: agentId }],
            padding: 0.45,
            duration: 500,
            maxZoom: 1.1,
        });
        setNodes(nodes.map((node) => ({
            ...node,
            selected: node.id === agentId,
        })));
    };

    return (
        <WorkflowProvider value={workflowContextValue}>
            <div className="flex flex-col h-screen">
                {/* New Workflow Editor Header */}
                <WorkflowEditorHeader
                    workflowName={workflowName}
                    isDirty={isDirty}
                    workflowValidationErrors={workflowValidationErrors}
                    rfInstance={rfInstance}
                    onRun={onRun}
                    isStartingRun={isStartingRun}
                    workflowId={workflowId}
                    publicId={publicId}
                    saveWorkflow={saveWorkflow}
                    user={user}
                    getAccessToken={getAccessToken}
                    onPhoneCallClick={() => setIsPhoneCallDialogOpen(true)}
                    onTestCallClick={() => setIsTestCallOpen(true)}
                    callType={workflowConfigurations?.call_type as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING' | undefined}
                />

                {/* Workflow Canvas */}
                <div className="flex-1 relative">
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        nodeTypes={nodeTypes}
                        edgeTypes={edgeTypes}
                        onConnect={onConnect}
                        onInit={(instance) => {
                            rfInstance.current = instance;
                            // Center the workflow on load
                            setTimeout(() => {
                                instance.fitView({ padding: 0.2, duration: 200, maxZoom: 0.75 });
                            }, 0);
                        }}
                        defaultEdgeOptions={defaultEdgeOptions}
                        defaultViewport={initialFlow?.viewport}
                        selectNodesOnDrag={false}
                        nodeDragThreshold={5}
                        elevateNodesOnSelect={true}
                        proOptions={{ hideAttribution: true }}
                    >
                        <Background
                            variant={BackgroundVariant.Dots}
                            gap={32}
                            size={2}
                            color="rgba(255, 255, 255, 0.05)"
                            className="bg-transparent"
                        />

                        {/* Top-right controls - vertical layout */}
                        <Panel position="top-right" className="m-6 !z-[20]">
                            <TooltipProvider>
                                <div className="flex flex-col gap-3 p-3 rounded-2xl bg-card border border-white/5 shadow-2xl ring-1 ring-white/5">
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => setIsAddNodePanelOpen(true)}
                                                className="h-11 w-11 rounded-xl bg-gradient-to-br from-primary/80 to-primary/40 hover:from-primary hover:to-primary/60 border border-white/10 text-primary-foreground transition-all duration-300 shadow-lg shadow-primary/20 hover:shadow-primary/40 hover:scale-105"
                                            >
                                                <Plus className="h-6 w-6" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="left">
                                            <p>Add node</p>
                                        </TooltipContent>
                                    </Tooltip>

                                    <div className="h-px w-full bg-gradient-to-r from-transparent via-white/10 to-transparent my-1" />

                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => setIsConfigurationsDialogOpen(true)}
                                                className="h-11 w-11 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                            >
                                                <Settings className="h-5 w-5" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="left">
                                            <p>Configurations</p>
                                        </TooltipContent>
                                    </Tooltip>

                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => setIsContextVarsDialogOpen(true)}
                                                className="h-11 w-11 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                            >
                                                <Variable className="h-5 w-5" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="left">
                                            <p>Template Context Variables</p>
                                        </TooltipContent>
                                    </Tooltip>

                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => setIsVariablesDialogOpen(true)}
                                                className="h-11 w-11 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                            >
                                                <Braces className="h-5 w-5" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="left">
                                            <p>All Variables (for integrations)</p>
                                        </TooltipContent>
                                    </Tooltip>

                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => setIsEmbedDialogOpen(true)}
                                                className="h-11 w-11 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                            >
                                                <Code2 className="h-5 w-5" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="left">
                                            <p>Embed on Website</p>
                                        </TooltipContent>
                                    </Tooltip>

                                </div>
                            </TooltipProvider>
                        </Panel>

                        {/* Workflow Overview */}
                        <Panel position="top-left" className="m-6 mt-24 z-[1000] pointer-events-none">
                            <div className="pointer-events-auto">
                                <AnimatePresence mode="wait">
                                    {showHelpPanel && agentNodes.length > 0 ? (
                                        <motion.div
                                            key="overview-expanded"
                                            initial={{ opacity: 0, y: -10 }}
                                            animate={{ opacity: 1, y: 0 }}
                                            exit={{ opacity: 0, y: -6 }}
                                            transition={{ duration: 0.2 }}
                                            className="w-[17rem] rounded-xl border border-white/[0.06] bg-[#0c0c0c]/90 backdrop-blur-xl shadow-[0_8px_30px_rgba(0,0,0,0.3)]"
                                        >
                                            <div className="flex items-center justify-between px-3 py-2.5">
                                                <div className="flex items-center gap-3">
                                                    <div className="flex items-center gap-1.5 text-[11px] text-white/50">
                                                        <span className="font-semibold text-white/80">{agentNodes.length}</span> agent{agentNodes.length !== 1 ? 's' : ''}
                                                    </div>
                                                    <div className="h-3 w-px bg-white/[0.06]" />
                                                    <div className="flex items-center gap-1.5 text-[11px] text-white/50">
                                                        <span className="font-semibold text-white/80">{connectedToolsCount}</span> tool{connectedToolsCount !== 1 ? 's' : ''}
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={() => setShowHelpPanel(false)}
                                                    className="flex h-5 w-5 items-center justify-center rounded text-white/20 hover:text-white/50 transition-colors"
                                                >
                                                    <X className="h-3 w-3" />
                                                </button>
                                            </div>

                                            <div className="border-t border-white/[0.04] max-h-[240px] overflow-y-auto">
                                                {agentNodes.map((agentNode) => {
                                                    const toolCount = agentNode.data.tools?.length || 0;
                                                    return (
                                                        <button
                                                            key={agentNode.id}
                                                            onClick={() => focusAgentNode(agentNode.id)}
                                                            className="group flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-white/[0.03]"
                                                        >
                                                            <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${toolCount > 0 ? 'bg-emerald-400' : 'bg-white/20'}`} />
                                                            <span className="truncate text-[12px] text-white/70 group-hover:text-white/90 flex-1">
                                                                {agentNode.data.name || 'Untitled'}
                                                            </span>
                                                            {toolCount > 0 && (
                                                                <span className="text-[10px] text-white/30">{toolCount}</span>
                                                            )}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                            <div className="border-t border-white/[0.04] px-3 py-2">
                                                <p className="text-[10px] text-white/25">
                                                    Use the <span className="text-white/45">AI Edit</span> bar below to add nodes, rewire flows, or modify agents with plain language.
                                                </p>
                                            </div>
                                        </motion.div>
                                    ) : showHelpPanel ? null : (
                                        <motion.button
                                            key="overview-collapsed"
                                            initial={{ opacity: 0, scale: 0.95 }}
                                            animate={{ opacity: 1, scale: 1 }}
                                            exit={{ opacity: 0, scale: 0.95 }}
                                            onClick={() => setShowHelpPanel(true)}
                                            className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-[#0c0c0c]/90 backdrop-blur-xl px-3 py-2 text-[11px] text-white/40 hover:text-white/60 shadow-md transition-colors"
                                        >
                                            <span className="font-semibold text-white/70">{agentNodes.length}</span> agent{agentNodes.length !== 1 ? 's' : ''}
                                            <span className="h-3 w-px bg-white/[0.06]" />
                                            <span className="font-semibold text-white/70">{connectedToolsCount}</span> tool{connectedToolsCount !== 1 ? 's' : ''}
                                        </motion.button>
                                    )}
                                </AnimatePresence>
                            </div>
                        </Panel>
                    </ReactFlow>

                    {/* Bottom-left controls - horizontal layout with custom buttons */}
                    <div className="absolute bottom-8 left-8 z-[20] flex gap-2 p-2 rounded-2xl bg-card border border-white/5 shadow-2xl ring-1 ring-white/5">
                        <TooltipProvider>
                            {/* Zoom In */}
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={() => rfInstance.current?.zoomIn()}
                                        className="h-10 w-10 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                    >
                                        <Plus className="h-4 w-4" />
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent side="top">
                                    <p>Zoom in</p>
                                </TooltipContent>
                            </Tooltip>

                            {/* Zoom Out */}
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={() => rfInstance.current?.zoomOut()}
                                        className="h-10 w-10 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                    >
                                        <Minus className="h-4 w-4" />
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent side="top">
                                    <p>Zoom out</p>
                                </TooltipContent>
                            </Tooltip>

                            <div className="w-px h-8 bg-gradient-to-b from-transparent via-white/10 to-transparent self-center mx-1" />

                            {/* Fit View */}
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={() => rfInstance.current?.fitView()}
                                        className="h-10 w-10 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                    >
                                        <Maximize2 className="h-4 w-4" />
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent side="top">
                                    <p>Fit view</p>
                                </TooltipContent>
                            </Tooltip>

                            {/* Tidy/Arrange Nodes */}
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={() => {
                                            setNodes(layoutNodes(nodes, edges, 'TB', rfInstance));
                                            setIsDirty(true);
                                        }}
                                        className="h-10 w-10 rounded-xl hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all duration-300"
                                    >
                                        <BrushCleaning className="h-4 w-4" />
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent side="top">
                                    <p>Tidy Up</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                </div>

                <AddNodePanel
                    isOpen={isAddNodePanelOpen}
                    onNodeSelect={handleNodeSelect}
                    onClose={() => setIsAddNodePanelOpen(false)}
                    callType={workflowConfigurations?.call_type as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING' | undefined}
                />

                <AIEditPanel
                    isOpen={isAIEditOpen}
                    onClose={() => setIsAIEditOpen(false)}
                    workflowId={workflowId}
                    getAccessToken={getAccessToken}
                    onApply={handleAIEditApply}
                    currentNodes={nodes}
                    currentEdges={edges}
                    currentViewport={rfInstance.current?.getViewport() ?? { x: 0, y: 0, zoom: 1 }}
                />

                <ConfigurationsDialog
                    open={isConfigurationsDialogOpen}
                    onOpenChange={setIsConfigurationsDialogOpen}
                    workflowConfigurations={workflowConfigurations}
                    workflowName={workflowName}
                    workflowId={workflowId}
                    onSave={saveWorkflowConfigurations}
                />

                <TemplateContextVariablesDialog
                    open={isContextVarsDialogOpen}
                    onOpenChange={setIsContextVarsDialogOpen}
                    templateContextVariables={templateContextVariables}
                    onSave={saveTemplateContextVariables}
                />

                <WorkflowVariablesDialog
                    open={isVariablesDialogOpen}
                    onOpenChange={setIsVariablesDialogOpen}
                />

                <PhoneCallDialog
                    open={isPhoneCallDialogOpen}
                    onOpenChange={setIsPhoneCallDialogOpen}
                    workflowId={workflowId}
                    getAccessToken={getAccessToken}
                    user={user}
                />

                <EmbedDialog
                    open={isEmbedDialogOpen}
                    onOpenChange={setIsEmbedDialogOpen}
                    workflowId={workflowId}
                    getAccessToken={getAccessToken}
                />

                <TestCallDialog
                    open={isTestCallOpen}
                    onClose={() => setIsTestCallOpen(false)}
                    workflowId={workflowId}
                    getAccessToken={getAccessToken}
                />
            </div>
        </WorkflowProvider>
    );
}

// Memoize the component to prevent unnecessary re-renders when parent re-renders
export default React.memo(RenderWorkflow, (prevProps, nextProps) => {
    // Only re-render if these specific props change
    return (
        prevProps.workflowId === nextProps.workflowId &&
        prevProps.initialWorkflowName === nextProps.initialWorkflowName &&
        prevProps.user.id === nextProps.user.id &&
        prevProps.getAccessToken === nextProps.getAccessToken
        // Note: We intentionally don't compare initialFlow, initialTemplateContextVariables,
        // or initialWorkflowConfigurations because they're only used for initialization
    );
});
