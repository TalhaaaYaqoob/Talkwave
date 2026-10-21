import { notFound } from 'next/navigation';

import { getBackendUrl } from '@/lib/apiClient';
import { getServerAccessToken } from '@/lib/auth/server';
import logger from '@/lib/logger';

/**
 * Server-side authorization guard for all /superadmin routes.
 *
 * The backend is the ultimate source of truth for the `is_superuser` flag. This
 * layout verifies it server-side (before any superadmin UI is rendered) so that
 * a merely authenticated, non-superuser account cannot reach impersonation
 * controls or cross-tenant data. Non-superusers get a 404.
 */
async function assertSuperuser(): Promise<void> {
  const token = await getServerAccessToken();
  if (!token) {
    notFound();
  }

  try {
    const res = await fetch(`${getBackendUrl()}/api/v1/user/me`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    });

    if (!res.ok) {
      notFound();
    }

    const user = await res.json();
    if (!user?.is_superuser) {
      notFound();
    }
  } catch (error) {
    logger.error('[superadmin] Failed to verify superuser status:', error);
    notFound();
  }
}

export default async function SuperadminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await assertSuperuser();
  return <>{children}</>;
}
