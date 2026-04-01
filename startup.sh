#!/bin/bash
mkdir -p /home/data
cd /home/site/wwwroot
source antenv/bin/activate
gunicorn -w 1 -k uvicorn.workers.UvicornWorker app.main:app \
  --bind 0.0.0.0:8000 \
  --timeout 600 \
  --access-logfile '-' \
  --error-logfile '-'
