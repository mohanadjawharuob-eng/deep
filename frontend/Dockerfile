# The website, built once and served as static files.
#
# Two stages. The first has Node and turns the source into a folder of HTML,
# CSS and JavaScript. The second has no Node at all — just Caddy and those
# files — because a web server that cannot run a build is a web server that
# cannot be talked into running one.
#
# Caddy also reverse-proxies /api to the backend, so the browser sees a single
# origin. That removes CORS from the picture entirely and means the session
# cookie, the API and the interface all agree about where "here" is.

# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Dependencies first: this layer is cached until package-lock.json changes,
# so an ordinary edit to a component does not re-download the internet.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .

# `npm run build` typechecks before it bundles, so a type error fails the
# image rather than shipping a broken interface.
RUN npm run build

# --------------------------------------------------------------------------
# Serve
# --------------------------------------------------------------------------
FROM caddy:2-alpine

COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

# Caddy's own healthcheck target; the platform's is behind /api.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:80/ || exit 1

EXPOSE 80 443
