#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -f config.json ]; then
  cp config.json.example config.json
  echo "Created config.json from config.json.example — review it before running."
fi

echo "Starting MiMo — OpenCode Bridge ..."
exec python3 mimo_proxy.py
