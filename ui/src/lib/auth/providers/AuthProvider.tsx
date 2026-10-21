'use client';

import { Spinner } from '@/components/ui/ai-loader';
import React, { createContext, lazy, Suspense, useContext } from 'react';

import type { AuthUser } from '../types';

// Shared context type for all providers (Clerk, Stack)
export interface AuthContextType {
  user: AuthUser | null;
  isAuthenticated: boolean;
  loading: boolean;
  getAccessToken: () => Promise<string>;
  redirectToLogin: () => void;
  logout: () => Promise<void>;
  provider: string;
  // Organization-specific (optional)
  getSelectedTeam?: () => unknown;
  listPermissions?: (team?: unknown) => Promise<Array<{ id: string }>>;
}

export const AuthContext = createContext<AuthContextType | null>(null);

// Lazy load provider-specific components only when needed
const StackProviderWrapper = lazy(() =>
  import('./StackProviderWrapper').then(module => ({
    default: module.StackProviderWrapper
  }))
);

const ClerkProviderWrapper = lazy(() =>
  import('./ClerkProviderWrapper').then(module => ({
    default: module.ClerkProviderWrapper
  }))
);

// Loading fallback component
function AuthLoadingFallback() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-background">
      <div className="flex flex-col items-center gap-4">
        <Spinner size="lg" />
        <p className="text-sm text-muted-foreground animate-pulse">Loading...</p>
      </div>
    </div>
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'clerk';

  // For Clerk provider (default)
  if (authProvider === 'clerk') {
    return (
      <Suspense fallback={<AuthLoadingFallback />}>
        <ClerkProviderWrapper>
          {children}
        </ClerkProviderWrapper>
      </Suspense>
    );
  }

  // For Stack provider
  if (authProvider === 'stack') {
    return (
      <Suspense fallback={<AuthLoadingFallback />}>
        <StackProviderWrapper>
          {children}
        </StackProviderWrapper>
      </Suspense>
    );
  }

  // No local/OSS bypass exists. Default to Clerk for any other value.
  return (
    <Suspense fallback={<AuthLoadingFallback />}>
      <ClerkProviderWrapper>
        {children}
      </ClerkProviderWrapper>
    </Suspense>
  );
}

export function useAuthContext() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuthContext must be used within AuthProvider');
  }
  return context;
}
