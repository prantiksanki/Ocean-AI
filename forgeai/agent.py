"""Generic agent runtime: loads ANY agent definition, retrieves, calls tools, returns contract JSON."""
from __future__ import annotations

import json
from pathlib import Path

from . import generator, ingest, llm, prompts
from .tools import describe_tools, run_tool

MAX_TOOL_STEPS = 3
REFUSAL_FALLBACK = "I can't answer that from the documents I have."


class Agent:
    def __init__(self, defn: dict, docs_dir: str | Path, index: ingest.Index | None = None):
        self.defn = defn
        self.docs_dir = str(docs_dir)
        r = defn["retrieval"]
        self.top_k = int(r["top_k"])
        self.index = index or ingest.Index(
            ingest.build_chunks(ingest.load_documents(docs_dir), r["chunk_size"], r["overlap"]))
        self.tool_names = [t["name"] if isinstance(t, dict) else t for t in defn.get("tools", [])]

    @classmethod
    def from_file(cls, path: str | Path, docs_dir: str | Path) -> "Agent":
        return cls(generator.load(path), docs_dir)

    def _system(self) -> str:
        tool_block = ""
        if self.tool_names:
            tool_block = ('Tool call: {"action": "tool", "tool": "<name>", "args": {...}}\n'
                          "Available tools:\n" + describe_tools(self.tool_names) + "\n")
        return self.defn["system_prompt"] + "\n\n" + prompts.load("agent_runtime", tool_block=tool_block)

    def answer(self, question: str, history: list[dict] | None = None) -> dict:
        hits = self.index.search(question, self.top_k)
        context = "\n\n".join(f"[{c.source}]\n{c.text}" for c, _ in hits)
        msgs = [{"role": "system", "content": self._system()}]
        msgs += (history or [])[-4:]
        msgs.append({"role": "user", "content": f"CONTEXT EXCERPTS:\n{context}\n\nQUESTION: {question}"})
        tool_calls, tool_outputs = [], []
        final = None
        for _ in range(MAX_TOOL_STEPS + 1):
            raw = llm.chat(msgs, model=self.defn.get("model", llm.DEFAULT_MODEL), json_mode=True)
            try:
                obj = llm.extract_json(raw)
                if not isinstance(obj, dict):
                    raise ValueError
            except ValueError:
                obj = {"action": "final", "answer": raw.strip()[:800], "sources": [], "refused": False}
            if obj.get("action") == "tool" and obj.get("tool") in self.tool_names and len(tool_calls) < MAX_TOOL_STEPS:
                out = run_tool(obj["tool"], obj.get("args") or {}, self.docs_dir)
                tool_calls.append({"tool": obj["tool"], "args": obj.get("args"), "output": out})
                tool_outputs.append(out)
                msgs += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"TOOL RESULT: {out}\nNow give the final answer JSON."}]
                continue
            final = obj
            break
        final = final or {"answer": REFUSAL_FALLBACK, "sources": [], "refused": True}
        answer = str(final.get("answer", "")).strip() or REFUSAL_FALLBACK
        srcs = final.get("sources") or []
        srcs = [str(s) for s in srcs] if isinstance(srcs, list) else [str(srcs)]
        return {"answer": answer, "sources": srcs, "refused": bool(final.get("refused", False)),
                "tool_calls": tool_calls, "tool_outputs": tool_outputs,
                "retrieved": [{"id": c.id, "source": c.source, "score": round(s, 3)} for c, s in hits],
                "context": context}
