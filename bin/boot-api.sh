#!/usr/bin/env bash

set -ev

gunicorn \
  --bind 0.0.0.0:80 \
  --worker-class uvicorn.workers.UvicornWorker \
  --pythonpath /app \
  --workers 1 \
  --timeout 300 \
  --reload \
  application:server

