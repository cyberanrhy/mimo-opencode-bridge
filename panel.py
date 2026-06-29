#!/usr/bin/env python3
"""
mimo-opencode-bridge Control Panel — Web UI for MiMo Proxy.
Zero external dependencies (stdlib only).
"""
import http.server
import json
import subprocess
import time
import os
import socket
import sys
import threading
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# ── Config ──────────────────────────────────────────────────────────────
PANEL_PORT = 12435
PROXY_PORT = 12434
PROXY_HOST = "127.0.0.1"
PROXY_LOG = "/tmp/mimo-proxy.log"
PROXY_DIR = str(Path(__file__).parent.resolve())
PROXY_SCRIPT = os.path.join(PROXY_DIR, "mimo_proxy.py")
MIMO_BIN = os.path.expanduser(
    "~/.npm-global/lib/node_modules/@mimo-ai/cli/node_modules/"
    "@mimo-ai/mimocode-linux-x64-baseline/bin/mimo"
)


def log(msg):
    print(f"[panel] {msg}", flush=True)


def check_port(port, host="127.0.0.1"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def http_get(url, timeout=5):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except Exception as e:
        return 0, str(e)


def http_post_json(url, data, timeout=30):
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            return resp.status, resp_body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        return e.code, err_body
    except Exception as e:
        return 0, str(e)


def read_log_file(filepath, lines=50):
    try:
        with open(filepath, "r", errors="replace") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except FileNotFoundError:
        return None
    except Exception as e:
        return f"[error: {e}]"


def proxy_running():
    return check_port(PROXY_PORT, PROXY_HOST)


def start_proxy():
    if proxy_running():
        return {"success": True, "message": "already running"}
    try:
        log_file = PROXY_LOG
        with open(log_file, "a") as lf:
            lf.write(f"\n--- panel start at {datetime.now().isoformat()} ---\n")
            proc = subprocess.Popen(
                [sys.executable, PROXY_SCRIPT, "--port", str(PROXY_PORT)],
                stdout=lf, stderr=lf, cwd=PROXY_DIR,
                stdin=subprocess.DEVNULL,
            )
        time.sleep(2)
        if proxy_running():
            return {"success": True, "message": f"PID {proc.pid}"}
        return {"success": False, "message": "failed to start"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def stop_proxy():
    try:
        subprocess.run(
            ["fuser", "-k", f"{PROXY_PORT}/tcp"],
            capture_output=True, timeout=5,
        )
        time.sleep(1)
        return {"success": True, "message": "stopped"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def restart_proxy():
    stop_proxy()
    time.sleep(1)
    return start_proxy()


def test_proxy():
    if not proxy_running():
        return {"success": False, "response": "proxy not running"}
    url = f"http://{PROXY_HOST}:{PROXY_PORT}/v1/chat/completions"
    payload = {
        "model": "mimo-auto",
        "messages": [{"role": "user", "content": "say hi in 3 words or less"}],
        "max_tokens": 10,
    }
    t0 = time.time()
    status, body = http_post_json(url, payload, timeout=30)
    elapsed = round(time.time() - t0, 3)
    if status == 200:
        try:
            data = json.loads(body)
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"success": True, "response": content.strip(), "time": elapsed}
        except Exception:
            return {"success": False, "response": body[:200], "time": elapsed}
    return {"success": False, "response": body[:200], "time": elapsed}


def get_status():
    alive = proxy_running()
    rt = None
    if alive:
        t0 = time.time()
        code, _ = http_get(f"http://{PROXY_HOST}:{PROXY_PORT}/v1/models")
        rt = round(time.time() - t0, 3)
        alive = code == 200
    return {
        "proxy": {
            "alive": alive,
            "port": PROXY_PORT,
            "response_time": rt,
        },
    }


# ── Web Handler ────────────────────────────────────────────────────────

class PanelHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log(f"{self.client_address[0]} - {fmt % args}")

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path in ("/", ""):
                self._serve_html()
            elif path == "/api/status":
                self._json(get_status())
            elif path == "/api/log":
                qs = parse_qs(parsed.query)
                lines = int(qs.get("lines", [50])[0])
                text = read_log_file(PROXY_LOG, lines)
                self._json({"log": text, "exists": text is not None})
            elif path == "/api/test":
                result = test_proxy()
                self._json(result)
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path == "/api/proxy/start":
                self._json(start_proxy())
            elif path == "/api/proxy/stop":
                self._json(stop_proxy())
            elif path == "/api/proxy/restart":
                self._json(restart_proxy())
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiMo — OpenCode Bridge</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#0f0;font-family:'Courier New',monospace;padding:20px;max-width:900px;margin:0 auto;min-height:100vh}
h1{font-size:1.3em;margin-bottom:4px;color:#0f0;text-transform:uppercase;letter-spacing:3px}
.sub{color:#080;font-size:0.75em;margin-bottom:20px}
.card{border:1px solid #0f0;padding:16px;background:#050505;position:relative}
.card-header{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.indicator{width:12px;height:12px;border-radius:50%;display:inline-block}
.indicator.alive{background:#0f0;box-shadow:0 0 8px #0f0;animation:pulse 2s infinite}
.indicator.dead{background:#500;box-shadow:0 0 4px #500}
.indicator.unknown{background:#440}
@keyframes pulse{0%{opacity:1}50%{opacity:0.5}100%{opacity:1}}
.card-title{font-size:1em;font-weight:bold;text-transform:uppercase;color:#0f0}
.card-body{font-size:0.8em;color:#0a0;line-height:1.6}
.card-body .row{display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid #0a0a0a}
.card-body .row:last-child{border:none}
.card-body .label{color:#060}
.card-body .value{color:#0f0}
.actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.btn{background:transparent;border:1px solid #0f0;color:#0f0;padding:6px 14px;cursor:pointer;font-family:inherit;font-size:0.78em;transition:all 0.2s}
.btn:hover{background:#0f0;color:#000;box-shadow:0 0 6px #0f0}
.btn.danger{border-color:#f00;color:#f00}
.btn.danger:hover{background:#f00;color:#000}
.btn:disabled{opacity:0.3;cursor:not-allowed}
.section-title{color:#0f0;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;margin:20px 0 10px;border-bottom:1px solid #0f0;padding-bottom:4px}
.log-box{background:#000;border:1px solid #0a0;padding:8px;font-size:0.68em;line-height:1.3;height:240px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;color:#080}
.log-box .bright{color:#0f0}
.test-result{background:#000;border:1px solid #0f0;padding:10px;font-size:0.75em;margin-top:8px;min-height:20px}
.test-result.success{border-color:#0f0}
.test-result.fail{border-color:#f00}
footer{margin-top:30px;padding-top:10px;border-top:1px solid #0a0a0a;font-size:0.7em;color:#060;text-align:center}
footer a{color:#080;text-decoration:none}
footer a:hover{color:#0f0}
.status-bar{display:flex;gap:16px;font-size:0.72em;color:#060;margin-bottom:16px;flex-wrap:wrap}
.status-bar span{display:flex;align-items:center;gap:4px}
.toast{position:fixed;bottom:20px;right:20px;background:#000;border:1px solid #0f0;padding:10px 16px;font-size:0.75em;z-index:999;max-width:400px;opacity:0;transition:opacity 0.3s}
.toast.show{opacity:1}
@media(max-width:700px){.card-grid{grid-template-columns:1fr}}
</style>
</head>
<body>

<div id="toast" class="toast"></div>

<h1>// MiMo — OpenCode Bridge</h1>
<div class="sub">[ proxy control panel v1.0 ]</div>

<div class="status-bar">
  <span id="statusIndicator"><span class="indicator unknown" style="width:6px;height:6px"></span> STATUS: <span id="statusText">checking...</span></span>
  <span>|</span>
  <span>PORT: <span id="portDisplay">12434</span></span>
  <span>|</span>
  <span id="timeDisplay">--:--:--</span>
  <span>|</span>
  <span><button id="langSwitch" onclick="toggleLang()" style="background:none;border:1px solid #0a0;color:#0f0;cursor:pointer;font-family:inherit;font-size:0.8em;padding:2px 6px">RU</button></span>
</div>

<div class="card">
  <div class="card-header">
    <span class="indicator unknown" id="proxyIndicator"></span>
    <span class="card-title">MIMO PROXY</span>
  </div>
  <div class="card-body" id="proxyBody">
    <div class="row"><span class="label">PORT</span><span class="value">12434</span></div>
    <div class="row"><span class="label" i18n="label_status">STATUS</span><span class="value" id="proxyStatus" i18n="scanning">scanning...</span></div>
    <div class="row"><span class="label" i18n="label_rt">RESPONSE TIME</span><span class="value" id="proxyRT">--</span></div>
    <div class="row"><span class="label">MODEL</span><span class="value">mimo-auto (free)</span></div>
  </div>
  <div class="actions">
    <button class="btn" id="btnStart" onclick="proxyAction('start')" i18n="btn_start">&gt; START</button>
    <button class="btn danger" id="btnStop" onclick="proxyAction('stop')" i18n="btn_stop">&gt; STOP</button>
    <button class="btn" onclick="proxyAction('restart')" i18n="btn_restart">&gt; RESTART</button>
    <button class="btn" onclick="testProxy()" i18n="btn_test">[ TEST ]</button>
  </div>
  <div id="testResult" class="test-result"><span style="color:#060" i18n="test_hint">TEST sends "say hi in 3 words" and shows response</span></div>
</div>

<div class="section-title" i18n="section_logs">// LOGS</div>
<div>
  <div style="font-size:0.7em;color:#060;margin-bottom:4px">/tmp/mimo-proxy.log</div>
  <div class="log-box" id="logBox"><span i18n="loading">Loading...</span></div>
</div>

<div class="section-title" i18n="section_quickinfo">// QUICK INFO</div>
<p style="font-size:0.75em;color:#060;line-height:1.8">
  <strong style="color:#0f0">START/STOP/RESTART</strong> — <span i18n="qi_control">control the proxy process</span>.<br>
  <strong style="color:#0f0">TEST</strong> — <span i18n="qi_test">send "say hi in 3 words" to check if proxy responds</span>.<br>
  <strong style="color:#0f0">ENDPOINT</strong> — <code style="color:#0f0">http://127.0.0.1:12434/v1</code><br>
  <strong style="color:#0f0">API KEY</strong> — <span i18n="qi_apikey">any value (e.g. "sk-proxy") or disable in config.json</span>.<br>
  <strong style="color:#0f0">MODELS</strong> — <span i18n="qi_models">mimo-auto (free), mimo-v2.5, mimo-v2.5-pro, mimo-v2.5-pro-ultraspeed, mimo-v2-flash</span>.<br>
  <strong style="color:#0f0">REQUIRES</strong> — <span i18n="qi_requires"><code>npm install -g @mimo-ai/cli</code></span>.<br>
  <strong style="color:#0f0">STATUS</strong> — <span i18n="qi_status">🟢 alive / 🔴 dead / 🟡 checking...</span>
</p>

<footer>
  <a href="https://github.com/cyberanrhy/mimo-opencode-bridge">mimo-opencode-bridge</a>
  &middot; Control Panel v1.0
  &middot; <span style="color:#060" i18n="footer_refresh">F5 — refresh</span>
</footer>

<script>
const LANG = {
  en: {
    lang_switch: 'RU',
    label_status: 'STATUS',
    label_rt: 'RESPONSE TIME',
    scanning: 'scanning...',
    btn_start: '> START',
    btn_stop: '> STOP',
    btn_restart: '> RESTART',
    btn_test: '[ TEST ]',
    test_hint: 'TEST sends "say hi in 3 words" and shows response',
    section_logs: '// LOGS',
    loading: 'Loading...',
    section_quickinfo: '// QUICK INFO',
    qi_control: 'control the proxy process',
    qi_test: 'send "say hi in 3 words" to check if proxy responds',
    qi_apikey: 'any value (e.g. "sk-proxy") or disable in config.json',
    qi_models: 'mimo-auto (free), mimo-v2.5, mimo-v2.5-pro, mimo-v2.5-pro-ultraspeed, mimo-v2-flash',
    qi_requires: 'npm install -g @mimo-ai/cli',
    qi_status: '🟢 alive / 🔴 dead / 🟡 checking...',
    footer_refresh: 'F5 — refresh',
    online: 'ONLINE',
    offline: 'OFFLINE',
    checking: 'checking...',
    unknown: 'unknown',
    sending: 'sending request...',
    ok: 'OK',
    fail: 'FAIL',
    no_response: 'no response',
    no_log: '[no log file]',
    empty: '[empty]',
    toast_network: 'Network error',
    toast_status: 'Status error',
    toast_started: 'Proxy started',
    toast_stopped: 'Proxy stopped',
    toast_restarted: 'Proxy restarted',
    toast_error: 'Error',
  },
  ru: {
    lang_switch: 'EN',
    label_status: 'STATUS',
    label_rt: 'RESPONSE TIME',
    scanning: 'scanning...',
    btn_start: '> START',
    btn_stop: '> STOP',
    btn_restart: '> RESTART',
    btn_test: '[ TEST ]',
    test_hint: 'Sends "say hi in 3 words" and shows the response',
    section_logs: '// LOGS',
    loading: 'Loading...',
    section_quickinfo: '// QUICK INFO',
    qi_control: 'control the proxy process',
    qi_test: 'send "say hi in 3 words" to check if proxy responds',
    qi_apikey: 'any value (e.g. "sk-proxy") or disable in config.json',
    qi_models: 'mimo-auto (free), mimo-v2.5, mimo-v2.5-pro, mimo-v2.5-pro-ultraspeed, mimo-v2-flash',
    qi_requires: 'npm install -g @mimo-ai/cli',
    qi_status: '🟢 alive / 🔴 dead / 🟡 checking...',
    footer_refresh: 'F5 — refresh',
    online: 'ONLINE',
    offline: 'OFFLINE',
    checking: 'checking...',
    unknown: 'unknown',
    sending: 'sending request...',
    ok: 'OK',
    fail: 'FAIL',
    no_response: 'no response',
    no_log: '[no log file]',
    empty: '[empty]',
    toast_network: 'Network error',
    toast_status: 'Status error',
    toast_started: 'Proxy started',
    toast_stopped: 'Proxy stopped',
    toast_restarted: 'Proxy restarted',
    toast_error: 'Error',
  }
};

let currentLang = localStorage.getItem('panel_lang') || 'ru';
document.getElementById('langSwitch').textContent = LANG[currentLang].lang_switch;

function t(key) {
  return LANG[currentLang][key] || key;
}

function applyLang() {
  document.querySelectorAll('[i18n]').forEach(el => {
    const key = el.getAttribute('i18n');
    el.innerHTML = t(key);
  });
  document.getElementById('langSwitch').textContent = t('lang_switch');
}

function toggleLang() {
  currentLang = currentLang === 'en' ? 'ru' : 'en';
  localStorage.setItem('panel_lang', currentLang);
  applyLang();
  fetchStatus();
}

function showToast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = '> ' + msg;
  t.style.borderColor = isError ? '#f00' : '#0f0';
  t.style.color = isError ? '#f00' : '#0f0';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 4000);
}

async function api(method, path) {
  try {
    const r = await fetch(path, { method });
    return await r.json();
  } catch (e) {
    return { error: e.message };
  }
}

async function fetchStatus() {
  const data = await api('GET', '/api/status');
  if (data.error) { showToast(t('toast_status') + ': ' + data.error, true); return; }
  const s = data.proxy;
  const ind = document.getElementById('proxyIndicator');
  const st = document.getElementById('proxyStatus');
  const rt = document.getElementById('proxyRT');
  const btnStart = document.getElementById('btnStart');
  const btnStop = document.getElementById('btnStop');

  if (s.alive) {
    ind.className = 'indicator alive';
    st.textContent = t('online');
    st.style.color = '#0f0';
    rt.textContent = s.response_time ? s.response_time + 's' : t('checking');
    btnStart.disabled = true;
    btnStop.disabled = false;
  } else {
    ind.className = 'indicator dead';
    st.textContent = t('offline');
    st.style.color = '#f00';
    rt.textContent = '--';
    btnStart.disabled = false;
    btnStop.disabled = true;
  }
  document.getElementById('timeDisplay').textContent = new Date().toLocaleTimeString();
  document.getElementById('statusText').textContent = st.textContent;
}

async function fetchLogs() {
  const box = document.getElementById('logBox');
  if (!box) return;
  const data = await api('GET', '/api/log');
  if (data.log === null) {
    box.textContent = t('no_log');
  } else {
    box.textContent = data.log || t('empty');
  }
  box.scrollTop = box.scrollHeight;
}

async function proxyAction(action) {
  const result = await api('POST', '/api/proxy/' + action);
  if (result.success) {
    const key = action === 'start' ? 'toast_started' : (action === 'stop' ? 'toast_stopped' : 'toast_restarted');
    showToast(t(key) + (result.message ? ': ' + result.message : ''), false);
    setTimeout(fetchStatus, 2000);
  } else {
    showToast(t('toast_error') + ': ' + (result.message || ''), true);
  }
}

async function testProxy() {
  const div = document.getElementById('testResult');
  div.textContent = '> ' + t('sending');
  div.className = 'test-result';
  const result = await api('GET', '/api/test');
  if (result.success) {
    div.className = 'test-result success';
    div.textContent = '> ' + t('ok') + ' (' + result.time + 's): "' + result.response + '"';
  } else {
    div.className = 'test-result fail';
    div.textContent = '> ' + t('fail') + ' (' + result.time + 's): ' + (result.response || t('no_response'));
  }
}

applyLang();
fetchStatus();
fetchLogs();
setInterval(fetchStatus, 10000);
setInterval(fetchLogs, 5000);
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────

class ThreadedPanelServer(ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_forever(host="0.0.0.0", port=PANEL_PORT):
    while True:
        try:
            server = ThreadedPanelServer((host, port), PanelHandler)
            log(f"Panel listening on http://{host}:{port}")
            log(f"Open http://127.0.0.1:{port} in your browser")
            server.serve_forever()
        except KeyboardInterrupt:
            log("shutting down")
            return
        except Exception as e:
            log(f"Server error ({e}), restarting in 2s...")
            time.sleep(2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MiMo — OpenCode Bridge Panel")
    parser.add_argument("--port", type=int, default=PANEL_PORT)
    args = parser.parse_args()
    serve_forever(port=args.port)
