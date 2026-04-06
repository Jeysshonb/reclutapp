#!/bin/bash
# Startup AraBot — Chrome ya viene instalado por npm install via PUPPETEER_CACHE_DIR
find /home -name "SingletonLock" -delete 2>/dev/null || true
exec node index.js
