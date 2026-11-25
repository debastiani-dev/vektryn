# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY . .
ARG VITE_SENTRY_DSN=""
ARG VITE_SENTRY_ENVIRONMENT="production"
ARG VITE_SENTRY_RELEASE=""
ARG VITE_SENTRY_SOURCEMAPS="false"
ARG SENTRY_ORG=""
ARG SENTRY_PROJECT=""
ENV VITE_SENTRY_DSN=${VITE_SENTRY_DSN} \
    VITE_SENTRY_ENVIRONMENT=${VITE_SENTRY_ENVIRONMENT} \
    VITE_SENTRY_RELEASE=${VITE_SENTRY_RELEASE} \
    VITE_SENTRY_SOURCEMAPS=${VITE_SENTRY_SOURCEMAPS}
RUN npm run build
RUN --mount=type=secret,id=sentry_auth_token,required=false <<'EOF'
set -eu
if [ "$VITE_SENTRY_SOURCEMAPS" = "true" ] \
  && [ -s /run/secrets/sentry_auth_token ] \
  && [ -n "$SENTRY_ORG" ] \
  && [ -n "$SENTRY_PROJECT" ]; then
  SENTRY_AUTH_TOKEN="$(cat /run/secrets/sentry_auth_token)"
  export SENTRY_AUTH_TOKEN
  npx --yes @sentry/cli sourcemaps inject ./dist
  npx --yes @sentry/cli sourcemaps upload ./dist \
    --org="$SENTRY_ORG" \
    --project="$SENTRY_PROJECT" \
    --release="$VITE_SENTRY_RELEASE"
fi
find dist -name '*.map' -delete
EOF

FROM nginx:1.27-alpine
ENV PORT=80 \
    NGINX_RESOLVER=127.0.0.11 \
    CONTROL_PLANE_URL=http://control-plane:8000 \
    STREAM_EDGE_URL=http://stream-edge:8001 \
    NGINX_ENVSUBST_FILTER="^(PORT|NGINX_RESOLVER|CONTROL_PLANE_URL|STREAM_EDGE_URL)$"

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
