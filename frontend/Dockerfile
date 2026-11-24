FROM node:22-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

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
