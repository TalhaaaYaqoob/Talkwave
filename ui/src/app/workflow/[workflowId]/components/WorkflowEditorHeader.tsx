"use client";

import { ReactFlowInstance } from "@xyflow/react";
import { AlertCircle, ArrowLeft, ChevronDown, Copy, Download, Globe, History, Lightbulb, Link2, LoaderCircle, MoreVertical, Phone, PhoneIncoming } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { WorkflowError } from "@/client/types.gen";
import { getBackendUrl } from "@/lib/apiClient";
import { useAuth } from "@/lib/auth";
import { FlowEdge, FlowNode } from "@/components/flow/types";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover";
import { WORKFLOW_RUN_MODES } from "@/constants/workflowRunModes";
import { useWorkflowStore } from "../stores/workflowStore";
import { ImprovementsPanel } from "./ImprovementsPanel";

// Component to render each validation error with click-to-focus functionality
const ValidationErrorItem = ({ 
    error, 
    rfInstance 
}: { 
    error: WorkflowError; 
    rfInstance: React.RefObject<ReactFlowInstance<FlowNode, FlowEdge> | null>;
}) => {
    const nodes = useWorkflowStore((state) => state.nodes);
    
    const handleClick = () => {
        if (!rfInstance.current || !error.id) return;
        
        // Find the node
        const node = nodes.find(n => n.id === error.id);
        if (!node) return;
        
        // Get node position and dimensions
        const nodeWidth = node.measured?.width || 350;
        const nodeHeight = node.measured?.height || 150;
        
        // Calculate center of the node
        const x = node.position.x + nodeWidth / 2;
        const y = node.position.y + nodeHeight / 2;
        
        // Pan and zoom to the node
        rfInstance.current.setCenter(x, y, { zoom: 1, duration: 500 });
        
        // Select the node to highlight it
        rfInstance.current.setNodes((nds) =>
            nds.map((n) => ({
                ...n,
                selected: n.id === error.id,
            }))
        );
    };
    
    // Get a friendly name for the node
    const node = nodes.find(n => n.id === error.id);
    const nodeData = node?.data as Record<string, unknown> | undefined;
    const nodeName = (nodeData?.label as string) || (nodeData?.name as string) || error.id || 'Unknown';
    
    return (
        <button
            onClick={handleClick}
            className="w-full text-left p-2 rounded-md hover:bg-red-500/10 transition-colors group"
        >
            <div className="flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                    <p className="text-sm text-red-300 font-medium truncate">
                        {nodeName}
                    </p>
                    <p className="text-xs text-red-400/70 mt-0.5 line-clamp-2">
                        {error.message}
                    </p>
                    {error.field && (
                        <p className="text-xs text-red-400/50 mt-1">
                            Field: {error.field}
                        </p>
                    )}
                </div>
                <span className="text-xs text-red-400/50 group-hover:text-red-400 transition-colors">
                    Click to view →
                </span>
            </div>
        </button>
    );
};

interface WorkflowEditorHeaderProps {
    workflowName: string;
    isDirty: boolean;
    workflowValidationErrors: WorkflowError[];
    rfInstance: React.RefObject<ReactFlowInstance<FlowNode, FlowEdge> | null>;
    onRun: (mode: string) => Promise<void>;
    isStartingRun?: boolean;
    workflowId: number;
    publicId?: string;
    saveWorkflow: (updateWorkflowDefinition?: boolean) => Promise<void>;
    user: { id: string; email?: string };
    getAccessToken: () => Promise<string>;
    onPhoneCallClick: () => void;
    onTestCallClick: () => void;
    callType?: 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING';
}

