"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import SpinLoader from "@/components/SpinLoader";
import { useAuth } from "@/lib/auth";
import { fetchWorkflowByToken } from "@/lib/workflowToken";

import WorkflowLayout from "../../WorkflowLayout";
import { WorkflowExecutions } from "../components/WorkflowExecutions";

export default function WorkflowRunsPage() {
    // The URL slug is the opaque public_id token, not the integer id.
    const { workflowId: token } = useParams<{ workflowId: string }>();
    const searchParams = useSearchParams();
    const { getAccessToken, isAuthenticated, loading } = useAuth();

    const [workflowId, setWorkflowId] = useState<number | null>(null);
    const [notFound, setNotFound] = useState(false);

    useEffect(() => {
        if (loading || !isAuthenticated) return;
        let cancelled = false;
        (async () => {
            const accessToken = await getAccessToken();
            const workflow = accessToken
                ? await fetchWorkflowByToken(String(token), accessToken)
                : null;
            if (cancelled) return;
            if (workflow) {
                setWorkflowId(workflow.id);
            } else {
                setNotFound(true);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [token, isAuthenticated, loading, getAccessToken]);

    return (
        <WorkflowLayout showFeaturesNav={false}>
            {notFound ? (
                <div className="flex items-center justify-center min-h-screen">
                    <div className="text-lg text-destructive">Workflow not found</div>
                </div>
            ) : workflowId == null ? (
                <SpinLoader />
            ) : (
                <WorkflowExecutions
                    workflowId={workflowId}
                    publicId={String(token)}
                    searchParams={searchParams}
                />
            )}
        </WorkflowLayout>
    );
}
