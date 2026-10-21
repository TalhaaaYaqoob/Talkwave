"use client";

import {
    ArrowRight,
    Check,
    ChevronDown,
    ChevronUp,
    GitBranch,
    Lightbulb,
    Pencil,
    PlusCircle,
    Sparkles,
    X,
} from "lucide-react";

import { Spinner } from "@/components/ui/ai-loader";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { getBackendUrl } from "@/lib/apiClient";
import { useAuth } from "@/lib/auth";

type SuggestionType =
    | "rewrite_prompt"
    | "add_exit_condition"
    | "add_node"
    | "adjust_edge"
    | "spawn_workflow";

interface ExitCondition {
    id?: string;
    name: string;
    llm_description?: string;
}

interface NewNodePayload {
    type?: string;
    name: string;
    prompt: string;
    source_node_id: string;
    trigger_condition: string;
    exit_conditions?: ExitCondition[];
}

interface EdgeChange {
    from_source: string;
    to_target: string;
    new_condition?: string;
}

interface SpawnPayload {
    name: string;
    initial_prompt: string;
    call_type?: string;
    use_case?: string;
}

interface Suggestion {
    type: SuggestionType;
    pattern_id?: string;
    target_node_id?: string;
    description: string;
    before?: string;
    after?: string;
    confidence: number;
    reason?: string;
    new_node?: NewNodePayload;
    new_exit_condition?: ExitCondition;
    edge_change?: EdgeChange;
    spawn?: SpawnPayload;
    evidence_run_ids?: number[];
}

interface Improvement {
    id: number;
    status: string;
    suggestions: Suggestion[];
    analysis_summary: string;
    calls_analyzed: number;
    created_at: string;
    applied_indices?: number[];
    rejected_indices?: number[];
}

interface ImprovementsPanelProps {
    workflowId: number;
    open: boolean;
    onClose: () => void;
}

const TYPE_META: Record<SuggestionType, { label: string; icon: typeof Pencil }> = {
    rewrite_prompt: { label: "rewrite prompt", icon: Pencil },
    add_exit_condition: { label: "add exit condition", icon: PlusCircle },
    add_node: { label: "add new agent node", icon: GitBranch },
    adjust_edge: { label: "adjust routing", icon: ArrowRight },
    spawn_workflow: { label: "spawn new workflow", icon: Sparkles },
};

