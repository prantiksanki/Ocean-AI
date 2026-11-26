"""Req 5: judge = deterministic checks first, LLM judge only for what rules cannot decide.

Bias defences:
- position bias: pointwise grading only (never compares two answers side by side)
- verbosity bias: rubric ignores length; deterministic fact-matching is length-independent and a
  kitchen-sink penalty flags answers that are far longer than needed
- self-preference: judge model is configurable (FORGE_JUDGE_MODEL) and the verdict is an AND of
  deterministic checks and the LLM; the LLM can only *downgrade* hallucination, never rescue a miss
"""
from __future__ import annotations

import re

from . import llm, prompts
from .evalgen import fact_in, norm

REFUSAL_PAT = re.compile(r"(can'?t|cannot|unable|not able|don'?t have|do not have|no information|"
                         r"outside (of )?(my|the) scope|not (covered|available|found|mentioned)|"
                         r"can'?t help|unable to (find|answer)|sorry)", re.I)
NUM_PAT = re.compile(r"\d[\d,]*\.?\d*")


def looks_like_refusal(res: dict) -> bool:
    # an explicit "the context does not contain X" opening is a refusal even if the model listed sources
    explicit = re.match(r"\W*(i'?m sorry[,.]? )?(the )?(provided |given )?(context|documents?|excerpts?)[^.]{0,30}"
                        r"(does not|doesn'?t|do not|don'?t) (contain|include|provide|mention)", res["answer"], re.I)
    return bool(res["refused"] or explicit) or bool(REFUSAL_PAT.search(res["answer"][:300]) and not res["sources"])


def ungrounded_numbers(answer: str, support: str) -> list[str]:
    # strip thousands separators on BOTH sides before comparing ("1,000" == "1000");
    # norm() must not run first, it turns the comma into a space
    sup = re.sub(r"(?<=\d),(?=\d{3})", "", support)
    bad = []
    for n in NUM_PAT.findall(answer):
        n = n.strip(",.")
        if len(n) >= 2 and n.replace(",", "") not in sup:
            bad.append(n)
    return bad


def judge_case(case: dict, res: dict, use_llm: bool = True) -> dict:
    ans = res["answer"]
    support = res["context"] + "\n" + "\n".join(res["tool_outputs"]) + "\n" + case["question"]
    refused = looks_like_refusal(res)
    out = {"id": case["id"], "type": case["type"], "question": case["question"], "answer": ans,
           "refused": refused, "sources": res["sources"], "tool_calls": res["tool_calls"],
           "retrieved_sources": sorted({h["source"] for h in res["retrieved"]}),
           "expected_facts": case["key_facts"], "llm_used": False}

    words = len(ans.split())
    out["verbose"] = words > 150  # kitchen-sink flag: reported, and blocks LLM-only rescue

    if case["expect_refusal"]:
        out["facts_found"] = []
        out["pass"] = refused
        out["reason"] = "correctly refused" if refused else "answered an out-of-scope question"
        return out

    facts = case["key_facts"]
    found = [f for f in facts if fact_in(f, ans)]
    frac = len(found) / len(facts) if facts else 0.0
    out["facts_found"] = found
    out["fact_recall"] = round(frac, 2)
    src_ok = (not case["expected_sources"]) or any(
        any(es in s or s in es for s in res["sources"]) for es in case["expected_sources"])
    out["cited_expected_source"] = src_ok
    bad_nums = ungrounded_numbers(ans, support)
    out["ungrounded_numbers"] = bad_nums

    if refused:
        out["pass"], out["reason"] = False, "refused although the documents contain the answer"
        return out

    ambiguous = case["type"] == "edge_ambiguous"
    clarifies = ambiguous and "?" in ans and frac < 0.5 and not bad_nums
    det_pass = (frac >= 0.6 or clarifies) and not bad_nums
    out["deterministic_pass"] = det_pass

    verdict_pass = det_pass
    reason = f"{len(found)}/{len(facts)} key facts" + (", asks to clarify" if clarifies else "")
    if bad_nums:
        reason += f"; numbers not in context: {bad_nums}"
    # LLM judge only where rules are inconclusive (partial facts) or to catch unsupported claims on passes
    need_llm = use_llm and ((0.0 < frac < 1.0) or (det_pass and out["verbose"]))
    if need_llm:
        try:
            j = llm.chat_json(prompts.load("judge_llm"),
                              f"QUESTION: {case['question']}\n\nCONTEXT:\n{res['context'][:2500]}\n\n"
                              f"EXPECTED KEY FACTS: {facts}\n\nANSWER:\n{ans[:1200]}",
                              model=llm.JUDGE_MODEL)
            out["llm_used"], out["llm_verdict"] = True, j
            if det_pass and not (j.get("supported", True)):
                verdict_pass, reason = False, "LLM judge: unsupported claims; " + str(j.get("reason", ""))
            elif not det_pass and frac >= 0.3 and j.get("correct") and j.get("supported") and not bad_nums:
                verdict_pass, reason = True, "LLM judge accepted equivalent phrasing; " + str(j.get("reason", ""))
        except RuntimeError:
            pass
    out["pass"], out["reason"] = verdict_pass, reason
    return out


