#!/bin/bash

CACHE_DIR="/home/.cache/puppeteer"
export PUPPETEER_CACHE_DIR="$CACHE_DIR"

echo "=== AraBot startup ==="

# Eliminar SingletonLock
find /home -name "SingletonLock" -delete 2>/dev/null && echo "SingletonLock eliminado" || true

# Buscar Chrome ya instalado
CHROME_BIN=$(find "$CACHE_DIR" -name "chrome" -type f 2>/dev/null | head -1)

if [ -z "$CHROME_BIN" ]; then
    echo "Chrome no encontrado — descargando (puede tardar 3-5 min)..."
    node node_modules/.bin/puppeteer browsers install chrome 2>&1 || true
    CHROME_BIN=$(find "$CACHE_DIR" -name "chrome" -type f 2>/dev/null | head -1)
fi

if [ -n "$CHROME_BIN" ]; then
    echo "Chrome encontrado: $CHROME_BIN"
    export PUPPETEER_EXECUTABLE_PATH="$CHROME_BIN"
else
    echo "WARN: Chrome no encontrado en cache, puppeteer usara su default"
fi

echo "Iniciando AraBot..."
exec node index.js
