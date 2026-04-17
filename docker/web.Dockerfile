FROM node:20-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json /app/
COPY apps/web/package.json /app/apps/web/package.json

RUN npm ci

COPY . /app

CMD ["npm", "--prefix", "apps/web", "run", "dev"]
