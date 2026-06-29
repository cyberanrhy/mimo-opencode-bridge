#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "============================================"
echo "  MiMo — OpenCode Bridge Setup & Launch"
echo "============================================"

# ─── Node.js / npm check ────────────────────────
if ! command -v node &>/dev/null; then
  echo "[FAIL] Node.js not found. Install it: https://nodejs.org"
  exit 1
fi

if ! command -v npm &>/dev/null; then
  echo "[FAIL] npm not found."
  exit 1
fi

echo "[OK] Node.js $(node -v) / npm $(npm -v)"

# ─── @mimo-ai/cli ──────────────────────────────
if ! npm list -g @mimo-ai/cli --depth=0 &>/dev/null; then
  echo "[..] Installing @mimo-ai/cli globally ..."
  npm install -g @mimo-ai/cli
  echo "[OK] @mimo-ai/cli installed"
else
  echo "[OK] @mimo-ai/cli already installed"
fi

# ─── Python 3 ──────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "[FAIL] Python 3 not found."
  exit 1
fi
echo "[OK] Python 3 $(python3 --version | cut -d' ' -f2)"

# ─── Config ────────────────────────────────────
if [ ! -f config.json ]; then
  if [ -f config.json.example ]; then
    cp config.json.example config.json
    echo "[OK] config.json created from config.json.example"
  else
    echo "[FAIL] config.json.example not found"
    exit 1
  fi
else
  echo "[OK] config.json exists"
fi

# ─── OpenCode Desktop config hint ──────────────
OPENCODE_CFG="$HOME/.config/opencode/opencode.json"
if [ -f "$OPENCODE_CFG" ]; then
  if grep -q "mimo" "$OPENCODE_CFG" 2>/dev/null; then
    echo "[OK] OpenCode provider 'mimo' already configured"
  else
    echo "[HINT] Add this provider to $OPENCODE_CFG:"
    echo '       "mimo": { "apiBase": "http://127.0.0.1:12434/v1", "type": "openai", "apiKey": "sk-mimo" }'
  fi
else
  echo "[HINT] OpenCode config not found at $OPENCODE_CFG"
fi

# ─── Launch ────────────────────────────────────
echo ""
echo "Starting proxy on http://127.0.0.1:12434"
echo "Panel at      http://127.0.0.1:12435"
echo "============================================"

# Start panel in background
python3 panel.py --port 12435 &
PANEL_PID=$!
echo "[OK] Panel started (PID $PANEL_PID)"

# Start proxy in foreground
exec python3 mimo_proxy.py --port 12434
