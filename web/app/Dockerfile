# Standard three-stage Next.js standalone build (deps -> build -> run),
# matching node_modules/next/dist/docs/.../output.md's own pattern.
# `output: 'standalone'` in next.config.ts is what makes the final stage
# possible: it traces only the files each page needs into
# .next/standalone plus a minimal server.js, so the runtime image needs
# no `npm install` at all -- only that traced output, .next/static, and
# public/.

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are INLINED into the client JS bundle at build time,
# not read at container start -- setting them only in docker-compose's
# `environment:` for the runtime container would silently ship a build
# with these baked in as empty strings. Must be build ARGs, passed via
# compose's `build.args:` (see docker-compose.yml at the repo root).
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
# next.config.ts pins ESLint/type errors to fail a real `next build`
# already (no override here) -- if that ever changes, add
# `RUN npm run lint` as a separate step so a lint failure surfaces before
# the (slower) build rather than only after.
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN groupadd --system --gid 1001 nodejs \
 && useradd --system --uid 1001 --gid nodejs nextjs

# Only the traced standalone output, static assets, and public/ --
# deliberately NOT node_modules or the full .next directory (see
# next.config.ts's output: 'standalone' comment).
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
