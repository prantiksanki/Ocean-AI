"""Req 1: intake interviewer -> structured requirements document."""
from __future__ import annotations

import json
from pathlib import Path

from . import llm, prompts


def digest(docs: dict[str, str], per_doc: int = 500) -> str:
    return "\n\n".join(f"[{n}] ({len(t)} chars)\n{t[:per_doc]}" for n, t in docs.items())


def propose_questions(brief: str, docs: dict[str, str], max_q: int = 5) -> list[str]:
    def ok(o):
        qs = [q for q in o.get("questions", []) if isinstance(q, str) and q.strip()]
        return {"questions": qs[:max_q]}  # hard cap regardless of what the model says
    obj = llm.chat_json(prompts.load("intake_questions", max_q=max_q),
                        f"BRIEF:\n{brief}\n\nDOCUMENTS:\n{digest(docs)}", validate=ok)
    return obj["questions"][:max_q]


def collect_answers(questions: list[str], mode: str, answers_file: str | None = None) -> list[dict]:
    """mode: 'interactive' (CLI dialogue), 'file' (JSON list of answers) or 'defaults'."""
    if mode == "interactive":
        out = []
        for i, q in enumerate(questions, 1):
            a = input(f"\n[ForgeAI Q{i}/{len(questions)}] {q}\n> ").strip()
            out.append({"q": q, "a": a or "(no preference - assume a sensible default)"})
        return out
    if mode == "file" and answers_file:
        given = json.loads(Path(answers_file).read_text(encoding="utf-8"))
        return [{"q": q, "a": given[i] if i < len(given) else "(no preference)"}
                for i, q in enumerate(questions)]
    return [{"q": q, "a": "(unattended run - assume a sensible default)"} for q in questions]


def write_requirements(brief: str, docs: dict[str, str], qa: list[dict]) -> dict:
    def ok(o):
        for k in ("scope", "audience", "tone", "must_answer", "must_refuse"):
            if k not in o:
                raise ValueError(f"missing {k}")
        for k in ("must_answer", "must_refuse", "assumptions"):
            v = o.get(k, [])
            o[k] = [str(x) for x in v] if isinstance(v, list) else [str(v)]
        for k in ("scope", "audience", "tone"):
            o[k] = str(o[k])
        return o
    qa_txt = "\n".join(f"Q: {x['q']}\nA: {x['a']}" for x in qa) or "(none asked)"
    req = llm.chat_json(prompts.load("intake_requirements"),
                        f"BRIEF:\n{brief}\n\nDOCUMENTS:\n{digest(docs, 300)}\n\nINTERVIEW:\n{qa_txt}",
                        validate=ok)
    req["brief"] = brief
    req["interview"] = qa
    req["documents"] = sorted(docs)
    req["unsupported"] = []
    return req


def to_markdown(req: dict) -> str:
    def bullets(xs):
        return "\n".join(f"- {x}" for x in xs) or "- (none)"
    parts = [f"# Requirements\n\n**Brief:** {req['brief']}\n",
             f"## Scope\n{req['scope']}\n", f"## Audience\n{req['audience']}\n",
             f"## Tone\n{req['tone']}\n", f"## Must answer\n{bullets(req['must_answer'])}\n",
             f"## Must refuse\n{bullets(req['must_refuse'])}\n",
             f"## Unsupported by documents (flagged by groundability guard)\n"
             + bullets([f"{u['topic']} - {u['reason']}" for u in req.get("unsupported", [])]) + "\n",
             f"## Assumptions\n{bullets(req.get('assumptions', []))}\n",
             "## Interview\n" + ("\n".join(f"- **Q:** {x['q']}\n  **A:** {x['a']}" for x in req["interview"]) or "- (none)")]
    return "\n".join(parts)
