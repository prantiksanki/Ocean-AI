"""Thin Ollama client: JSON mode, validation/retry, disk cache, usage counters."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("FORGE_MODEL", "mistral")
JUDGE_MODEL = os.environ.get("FORGE_JUDGE_MODEL", "mistral")
EMBED_MODEL = os.environ.get("FORGE_EMBED_MODEL", "nomic-embed-text")
CACHE_DIR = Path(os.environ.get("FORGE_CACHE", ".forge_cache"))


class Usage:
    """Global counters used for budget enforcement and the report."""

    calls = 0
    cached = 0
    seconds = 0.0
    chars_in = 0
    chars_out = 0

    @classmethod
    def snapshot(cls) -> dict:
        return {"calls": cls.calls, "cached": cls.cached, "seconds": round(cls.seconds, 1),
                "chars_in": cls.chars_in, "chars_out": cls.chars_out}


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _cache_get(k: str):
    p = CACHE_DIR / f"{k}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _cache_put(k: str, v) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.0,
         json_mode: bool = False, use_cache: bool = True, timeout: int = 900,
         num_predict: int = 500) -> str:
    model = model or DEFAULT_MODEL
    k = _key("chat", model, messages, temperature, json_mode, num_predict)
    if use_cache and (hit := _cache_get(k)) is not None:
        Usage.cached += 1
        return hit
    body = {"model": model, "messages": messages, "stream": False,
            "options": {"temperature": temperature, "seed": 7, "num_predict": num_predict,
                        "num_ctx": 4096}}
    if json_mode:
        body["format"] = "json"
    t0 = time.time()
    for attempt in range(3):  # a stalled call is retried instead of killing a long run
        try:
            r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=min(timeout, 400))
            break
        except (requests.ReadTimeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(5)
    r.raise_for_status()
    out = r.json()["message"]["content"]
    Usage.calls += 1
    Usage.seconds += time.time() - t0
    Usage.chars_in += sum(len(m["content"]) for m in messages)
    Usage.chars_out += len(out)
    if use_cache:
        _cache_put(k, out)
    return out


def extract_json(text: str):
    """Parse JSON from a model reply, tolerating fences and surrounding prose."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s, e = text.find(open_c), text.rfind(close_c)
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model output")


def chat_json(system: str, user: str, validate=None, model: str | None = None,
              retries: int = 3, temperature: float = 0.0):
    """Ask for JSON; validate(obj) must raise on bad shape. Retries with a repair hint."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_err = None
    for attempt in range(retries):
        # vary temperature slightly on retries so the cache doesn't replay a bad answer
        raw = chat(messages, model=model, json_mode=True,
                   temperature=temperature + 0.2 * attempt)
        try:
            obj = extract_json(raw)
            if validate:
                obj = validate(obj) or obj
            return obj
        except Exception as e:  # noqa: BLE001
            last_err = e
            messages = messages[:2] + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That output was invalid ({e}). "
                                            "Reply again with ONLY valid JSON matching the requested shape."}]
    raise RuntimeError(f"LLM failed to produce valid JSON after {retries} tries: {last_err}")


def embed(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    out = []
    for t in texts:
        k = _key("embed", model, t)
        hit = _cache_get(k)
        if hit is None:
            r = requests.post(f"{OLLAMA_URL}/api/embeddings",
                              json={"model": model, "prompt": t}, timeout=120)
            r.raise_for_status()
            hit = r.json()["embedding"]
            _cache_put(k, hit)
        out.append(hit)
    return out


def embeddings_available(model: str = EMBED_MODEL) -> bool:
    try:
        embed(["ping"], model)
        return True
    except Exception:  # noqa: BLE001
        return False
