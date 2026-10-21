import { Suspense } from 'react';

import { FlowEdge, FlowNode } from '@/components/flow/types';
import SpinLoader from '@/components/SpinLoader';
import { getBackendUrl } from '@/lib/apiClient';
import { getServerAccessToken } from '@/lib/auth/server';
import logger from '@/lib/logger';
import { DEFAULT_WORKFLOW_CONFIGURATIONS, WorkflowConfigurations } from '@/types/workflow-configurations';

import WorkflowLayout from '../WorkflowLayout';
import WorkflowDetailClient from './WorkflowDetailClient';

// This page requires authentication, so it must be dynamic
export const dynamic = 'force-dynamic';
export const revalidate = 0;

interface WorkflowDetailPageProps {
    // The URL slug is the workflow's opaque public_id token, never the
    // enumerable integer primary key.
    params: Promise<{ workflowId: string }>;
}

// Server component for data fetching. `token` is the opaque public_id.
async function WorkflowContent({ token }: { token: string }) {
    const accessToken = await getServerAccessToken();

    if (!accessToken) {
        const { redirect } = await import('next/navigation');
        redirect('/sign-in');
    }

    try {
        // Resolve by opaque token only. A sequential integer in the URL will
        // not match any public_id and therefore 404s (hard cut).
        const res = await fetch(
            `${getBackendUrl()}/api/v1/workflow/by-token/${encodeURIComponent(token)}`,
            {
                headers: { 'Authorization': `Bearer ${accessToken}` },
                cache: 'no-store',
            }
        );

        if (!res.ok) {
            return (
                <WorkflowLayout showFeaturesNav={false}>
                    <div className="flex items-center justify-center min-h-screen">
                        <div className="text-lg text-destructive">Workflow not found</div>
                    </div>
                </WorkflowLayout>
            );
        }

        const workflow = await res.json();

        return (
            <WorkflowDetailClient
                initialWorkflowName={workflow.name}
                workflowId={workflow.id}
                publicId={workflow.public_id}
                initialFlow={{
                    nodes: workflow.workflow_definition.nodes as FlowNode[],
                    edges: workflow.workflow_definition.edges as FlowEdge[],
                    viewport: { x: 0, y: 0, zoom: 0 }
                }}
                initialTemplateContextVariables={workflow.template_context_variables as Record<string, string> || {}}
                initialWorkflowConfigurations={(workflow.workflow_configurations as WorkflowConfigurations) || DEFAULT_WORKFLOW_CONFIGURATIONS}
            />
        );
    } catch (err) {
        logger.error(`Error fetching workflow: ${err}`);
        return (
            <WorkflowLayout showFeaturesNav={false}>
                <div className="flex items-center justify-center min-h-screen">
                    <div className="text-lg text-destructive">Failed to fetch workflow</div>
                </div>
            </WorkflowLayout>
        );
    }
}

export default async function WorkflowDetailPage({ params }: WorkflowDetailPageProps) {
    const { workflowId: token } = await params;

    return (
        <Suspense fallback={
            <WorkflowLayout>
                <SpinLoader />
            </WorkflowLayout>
        }>
            <WorkflowContent token={token} />
        </Suspense>
    );
}
