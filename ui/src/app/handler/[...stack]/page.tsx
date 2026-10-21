import { StackHandler } from "@stackframe/stack";

import { stackServerApp } from "../../../stack";

const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER;

export default function Handler(props: unknown) {
  // Only render Stack handler when using Stack auth and it's properly configured
  if (authProvider !== "stack" || !stackServerApp) {
    return (
      <div style={{ padding: '20px', textAlign: 'center' }}>
        <h1>Auth Handler</h1>
        <p>This handler is only available when using Stack authentication.</p>
        <p>Current auth provider: {authProvider || 'not set'}</p>
      </div>
    );
  }
  
  return <StackHandler
    fullPage
    app={stackServerApp}
    routeProps={props}
  />;
}
