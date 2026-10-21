'use client';

import { AlertTriangle } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useCallback, useEffect, useState, useTransition } from 'react';

import { Badge } from "@/components/ui/badge";
import { CreateWorkflowButton } from "@/components/workflow/CreateWorkflowButton";
import { UploadWorkflowButton } from '@/components/workflow/UploadWorkflowButton';
import { WorkflowTable } from "@/components/workflow/WorkflowTable";
import { useAuth } from '@/lib/auth';
import { useUserConfig } from '@/context/UserConfigContext';
import { getBackendUrl } from '@/lib/apiClient';

import WorkflowLayout from "./WorkflowLayout";

interface Workflow {
    id: number;
    public_id?: string;
    name: string;
    status: string;
    created_at: string;
    total_runs?: number | null;
    workflow_configurations?: Record<string, unknown> | null;
}

export default function WorkflowPage() {
    const { getAccessToken, loading: authLoading, isAuthenticated } = useAuth();
    const { subscription } = useUserConfig();
    const [activeWorkflows, setActiveWorkflows] = useState<Workflow[]>([]);
    const [archivedWorkflows, setArchivedWorkflows] = useState<Workflow[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchWorkflows = useCallback(async (silent = false) => {
        if (!silent) setIsLoading(true);
        setError(null);
        try {
            const accessToken = await getAccessToken();
            if (!accessToken) {
                setError('Failed to load workflows. Please try again.');
                return;
            }
            const baseUrl = getBackendUrl();
            const response = await fetch(`${baseUrl}/api/v1/workflow/fetch?status=active,archived`, {
                headers: { 'Authorization': `Bearer ${accessToken}` },
            });

            if (!response.ok) throw new Error('Failed to fetch workflows');

            const data: Workflow[] = await response.json();

            const active = data
                .filter(w => w.status === 'active')
                .sort((a, b) => {
                    const aGen = (a.workflow_configurations as any)?._generating ? 1 : 0;
                    const bGen = (b.workflow_configurations as any)?._generating ? 1 : 0;
                    if (bGen !== aGen) return bGen - aGen;
                    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
                });

            const archived = data
                .filter(w => w.status === 'archived')
                .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

            setActiveWorkflows(active);
            setArchivedWorkflows(archived);
            setError(null);
        } catch (err) {
            console.error('Error fetching workflows:', err);
            if (!silent) setError('Failed to load workflows. Please try again.');
        } finally {
            setIsLoading(false);
        }
    }, [getAccessToken]);

    useEffect(() => {
        if (authLoading || !isAuthenticated) return;
        fetchWorkflows();
    }, [fetchWorkflows, authLoading, isAuthenticated]);

    // Auto-refresh if any workflow is generating (silent to avoid full-page loader flash)
    const hasGenerating = activeWorkflows.some(w => (w.workflow_configurations as any)?._generating);
    useEffect(() => {
        if (!hasGenerating) return;
        const interval = setInterval(() => fetchWorkflows(true), 5000);
        return () => clearInterval(interval);
    }, [hasGenerating, fetchWorkflows]);

    return (
        <WorkflowLayout showFeaturesNav={true}>
            <div className="container mx-auto px-4 py-4 sm:py-8">
                <div className="mb-6">
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
                        <div className="flex items-center gap-3">
                            <h1 className="text-xl sm:text-2xl font-bold">Your Agents</h1>
                            {subscription?.billing_enabled && (
                                <Badge variant="outline" className="text-xs text-muted-foreground">
                                    {activeWorkflows.length} / {subscription.max_workflows} used
                                </Badge>
                            )}
                        </div>
                        <div className="flex gap-2 w-full sm:w-auto">
                            {subscription && activeWorkflows.length >= subscription.max_workflows ? (
                                <Badge variant="destructive" className="px-3 py-1.5 text-sm">
                                    <AlertTriangle className="h-3.5 w-3.5 mr-1.5" />
                                    Workflow limit reached
                                </Badge>
                            ) : (
                                <>
                                    <UploadWorkflowButton />
                                    <CreateWorkflowButton />
                                </>
                            )}
                        </div>
                    </div>

                    {isLoading ? (
                        <div className="flex items-center justify-center py-16">
                            <Spinner size="lg" />
                        </div>
                    ) : error ? (
                        <div className="text-red-500 bg-destructive/10 rounded-lg p-8 text-center">
                            {error}
                        </div>
                    ) : (
                        <>
                            <div className="mb-8">
                                <h2 className="text-xl font-semibold mb-4">Active Agents</h2>
                                {activeWorkflows.length > 0 ? (
                                    <WorkflowTable workflows={activeWorkflows} showArchived={false} onRefresh={fetchWorkflows} />
                                ) : (
                                    <div className="text-muted-foreground bg-muted rounded-lg p-8 text-center">
                                        No active workflows found. Create your first workflow to get started.
                                    </div>
                                )}
                            </div>

                            {archivedWorkflows.length > 0 && (
                                <div className="mb-8">
                                    <h2 className="text-xl font-semibold mb-4 text-muted-foreground">Archived Workflows</h2>
                                    <WorkflowTable workflows={archivedWorkflows} showArchived={true} onRefresh={fetchWorkflows} />
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </WorkflowLayout>
    );
}