export const WorkflowEditorHeader = ({
    workflowName,
    isDirty,
    workflowValidationErrors,
    rfInstance,
    saveWorkflow,
    onRun,
    isStartingRun = false,
    onPhoneCallClick,
    onTestCallClick,
    workflowId,
    publicId,
    callType,
}: WorkflowEditorHeaderProps) => {
    const router = useRouter();
    const { getAccessToken } = useAuth();
    const [savingWorkflow, setSavingWorkflow] = useState(false);
    const [isInboundDialogOpen, setIsInboundDialogOpen] = useState(false);

    // Self-improving state
    const workflowConfigurations = useWorkflowStore((s) => s.workflowConfigurations);
    const setWorkflowConfigurations = useWorkflowStore((s) => s.setWorkflowConfigurations);
    const autoImproveEnabled = workflowConfigurations?.auto_improve_enabled === true;
    const [pendingImprovementCount, setPendingImprovementCount] = useState(0);
    const [improvementsPanelOpen, setImprovementsPanelOpen] = useState(false);
    const [togglingImprove, setTogglingImprove] = useState(false);

    const fetchImprovementCount = useCallback(async () => {
        if (!autoImproveEnabled) { setPendingImprovementCount(0); return; }
        try {
            const token = await getAccessToken();
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/workflow/${workflowId}/improvements/count`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                const data = await res.json();
                setPendingImprovementCount(data.pending_count || 0);
            }
        } catch { /* silent */ }
    }, [workflowId, autoImproveEnabled, getAccessToken]);

    useEffect(() => { fetchImprovementCount(); }, [fetchImprovementCount]);

    const handleToggleSelfImprove = async (enabled: boolean) => {
        setTogglingImprove(true);
        const updated = { ...workflowConfigurations, auto_improve_enabled: enabled } as typeof workflowConfigurations;
        if (updated) setWorkflowConfigurations(updated);

        try {
            const token = await getAccessToken();
            const baseUrl = getBackendUrl();
            await fetch(`${baseUrl}/api/v1/workflow/${workflowId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({
                    name: workflowName,
                    workflow_configurations: { auto_improve_enabled: enabled },
                }),
            });
            toast.success(enabled ? "Self-improving enabled" : "Self-improving disabled");
            if (!enabled) setPendingImprovementCount(0);
        } catch {
            toast.error("Failed to update setting");
            const reverted = { ...workflowConfigurations, auto_improve_enabled: !enabled } as typeof workflowConfigurations;
            if (reverted) setWorkflowConfigurations(reverted);
        } finally {
            setTogglingImprove(false);
        }
    };

    const hasValidationErrors = workflowValidationErrors.length > 0;
    const isCallDisabled = isDirty || hasValidationErrors;
    
    // Get the inbound webhook URL — trim to avoid trailing spaces from env vars.
    // Use the opaque public_id token (not the enumerable integer id) in this
    // externally-configured URL; fall back to the id only if the token is
    // unavailable (e.g. very old cached workflow payloads).
    const backendUrl = getBackendUrl().trim();
    const inboundWebhookUrl = `${backendUrl}/api/v1/telephony/inbound/${publicId ?? workflowId}`;
    
    const copyWebhookUrl = () => {
        navigator.clipboard.writeText(inboundWebhookUrl);
        toast.success("Webhook URL copied to clipboard!");
    };

    const handleSave = async () => {
        setSavingWorkflow(true);
        await saveWorkflow();
        setSavingWorkflow(false);
    };

    const handleBack = () => {
        router.push("/workflow");
    };

    const handleShareLink = async () => {
        try {
            const accessToken = await getAccessToken();
            const res = await fetch(`${getBackendUrl()}/api/v1/workflow/${workflowId}/share`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${accessToken}`,
                },
                body: JSON.stringify({ expires_days: 7 }),
            });

            if (!res.ok) throw new Error('Failed to generate share link');
            const data = await res.json();
            await navigator.clipboard.writeText(data.share_url);
            toast.success('Share link copied to clipboard!', {
                description: `Expires in 7 days. ${data.share_url}`,
            });
        } catch (err: any) {
            toast.error('Failed to generate share link', { description: err.message });
        }
    };

    const handleDownloadWorkflow = () => {
        if (!rfInstance.current) return;

        const workflowDefinition = rfInstance.current.toObject();
        const exportData = {
            name: workflowName,
            workflow_definition: workflowDefinition,
        };

        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${workflowName}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    };

    return (
        <>
        <div className="flex items-center justify-between w-full h-16 px-6 bg-background/95 border-b border-white/5 z-50">
            {/* Left section: Back button + Workflow name */}
            <div className="flex items-center gap-4">
                <button
                    onClick={handleBack}
                    className="flex items-center justify-center w-9 h-9 rounded-xl hover:bg-white/5 border border-transparent hover:border-white/5 transition-all duration-200 group"
                >
                    <ArrowLeft className="w-5 h-5 text-muted-foreground group-hover:text-foreground" />
                </button>

                <div className="flex flex-col">
                    <h1 className="text-lg font-semibold text-foreground tracking-tight">
                        {workflowName}
                    </h1>
                </div>
            </div>

            {/* Right section: Unsaved indicator + Call button + Save button */}
            <div className="flex items-center gap-3">
                {/* Validation errors indicator - clickable to show errors and focus on nodes */}
                {hasValidationErrors && (
                    <Popover>
                        <PopoverTrigger asChild>
                            <button className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-red-500/20 bg-red-500/5 backdrop-blur-sm animate-in fade-in duration-300 hover:bg-red-500/10 hover:border-red-500/30 transition-colors cursor-pointer">
                                <div className="w-1.5 h-1.5 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]" />
                                <span className="text-xs font-medium text-red-500/90">
                                    {workflowValidationErrors.length} validation {workflowValidationErrors.length === 1 ? 'error' : 'errors'}
                                </span>
                            </button>
                        </PopoverTrigger>
                        <PopoverContent 
                            className="w-80 p-2 bg-[#0A0A0A] border-red-500/20" 
                            align="end"
                        >
                            <div className="space-y-1">
                                <h4 className="text-sm font-medium text-red-400 px-2 py-1 flex items-center gap-2">
                                    <AlertCircle className="w-4 h-4" />
                                    Validation Errors
                                </h4>
                                <div className="max-h-60 overflow-y-auto space-y-1">
                                    {workflowValidationErrors.map((error, index) => (
                                        <ValidationErrorItem 
                                            key={`${error.id}-${index}`} 
                                            error={error} 
                                            rfInstance={rfInstance}
                                        />
                                    ))}
                                </div>
                            </div>
                        </PopoverContent>
                    </Popover>
                )}

                {/* Unsaved changes indicator */}
                {isDirty && !hasValidationErrors && (
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-yellow-500/20 bg-yellow-500/5 backdrop-blur-sm animate-in fade-in duration-300">
                        <div className="w-1.5 h-1.5 rounded-full bg-yellow-500 shadow-[0_0_8px_rgba(234,179,8,0.6)]" />
                        <span className="text-xs font-medium text-yellow-500/90">Unsaved changes</span>
                    </div>
                )}

                {/* Self-Improving Agent toggle + badge */}
                <div className="flex items-center gap-2">
                    <Popover>
                        <PopoverTrigger asChild>
                            <button className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full border text-xs font-medium transition-colors ${autoImproveEnabled ? 'border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/15' : 'border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10'}`}>
                                <Lightbulb className="w-3.5 h-3.5" />
                                Self-Improving
                            </button>
                        </PopoverTrigger>
                        <PopoverContent className="w-72 p-4 bg-[#0A0A0A] border-white/10" align="end">
                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-sm font-medium">Self-Improving Agent</p>
                                        <p className="text-xs text-muted-foreground mt-0.5">
                                            AI analyzes calls and suggests workflow improvements
                                        </p>
                                    </div>
                                    <Switch
                                        checked={autoImproveEnabled}
                                        onCheckedChange={handleToggleSelfImprove}
                                        disabled={togglingImprove}
                                    />
                                </div>
                                {autoImproveEnabled && (
                                    <p className="text-[11px] text-muted-foreground/70 border-t border-white/5 pt-2">
                                        After every {workflowConfigurations?.auto_improve_interval || 10} calls, AI reviews transcripts and suggests prompt rewrites, new nodes, and routing fixes. Configure thresholds in Settings.
                                    </p>
                                )}
                            </div>
                        </PopoverContent>
                    </Popover>
                    {autoImproveEnabled && pendingImprovementCount > 0 && (
                        <button
                            onClick={() => setImprovementsPanelOpen(true)}
                            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs font-medium hover:bg-emerald-500/15 transition-colors animate-in fade-in duration-300"
                        >
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]" />
                            {pendingImprovementCount} suggestion{pendingImprovementCount !== 1 ? 's' : ''}
                        </button>
                    )}
                </div>

                <div className="h-6 w-px bg-white/10 mx-2" />

                {/* Call button with dropdown - different options based on call type */}
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            className="flex items-center gap-2 h-9 bg-white/5 border-white/10 hover:bg-white/10 hover:text-white transition-all duration-200"
                            disabled={isCallDisabled || isStartingRun}
                        >
                            {isStartingRun ? (
                                <LoaderCircle className="w-4 h-4 animate-spin" />
                            ) : callType === 'WEBSITE' ? (
                                <Globe className="w-4 h-4" />
                            ) : callType === 'INBOUND' ? (
                                <PhoneIncoming className="w-4 h-4" />
                            ) : (
                                <Phone className="w-4 h-4" />
                            )}
                            {isStartingRun ? 'Starting...' : callType === 'WEBSITE' ? 'Test Widget' : callType === 'INBOUND' ? 'Receive Calls' : 'Call'}
                            {!isStartingRun && <ChevronDown className="w-3 h-3 opacity-50 ml-1" />}
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="bg-[#0A0A0A] border-white/10 p-1 min-w-[180px]">
                        {/* Web Call - opens test call dialog inline */}
                        <DropdownMenuItem
                            onClick={onTestCallClick}
                            disabled={isStartingRun}
                            className="text-muted-foreground hover:text-white focus:bg-white/10 cursor-pointer rounded-md py-2"
                        >
                            <Phone className="w-4 h-4 mr-2" />
                            Test Call
                        </DropdownMenuItem>
                        
                        {/* INBOUND: Show webhook configuration option */}
                        {callType === 'INBOUND' && (
                            <DropdownMenuItem
                                onClick={() => setIsInboundDialogOpen(true)}
                                className="text-muted-foreground hover:text-white focus:bg-white/10 cursor-pointer rounded-md py-2"
                            >
                                <PhoneIncoming className="w-4 h-4 mr-2" />
                                Configure Inbound
                            </DropdownMenuItem>
                        )}
                        
                        {/* OUTBOUND: Show phone call option */}
                        {callType === 'OUTBOUND' && (
                            <DropdownMenuItem
                                onClick={() => {
                                    setTimeout(onPhoneCallClick, 0);
                                }}
                                className="text-muted-foreground hover:text-white focus:bg-white/10 cursor-pointer rounded-md py-2"
                            >
                                <Phone className="w-4 h-4 mr-2" />
                                Phone Call
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>

                {/* Save button */}
                <Button
                    onClick={handleSave}
                    disabled={!isDirty || savingWorkflow}
                    className="bg-primary hover:bg-primary/90 text-primary-foreground h-9 px-5 font-medium shadow-[0_0_20px_rgba(52,245,194,0.25)] transition-all duration-200"
                >
                    {savingWorkflow ? (
                        <>
                            <LoaderCircle className="w-4 h-4 mr-2 animate-spin" />
                            Saving...
                        </>
                    ) : (
                        "Save Changes"
                    )}
                </Button>

                {/* More options dropdown */}
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-white/5 rounded-lg"
                        >
                            <MoreVertical className="w-5 h-5" />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="bg-[#0A0A0A] border-white/10 p-1 min-w-[200px]">
                        <DropdownMenuItem
                            onClick={() => router.push(`/workflow/${publicId ?? workflowId}/runs`)}
                            className="text-muted-foreground hover:text-white focus:bg-white/10 cursor-pointer rounded-md py-2"
                        >
                            <History className="w-4 h-4 mr-2" />
                            View Runs
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={handleDownloadWorkflow}
                            className="text-muted-foreground hover:text-white focus:bg-white/10 cursor-pointer rounded-md py-2"
                        >
                            <Download className="w-4 h-4 mr-2" />
                            Download Workflow
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={handleShareLink}
                            className="text-muted-foreground hover:text-white focus:bg-white/10 cursor-pointer rounded-md py-2"
                        >
                            <Link2 className="w-4 h-4 mr-2" />
                            Share Test Link
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
            
        </div>
            
            {/* Inbound Configuration Panel — uses a fixed overlay instead of Radix Dialog 
                to avoid the pointer-events: none bug that blocks the entire UI */}
            {isInboundDialogOpen && (
                <div className="fixed inset-0 z-[100]" onClick={() => setIsInboundDialogOpen(false)}>
                    {/* Backdrop */}
                    <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
                    {/* Panel */}
                    <div 
                        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-xl bg-background border border-white/10 rounded-xl shadow-2xl p-6 animate-in fade-in zoom-in-95 duration-200"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <h2 className="text-lg font-semibold flex items-center gap-2">
                                    <PhoneIncoming className="w-5 h-5" />
                                    Configure Inbound Calls
                                </h2>
                                <p className="text-sm text-muted-foreground mt-1">
                                    Set up your Twilio phone number to receive calls from users
                                </p>
                            </div>
                            <button 
                                onClick={() => setIsInboundDialogOpen(false)}
                                className="p-1.5 rounded-lg hover:bg-white/10 text-muted-foreground hover:text-white transition-colors"
                            >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
                            </button>
                        </div>
                    
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <h4 className="font-medium text-sm">Step 1: Copy the Webhook URL</h4>
                                <p className="text-sm text-muted-foreground">
                                    This URL will receive incoming calls and connect them to your AI agent.
                                </p>
                                <div className="flex items-center gap-2 p-3 bg-muted/50 rounded-lg border">
                                    <code className="flex-1 text-xs break-all font-mono">
                                        {inboundWebhookUrl}
                                    </code>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={copyWebhookUrl}
                                        className="shrink-0"
                                    >
                                        <Copy className="w-4 h-4" />
                                    </Button>
                                </div>
                            </div>
                            
                            <div className="space-y-2">
                                <h4 className="font-medium text-sm">Step 2: Configure in Twilio Console</h4>
                                <ol className="text-sm text-muted-foreground space-y-2 list-decimal list-inside">
                                    <li>Go to <a href="https://console.twilio.com/us1/develop/phone-numbers/manage/incoming" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Twilio Console → Phone Numbers</a></li>
                                    <li>Click on your phone number</li>
                                    <li>Under &quot;Voice Configuration&quot; → &quot;A call comes in&quot;</li>
                                    <li>Select &quot;Webhook&quot; and paste the URL above</li>
                                    <li>Set HTTP method to &quot;POST&quot;</li>
                                    <li>Click &quot;Save configuration&quot;</li>
                                </ol>
                            </div>
                            
                            <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                                <p className="text-sm text-green-400">
                                    <strong>✓ Ready to receive calls!</strong> Once configured, anyone who calls your Twilio number will be connected to this AI agent.
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Self-Improving Improvements Panel */}
            <ImprovementsPanel
                workflowId={workflowId}
                open={improvementsPanelOpen}
                onClose={() => {
                    setImprovementsPanelOpen(false);
                    fetchImprovementCount();
                }}
            />
        </>
    );
};
