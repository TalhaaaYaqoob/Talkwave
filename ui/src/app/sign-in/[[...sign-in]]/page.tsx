'use client';

import { SignIn, useClerk } from '@clerk/nextjs';
import { AlertCircle, ExternalLink } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useEffect, useState } from 'react';

export default function SignInPage() {
  const [mounted, setMounted] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const { loaded: clerkLoaded } = useClerk();

  useEffect(() => {
    setMounted(true);
    
    // Set a timeout to detect if Clerk fails to load
    const timeout = setTimeout(() => {
      if (mounted && !clerkLoaded) {
        setLoadError(true);
      }
    }, 15000); // 15 second timeout (longer for production)

    return () => clearTimeout(timeout);
  }, [mounted, clerkLoaded]);

  // Reset error if Clerk eventually loads
  useEffect(() => {
    if (clerkLoaded && loadError) {
      setLoadError(false);
    }
  }, [clerkLoaded, loadError]);

  // Show error state if Clerk failed to load after timeout
  if (mounted && loadError && !clerkLoaded) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-[#050a0a] via-[#081110] to-[#050a0a] p-4">
        <div className="w-full max-w-lg">
          <div className="rounded-xl bg-red-950/50 border border-red-500/30 p-6">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-6 w-6 text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <h2 className="text-xl font-bold text-red-400 mb-3">Authentication Service Unavailable</h2>
                <p className="text-red-300/80 text-sm mb-4">
                  Unable to connect to the authentication service. This usually happens when:
                </p>
                <ul className="list-disc list-inside text-red-300/70 text-sm space-y-2 mb-4">
                  <li>Your domain is not configured in Clerk Dashboard</li>
                  <li>Using production keys without verifying your domain</li>
                  <li>The <code className="bg-red-900/50 px-1 rounded">NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY</code> is incorrect</li>
                </ul>
                <div className="bg-red-900/30 rounded-lg p-4 text-sm">
                  <p className="font-medium text-red-300 mb-2">How to fix:</p>
                  <ol className="list-decimal list-inside space-y-2 text-red-300/70">
                    <li>Go to <a href="https://dashboard.clerk.com" target="_blank" rel="noopener noreferrer" className="text-red-400 hover:text-red-300 underline">Clerk Dashboard</a></li>
                    <li>Select your production instance</li>
                    <li>Go to <strong>Settings → Domains</strong></li>
                    <li>Add the domain you serve TalkWave from</li>
                    <li>Verify the domain ownership</li>
                    <li>Redeploy your application</li>
                  </ol>
                  <a 
                    href="https://clerk.com/docs/deployments/overview" 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 mt-4 text-red-400 hover:text-red-300 underline underline-offset-2"
                  >
                    Clerk Production Deployment Guide
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-[#050a0a] via-[#081110] to-[#050a0a]">
      <div className="w-full max-w-md">
        {mounted ? (
          <SignIn
            appearance={{
              elements: {
                rootBox: "mx-auto",
                card: "bg-[#0a1413]/80 backdrop-blur-xl border border-[#34F5C2]/15 shadow-2xl",
                headerTitle: "text-white",
                headerSubtitle: "text-[#8FA69F]",
                socialButtonsBlockButton: "bg-white/[0.04] border border-[#34F5C2]/15 hover:bg-[#34F5C2]/[0.07] text-white",
                socialButtonsBlockButtonText: "text-white",
                dividerLine: "bg-[#34F5C2]/15",
                dividerText: "text-[#8FA69F]",
                formFieldLabel: "text-[#c9ded7]",
                formFieldInput: "bg-white/[0.04] border-[#34F5C2]/20 text-white placeholder:text-[#5d736c] focus:border-[#34F5C2] focus:ring-[#34F5C2]",
                formButtonPrimary: "bg-[#34F5C2] hover:bg-[#5ff7d0] text-[#04110c] font-semibold",
                footerActionLink: "text-[#34F5C2] hover:text-[#5ff7d0]",
                identityPreviewText: "text-white",
                identityPreviewEditButton: "text-[#34F5C2]",
              },
            }}
            routing="path"
            path="/sign-in"
            signUpUrl="/sign-up"
            afterSignInUrl="/"
            fallbackRedirectUrl="/"
          />
        ) : (
          <div className="flex items-center justify-center p-8">
            <Spinner size="lg" />
          </div>
        )}
      </div>
    </div>
  );
}