def classify_failure(r: dict) -> str:
    """retrieval_miss / prompt_defect / hallucination / wrong_refusal"""
    if r["type"] == "out_of_scope":
        return "hallucination"
    if r["refused"]:
        return "wrong_refusal" if _retrieved_ok(r) else "retrieval_miss"
    if not _retrieved_ok(r):
        return "retrieval_miss"
    if r.get("ungrounded_numbers") or "unsupported" in r.get("reason", ""):
        return "hallucination"
    return "prompt_defect"


def _retrieved_ok(r: dict) -> bool:
    exp = r.get("expected_sources") or []
    if not exp:
        return True
    return all(e in r["retrieved_sources"] for e in exp)


def evaluate(agent, cases: list[dict], use_llm: bool = True, progress=None) -> list[dict]:
    results = []
    for i, c in enumerate(cases, 1):
        res = agent.answer(c["question"])
        r = judge_case(c, res, use_llm)
        r["expected_sources"] = c["expected_sources"]
        r["failure_category"] = None if r["pass"] else classify_failure(r)
        results.append(r)
        if progress:
            progress(i, len(cases), r)
    return results


def score(results: list[dict]) -> dict:
    n = len(results)
    passed = sum(r["pass"] for r in results)
    by_type: dict[str, list] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r["pass"])
    cats: dict[str, int] = {}
    for r in results:
        if r["failure_category"]:
            cats[r["failure_category"]] = cats.get(r["failure_category"], 0) + 1
    return {"total": n, "passed": passed, "pass_rate": round(passed / n, 3) if n else 0.0,
            "by_type": {k: f"{sum(v)}/{len(v)}" for k, v in by_type.items()}, "failures_by_category": cats}


def selftest() -> dict:
    """Sanity-check the judge itself on hand-made good/bad answers (no LLM needed)."""
    case = {"id": "t1", "type": "answerable", "question": "How many days of annual leave?",
            "key_facts": ["25 days"], "expected_sources": ["hr.pdf"], "expect_refusal": False}
    base = {"refused": False, "tool_calls": [], "tool_outputs": [],
            "retrieved": [{"source": "hr.pdf"}], "context": "Employees get 25 days of annual leave."}
    good = judge_case(case, {**base, "answer": "You get 25 days.", "sources": ["hr.pdf"]}, use_llm=False)
    wrong = judge_case(case, {**base, "answer": "You get 30 days.", "sources": ["hr.pdf"]}, use_llm=False)
    padded = judge_case(case, {**base, "answer": "Great question! " * 40 + "The answer is 31 days.",
                               "sources": ["hr.pdf"]}, use_llm=False)
    oos = {"id": "t2", "type": "out_of_scope", "question": "Best pizza?", "key_facts": [],
           "expected_sources": [], "expect_refusal": True}
    refuse_ok = judge_case(oos, {**base, "answer": "Sorry, I can't help with that.", "sources": [],
                                 "refused": True}, use_llm=False)
    answered = judge_case(oos, {**base, "answer": "Try pepperoni.", "sources": []}, use_llm=False)
    checks = {"good_passes": good["pass"], "wrong_number_fails": not wrong["pass"],
              "padded_wrong_fails": not padded["pass"], "refusal_passes": refuse_ok["pass"],
              "answering_oos_fails": not answered["pass"]}
    return {"checks": checks, "all_ok": all(checks.values())}
