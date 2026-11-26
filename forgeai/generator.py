"""Req 3: agent generator -> declarative agent definition (YAML)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from . import llm, prompts
from .tools import REGISTRY, eligible_tools

OUTPUT_CONTRACT = {
    "format": "json",
    "fields": {"answer": "string - grounded answer or polite refusal",
               "sources": "list of document file names used (empty when refused)",
               "refused": "boolean - true when declining"},
}

DEFAULT_RETRIEVAL = {"chunk_size": 800, "overlap": 120, "top_k": 4}


def pick_retrieval(docs: dict[str, str]) -> dict:
    """Heuristic from the corpus: tabular/short-line docs get smaller chunks."""
    r = dict(DEFAULT_RETRIEVAL)
    avg = sum(len(t) for t in docs.values()) / len(docs)
    if avg < 3000:
        r["chunk_size"], r["overlap"] = 600, 100
    return r


def select_tools(req: dict, doc_names: list[str]) -> list[dict]:
    """LLM proposes, deterministic eligibility rules dispose: only justified AND eligible tools."""
    text = " ".join([req["brief"], req["scope"], *req["must_answer"]])
    allowed = set(eligible_tools(text, doc_names))
    if not allowed:
        return []
    menu = "\n".join(f"- {n}: {REGISTRY[n]['description']}" for n in REGISTRY)
    obj = llm.chat_json(prompts.load("generator_tool_select"),
                        f"BRIEF: {req['brief']}\nSCOPE: {req['scope']}\nMUST ANSWER: {req['must_answer']}\n"
                        f"DOCUMENT FILES: {doc_names}\n\nAVAILABLE TOOLS:\n{menu}",
                        validate=lambda o: o if isinstance(o.get("tools", []), list) else (_ for _ in ()).throw(ValueError("tools")))
    chosen = []
    for t in obj.get("tools", []):
        name = t.get("name") if isinstance(t, dict) else None
        just = (t.get("justification") or "").strip() if isinstance(t, dict) else ""
        if name in allowed and just and name not in [c["name"] for c in chosen]:
            chosen.append({"name": name, "justification": just})
    return chosen


def generate_prompt(req: dict, style: str = "") -> str:
    def ok(o):
        sp = o.get("system_prompt")
        if not isinstance(sp, str) or len(sp) < 80:
            raise ValueError("system_prompt missing/too short")
        return o
    payload = {k: req[k] for k in ("scope", "audience", "tone", "must_answer", "must_refuse")}
    payload["unsupported_topics"] = [u["topic"] for u in req.get("unsupported", [])]
    payload["documents"] = req["documents"]
    obj = llm.chat_json(prompts.load("generator_system_prompt") + style, json.dumps(payload, indent=1),
                        validate=ok)
    return obj["system_prompt"].strip()


def generate(req: dict, docs: dict[str, str], name: str = "agent", system_prompt: str | None = None) -> dict:
    return {
        "name": name,
        "model": llm.DEFAULT_MODEL,
        "system_prompt": system_prompt or generate_prompt(req),
        "retrieval": pick_retrieval(docs),
        "tools": select_tools(req, sorted(docs)),
        "output_contract": OUTPUT_CONTRACT,
        "refusal_topics": req["must_refuse"],
        "documents": sorted(docs),
    }


def save(defn: dict, path: str | Path) -> None:
    Path(path).write_text(yaml.safe_dump(defn, sort_keys=False, allow_unicode=True, width=100),
                          encoding="utf-8")


def load(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
