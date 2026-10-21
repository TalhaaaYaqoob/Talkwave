import "server-only";

import type { CurrentUser, StackServerApp } from '@stackframe/stack';

import logger from '@/lib/logger';

import type { ClerkUser, LocalUser } from './types';

// Server-side auth utilities for SSR pages
// This file should only be imported in server components

let stackServerApp: StackServerApp<boolean, string> | null = null;

// Lazy load and cache the stack server app
async function getStackServerApp(): Promise<StackServerApp<boolean, string> | null> {
  if (!stackServerApp) {
    // Only import if using Stack provider
    const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'clerk';
    if (authProvider === 'stack') {
      const stackModule = await import('@stackframe/stack');
      const { StackServerApp } = stackModule;
      stackServerApp = new StackServerApp({
        tokenStore: "nextjs-cookie",
        urls: {
          afterSignIn: "/after-sign-in"
        }
      });
    }
  }
  return stackServerApp;
}

/**
 * Get Clerk token on the server side
 * Only returns the token - actual user validation happens on the BACKEND
 */
async function getClerkToken(): Promise<string | null> {
  try {
    const { auth } = await import('@clerk/nextjs/server');
    const { getToken } = await auth();
    return await getToken();
  } catch (error) {
    logger.error('Error getting Clerk token:', error);
    return null;
  }
}

/**
 * Get Clerk user info from the token claims (minimal info for SSR)
 * Full user validation and data should come from the BACKEND
 */
async function getClerkUser(): Promise<ClerkUser | null> {
  try {
    const { currentUser } = await import('@clerk/nextjs/server');
    const user = await currentUser();

    if (!user) {
      return null;
    }

    // Return minimal user info - full validation is on the backend
    return {
      id: user.id,
      email: user.primaryEmailAddress?.emailAddress,
      name: user.fullName ?? user.firstName ?? undefined,
      image: user.imageUrl,
      provider: 'clerk',
    };
  } catch (error) {
    logger.error('Error getting user from Clerk:', error);
    return null;
  }
}

/**
 * Get the current user on the server side (for SSR)
 * Note: For Clerk, this returns minimal info. Full auth validation happens on the BACKEND.
 */
export async function getServerUser(): Promise<CurrentUser | ClerkUser | LocalUser | null> {
  const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'clerk';

  if (authProvider === 'clerk') {
    return await getClerkUser();
  } else if (authProvider === 'stack') {
    const app = await getStackServerApp();
    if (app) {
      try {
        const user = await app.getUser();
        return user;
      } catch (error) {
        logger.error('Error getting user from Stack:', error);
        return null;
      }
    }
  }

  return null;
}

/**
 * Check if user is authenticated on the server side
 */
export async function isServerAuthenticated(): Promise<boolean> {
  const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'clerk';

  if (authProvider === 'clerk') {
    const token = await getClerkToken();
    return !!token;
  }

  if (authProvider === 'stack') {
    const user = await getServerUser();
    return !!user;
  }

  return false;
}

/**
 * Get provider name for server-side rendering
 */
export function getServerAuthProvider(): string {
  return process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'clerk';
}

/**
 * Get access token for API calls
 * This token is passed to the BACKEND which handles all auth validation
 */
export async function getServerAccessToken(): Promise<string | null> {
  const authProvider = getServerAuthProvider();

  if (authProvider === 'clerk') {
    return await getClerkToken();
  } else if (authProvider === 'stack') {
    const user = await getServerUser();
    if (user && 'getAuthJson' in user) {
      const auth = await user.getAuthJson();
      return auth?.accessToken ?? null;
    }
  }

  return null;
}
