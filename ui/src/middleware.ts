import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

// Define public routes that don't require an authenticated session.
// NOTE: Actual authorization is always enforced on the BACKEND. These entries
// only control whether the UI forces a sign-in redirect before rendering.
const isPublicRoute = createRouteMatcher([
  '/sign-in(.*)',
  '/sign-up(.*)',
  '/api/(.*)',       // All API routes - backend handles auth
  '/handler/(.*)',   // Stack auth handler routes
  '/share/(.*)',     // Anonymous, token-scoped workflow share pages
]);

// Main middleware function
export default function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (/\.(?:png|jpg|jpeg|gif|webp|svg|ico|css|js|woff2?|ttf|eot)$/i.test(pathname)) {
    return NextResponse.next();
  }

  const authProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER || 'clerk';

  if (authProvider === 'clerk') {
    return clerkMiddleware(async (auth, req) => {
      if (isPublicRoute(req)) {
        return NextResponse.next();
      }

      const { userId } = await auth();
      if (!userId) {
        const signInUrl = new URL('/sign-in', req.url);
        // Only preserve a same-origin relative path to avoid open-redirect abuse.
        const target = `${req.nextUrl.pathname}${req.nextUrl.search}`;
        if (/^\/(?!\/)/.test(target)) {
          signInUrl.searchParams.set('redirect_url', target);
        }
        return NextResponse.redirect(signInUrl);
      }

      return NextResponse.next();
    })(request, {} as never);
  }

  // Stack auth handles its own session; the backend validates every token.
  // Unknown providers are treated as Stack (no local/OSS bypass exists).
  return NextResponse.next();
}

// Configure which routes the middleware runs on
export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public files (public folder)
     */
    '/((?!_next/static|_next/image|favicon\\.ico).*)',
  ],
};
