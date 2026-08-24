FROM node:24-slim AS build
WORKDIR /workspace
COPY package.json package-lock.json ./
COPY apps/customer-web/package.json apps/customer-web/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
RUN npm ci
COPY tsconfig.base.json ./
COPY apps/customer-web apps/customer-web
COPY packages/shared-types packages/shared-types
RUN npm run build --workspace @spa/customer-web

FROM node:24-slim AS runtime
ENV NODE_ENV=production PORT=8080 HOSTNAME=0.0.0.0
RUN addgroup --system spa && adduser --system --ingroup spa spa
WORKDIR /app
COPY --from=build --chown=spa:spa /workspace/apps/customer-web/.next/standalone ./
COPY --from=build --chown=spa:spa /workspace/apps/customer-web/.next/static ./apps/customer-web/.next/static
COPY --from=build --chown=spa:spa /workspace/apps/customer-web/public ./apps/customer-web/public
USER spa
EXPOSE 8080
CMD ["node", "apps/customer-web/server.js"]
