FROM node:20-alpine AS build

ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" \
    && npm ci

COPY frontend/ ./
RUN npm run build

FROM nginx:alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
