FROM node:20-slim

# Instalar Chromium del sistema + todas sus dependencias de una vez
# Esto queda en la imagen — no hay apt-get en cada reinicio
RUN apt-get update && apt-get install -y \
    chromium \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Decirle a puppeteer que use el Chromium del sistema
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV PORT=8080

# Sesion WhatsApp en /home que persiste entre reinicios en Azure
ENV SESSION_DIR=/home/.arabot_session
ENV PUPPETEER_CACHE_DIR=/home/.cache/puppeteer

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

EXPOSE 8080
CMD ["node", "index.js"]
