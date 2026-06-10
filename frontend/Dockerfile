# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- runtime stage ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-locations.conf /etc/nginx/snippets/horus-locations.conf
# SSL server block kept OUTSIDE conf.d; enabled at startup only if certs exist
COPY nginx-ssl.conf /etc/nginx/horus/ssl.conf
COPY docker/45-enable-ssl.sh /docker-entrypoint.d/45-enable-ssl.sh
RUN chmod +x /docker-entrypoint.d/45-enable-ssl.sh

EXPOSE 80 443
