"""Whole pipeline with a scripted fake model: checks the wiring in seconds, NOT model quality."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forgeai import evalgen, llm, pipeline


def fake_chat(messages, **_):
    system, user = messages[0]["content"], messages[-1]["content"]
    if "intake interviewer" in system:
        out = {"questions": ["Who is the audience?"]}
    elif "requirements document" in system:
        out = {"scope": "HR", "audience": "staff", "tone": "friendly",
               "must_answer": ["annual leave", "stock option vesting"], "must_refuse": ["legal advice"]}
    elif "groundedness auditor" in system:
        out = {"supported": "annual leave" in user.split("\n")[0], "reason": "scripted"}
    elif "SYSTEM PROMPT" in system:
        out = {"system_prompt": "Answer only from the context. Refuse otherwise. Cite the source files. " * 2}
    elif "from ONE passage" in system or "is ONE passage" in system:
        out = {"cases": [{"question": f"Leave question {abs(hash(system + user)) % 10**8} {i}?", "key_facts": ["25 days"]}
                         for i in range(2)]}
    elif "BOTH passages" in system or "out-of-scope test" in system or "ambiguous" in system.split(".")[0]:
        out = {}
    elif "Response protocol" in system:
        q = user.split("QUESTION:")[-1]
        refuse = "eave" not in q
        out = {"action": "final", "answer": "I cannot help with that." if refuse else "You get 25 days.",
               "sources": [] if refuse else ["leave.txt"], "refused": refuse}
    else:
        out = {"patch": "Always quote exact values from the context.", "rationale": "x",
               "correct": True, "supported": True}
    return json.dumps(out)


def test_pipeline_end_to_end(monkeypatch):
    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "embeddings_available", lambda *a: False)
    with tempfile.TemporaryDirectory(dir=str(Path(__file__).parent)) as d:
        docs = Path(d) / "docs"
        docs.mkdir()
        (docs / "leave.txt").write_text("\n".join(
            f"Section {i}. Staff get 25 days of annual leave each year, rule {i}." for i in range(60)))
        out = Path(d) / "run"
        res = pipeline.run("HR assistant for annual leave and stock option vesting", str(docs), str(out))
        for f in ["requirements.json", "agent_definition.yaml", "evalset.jsonl", "scorecard.json",
                  "report.md", "iterations.json", "final_results.jsonl", "run_meta.json"]:
            assert (out / f).exists(), f
        assert [u["topic"] for u in res["requirements"]["unsupported"]] == ["stock option vesting"]
        assert res["definition"]["tools"] == []
        assert len(evalgen.load(out / "evalset.jsonl")) >= 20
        reg = pipeline.regress(str(out), str(docs), str(Path(d) / "reg"))
        assert reg == {"broke": [], "fixed": []}


def test_number_words_and_bare_numbers():
    assert evalgen.fact_in("up to three (3)", "3")
    assert evalgen.fact_in("three days", "You may work remotely 3 days a week")
    assert not evalgen.fact_in("up to three (3)", "5")
    assert not evalgen.fact_in("25 days", "You get 25 weeks of parental leave")
