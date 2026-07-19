FROM node:24-alpine AS runtime

WORKDIR /app
COPY apps/web/package.json ./
COPY apps/web/server.js ./

RUN addgroup -S founder && adduser -S -G founder -u 10001 founder
USER founder

EXPOSE 3000
CMD ["node", "server.js"]
