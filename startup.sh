#!/bin/bash
mkdir -p /home/data
cd /home/site/wwwroot
python3.11 -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --log-level info
