"""Client for a locally running Ollama server (loopback only, proxies disabled)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config

BASE = f"http://{config.OLLAMA_HOST}:{config.OLLAMA_PORT}"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route via a proxy


class LLMUnavailable(Exception):
    pass


def _req(path: str, payload: dict | None = None, timeout: float = 5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
    try:
        with _opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        raise LLMUnavailable(f"Ollama returned HTTP {e.code}. {body}") from e
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise LLMUnavailable("Local Ollama server is not reachable. Start Ollama (or run `ollama serve`).") from e


def status(model: str) -> dict:
    try:
        tags = _req("/api/tags", timeout=2)
    except LLMUnavailable as e:
        return {"running": False, "model_present": False, "ready": False, "models": [], "message": str(e)}
    names = [m.get("name", "") for m in tags.get("models", [])]
    present = any(n == model or n.split(":")[0] == model or n == model + ":latest" for n in names)
    return {
        "running": True, "model_present": present, "ready": present, "models": names,
        "message": "Ready" if present else f"Model '{model}' is not installed - run `ollama pull {model}` while online",
    }


def chat_json(model: str, system: str, user: str, schema: dict | None, timeout: float = 300, num_ctx: int = 8192) -> str:
    payload = {
        "model": model, "stream": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": 0, "num_ctx": num_ctx, "seed": 7},
        "format": schema if schema else "json",
        "keep_alive": "10m",
    }
    out = _req("/api/chat", payload, timeout=timeout)
    try:
        return out["message"]["content"]
    except (KeyError, TypeError) as e:
        raise LLMUnavailable("Unexpected response from the local model server.") from e
