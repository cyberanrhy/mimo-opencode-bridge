#!/usr/bin/env python3
"""
mimo-opencode-bridge — OpenAI-compatible proxy for MiMoCode (Xiaomi MiMo models).
Use with OpenCode Desktop as a custom provider.
"""
import subprocess
import json
import sys
import os
import re
import time
import uuid
import signal
import socket
import select
import logging
import threading
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime

# ─── Config ────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "port": 12434,
    "host": "127.0.0.1",
    "default_model": "mimo-auto",
    "mimo_bin": "",
    "timeout": 180,
    "log_file": "/tmp/mimo-proxy.log",
    "log_level": "INFO",
    "api_keys": [],
    "max_concurrency": 1,
}

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.json"

# ─── Globals ───────────────────────────────────────────────────────────────

config = dict(DEFAULT_CONFIG)
mimo_bin = None
request_lock = threading.Semaphore()
logger = logging.getLogger("mimo-proxy")

# ─── Model map ─────────────────────────────────────────────────────────────

MODEL_MAP = {
    "mimo-auto": "mimo/mimo-auto",
    "mimo-v2.5": "xiaomi/mimo-v2.5",
    "mimo-v2.5-pro": "xiaomi/mimo-v2.5-pro",
    "mimo-v2.5-pro-ultraspeed": "xiaomi/mimo-v2.5-pro-ultraspeed",
    "mimo-v2-flash": "mimo/mimo-v2-flash",
    "mimo/mimo-auto": "mimo/mimo-auto",
    "xiaomi/mimo-v2.5": "xiaomi/mimo-v2.5",
    "xiaomi/mimo-v2.5-pro": "xiaomi/mimo-v2.5-pro",
    "xiaomi/mimo-v2.5-pro-ultraspeed": "xiaomi/mimo-v2.5-pro-ultraspeed",
    "mimo/mimo-v2-flash": "mimo/mimo-v2-flash",
}

MODELS_LIST = [
    {"id": "mimo-auto", "object": "model", "created": 1718000001, "owned_by": "mimo"},
    {"id": "mimo-v2.5", "object": "model", "created": 1718000002, "owned_by": "xiaomi"},
    {"id": "mimo-v2.5-pro", "object": "model", "created": 1718000003, "owned_by": "xiaomi"},
    {"id": "mimo-v2.5-pro-ultraspeed", "object": "model", "created": 1718000004, "owned_by": "xiaomi"},
    {"id": "mimo-v2-flash", "object": "model", "created": 1718000005, "owned_by": "mimo"},
]

# ─── Helpers ───────────────────────────────────────────────────────────────

def load_config():
    global config
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                file_cfg = json.load(f)
            config.update(file_cfg)
            logger.info(f"Loaded config from {CONFIG_FILE}")
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    else:
        logger.info("No config.json found, using defaults")


def supports_avx2():
    try:
        with open("/proc/cpuinfo") as f:
            return "avx2" in f.read().lower()
    except Exception:
        return False


