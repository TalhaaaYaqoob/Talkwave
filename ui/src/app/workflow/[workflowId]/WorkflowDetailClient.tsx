'use client';

import { useMemo } from 'react';

import { FlowEdge, FlowNode } from '@/components/flow/types';
import SpinLoader from '@/components/SpinLoader';
import { useAuth } from '@/lib/auth';
import { WorkflowConfigurations } from '@/types/workflow-configurations';

import RenderWorkflow from './RenderWorkflow';

interface WorkflowDetailClientProps {
    initialWorkflowName: string;
    workflowId: number;
    publicId?: string;
    initialFlow: {
        nodes: FlowNode[];
        edges: FlowEdge[];
        viewport: { x: number; y: number; zoom: number };
    };
    initialTemplateContextVariables: Record<string, string>;
    initialWorkflowConfigurations: WorkflowConfigurations;
}

export default function WorkflowDetailClient({
    initialWorkflowName,
    workflowId,
    publicId,
    initialFlow,
    initialTemplateContextVariables,
    initialWorkflowConfigurations,
}: WorkflowDetailClientProps) {
    const { user, getAccessToken } = useAuth();

    // Memoize user and getAccessToken to prevent unnecessary re-renders
    const stableUser = useMemo(() => user, [user]);
    const stableGetAccessToken = useMemo(() => getAccessToken, [getAccessToken]);

    // Show the loader (not a blank screen) until client auth hydrates, so
    // there's no "stuck" gap after the route has already navigated.
    if (!stableUser) {
        return <SpinLoader />;
    }

    return (
        <RenderWorkflow
            initialWorkflowName={initialWorkflowName}
            workflowId={workflowId}
            publicId={publicId}
            initialFlow={initialFlow}
            initialTemplateContextVariables={initialTemplateContextVariables}
            initialWorkflowConfigurations={initialWorkflowConfigurations}
            user={stableUser}
            getAccessToken={stableGetAccessToken}
        />
    );
}

