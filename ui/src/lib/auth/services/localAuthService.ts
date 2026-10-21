'use client';

import logger from '@/lib/logger';

import type { LocalUser } from '../types';
import type { IAuthService } from './interface';

/**
 * Minimal auth-service stub.
 *
 * The legacy OSS/local authentication mode (which trusted unverified tokens
 * and auto-issued sessions) has been removed. This stub remains only so the
 * Clerk provider path, which sources its token directly from Clerk's context,
 * has a compatible no-op service. It never mints, stores, or returns any
 * credential and is never treated as authenticated.
 */
export class LocalAuthService implements IAuthService {
  private static instance: LocalAuthService | null = null;

  constructor() {
    if (LocalAuthService.instance) {
      return LocalAuthService.instance;
    }
    LocalAuthService.instance = this;
  }

  async getAccessToken(): Promise<string> {
    logger.warn('getAccessToken called on stub auth service; returning empty token');
    return '';
  }

  async refreshToken(): Promise<string> {
    return this.getAccessToken();
  }

  async getCurrentUser(): Promise<LocalUser | null> {
    return null;
  }

  isAuthenticated(): boolean {
    return false;
  }

  redirectToLogin(): void {
    if (typeof window !== 'undefined') {
      window.location.href = '/sign-in';
    }
  }

  async logout(): Promise<void> {
    // Nothing to clear for the stub service.
  }

  getProviderName(): string {
    return 'none';
  }
}
