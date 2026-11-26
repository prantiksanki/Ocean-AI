"""Req 7: honest reporting."""
from __future__ import annotations

from . import judge


def scorecard_md(scorecard: list[dict]) -> str:
    rows = ["| Iter | Passed | Pass rate | Failures by category | Note |", "|---|---|---|---|---|"]
    for s in scorecard:
        cats = ", ".join(f"{k}={v}" for k, v in s["failures_by_category"].items()) or "-"
        rows.append(f"| {s['iteration']} | {s['passed']}/{s['total']} | {s['pass_rate']:.0%} | {cats} | {s['note']} |")
    return "\n".join(rows)


def build(req: dict, final_defn: dict, scorecard: list[dict], changelog: list[dict],
          final_results: list[dict], usage: dict, selftest: dict, judge_model: str, agent_model: str) -> str:
    final = scorecard[-1] if not changelog else max(scorecard, key=lambda s: (s["passed"], -s["iteration"]))
    fails = [r for r in final_results if not r["pass"]]
    lines = [f"# Quality report - {final_defn['name']}", "",
             f"**Final result: {final['passed']}/{final['total']} cases passed ({final['pass_rate']:.0%}).** "
             f"Baseline was {scorecard[0]['passed']}/{scorecard[0]['total']} ({scorecard[0]['pass_rate']:.0%}).", "",
             "This is measured on an auto-generated eval set (see limits below), not on real users. "
             "Treat the number as an estimate, not a guarantee.", "",
             "## Scorecard per iteration", scorecard_md(scorecard), "",
             "## By case type (final)", "", *[f"- {k}: {v}" for k, v in final["by_type"].items()], ""]

    lines += ["## Groundability guard", ""]
    if req.get("unsupported"):
        lines += ["The brief asked for topics the documents cannot support. They were NOT promised to the "
                  "requester and the agent is instructed to refuse them:", ""]
        lines += [f"- **{u['topic']}** - {u['reason']}" for u in req["unsupported"]]
    else:
        lines += ["All requested topics were found to be supported by the documents."]
    lines += ["", "## Tools attached", ""]
    lines += [f"- `{t['name']}` - {t['justification']}" for t in final_defn["tools"]] or ["- none (the brief needs none)"]

    lines += ["", "## Change log", ""]
    if not changelog:
        lines.append("No optimizer iterations were needed or applicable.")
    for c in changelog:
        lines.append(f"### Iteration {c['iteration']} - {c['decision']}  "
                     f"({c['passed_before']} -> {c['passed_after']} passed)")
        for ch in c["changes"]:
            lines.append(f"- **{ch['kind']}**: {ch.get('patch', '')} {ch['why']} (targets: {', '.join(ch['addresses'])})")
        lines.append(f"- newly fixed: {c['newly_fixed'] or 'none'}; newly broken: {c['newly_broken'] or 'none'}")
        lines.append("")

    lines += ["## What still fails and why", ""]
    if not fails:
        lines += ["No failures on this eval set - which says more about the eval set's difficulty than about "
                  "the agent being perfect. See limits."]
    for r in fails:
        lines.append(f"- `{r['id']}` [{r['type']}] **{r['failure_category']}**: \"{r['question']}\" - {r['reason']}")

    lines += ["", "## Limits of this evaluation (read before trusting the score)", "",
              f"- Agent model `{agent_model}`; judge model `{judge_model}`"
              + (" (same model: self-preference is possible, so deterministic checks gate every verdict)."
                 if agent_model == judge_model else "."),
              "- Eval questions and key facts are LLM-generated from the same documents; key facts are verified "
              "verbatim against the source, but question coverage is sampled, not exhaustive.",
              "- Fact matching is lexical: a correct paraphrase can be marked wrong (false failure), and a "
              "padded answer can contain a fact by luck (mitigated by the number-grounding and verbosity checks).",
              f"- Judge self-test (known good/bad answers): {'all passed' if selftest['all_ok'] else 'FAILED - ' + str(selftest['checks'])}.",
              "- The optimizer only keeps a patch if the pass count rises on the SAME eval set it was tuned on, "
              "so some of the improvement may be overfitting to it. No held-out set was used.",
              f"- Compute: {usage['calls']} model calls ({usage['cached']} served from cache), "
              f"{usage['seconds']}s of model time."]
    return "\n".join(lines) + "\n"
