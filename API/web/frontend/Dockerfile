# Build production cho frontend (Next.js standalone output).
# NEXT_PUBLIC_API_URL được NƯỚNG vào bundle lúc build — đổi URL backend là phải
# build lại image. Mặc định "/api": Caddy proxy /api/* sang backend cùng domain.
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
# --legacy-peer-deps: @react-three/drei khai báo peer fiber ^9 nhưng project
# dùng fiber 10 alpha (giống cách node_modules local đã được cài).
RUN npm ci --legacy-peer-deps

COPY . .

ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM node:22-alpine

WORKDIR /app
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# standalone không tự kèm public/ và .next/static — copy tay theo docs.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/public ./public
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
