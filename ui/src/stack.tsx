import "server-only";

import { StackServerApp } from "@stackframe/stack";

const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER;

function createStackApp(): StackServerApp | null {
  // Only initialize Stack Auth when explicitly configured
  if (authProvider !== "stack") {
    return null;
  }
  
  // Check if required env vars are present
  if (!process.env.NEXT_PUBLIC_STACK_PROJECT_ID) {
    console.warn("Stack Auth: NEXT_PUBLIC_STACK_PROJECT_ID not set");
    return null;
  }
  
  return new StackServerApp({
    tokenStore: "nextjs-cookie",
    urls: {
      afterSignIn: "/after-sign-in"
    }
  });
}

export const stackServerApp = createStackApp();
