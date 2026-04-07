FROM node:20-slim

# Sin Chrome — Baileys usa WebSocket directo
ENV PORT=8080
ENV SESSION_DIR=/home/.arabot_session

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

EXPOSE 8080
CMD ["node", "index.js"]
