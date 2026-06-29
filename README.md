![MiMo — OpenCode Bridge](preview.jpg)

# MiMo — OpenCode Bridge 🚀

**OpenAI-compatible proxy for Xiaomi MiMo free AI models.**  
Connect Xiaomi's MiMo models to **OpenCode Desktop**, **Claude Code**, **Cline**, **Continue**, or any OpenAI-compatible client.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![Node.js 18+](https://img.shields.io/badge/node-18+-brightgreen.svg)](https://nodejs.org)
[![MiMoCode 0.1.3](https://img.shields.io/badge/mimocode-0.1.3-purple)](https://github.com/XiaomiMiMo/MiMo-Code)

> **No API keys required** — uses MiMoCode's built-in free model `mimo-auto` (zero cost).

---

## 📌 What is this?

`mimo-opencode-bridge` is a lightweight proxy that translates **OpenAI API calls** into **MiMoCode CLI** commands, giving you access to Xiaomi MiMo AI models through any OpenAI-compatible tool.

It solves the problem of MiMo Web API requiring a proprietary bundled provider — by running MiMoCode locally and proxying through it.

---

## ✨ Features

| Feature | Details |
|---------|---------|
| 🆓 **Free model** | `mimo-auto` — 0 cost, no API key needed |
| 🔄 **Streaming** | Real-time SSE streaming |
| 🧵 **Concurrency control** | Queue system prevents DB corruption |
| ⏱ **Smart timeout** | Auto-kills stale processes |
| 🖥 **Web panel** | Built-in control UI (start/stop/restart/logs/test) |
| 🔌 **OpenAI-compatible** | Works with any `/v1/chat/completions` client |
| 🔒 **Optional auth** | API key whitelist support |

## 🧩 Available Models

| Model ID | Description | Cost |
|----------|-------------|------|
| `mimo-auto` | MiMo Auto (smart selection) | **Free** |
| `mimo-v2-flash` | MiMo V2 Flash (lightweight) | Depends |
| `mimo-v2.5` | Xiaomi MiMo V2.5 | Depends |
| `mimo-v2.5-pro` | Xiaomi MiMo V2.5 Pro (flagship) | Depends |
| `mimo-v2.5-pro-ultraspeed` | MiMo V2.5 Pro UltraSpeed | Depends |

---

## 📦 Requirements

- **Node.js 18+** — for [MiMoCode CLI](https://github.com/XiaomiMiMo/MiMo-Code) (`@mimo-ai/cli`)
- **Python 3.8+** — for the bridge proxy
- **Linux x86_64** (other platforms may work but untested)

---

## 🔧 Quick Start

### 1. Install MiMoCode CLI

```bash
npm install -g @mimo-ai/cli

# Verify
mimo --version        # → 0.1.3
mimo models           # → mimo/mimo-auto, xiaomi/mimo-v2.5, ...
```

### 2. Clone & run

```bash
git clone https://github.com/cyberanrhy/mimo-opencode-bridge.git
cd mimo-opencode-bridge
bash start.sh
```

The proxy starts on `http://127.0.0.1:12434`.

### 3. Verify

```bash
# Check models
curl http://127.0.0.1:12434/v1/models

# Send a message
curl -X POST http://127.0.0.1:12434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mimo-auto","messages":[{"role":"user","content":"Say hello in Russian"}]}'
# → {"choices":[{"message":{"content":"Привет"}}]}
```

---

## 🖥 Web Control Panel

Start the panel to manage the proxy from your browser:

```bash
python3 panel.py
# Open http://127.0.0.1:12435
```

Features: start/stop/restart, live logs, test request, response time monitor.

---

## 🔗 Usage with Clients

### OpenCode Desktop

Add to `~/.config/opencode/opencode.json`:

```json
{
  "provider": {
    "mimo": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "MiMo Bridge",
      "options": {
        "baseURL": "http://127.0.0.1:12434/v1",
        "apiKey": "sk-proxy",
        "timeout": 180000,
        "headerTimeout": 60000,
        "chunkTimeout": 110000
      },
      "models": {
        "mimo-auto": { "name": "MiMo Auto (free)" },
        "mimo-v2.5": { "name": "MiMo V2.5" },
        "mimo-v2.5-pro": { "name": "MiMo V2.5 Pro" },
        "mimo-v2.5-pro-ultraspeed": { "name": "MiMo V2.5 Pro UltraSpeed" },
        "mimo-v2-flash": { "name": "MiMo V2 Flash" }
      }
    }
  }
}
```

### Claude Code

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:12434/v1"
export ANTHROPIC_AUTH_TOKEN="sk-proxy"
```

### Continue / Cline

Configure as any OpenAI-compatible provider with `baseURL: http://127.0.0.1:12434/v1`.

---

## ⚙️ Configuration

Copy `config.json.example` to `config.json`:

| Field | Default | Description |
|-------|---------|-------------|
| `port` | `12434` | Proxy listen port |
| `host` | `127.0.0.1` | Bind address |
| `default_model` | `mimo-auto` | Default model |
| `timeout` | `180` | Request timeout (seconds) |
| `log_file` | `/tmp/mimo-proxy.log` | Log file |
| `log_level` | `INFO` | Log level |
| `api_keys` | `[]` | Restrict access (empty = open) |
| `max_concurrency` | `1` | Max concurrent requests |
| `mimo_bin` | `""` | Force binary path (auto-detect) |

---

## 🚀 Systemd Autostart

```ini
# ~/.config/systemd/user/mimo-proxy.service
[Unit]
Description=MiMo — OpenCode Bridge
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/mimo_opencode_bridge/mimo_proxy.py --port 12434
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now mimo-proxy.service
systemctl --user status mimo-proxy.service
```

---

## ❓ Troubleshooting

**Proxy won't start / "mimo binary not found"**
```bash
npm install -g @mimo-ai/cli
which mimo
```

**Multiple "mimo run" processes stuck**
```bash
kill $(ps aux | grep "mimo run" | grep -v grep | awk '{print $2}')
systemctl --user restart mimo-proxy.service
```

**OpenCode shows error with MiMo models**
1. `curl http://127.0.0.1:12434/v1/models` — is proxy alive?
2. Check `~/.config/opencode/opencode.json` syntax
3. Restart OpenCode Desktop

**503 "server busy"**
Another request is in progress. The bridge processes one at a time using a queue to prevent database corruption. Retry shortly.

---

## 📁 Project Structure

```
mimo-opencode-bridge/
├── mimo_proxy.py         # 🔧 Proxy server (main)
├── panel.py              # 🖥 Web control panel
├── config.json.example   # 📋 Configuration template
├── start.sh              # 🚀 Start script
├── .gitignore
├── LICENSE               # MIT
└── README.md             # 📖 This file
```

---

## 🔍 Keywords / Поисковые теги

`xiaomi mimo` `mimo model` `mimocode` `бесплатная нейросеть` `free ai model`  
`opencode provider` `opencode custom provider` `opencode mimo`  
`openai compatible proxy` `ai proxy` `llm proxy`  
`mimo api` `xiaomi ai` `miмо` `mimo v2.5` `mimo-auto free`  
`claude code mimo` `continue dev mimo` `cline mimo`

---

## 📄 License

MIT

---

## 🙏 Credits

- [Xiaomi MiMo Team](https://mimo.xiaomi.com/coder) for MiMoCode
- [OpenCode](https://opencode.ai) for the extensible AI platform