export const ImprovementsPanel = ({ workflowId, open, onClose }: ImprovementsPanelProps) => {
    const { getAccessToken } = useAuth();
    const router = useRouter();
    const [improvements, setImprovements] = useState<Improvement[]>([]);
    const [loading, setLoading] = useState(false);
    const [expandedSuggestion, setExpandedSuggestion] = useState<string | null>(null);
    const [busyKey, setBusyKey] = useState<string | null>(null);

    const fetchImprovements = useCallback(async () => {
        setLoading(true);
        try {
            const token = await getAccessToken();
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/workflow/${workflowId}/improvements`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                const data = await res.json();
                setImprovements(data);
            }
        } catch {
            // silent
        } finally {
            setLoading(false);
        }
    }, [workflowId, getAccessToken]);

    useEffect(() => {
        if (open) fetchImprovements();
    }, [open, fetchImprovements]);

    // Mutate one suggestion locally so the user sees instant feedback while we wait for refetch.
    const markLocally = useCallback(
        (improvementId: number, index: number, decision: "applied" | "rejected") => {
            setImprovements((prev) =>
                prev.map((imp) => {
                    if (imp.id !== improvementId) return imp;
                    const applied = new Set(imp.applied_indices || []);
                    const rejected = new Set(imp.rejected_indices || []);
                    if (decision === "applied") applied.add(index);
                    if (decision === "rejected") rejected.add(index);
                    return {
                        ...imp,
                        applied_indices: Array.from(applied).sort((a, b) => a - b),
                        rejected_indices: Array.from(rejected).sort((a, b) => a - b),
                    };
                })
            );
        },
        []
    );

    const handleSingle = async (
        improvementId: number,
        index: number,
        action: "apply" | "reject",
        suggestion: Suggestion,
    ) => {
        const key = `${improvementId}-${index}-${action}`;
        setBusyKey(key);
        try {
            const token = await getAccessToken();
            const baseUrl = getBackendUrl();
            const res = await fetch(
                `${baseUrl}/api/v1/workflow/${workflowId}/improvements/${improvementId}/suggestions/${index}/${action}`,
                { method: "POST", headers: { Authorization: `Bearer ${token}` } }
            );
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                toast.error(err?.detail || `Could not ${action} suggestion`);
                return;
            }

            const data = await res.json().catch(() => ({}));
            markLocally(improvementId, index, action === "apply" ? "applied" : "rejected");

            if (action === "reject") {
                toast.success("Suggestion dismissed");
                return;
            }

            if (suggestion.type === "spawn_workflow" && data?.new_workflow_id) {
                const newToken = data.new_workflow_public_id ?? data.new_workflow_id;
                toast.success(`New agent created`, {
                    description: `"${data.new_workflow_name}" is opening now.`,
                });
                router.push(`/workflow/${newToken}`);
                return;
            }

            if (suggestion.type === "add_node" && data?.new_node_name) {
                toast.success("New agent node added", {
                    description: `"${data.new_node_name}" is now part of your workflow.`,
                });
                // Reload so the canvas picks up the new node + edge from the workflow definition.
                setTimeout(() => window.location.reload(), 600);
                return;
            }

            const labels: Record<string, string> = {
                rewrite_prompt: "Prompt updated",
                add_exit_condition: "Exit condition added",
                adjust_edge: "Routing adjusted",
            };
            toast.success(labels[suggestion.type] || "Suggestion applied", {
                description: "Refreshing your workflow…",
            });
            setTimeout(() => window.location.reload(), 600);
        } catch {
            toast.error("Network error");
        } finally {
            setBusyKey(null);
        }
    };

    const handleBatch = async (improvementId: number, action: "apply" | "reject") => {
        const key = `${improvementId}-batch-${action}`;
        setBusyKey(key);
        try {
            const token = await getAccessToken();
            const baseUrl = getBackendUrl();
            const res = await fetch(
                `${baseUrl}/api/v1/workflow/${workflowId}/improvements/${improvementId}/${action}`,
                { method: "POST", headers: { Authorization: `Bearer ${token}` } }
            );
            if (res.ok) {
                if (action === "apply") {
                    const data = await res.json().catch(() => ({}));
                    const newWorkflowIds: number[] = data?.new_workflow_ids || [];
                    const count = data?.applied_count || 0;
                    if (newWorkflowIds.length > 0) {
                        toast.success("Improvements applied", {
                            description: `${count} suggestion${count === 1 ? "" : "s"} applied. ${newWorkflowIds.length} new agent${newWorkflowIds.length === 1 ? "" : "s"} created.`,
                        });
                    } else {
                        toast.success("Improvements applied", {
                            description: `${count} suggestion${count === 1 ? "" : "s"} applied to your workflow.`,
                        });
                    }
                    setTimeout(() => window.location.reload(), 700);
                } else {
                    toast.success("Suggestions dismissed");
                    setImprovements((prev) => prev.filter((i) => i.id !== improvementId));
                }
            } else {
                toast.error("Couldn't apply that. Try again.");
            }
        } catch {
            toast.error("Network error");
        } finally {
            setBusyKey(null);
        }
    };

    const getConfidenceBadge = (confidence: number) => {
        if (confidence >= 0.8)
            return <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">High</span>;
        if (confidence >= 0.5)
            return <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">Medium</span>;
        return <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">Low</span>;
    };

    const renderStructuralBody = (s: Suggestion) => {
        if (s.type === "rewrite_prompt") {
            return (
                <div className="space-y-2">
                    {s.before && (
                        <div>
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Current prompt</p>
                            <div className="text-xs p-2.5 rounded-lg bg-red-500/5 border border-red-500/10 text-muted-foreground line-clamp-4">
                                {s.before}
                            </div>
                        </div>
                    )}
                    {s.after && (
                        <div>
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">New prompt</p>
                            <div className="text-xs p-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/10 text-foreground/80 line-clamp-6">
                                {s.after}
                            </div>
                        </div>
                    )}
                </div>
            );
        }

        if (s.type === "add_exit_condition" && s.new_exit_condition) {
            const ec = s.new_exit_condition;
            return (
                <div className="space-y-2">
                    <div>
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                            New exit on <span className="font-mono">{s.target_node_id}</span>
                        </p>
                        <div className="text-xs p-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
                            <div className="font-mono text-foreground/90">{ec.name}</div>
                            {ec.llm_description && (
                                <p className="text-muted-foreground mt-1">{ec.llm_description}</p>
                            )}
                        </div>
                    </div>
                </div>
            );
        }

        if (s.type === "add_node" && s.new_node) {
            const n = s.new_node;
            return (
                <div className="space-y-2">
                    <div className="text-xs flex items-center gap-2 text-muted-foreground">
                        <span className="font-mono text-foreground/80">{n.source_node_id}</span>
                        <ArrowRight className="w-3 h-3" />
                        <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-mono text-[10px]">
                            when {n.trigger_condition}
                        </span>
                        <ArrowRight className="w-3 h-3" />
                        <span className="font-medium text-emerald-400">{n.name}</span>
                    </div>

                    <div>
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">New agent prompt</p>
                        <div className="text-xs p-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/10 text-foreground/80 line-clamp-6 whitespace-pre-wrap">
                            {n.prompt}
                        </div>
                    </div>

                    {n.exit_conditions && n.exit_conditions.length > 0 && (
                        <div>
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Exit conditions</p>
                            <div className="flex flex-wrap gap-1.5">
                                {n.exit_conditions.map((ec, i) => (
                                    <span key={i} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/[0.04] border border-white/10 text-foreground/70">
                                        {ec.name}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            );
        }

        if (s.type === "adjust_edge" && s.edge_change) {
            const c = s.edge_change;
            return (
                <div className="space-y-2">
                    <div className="text-xs flex items-center gap-2">
                        <span className="font-mono text-foreground/80">{c.from_source}</span>
                        <ArrowRight className="w-3 h-3 text-muted-foreground" />
                        <span className="font-mono text-foreground/80">{c.to_target}</span>
                    </div>
                    {c.new_condition && (
                        <div>
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">New condition</p>
                            <div className="text-xs p-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/10 font-mono">
                                {c.new_condition}
                            </div>
                        </div>
                    )}
                </div>
            );
        }

        if (s.type === "spawn_workflow" && s.spawn) {
            const spawn = s.spawn;
            return (
                <div className="space-y-2">
                    <div className="flex items-center gap-2 text-xs">
                        <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                        <span className="text-muted-foreground">New top-level agent</span>
                        <span className="font-medium text-foreground/90">{spawn.name}</span>
                        {spawn.call_type && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20 font-mono">
                                {spawn.call_type}
                            </span>
                        )}
                    </div>
                    {spawn.use_case && (
                        <p className="text-xs text-muted-foreground italic">{spawn.use_case}</p>
                    )}
                    <div>
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Agent prompt</p>
                        <div className="text-xs p-2.5 rounded-lg bg-purple-500/5 border border-purple-500/15 text-foreground/80 line-clamp-6 whitespace-pre-wrap">
                            {spawn.initial_prompt}
                        </div>
                    </div>
                    {s.evidence_run_ids && s.evidence_run_ids.length > 0 && (
                        <p className="text-[10px] text-muted-foreground">
                            Backed by {s.evidence_run_ids.length} caller{s.evidence_run_ids.length > 1 ? "s" : ""} who asked about this on past calls
                        </p>
                    )}
                </div>
            );
        }

        return null;
    };

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-[100]" onClick={onClose}>
            <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
            <div
                className="absolute top-0 right-0 h-full w-full max-w-lg bg-background border-l border-white/10 shadow-2xl animate-in slide-in-from-right duration-300 flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
                    <div className="flex items-center gap-2">
                        <Lightbulb className="w-5 h-5 text-amber-400" />
                        <h2 className="text-lg font-semibold">AI Improvements</h2>
                    </div>
                    <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10 text-muted-foreground hover:text-white transition-colors">
                        <X className="w-4 h-4" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-4">
                    {loading ? (
                        <div className="flex items-center justify-center py-12">
                            <Spinner size="lg" />
                        </div>
                    ) : improvements.length === 0 ? (
                        <div className="text-center py-12">
                            <Lightbulb className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
                            <p className="text-sm text-muted-foreground">No improvement suggestions yet.</p>
                            <p className="text-xs text-muted-foreground/60 mt-1">
                                Suggestions appear after your agent handles enough calls.
                            </p>
                        </div>
                    ) : (
                        improvements.map((imp) => {
                            const applied = new Set(imp.applied_indices || []);
                            const rejected = new Set(imp.rejected_indices || []);
                            const total = imp.suggestions.length;
                            const settledCount = applied.size + rejected.size;
                            const hasUndecided = settledCount < total;

                            return (
                                <div key={imp.id} className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
                                    {/* Analysis header */}
                                    <div className="px-4 py-3 bg-white/[0.03] border-b border-white/5">
                                        <p className="text-sm font-medium">{imp.analysis_summary}</p>
                                        <p className="text-xs text-muted-foreground mt-1">
                                            Based on {imp.calls_analyzed} recent calls &middot; {new Date(imp.created_at).toLocaleDateString()}
                                            {total > 0 && (
                                                <>
                                                    {" "}&middot; {applied.size} of {total} applied
                                                    {rejected.size > 0 && `, ${rejected.size} dismissed`}
                                                </>
                                            )}
                                        </p>
                                    </div>

                                    {/* Suggestions */}
                                    <div className="divide-y divide-white/5">
                                        {imp.suggestions.map((s, idx) => {
                                            const key = `${imp.id}-${idx}`;
                                            const isExpanded = expandedSuggestion === key;
                                            const isApplied = applied.has(idx);
                                            const isRejected = rejected.has(idx);
                                            const meta = TYPE_META[s.type as SuggestionType] || TYPE_META.rewrite_prompt;
                                            const Icon = meta.icon;

                                            return (
                                                <div
                                                    key={key}
                                                    className={`px-4 py-3 transition-colors ${isApplied ? "opacity-60" : ""} ${isRejected ? "opacity-40" : ""}`}
                                                >
                                                    <button
                                                        className="w-full text-left flex items-start justify-between gap-3"
                                                        onClick={() => setExpandedSuggestion(isExpanded ? null : key)}
                                                    >
                                                        <div className="flex-1 min-w-0">
                                                            <div className="flex items-center gap-2 flex-wrap">
                                                                <span className="text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 inline-flex items-center gap-1">
                                                                    <Icon className="w-3 h-3" />
                                                                    {meta.label}
                                                                </span>
                                                                {getConfidenceBadge(s.confidence)}
                                                                {s.target_node_id && (
                                                                    <span className="text-[10px] text-muted-foreground font-mono">{s.target_node_id}</span>
                                                                )}
                                                                {isApplied && (
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1">
                                                                        <Check className="w-3 h-3" /> Applied
                                                                    </span>
                                                                )}
                                                                {isRejected && (
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border inline-flex items-center gap-1">
                                                                        <X className="w-3 h-3" /> Dismissed
                                                                    </span>
                                                                )}
                                                            </div>
                                                            <p className="text-sm mt-1.5">{s.description}</p>
                                                            {s.reason && <p className="text-xs text-muted-foreground mt-1">{s.reason}</p>}
                                                        </div>
                                                        {isExpanded ? <ChevronUp className="w-4 h-4 text-muted-foreground flex-shrink-0 mt-1" /> : <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0 mt-1" />}
                                                    </button>

                                                    {isExpanded && (
                                                        <div className="mt-3 space-y-3">
                                                            {renderStructuralBody(s)}

                                                            {!isApplied && !isRejected && (
                                                                <div className="flex items-center gap-2 pt-1">
                                                                    <Button
                                                                        size="sm"
                                                                        onClick={() => handleSingle(imp.id, idx, "apply", s)}
                                                                        disabled={busyKey?.startsWith(`${imp.id}-${idx}`)}
                                                                        className="flex-1"
                                                                    >
                                                                        {busyKey === `${imp.id}-${idx}-apply` ? (
                                                                            <Spinner size="sm" className="mr-1.5" />
                                                                        ) : s.type === "spawn_workflow" ? (
                                                                            <Sparkles className="w-3.5 h-3.5 mr-1.5" />
                                                                        ) : (
                                                                            <Check className="w-3.5 h-3.5 mr-1.5" />
                                                                        )}
                                                                        {s.type === "spawn_workflow" ? "Create new agent" : "Accept"}
                                                                    </Button>
                                                                    <Button
                                                                        size="sm"
                                                                        variant="ghost"
                                                                        onClick={() => handleSingle(imp.id, idx, "reject", s)}
                                                                        disabled={busyKey?.startsWith(`${imp.id}-${idx}`)}
                                                                        className="text-muted-foreground"
                                                                    >
                                                                        {busyKey === `${imp.id}-${idx}-reject` ? (
                                                                            <Spinner size="sm" className="mr-1.5" />
                                                                        ) : (
                                                                            <X className="w-3.5 h-3.5 mr-1.5" />
                                                                        )}
                                                                        Dismiss
                                                                    </Button>
                                                                </div>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>

                                    {/* Batch actions footer — only when there are still undecided suggestions */}
                                    {imp.status === "pending" && hasUndecided && (
                                        <div className="flex items-center gap-2 px-4 py-3 border-t border-white/5 bg-white/[0.02]">
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                onClick={() => handleBatch(imp.id, "apply")}
                                                disabled={busyKey?.startsWith(`${imp.id}-batch`)}
                                                className="flex-1"
                                            >
                                                {busyKey === `${imp.id}-batch-apply` ? (
                                                    <Spinner size="sm" className="mr-1.5" />
                                                ) : (
                                                    <Check className="w-3.5 h-3.5 mr-1.5" />
                                                )}
                                                Accept all remaining
                                            </Button>
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                onClick={() => handleBatch(imp.id, "reject")}
                                                disabled={busyKey?.startsWith(`${imp.id}-batch`)}
                                                className="text-muted-foreground"
                                            >
                                                {busyKey === `${imp.id}-batch-reject` ? (
                                                    <Spinner size="sm" className="mr-1.5" />
                                                ) : (
                                                    <X className="w-3.5 h-3.5 mr-1.5" />
                                                )}
                                                Dismiss all
                                            </Button>
                                        </div>
                                    )}
                                </div>
                            );
                        })
                    )}
                </div>
            </div>
        </div>
    );
};
