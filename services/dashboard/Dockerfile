# services/dashboard/Dockerfile

# ---- Stage 1: build the Vite app ------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps from a lockfile-less manifest (deterministic enough for now;
# we'll lock it once the surface area stops moving).
COPY package.json ./
RUN npm install --no-audit --no-fund --loglevel=error

# Bring in source and build.
COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
COPY tailwind.config.js postcss.config.js index.html ./
COPY src/ ./src/

RUN npm run build

# ---- Stage 2: serve via nginx --------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Drop the default config and replace with our reverse-proxy template.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/dashboard.conf

# The Vite build output goes to /usr/share/nginx/html.
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080

# nginx in foreground so Docker can supervise it.
CMD ["nginx", "-g", "daemon off;"]
