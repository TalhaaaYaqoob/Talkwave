import SpinLoader from '@/components/SpinLoader';

import WorkflowLayout from '../WorkflowLayout';

// Instant loading state for the agent editor route. Mirrors the in-page
// Suspense fallback (WorkflowLayout shell + loader) so navigating into an
// agent shows immediate feedback instead of freezing on the list while the
// force-dynamic server component awaits auth + the workflow fetch.
export default function Loading() {
    return (
        <WorkflowLayout>
            <SpinLoader />
        </WorkflowLayout>
    );
}
