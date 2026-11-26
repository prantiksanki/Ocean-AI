"""Req 2: groundability guard. Flags requested topics the documents cannot support."""
from __future__ import annotations

from . import llm, prompts
from .ingest import Index, keyword_overlap


def check(req: dict, index: Index, top_k: int = 4) -> dict:
    """Moves unsupported topics out of must_answer into req['unsupported'] and must_refuse."""
    supported, unsupported = [], []
    for n, topic in enumerate(req["must_answer"], 1):
        print(f"[forgeai] guard {n}/{len(req['must_answer'])}: checking '{topic}'", flush=True)
        hits = index.search(topic, top_k)
        texts = [c.text for c, _ in hits]
        overlap = keyword_overlap(topic, texts)
        excerpt = "\n---\n".join(f"[{c.source}] {c.text[:600]}" for c, _ in hits)
        verdict = llm.chat_json(prompts.load("guard_verdict"),
                                f"TOPIC: {topic}\n\nEXCERPTS:\n{excerpt}",
                                validate=lambda o: o if "supported" in o else (_ for _ in ()).throw(ValueError("no verdict")))
        llm_ok = bool(verdict.get("supported"))
        # Combine: no lexical evidence at all -> unsupported; the LLM may veto partial evidence.
        is_supported = overlap >= 0.5 and llm_ok or overlap >= 0.85
        if overlap < 0.3:
            is_supported = False
        entry = {"topic": topic, "overlap": round(overlap, 2), "llm_supported": llm_ok,
                 "reason": str(verdict.get("reason", ""))[:200]}
        (supported if is_supported else unsupported).append(entry)
    req["must_answer"] = [e["topic"] for e in supported]
    req["unsupported"] = unsupported
    req["must_refuse"] = list(dict.fromkeys(req["must_refuse"] + [e["topic"] for e in unsupported]))
    req["guard_report"] = {"supported": supported, "unsupported": unsupported}
    return req
