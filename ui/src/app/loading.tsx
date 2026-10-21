import SpinLoader from '@/components/SpinLoader';

// Root-level instant loading boundary. Next.js shows this immediately on any
// client navigation whose destination segment has no more-specific loading.tsx,
// so the app never appears "stuck" on the previous page while the next route's
// server component / data fetch resolves.
export default function Loading() {
    return <SpinLoader />;
}
