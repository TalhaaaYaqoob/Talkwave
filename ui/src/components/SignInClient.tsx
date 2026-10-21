"use client";

import { Spinner } from '@/components/ui/ai-loader';
import dynamic from 'next/dynamic';

import Footer from './Footer';

// Only load Stack's SignIn component when Stack provider is active
const SignIn = dynamic(
  () => import('@stackframe/stack').then(mod => ({ default: mod.SignIn })),
  { ssr: false, loading: () => <Spinner size="md" /> }
);

export default function SignInClient() {
  const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'local';

  if (authProvider !== 'stack') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4">Local Authentication</h1>
          <p className="text-gray-600">Local authentication is enabled. No sign-in required.</p>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <>
      <SignIn />
      <Footer />
    </>
  );
}