def find_mimo_bin():
    npm_root = os.path.expanduser("~/.npm-global")
    has_avx2 = supports_avx2()
    logger.info(f"CPU AVX2: {'yes' if has_avx2 else 'no'}, preferring baseline")

    # Order by preference: baseline (stable) > avx2
    x64_names = ["mimocode-linux-x64-baseline", "mimocode-linux-x64"]
    if has_avx2:
        x64_names.reverse()

    candidates = []

    # Config path
    if config.get("mimo_bin"):
        candidates.append(Path(config["mimo_bin"]))

    # Global npm
    for arch in x64_names:
        p = Path(npm_root) / "lib/node_modules/@mimo-ai" / arch / "bin" / "mimo"
        candidates.append(p)

    # Inside cli node_modules
    for arch in x64_names:
        p = Path(npm_root) / "lib/node_modules/@mimo-ai/cli/node_modules/@mimo-ai" / arch / "bin" / "mimo"
        candidates.append(p)

    # which
    try:
        result = subprocess.run(["which", "mimo"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            candidates.append(Path(result.stdout.strip()))
    except Exception:
        pass

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            logger.info(f"Found mimo binary: {candidate}")
            return str(candidate.resolve())

    logger.error("Mimo binary not found. Install: npm install -g @mimo-ai/cli")
    return None


def format_messages(messages):
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text", ""))
            content = " ".join(texts)
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
    return "\n".join(parts)


def run_mimo(model_provider, prompt_text, timeout):
    """Run mimo in a subprocess with timeout and forced kill."""
    cmd = [mimo_bin, "run", "-m", model_provider, "--format", "json"]

    env = os.environ.copy()
    env["MIMOCODE_NO_TELEMETRY"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    try:
        stdout_bytes, stderr_bytes = proc.communicate(input=prompt_text.encode("utf-8"), timeout=timeout)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return stdout, stderr, proc.returncode
    except subprocess.TimeoutExpired:
        logger.warning(f"mimo run timed out after {timeout}s, killing PID {proc.pid}")
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return "", f"Timeout after {timeout}s", -1


def extract_text_from_output(output):
    text_parts = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            t = obj.get("type")
            if t == "text":
                text_parts.append(obj["part"].get("text", ""))
            elif t == "reasoning":
                text_parts.append(obj["part"].get("text", ""))
            elif t == "tool_use":
                out = obj.get("part", {}).get("state", {}).get("output", "")
                if out:
                    text_parts.append(f"\n[tool]\n{out}\n")
        except json.JSONDecodeError:
            pass
    return "".join(text_parts)


def extract_token_usage(output):
    tokens = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "step_finish":
                t = obj.get("part", {}).get("tokens", {})
                tokens["prompt_tokens"] = t.get("input", 0)
                tokens["completion_tokens"] = t.get("output", 0)
                tokens["total_tokens"] = t.get("total", tokens.get("prompt_tokens", 0) + tokens.get("completion_tokens", 0))
        except json.JSONDecodeError:
            pass
    return tokens


def check_api_key(headers):
    if not config.get("api_keys"):
        return True
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        key = auth[7:]
        if key in config["api_keys"]:
            return True
    return False


# ─── HTTP Handler ──────────────────────────────────────────────────────────

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info(f"{self.client_address[0]} - {fmt % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/v1/models":
            self._send_json({"object": "list", "data": MODELS_LIST})
        elif path in ("/health", "/"):
            self._send_json({"status": "ok", "provider": "mimo-opencode-bridge", "version": "1.0.0"})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        # Disable Nagle's algorithm for real-time SSE
        try:
            self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        path = urlparse(self.path).path
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json({"error": "not found"}, 404)
            return

        if not check_api_key(self.headers):
            self._send_json({"error": "unauthorized"}, 401)
            return

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        model = req.get("model", config.get("default_model", "mimo-auto"))
        messages = req.get("messages", [])
        stream = req.get("stream", False)

        mapped_model = MODEL_MAP.get(model, model)
        prompt_text = format_messages(messages)
        timeout = config.get("timeout", 180)

        if not prompt_text.strip():
            self._send_json({"error": "empty messages"}, 400)
            return

        if stream:
            self._handle_stream(mapped_model, model, prompt_text, timeout)
        else:
            self._handle_nonstream(mapped_model, model, prompt_text, timeout)

    def _handle_nonstream(self, mapped_model, model_name, prompt_text, timeout):
        acquired = request_lock.acquire(timeout=timeout)
        if not acquired:
            self._send_json({"error": "server busy, try again"}, 503)
            return
        try:
            stdout, stderr, retcode = run_mimo(mapped_model, prompt_text, timeout)
            if retcode != 0:
                err_msg = stderr[:300] if stderr else f"exit code {retcode}"
                self._send_json({"error": f"mimo run failed: {err_msg}"}, 500)
                return

            text = extract_text_from_output(stdout)
            usage = extract_token_usage(stdout)

            response = {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": text,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }
            self._send_json(response)
        finally:
            request_lock.release()

    def _handle_stream(self, mapped_model, model_name, prompt_text, timeout):
        acquired = request_lock.acquire(timeout=timeout)
        if not acquired:
            self._send_json({"error": "server busy, try again"}, 503)
            return
        proc = None
        try:
            cmd = [mimo_bin, "run", "-m", mapped_model, "--format", "json"]
            env = os.environ.copy()
            env["MIMOCODE_NO_TELEMETRY"] = "1"

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.flush()

            sent_text = ""

            # All chunks in one response share the same ID per OpenAI spec
            stream_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created_ts = int(time.time())

            # Send initial role chunk so client knows connection is alive
            role_chunk = {
                "id": stream_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            self._write_sse(role_chunk)

            # Write prompt
            proc.stdin.write(prompt_text.encode("utf-8"))
            proc.stdin.close()

            # Read stdout with select() — non-blocking, checks deadline every 1s
            deadline = time.time() + timeout
            stdout_fd = proc.stdout.fileno()
            while True:
                readable, _, _ = select.select([stdout_fd], [], [], 1.0)
                if not readable:
                    if time.time() > deadline:
                        logger.warning(f"Stream timeout, killing PID {proc.pid}")
                        proc.kill()
                        break
                    continue

                line_bytes = proc.stdout.readline()
                if not line_bytes:
                    break  # EOF

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    event_type = obj.get("type")
                    # Forward text, reasoning, and tool_use as content chunks
                    if event_type == "text":
                        text_chunk = obj["part"].get("text", "")
                    elif event_type == "reasoning":
                        text_chunk = obj["part"].get("text", "")
                    elif event_type == "tool_use":
                        tool_input = obj.get("part", {}).get("state", {}).get("input", {})
                        tool_name = tool_input.get("command", "") if tool_input else ""
                        tool_output = obj.get("part", {}).get("state", {}).get("output", "")
                        if tool_output:
                            text_chunk = f"\n[tool: {tool_name}]\n{tool_output}\n"
                        else:
                            text_chunk = f"\n[running: {tool_name}]...\n"
                    else:
                        text_chunk = None

                    if text_chunk:
                        sent_text += text_chunk
                        chunk = {
                            "id": stream_id,
                            "object": "chat.completion.chunk",
                            "created": created_ts,
                            "model": model_name,
                            "choices": [{"index": 0, "delta": {"content": text_chunk}, "finish_reason": None}],
                        }
                        self._write_sse(chunk)
                except json.JSONDecodeError:
                    pass

            proc.wait(timeout=10)

            finish = {
                "id": stream_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self._write_sse(finish)
            self._write_raw("data: [DONE]\n\n")

            logger.info(f"Streamed {len(sent_text)} chars for model {model_name}")
        except (BrokenPipeError, ConnectionResetError, OSError):
            logger.info("Client disconnected, killing subprocess")
        finally:
            if proc and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            request_lock.release()

    def _write_sse(self, chunk):
        self._write_raw(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n")

    def _write_raw(self, text):
        self.wfile.write(text.encode())
        self.wfile.flush()


class ThreadedProxyServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


# ─── Main ──────────────────────────────────────────────────────────────────

def setup_logging():
    log_file = config.get("log_file", "/tmp/mimo-proxy.log")
    log_level = getattr(logging, config.get("log_level", "INFO").upper(), logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    handler_file = logging.FileHandler(log_file)
    handler_file.setFormatter(formatter)

    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.setFormatter(formatter)

    logger.setLevel(log_level)
    logger.addHandler(handler_file)
    logger.addHandler(handler_stdout)


def cleanup_sessions():
    """Clean old sessions to prevent database bloat."""
    try:
        result = subprocess.run(
            [mimo_bin, "session", "list", "--format", "json", "-n", "1"],
            capture_output=True, text=True, timeout=10,
        )
        logger.info(f"Session check: {result.stdout.strip()[:100] or 'ok'}")
    except Exception as e:
        logger.warning(f"Session check skipped: {e}")


def main():
    parser = argparse.ArgumentParser(description="MiMo — OpenCode Bridge Proxy")
    parser.add_argument("--port", type=int, default=0, help="Port to listen on")
    parser.add_argument("--host", type=str, default="", help="Host to bind to")
    parser.add_argument("--config", type=str, default=str(CONFIG_FILE), help="Config file path")
    args = parser.parse_args()

    load_config()

    if args.port:
        config["port"] = args.port
    if args.host:
        config["host"] = args.host

    setup_logging()

    global mimo_bin
    mimo_bin = find_mimo_bin()
    if not mimo_bin:
        logger.error("Cannot find mimo binary. Install: npm install -g @mimo-ai/cli")
        sys.exit(1)

    logger.info("Starting MiMo — OpenCode Bridge")
    logger.info(f"Config: port={config['port']}, host={config['host']}")
    logger.info(f"Binary: {mimo_bin}")
    logger.info(f"Default model: {config['default_model']}")
    logger.info(f"Concurrency: {config.get('max_concurrency', 1)}")
    logger.info(f"API keys: {'configured' if config.get('api_keys') else 'none (open access)'}")

    cleanup_sessions()

    server = ThreadedProxyServer((config["host"], config["port"]), ProxyHandler)
    port = server.server_address[1]
    logger.info(f"Proxy running on http://{config['host']}:{port}")
    logger.info(f"OpenAI endpoint: http://{config['host']}:{port}/v1")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
