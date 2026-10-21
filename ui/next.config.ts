import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Ignore ESLint during builds (fix locally later)
  eslint: {
    ignoreDuringBuilds: true,
  },
  // Ignore TypeScript errors during builds
  typescript: {
    ignoreBuildErrors: true,
  },
  // Performance optimizations
  poweredByHeader: false,
  compress: true,
  // Images configuration for external sources.
  // Restrict the optimizer to known hosts. A wildcard ("**") would let the
  // Next image optimizer be abused as an SSRF proxy against internal services.
  // Additional hosts can be added via NEXT_PUBLIC_IMAGE_HOSTS (comma-separated).
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'img.clerk.com' },
      { protocol: 'https', hostname: 'images.clerk.dev' },
      { protocol: 'https', hostname: 'lh3.googleusercontent.com' },
      { protocol: 'https', hostname: '*.supabase.co' },
      { protocol: 'https', hostname: '*.amazonaws.com' },
      ...(process.env.NEXT_PUBLIC_IMAGE_HOSTS || '')
        .split(',')
        .map((h) => h.trim())
        .filter(Boolean)
        .map((hostname) => ({ protocol: 'https' as const, hostname })),
    ],
    // Optimize image loading
    minimumCacheTTL: 60,
  },
  // Experimental features for performance
  experimental: {
    // Optimize package imports to reduce bundle size
    optimizePackageImports: ['lucide-react', '@radix-ui/react-icons', '@phosphor-icons/react'],
  },
  async rewrites() {
    let backendUrl = process.env.BACKEND_URL;
    
    if (backendUrl) {
      // Prevent mixed-content errors: always use HTTPS in production
      if (backendUrl.startsWith('http://') && !backendUrl.includes('localhost') && !backendUrl.includes('127.0.0.1')) {
        backendUrl = backendUrl.replace('http://', 'https://');
      }
      return [
        {
          source: "/api/:path((?!config|auth).*)*",
          destination: `${backendUrl}/api/:path*`,
        },
      ];
    }
    
    return [];
  },
  // Add caching headers for static assets
  async headers() {
    // Baseline security headers applied to every response. These mitigate
    // clickjacking, MIME sniffing, referrer leakage, and enforce HTTPS.
    const securityHeaders = [
      { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
      {
        key: 'Strict-Transport-Security',
        value: 'max-age=63072000; includeSubDomains; preload',
      },
      {
        key: 'Permissions-Policy',
        // Only microphone is needed (voice agent). Everything else denied.
        value: 'camera=(), geolocation=(), microphone=(self), payment=()',
      },
      { key: 'X-DNS-Prefetch-Control', value: 'off' },
    ];

    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
      {
        source: '/:all*(svg|jpg|png|webp|gif|ico)',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable',
          },
        ],
      },
      {
        source: '/_next/static/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable',
          },
        ],
      },
    ];
  },
};

export default nextConfig;
