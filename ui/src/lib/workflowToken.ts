import { getBackendUrl } from '@/lib/apiClient';

export interface ResolvedWorkflow {
    id: number;
    public_id: string;
    name: string;
    status: string;
    workflow_definition: { nodes: unknown[]; edges: unknown[] };
    template_context_variables: Record<string, string> | null;
    call_disposition_codes: Record<string, unknown> | null;
    workflow_configurations: Record<string, unknown> | null;
}

/**
 * Resolve a workflow from its opaque `public_id` token (the value used in
 * user-facing URLs). Returns null when the token does not resolve — e.g. when a
 * sequential integer id is put in the URL, which intentionally does not match
 * any token (hard cut away from enumerable ids).
 */
export async function fetchWorkflowByToken(
    token: string,
    accessToken: string
): Promise<ResolvedWorkflow | null> {
    const res = await fetch(
        `${getBackendUrl()}/api/v1/workflow/by-token/${encodeURIComponent(token)}`,
        {
            headers: { Authorization: `Bearer ${accessToken}` },
            cache: 'no-store',
        }
    );
    if (!res.ok) return null;
    return res.json();
}
