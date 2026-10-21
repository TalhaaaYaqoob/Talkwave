# Multi-stage build
# Stage 1: Dependencies
FROM node:20-alpine AS deps
WORKDIR /app

# Install Python and build dependencies for native modules
# This helps with ARM64 builds and native module compilation
RUN apk add --no-cache python3 make g++ libc6-compat

# Copy package files
COPY ui/package*.json ./

# Clean install strictly from the committed lockfile so the production image is
# reproducible and cannot silently float to unpinned dependency versions.
RUN rm -rf node_modules && \
    npm ci

# Stage 2: Builder
FROM node:20-alpine AS builder
WORKDIR /app

# Install libc6-compat for native modules in builder stage too
RUN apk add --no-cache libc6-compat

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy all files needed for build
COPY ui/package*.json ./
COPY ui/tsconfig.json ./
COPY ui/next.config.ts ./
COPY ui/components.json ./
COPY ui/sentry.edge.config.ts ./
COPY ui/sentry.server.config.ts ./
COPY ui/postcss.config.mjs ./
COPY ui/public ./public
COPY ui/src ./src

# Build-time environment variables (needed for Next.js build).
# Secrets/tokens must NOT be baked into the image. Any NEXT_PUBLIC_* value that
# identifies a tenant/channel (e.g. Chatwoot website token) is supplied at build
# time via a build arg / CI secret, never hardcoded here.
ARG NEXT_PUBLIC_AUTH_PROVIDER="clerk"
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=""
ARG NEXT_PUBLIC_CHATWOOT_URL=""
ARG NEXT_PUBLIC_CHATWOOT_TOKEN=""
ENV NEXT_PUBLIC_AUTH_PROVIDER=${NEXT_PUBLIC_AUTH_PROVIDER}
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
ENV BACKEND_URL="http://api:8000"
ENV NEXT_TELEMETRY_DISABLED="1"
ENV NEXT_PUBLIC_CHATWOOT_URL=${NEXT_PUBLIC_CHATWOOT_URL}
ENV NEXT_PUBLIC_CHATWOOT_TOKEN=${NEXT_PUBLIC_CHATWOOT_TOKEN}

# Build the application with standalone mode
RUN npm run build && \
    rm -rf /tmp/* /root/.npm /root/.next/cache

# Stage 3: Runner (production image)
FROM node:20-alpine AS runner
WORKDIR /app

# Environment variables will be provided by docker-compose
ENV NODE_ENV=production

# Create a non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy standalone build output
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

# Switch to non-root user
USER nextjs

# Expose the port Next.js runs on
EXPOSE 3010

# Start the production server using the standalone Node.js server
CMD sh -c "echo '🚀 Application ready at http://localhost:3010' && PORT=3010 node server.js"