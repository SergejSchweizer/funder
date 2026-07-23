FROM node:24-alpine AS runtime

WORKDIR /app
COPY apps/web/package.json ./
COPY apps/web/server.js ./

RUN addgroup -S camovar && adduser -S -G camovar -u 10001 camovar
USER camovar

EXPOSE 3000
CMD ["node", "server.js"]
