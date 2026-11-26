"""Req 6: critic-optimizer loop. Classify failures -> targeted patch -> re-run. Max 3 iterations.

Patches are *edits* (retrieval parameters or an appended rule), never a full regeneration.
A patch set that does not improve the score is reverted and logged as such.
"""
from __future__ import annotations

import copy
import time

from . import judge, llm, prompts
from .agent import Agent


def _patch_retrieval(defn: dict, failures: list[dict]) -> tuple[dict, str] | None:
    r = defn["retrieval"]
    if r["top_k"] >= 8 and r["overlap"] >= 250:
        return None
    new = dict(r)
    new["top_k"] = min(8, r["top_k"] + 2)
    new["overlap"] = min(250, r["overlap"] + 60)
    if any(f["type"] == "edge_cross_doc" for f in failures):
        new["chunk_size"] = min(1400, r["chunk_size"] + 300)
    return new, (f"retrieval {r} -> {new}: expected source missing from top-k for "
                 f"{len(failures)} case(s); widen top_k/overlap" +
                 ("/chunk_size (cross-document cases)" if new["chunk_size"] != r["chunk_size"] else ""))


def _patch_prompt(defn: dict, category: str, failures: list[dict]) -> tuple[str, str] | None:
    ex = "\n\n".join(f"Q: {f['question']}\nAssistant answered: {f['answer'][:300]}\nProblem: {f['reason']}"
                     for f in failures[:3])
    try:
        o = llm.chat_json(prompts.load("critic_patch"),
                          f"CATEGORY: {category}\n\nCURRENT SYSTEM PROMPT:\n{defn['system_prompt']}\n\nFAILED CASES:\n{ex}",
                          validate=lambda o: o if isinstance(o.get("patch"), str) and len(o["patch"]) > 15 else (_ for _ in ()).throw(ValueError("patch")))
    except RuntimeError:
        return None
    patch = o["patch"].strip()
    if patch in defn["system_prompt"]:
        return None
    return patch, str(o.get("rationale", ""))


def optimize(defn: dict, docs_dir: str, cases: list[dict], out_log: list, max_iters: int = 3,
             target: float = 0.9, budget_seconds: float | None = None, use_llm_judge: bool = True,
             progress=None, save_iter=None) -> tuple[dict, list[dict]]:
    """Returns (best_definition, scorecard rows). out_log receives change-log entries."""
    t0 = time.time()
    agent = Agent(defn, docs_dir)
    results = judge.evaluate(agent, cases, use_llm_judge, progress)
    sc = judge.score(results)
    scorecard = [{"iteration": 0, **sc, "note": "baseline (generated definition)"}]
    if save_iter:
        save_iter(0, results, defn)
    best = defn

    for it in range(1, max_iters + 1):
        if sc["pass_rate"] >= target:
            scorecard[-1]["note"] += " - target reached, stopping"
            break
        if budget_seconds and time.time() - t0 > budget_seconds:
            scorecard[-1]["note"] += " - time budget exhausted, stopping"
            break
        failures = [r for r in results if not r["pass"]]
        by_cat: dict[str, list[dict]] = {}
        for f in failures:
            by_cat.setdefault(f["failure_category"], []).append(f)

        cand, changes = copy.deepcopy(best), []
        if "retrieval_miss" in by_cat:
            p = _patch_retrieval(cand, by_cat["retrieval_miss"])
            if p:
                cand["retrieval"], why = p
                changes.append({"kind": "retrieval", "why": why,
                                "addresses": [f["id"] for f in by_cat["retrieval_miss"]]})
        for cat in ("hallucination", "wrong_refusal", "prompt_defect"):
            if cat in by_cat:
                p = _patch_prompt(cand, cat, by_cat[cat])
                if p:
                    cand["system_prompt"] += f"\n\n[{cat} fix v{it}] {p[0]}"
                    changes.append({"kind": f"prompt:{cat}", "patch": p[0], "why": p[1],
                                    "addresses": [f["id"] for f in by_cat[cat]]})
        if not changes:
            scorecard[-1]["note"] += " - no applicable fix, stopping"
            break

        new_agent = Agent(cand, docs_dir)
        new_results = judge.evaluate(new_agent, cases, use_llm_judge, progress)
        new_sc = judge.score(new_results)
        fixed = sorted(set(r["id"] for r in results if not r["pass"]) & set(r["id"] for r in new_results if r["pass"]))
        broke = sorted(set(r["id"] for r in results if r["pass"]) & set(r["id"] for r in new_results if not r["pass"]))
        accepted = new_sc["passed"] > sc["passed"]
        out_log.append({"iteration": it, "changes": changes, "score_before": sc["pass_rate"],
                        "score_after": new_sc["pass_rate"], "passed_before": sc["passed"],
                        "passed_after": new_sc["passed"], "newly_fixed": fixed, "newly_broken": broke,
                        "accepted": accepted,
                        "decision": "kept" if accepted else "reverted (no net improvement)"})
        scorecard.append({"iteration": it, **new_sc,
                          "note": "patch kept" if accepted else "patch reverted - score did not improve"})
        if save_iter:
            save_iter(it, new_results, cand)
        if accepted:
            best, results, sc = cand, new_results, new_sc
        else:
            # keep best; a rerun with the same patch would be identical, so stop early
            break
    return best, scorecard
