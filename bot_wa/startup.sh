#!/bin/bash
# Instalar libs que necesita Chrome en Azure App Service (Debian-based)
echo "Instalando dependencias de Chrome..."
apt-get install -y -q \
  libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libx11-6 libxcb1 \
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
  libgbm1 libpango-1.0-0 libcairo2 libasound2 \
  2>/dev/null || true

# Eliminar SingletonLock
find /home -name "SingletonLock" -delete 2>/dev/null || true

echo "Iniciando AraBot..."
exec node index.js
