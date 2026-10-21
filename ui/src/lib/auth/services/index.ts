'use client';

import logger from '@/lib/logger';

import type { AuthProvider } from '../types';
import type { IAuthService } from './interface';
// Only import local services statically
// ClerkAuthService is not needed here since ClerkProviderWrapper handles auth directly
import { LocalAuthService } from './localAuthService';

// Singleton instances for auth services
let localServiceInstance: LocalAuthService | null = null;
let stackServiceInstance: IAuthService | null = null;

export function createAuthService(provider?: AuthProvider | string): IAuthService {
  const authProvider = provider || process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'clerk';

  switch (authProvider) {
    case 'stack':
      // Dynamically import StackAuthService to avoid bundling @stackframe/stack everywhere
      if (!stackServiceInstance) {
        logger.debug('[createAuthService] Creating singleton StackAuthService instance');
        const { StackAuthService } = require('./stackAuthService');
        stackServiceInstance = new StackAuthService();
      }
      return stackServiceInstance;
    case 'clerk':
    default:
      // For Clerk, ClerkProviderWrapper handles auth directly via the useAuth
      // hook. This stub only exists for interface compatibility. There is no
      // local/OSS bypass.
      if (!localServiceInstance) {
        localServiceInstance = new LocalAuthService();
      }
      return localServiceInstance;
  }
}

export type { IAuthService } from './interface';
export { LocalAuthService } from './localAuthService';
