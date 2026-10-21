'use client';

import { ClerkProvider, useAuth, useUser } from '@clerk/nextjs';
import React, { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react';

import { getBackendUrl } from '@/lib/apiClient';
import logger from '@/lib/logger';

import type { AuthUser } from '../types';
import { AuthContext } from './AuthProvider';

interface ClerkProviderWrapperProps {
  children: React.ReactNode;
}

// Backend user data that enriches Clerk user
interface BackendUserData {
  is_superuser?: boolean;
  selected_organization_id?: number;
  organization_name?: string;
}

/**
 * Internal context provider that gets user data from the BACKEND
 * Clerk is only used for getting the JWT token - all auth logic is on the backend
 * 
 * OPTIMIZED: Uses Clerk's user data immediately for rendering, then enriches with backend data
 */
function ClerkAuthContextProvider({ children }: { children: React.ReactNode }) {
  const { getToken, isLoaded, isSignedIn, signOut } = useAuth();
  const { user: clerkUser, isLoaded: isClerkUserLoaded } = useUser();
  const [backendUserData, setBackendUserData] = useState<BackendUserData | null>(null);
  const [loading, setLoading] = useState(true);
  const [, startTransition] = useTransition();
  const hasFetchedBackendData = useRef(false);

  // Create initial user from Clerk data immediately (fast)
  const initialUser = useMemo(() => {
    if (!isLoaded || !isSignedIn || !clerkUser) return null;
    
    const user: AuthUser = {
      id: clerkUser.id,
      provider: 'clerk' as const,
      provider_id: clerkUser.id,
      email: clerkUser.primaryEmailAddress?.emailAddress,
      // These will be enriched from backend
      is_superuser: backendUserData?.is_superuser ?? false,
      selected_organization_id: backendUserData?.selected_organization_id,
      organization_name: backendUserData?.organization_name,
    };
    return user;
  }, [isLoaded, isSignedIn, clerkUser, backendUserData]);

  // Fetch additional user data from backend (non-blocking with timeout)
  const fetchBackendUserData = useCallback(async () => {
    if (!isLoaded || !isSignedIn || hasFetchedBackendData.current) return;
    hasFetchedBackendData.current = true;

    try {
      const token = await getToken();
      if (!token) return;

      const apiUrl = getBackendUrl();
      
      // Add 5 second timeout to prevent hanging
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      try {
        const response = await fetch(`${apiUrl}/api/v1/user/me`, {
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          signal: controller.signal,
        });
        
        clearTimeout(timeoutId);

        if (response.ok) {
          const userData = await response.json();
          // Enrich user with backend data
          startTransition(() => {
            setBackendUserData({
              is_superuser: userData.is_superuser,
              selected_organization_id: userData.selected_organization_id,
              organization_name: userData.organization_name,
            });
          });
        } else if (response.status === 401) {
          logger.warn('[ClerkAuthContextProvider] Backend rejected token');
        } else {
          logger.error('[ClerkAuthContextProvider] Backend error:', response.status);
        }
      } catch (fetchError) {
        clearTimeout(timeoutId);
        if ((fetchError as Error).name === 'AbortError') {
          logger.warn('[ClerkAuthContextProvider] Backend request timed out - continuing without backend data');
        } else {
          throw fetchError;
        }
      }
    } catch (error) {
      logger.error('[ClerkAuthContextProvider] Error fetching user from backend:', error);
    }
  }, [isLoaded, isSignedIn, getToken]);

  // Set loading to false once Clerk is loaded (don't wait for backend)
  useEffect(() => {
    if (isLoaded && isClerkUserLoaded) {
      setLoading(false);
    }
  }, [isLoaded, isClerkUserLoaded]);

  // Fetch backend data in background after initial render
  useEffect(() => {
    if (isLoaded && isSignedIn) {
      fetchBackendUserData();
    }
  }, [isLoaded, isSignedIn, fetchBackendUserData]);

  // Get access token - just passes through to Clerk
  const getAccessToken = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error('No access token available');
    }
    return token;
  }, [getToken]);

  const redirectToLogin = useCallback(() => {
    if (typeof window !== 'undefined') {
      window.location.href = '/sign-in';
    }
  }, []);

  const logout = useCallback(async () => {
    await signOut();
    hasFetchedBackendData.current = false;
    setBackendUserData(null);
  }, [signOut]);

  const contextValue = useMemo(() => ({
    user: initialUser,
    isAuthenticated: !!initialUser,
    loading: !isLoaded || loading,
    getAccessToken,
    redirectToLogin,
    logout,
    provider: 'clerk' as const,
  }), [initialUser, isLoaded, loading, getAccessToken, redirectToLogin, logout]);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Clerk Provider Wrapper
 * Clerk is ONLY used for sign-in/sign-up UI and getting JWT tokens
 * All actual authentication logic is handled by the backend
 */
export function ClerkProviderWrapper({ children }: ClerkProviderWrapperProps) {
  // Check if Clerk publishable key is configured
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  
  if (!publishableKey) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-4">
        <div className="max-w-md rounded-xl bg-red-950/50 border border-red-500/30 p-6 text-center">
          <h2 className="text-xl font-bold text-red-400 mb-3">Clerk Configuration Error</h2>
          <p className="text-red-300/80 text-sm mb-4">
            The <code className="bg-red-900/50 px-1 rounded">NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY</code> environment variable is not set.
          </p>
          <p className="text-red-300/60 text-xs">
            Please add your Clerk publishable key to your environment variables in Vercel Dashboard → Settings → Environment Variables.
          </p>
        </div>
      </div>
    );
  }

  // If custom domain DNS isn't ready, you can set this env var to use default Clerk domain
  // Set NEXT_PUBLIC_CLERK_FRONTEND_API to empty string or remove it to use custom domain
  // Set it to a specific value to override (e.g., "clerk.your-domain.com")
  const frontendApi = process.env.NEXT_PUBLIC_CLERK_FRONTEND_API;
  
  // Clerk provider configuration
  const clerkConfig: {
    publishableKey: string;
    afterSignOutUrl: string;
    signInUrl: string;
    signUpUrl: string;
    frontendApi?: string;
  } = {
    publishableKey,
    afterSignOutUrl: "/",
    signInUrl: "/sign-in",
    signUpUrl: "/sign-up",
  };

  // Only add frontendApi if explicitly set (to override custom domain)
  // If not set, Clerk will automatically use the custom domain from your publishable key config
  if (frontendApi !== undefined && frontendApi !== '') {
    clerkConfig.frontendApi = frontendApi;
  }

  return (
    <ClerkProvider
      {...clerkConfig}
    >
      <ClerkAuthContextProvider>
        {children}
      </ClerkAuthContextProvider>
    </ClerkProvider>
  );
}
