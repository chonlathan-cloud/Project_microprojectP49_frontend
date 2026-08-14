FROM node:24-slim AS build
WORKDIR /workspace
COPY package.json package-lock.json ./
COPY apps/admin-web/package.json apps/admin-web/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
RUN npm ci
COPY tsconfig.base.json ./
COPY apps/admin-web apps/admin-web
COPY packages/shared-types packages/shared-types
RUN npm run build --workspace @spa/admin-web

FROM node:24-slim AS runtime
ENV NODE_ENV=production PORT=8080 HOSTNAME=0.0.0.0
RUN addgroup --system spa && adduser --system --ingroup spa spa
WORKDIR /app
COPY --from=build --chown=spa:spa /workspace/apps/admin-web/.next/standalone ./
COPY --from=build --chown=spa:spa /workspace/apps/admin-web/.next/static ./apps/admin-web/.next/static
USER spa
EXPOSE 8080
CMD ["node", "apps/admin-web/server.js"]
