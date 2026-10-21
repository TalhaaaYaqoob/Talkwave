'use client';

import { Archive, Eye, Globe, PhoneIncoming, PhoneOutgoing, RotateCcw, Trash2, Video } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useRouter } from 'next/navigation';
import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import { updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut } from '@/client/sdk.gen';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from '@/components/ui/button';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { useUserConfig } from '@/context/UserConfigContext';
import { getBackendUrl } from '@/lib/apiClient';

interface Workflow {
    id: number;
    // Opaque token used in the URL instead of the enumerable integer id.
    public_id?: string;
    name: string;
    status: string;
    created_at: string;
    total_runs?: number | null;
    workflow_configurations?: {
        _generating?: boolean;
        _error?: string;
        [key: string]: unknown;
    } | null;
}

interface WorkflowTableProps {
    workflows: Workflow[];
    showArchived: boolean;
    onRefresh?: () => void;
}

const CALL_TYPE_STYLES: Record<string, { bg: string; icon: React.ReactNode; label: string }> = {
    WEBSITE:  { bg: 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20', icon: <Globe className="w-3 h-3" />, label: 'Website' },
    OUTBOUND: { bg: 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20', icon: <PhoneOutgoing className="w-3 h-3" />, label: 'Outbound' },
    MEETING:  { bg: 'bg-purple-500/10 text-purple-500 border border-purple-500/20', icon: <Video className="w-3 h-3" />, label: 'Meeting' },
    INBOUND:  { bg: 'bg-amber-500/10 text-amber-500 border border-amber-500/20', icon: <PhoneIncoming className="w-3 h-3" />, label: 'Inbound' },
};

export function WorkflowTable({ workflows, showArchived, onRefresh }: WorkflowTableProps) {
    const router = useRouter();
    const { accessToken } = useUserConfig();
    const [isPending, startTransition] = useTransition();
    const [loadingWorkflowId, setLoadingWorkflowId] = useState<number | null>(null);
    const [deletingWorkflowId, setDeletingWorkflowId] = useState<number | null>(null);
    const [navigatingWorkflowId, setNavigatingWorkflowId] = useState<number | null>(null);
    const [workflowToDelete, setWorkflowToDelete] = useState<Workflow | null>(null);

    const handleView = (workflow: Workflow) => {
        // Mark the row as navigating immediately so the user gets instant
        // feedback, and wrap the push in a transition so React keeps the UI
        // responsive while the destination route loads (loading.tsx shows the
        // route-level loader as well). The URL uses the opaque public_id token.
        setNavigatingWorkflowId(workflow.id);
        startTransition(() => {
            router.push(`/workflow/${workflow.public_id ?? workflow.id}`);
        });
    };

    // Warm the route + its data on hover so the click feels instant.
    const handlePrefetchView = (workflow: Workflow) => {
        router.prefetch(`/workflow/${workflow.public_id ?? workflow.id}`);
    };

    const handleArchiveToggle = async (id: number, currentStatus: string) => {
        if (!accessToken) {
            toast.error('Authentication required');
            return;
        }

        const newStatus = currentStatus === 'active' ? 'archived' : 'active';
        const action = currentStatus === 'active' ? 'Archive' : 'Restore';

        setLoadingWorkflowId(id);

        try {
            const response = await updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut({
                path: { workflow_id: id },
                body: { status: newStatus },
                headers: { 'Authorization': `Bearer ${accessToken}` },
            });

            if (response.data) {
                toast.success(`Workflow ${action.toLowerCase()}d successfully`);
                if (onRefresh) {
                    onRefresh();
                } else {
                    startTransition(() => { router.refresh(); });
                }
            }
        } catch (error) {
            console.error(`Error ${action.toLowerCase()}ing workflow:`, error);
            toast.error(`Failed to ${action.toLowerCase()} workflow`);
        } finally {
            setLoadingWorkflowId(null);
        }
    };

    const handleDelete = async (workflow: Workflow) => {
        if (!accessToken) {
            toast.error('Authentication required');
            return;
        }

        setDeletingWorkflowId(workflow.id);

        try {
            const response = await fetch(`${getBackendUrl()}/api/v1/workflow/${workflow.id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${accessToken}` },
            });

            if (response.ok) {
                toast.success('Workflow deleted successfully');
                setWorkflowToDelete(null);
                if (onRefresh) {
                    onRefresh();
                } else {
                    startTransition(() => { router.refresh(); });
                }
            } else {
                const error = await response.json();
                toast.error(error.detail || 'Failed to delete workflow');
            }
        } catch (error) {
            console.error('Error deleting workflow:', error);
            toast.error('Failed to delete workflow');
        } finally {
            setDeletingWorkflowId(null);
        }
    };

    const isGenerating = (workflow: Workflow) => !!workflow.workflow_configurations?._generating;
    const isError = (workflow: Workflow) => !!workflow.workflow_configurations?._error;

    const getCallType = (workflow: Workflow) => {
        const callType = (workflow.workflow_configurations as Record<string, unknown>)?.call_type as string | undefined;
        return CALL_TYPE_STYLES[callType || 'INBOUND'] || CALL_TYPE_STYLES.INBOUND;
    };

    return (
        <>
            {/* ─── Mobile: Card layout ─── */}
            <div className="md:hidden space-y-3">
                {workflows.map((workflow) => {
                    const generating = isGenerating(workflow);
                    const errored = isError(workflow);
                    const typeStyle = getCallType(workflow);

                    return (
                        <div
                            key={workflow.id}
                            className={`rounded-xl border bg-card p-4 transition-all ${
                                generating
                                    ? 'border-primary/30'
                                    : errored
                                        ? 'border-destructive/30'
                                        : showArchived
                                            ? 'opacity-60'
                                            : ''
                            }`}
                        >

                            <div className="flex items-start justify-between gap-3 mb-3">
                                <div className="min-w-0 flex-1">
                                    <h3 className="font-semibold text-sm truncate">{workflow.name}</h3>
                                    <p className="text-xs text-muted-foreground mt-0.5">
                                        {new Date(workflow.created_at).toLocaleDateString('en-US', {
                                            year: 'numeric', month: 'short', day: 'numeric',
                                        })}
                                    </p>
                                </div>
                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full shrink-0 ${typeStyle.bg}`}>
                                    {typeStyle.icon}
                                    {typeStyle.label}
                                </span>
                            </div>

                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    {generating ? (
                                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 text-[11px] font-medium rounded-full bg-primary/10 text-primary border border-primary/20">
                                            <Spinner size="sm" />
                                            Building...
                                        </span>
                                    ) : errored ? (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium rounded-full bg-destructive/10 text-destructive border border-destructive/20">
                                            Failed
                                        </span>
                                    ) : (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium rounded-full bg-green-500/10 text-green-500 border border-green-500/20">
                                            <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                                            Ready
                                        </span>
                                    )}
                                    {!generating && (
                                        <span className="text-xs text-muted-foreground">
                                            {workflow.total_runs || 0} runs
                                        </span>
                                    )}
                                </div>

                                {!generating && (
                                    <div className="flex gap-1.5">
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            className="h-8 px-2.5 text-xs"
                                            onClick={() => handleView(workflow)}
                                            onMouseEnter={() => handlePrefetchView(workflow)}
                                            disabled={navigatingWorkflowId === workflow.id}
                                        >
                                            {navigatingWorkflowId === workflow.id ? (
                                                <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                            ) : (
                                                <Eye className="w-3.5 h-3.5" />
                                            )}
                                        </Button>
                                        <Button
                                            variant={showArchived ? "default" : "outline"}
                                            size="sm"
                                            className="h-8 px-2.5 text-xs"
                                            onClick={() => handleArchiveToggle(workflow.id, workflow.status)}
                                            disabled={loadingWorkflowId === workflow.id || isPending}
                                        >
                                            {loadingWorkflowId === workflow.id ? (
                                                <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                            ) : showArchived ? (
                                                <RotateCcw className="w-3.5 h-3.5" />
                                            ) : (
                                                <Archive className="w-3.5 h-3.5" />
                                            )}
                                        </Button>
                                        <Button
                                            variant="destructive"
                                            size="sm"
                                            className="h-8 px-2.5 text-xs"
                                            onClick={() => setWorkflowToDelete(workflow)}
                                            disabled={deletingWorkflowId === workflow.id || isPending}
                                        >
                                            <Trash2 className="w-3.5 h-3.5" />
                                        </Button>
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* ─── Desktop: Table layout ─── */}
            <div className="hidden md:block bg-card border rounded-lg shadow-sm overflow-x-auto">
                <Table className="w-full table-fixed">
                    <colgroup>
                        <col className="w-[30%]" />
                        <col className="w-[12%]" />
                        <col className="w-[12%]" />
                        <col className="w-[14%]" />
                        <col className="w-[10%]" />
                        <col className="w-[22%]" />
                    </colgroup>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="font-semibold">Agent Name</TableHead>
                            <TableHead className="font-semibold">Type</TableHead>
                            <TableHead className="font-semibold">Status</TableHead>
                            <TableHead className="font-semibold">Created At</TableHead>
                            <TableHead className="font-semibold text-center">Total Runs</TableHead>
                            <TableHead className="font-semibold text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {workflows.map((workflow) => {
                            const generating = isGenerating(workflow);
                            const errored = isError(workflow);
                            const typeStyle = getCallType(workflow);

                            return (
                                <TableRow
                                    key={workflow.id}
                                    className={`group border-b border-white/5 transition-all duration-200 ${
                                        generating
                                            ? 'bg-primary/[0.03]'
                                            : errored
                                                ? 'bg-destructive/5'
                                                : showArchived
                                                    ? 'opacity-60 hover:bg-white/5'
                                                    : 'hover:bg-white/5'
                                    }`}
                                >
                                    <TableCell className="font-medium truncate max-w-0">
                                        {workflow.name}
                                    </TableCell>
                                    <TableCell>
                                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full ${typeStyle.bg}`}>
                                            {typeStyle.icon}
                                            {typeStyle.label}
                                        </span>
                                    </TableCell>
                                    <TableCell>
                                        {generating ? (
                                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-primary/10 text-primary border border-primary/20">
                                                <Spinner size="sm" />
                                                Building...
                                            </span>
                                        ) : errored ? (
                                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-destructive/10 text-destructive border border-destructive/20">
                                                Failed
                                            </span>
                                        ) : (
                                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-green-500/10 text-green-500 border border-green-500/20">
                                                <span className="h-1.5 w-1.5 rounded-full bg-green-500"></span>
                                                Ready
                                            </span>
                                        )}
                                    </TableCell>
                                    <TableCell className="whitespace-nowrap text-sm">
                                        {new Date(workflow.created_at).toLocaleDateString('en-US', {
                                            month: 'short',
                                            day: 'numeric',
                                            year: 'numeric',
                                        })}
                                    </TableCell>
                                    <TableCell className="text-center">
                                        <span className="inline-flex items-center justify-center min-w-[2rem] px-2 py-1 text-sm font-semibold bg-muted rounded-full">
                                            {generating ? '—' : (workflow.total_runs || 0)}
                                        </span>
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {generating ? (
                                            <span className="text-xs text-muted-foreground italic">
                                                Building agent...
                                            </span>
                                        ) : (
                                            <div className="flex justify-end gap-2">
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => handleView(workflow)}
                                                    onMouseEnter={() => handlePrefetchView(workflow)}
                                                    disabled={navigatingWorkflowId === workflow.id}
                                                    className="flex items-center gap-2"
                                                >
                                                    {navigatingWorkflowId === workflow.id ? (
                                                        <>
                                                            <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                                            Opening...
                                                        </>
                                                    ) : (
                                                        <>
                                                            <Eye size={16} />
                                                            View
                                                        </>
                                                    )}
                                                </Button>
                                                <Button
                                                    variant={showArchived ? "default" : "outline"}
                                                    size="sm"
                                                    onClick={() => handleArchiveToggle(workflow.id, workflow.status)}
                                                    disabled={loadingWorkflowId === workflow.id || isPending}
                                                    className="flex items-center gap-2"
                                                >
                                                    {loadingWorkflowId === workflow.id ? (
                                                        <>
                                                            <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                                            {showArchived ? 'Restoring...' : 'Archiving...'}
                                                        </>
                                                    ) : showArchived ? (
                                                        <><RotateCcw size={16} />Restore</>
                                                    ) : (
                                                        <><Archive size={16} />Archive</>
                                                    )}
                                                </Button>
                                                <Button
                                                    variant="destructive"
                                                    size="sm"
                                                    onClick={() => setWorkflowToDelete(workflow)}
                                                    disabled={deletingWorkflowId === workflow.id || isPending}
                                                    className="flex items-center gap-2"
                                                >
                                                    {deletingWorkflowId === workflow.id ? (
                                                        <>
                                                            <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                                            Deleting...
                                                        </>
                                                    ) : (
                                                        <><Trash2 size={16} />Delete</>
                                                    )}
                                                </Button>
                                            </div>
                                        )}
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </div>

            {/* Delete Confirmation Dialog */}
            <AlertDialog open={!!workflowToDelete} onOpenChange={(open) => !open && setWorkflowToDelete(null)}>
                <AlertDialogContent className="max-w-[90vw] sm:max-w-lg">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete Workflow</AlertDialogTitle>
                        <AlertDialogDescription>
                            Are you sure you want to permanently delete <strong>&quot;{workflowToDelete?.name}&quot;</strong>?
                            This action cannot be undone and will remove all associated runs and data.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={() => workflowToDelete && handleDelete(workflowToDelete)}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                            {deletingWorkflowId === workflowToDelete?.id ? (
                                <>
                                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent mr-2" />
                                    Deleting...
                                </>
                            ) : (
                                'Delete Permanently'
                            )}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>

        </>
    );
}
