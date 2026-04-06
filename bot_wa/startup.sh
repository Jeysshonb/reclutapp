#!/bin/bash
set -e

CACHE_DIR="/home/.cache/puppeteer"
export PUPPETEER_CACHE_DIR="$CACHE_DIR"

echo "=== AraBot startup ==="
echo "Buscando Chrome en $CACHE_DIR ..."

# Eliminar SingletonLock si existe
find /home -name "SingletonLock" -delete 2>/dev/null && echo "SingletonLock eliminado" || true

# Si no hay Chrome, descargarlo
if [ -z "$(find "$CACHE_DIR" -name "chrome" -type f 2>/dev/null | head -1)" ]; then
    echo "Chrome no encontrado — descargando..."
    node node_modules/.bin/puppeteer browsers install chrome 2>&1 || \
    npx puppeteer browsers install chrome 2>&1 || \
    echo "WARN: descarga falló, intentando de todas formas..."
else
    echo "Chrome encontrado en cache"
fi

echo "Iniciando bot Node.js..."
exec node index.js
