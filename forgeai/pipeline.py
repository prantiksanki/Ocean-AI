"""End-to-end orchestration: brief + docs -> requirements -> guard -> agent -> evals -> optimize -> report."""
from __future__ import annotations

import json
from pathlib import Path

from . import evalgen, generator, guard, ingest, intake, judge, llm, optimizer, report
from .agent import Agent


def log(msg: str) -> None:
    print(f"[forgeai] {msg}", flush=True)


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _progress(i, n, r):
    log(f"  eval {i}/{n} {r['id']} {'PASS' if r['pass'] else 'FAIL'} ({r['type']})")


def _index(docs: dict, retrieval: dict) -> ingest.Index:
    return ingest.Index(ingest.build_chunks(docs, retrieval["chunk_size"], retrieval["overlap"]))


def build_requirements(brief: str, docs: dict, mode: str = "defaults", answers_file: str | None = None) -> dict:
    """Intake interview + groundability guard."""
    questions = intake.propose_questions(brief, docs)
    log(f"intake: {len(questions)} clarifying question(s)")
    req = intake.write_requirements(brief, docs, intake.collect_answers(questions, mode, answers_file))
    index = _index(docs, generator.pick_retrieval(docs))
    log(f"retrieval backend: {'dense+BM25 hybrid' if index.dense else 'BM25 only (no embedding model)'}")
    req = guard.check(req, index)
    if req["unsupported"]:
        log("GUARD flagged unsupported topics: " + "; ".join(u["topic"] for u in req["unsupported"]))
    return req


def save_requirements(req: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "requirements.json", req)
    (out / "requirements.md").write_text(intake.to_markdown(req), encoding="utf-8")


def tournament(defn: dict, req: dict, docs_dir: str, cases: list[dict], n: int,
               use_llm_judge: bool) -> tuple[dict, list[dict]]:
    """Stretch: n candidate system prompts; the eval set picks the winner (ties keep the earlier one)."""
    styles = ["", "\nStyle for this candidate: very short, strict numbered rules.",
              "\nStyle for this candidate: explain step by step when to answer and when to refuse."]
    candidates, table = [], []
    for i in range(min(n, len(styles))):
        d = dict(defn)
        if i:
            d["system_prompt"] = generator.generate_prompt(req, styles[i])
        log(f"tournament: evaluating candidate {i + 1}")
        sc = judge.score(judge.evaluate(Agent(d, docs_dir), cases, use_llm_judge, _progress))
        candidates.append(d)
        table.append({"candidate": i + 1, "passed": sc["passed"], "total": sc["total"], "pass_rate": sc["pass_rate"]})
    best = max(range(len(table)), key=lambda i: table[i]["passed"])
    table[best]["winner"] = True
    log(f"tournament winner: candidate {best + 1}")
    return candidates[best], table


def run(brief: str, docs_dir: str, out_dir: str, name: str = "agent", mode: str = "defaults",
        answers_file: str | None = None, max_iters: int = 3, target: float = 0.9, n_cases: int = 24,
        budget_seconds: float | None = None, checkpoint: bool = False, use_llm_judge: bool = True,
        requirements_file: str | None = None, n_prompts: int = 1) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    docs = ingest.load_documents(docs_dir)
    log(f"loaded {len(docs)} documents: {', '.join(docs)}")
    _write_json(out / "run_meta.json", {"brief": brief, "docs_dir": str(Path(docs_dir).as_posix()), "name": name,
                                        "model": llm.DEFAULT_MODEL, "judge_model": llm.JUDGE_MODEL})

    # 1 + 2. intake and guard (or requirements already approved by a human)
    if requirements_file:
        req = json.loads(Path(requirements_file).read_text(encoding="utf-8"))
        log("using approved requirements file")
    else:
        req = build_requirements(brief, docs, mode, answers_file)
    save_requirements(req, out)
    if checkpoint:
        print("\n" + intake.to_markdown(req))
        if input("\nApprove requirements? [Y/edit] ").strip().lower() == "edit":
            input(f"Edit {out / 'requirements.json'} then press Enter...")
            req = json.loads((out / "requirements.json").read_text(encoding="utf-8"))
            save_requirements(req, out)

    # 3. generate agent
    log("generating agent definition (system prompt + tool selection)...")
    defn = generator.generate(req, docs, name=name)
    log(f"generated agent; tools attached: {[t['name'] for t in defn['tools']] or 'none'}")

    # 4. eval set
    log("generating eval set from the documents (many model calls, be patient)...")
    index = _index(docs, defn["retrieval"])
    cases = evalgen.generate(req, index.chunks, target=n_cases, index=index)
    evalgen.save(cases, out / "evalset.jsonl")
    log(f"eval set: {len(cases)} cases " + str({t: sum(c['type'] == t for c in cases) for t in {c['type'] for c in cases}}))

    table = []
    if n_prompts > 1:
        defn, table = tournament(defn, req, docs_dir, cases, n_prompts, use_llm_judge)
        _write_json(out / "tournament.json", table)
    generator.save(defn, out / "agent_definition.v0.yaml")

    # 5 + 6. evaluate and optimize
    results_by_iter: dict[int, list[dict]] = {}

    def save_iter(it, results, d):
        results_by_iter[it] = results
        _write_jsonl(out / f"iteration_{it}_results.jsonl", results)
        generator.save(d, out / f"agent_definition.iter{it}.yaml")

    changelog: list[dict] = []
    final_defn, scorecard = optimizer.optimize(defn, docs_dir, cases, changelog, max_iters, target,
                                               budget_seconds, use_llm_judge, _progress, save_iter)
    generator.save(final_defn, out / "agent_definition.yaml")
    _write_json(out / "iterations.json", changelog)
    _write_json(out / "scorecard.json", scorecard)
    (out / "scorecard.md").write_text(report.scorecard_md(scorecard) + "\n", encoding="utf-8")

    # 7. honest report on the definition that was actually shipped
    best_iter = max(scorecard, key=lambda s: (s["passed"], -s["iteration"]))["iteration"]
    _write_jsonl(out / "final_results.jsonl", results_by_iter[best_iter])
    rep = report.build(req, final_defn, scorecard, changelog, results_by_iter[best_iter], llm.Usage.snapshot(),
                       judge.selftest(), llm.JUDGE_MODEL, final_defn["model"])
    if table:
        rep += "\n## Prompt tournament\n\n" + "\n".join(
            f"- candidate {t['candidate']}: {t['passed']}/{t['total']}{' (winner)' if t.get('winner') else ''}"
            for t in table) + "\n"
    (out / "report.md").write_text(rep, encoding="utf-8")
    _write_json(out / "usage.json", llm.Usage.snapshot())
    log(f"done. final {scorecard[best_iter]['passed']}/{scorecard[best_iter]['total']}. artifacts in {out}")
    return {"definition": final_defn, "scorecard": scorecard, "changelog": changelog, "requirements": req}


def regress(old_run: str, docs_dir: str, out_dir: str, use_llm_judge: bool = True) -> dict:
    """Stretch: documents changed -> regenerate the agent, re-run the OLD eval set, report what broke."""
    old, out = Path(old_run), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    docs = ingest.load_documents(docs_dir)
    req = json.loads((old / "requirements.json").read_text(encoding="utf-8"))
    req["documents"] = sorted(docs)
    cases = evalgen.load(old / "evalset.jsonl")
    before = {r["id"]: r for r in map(json.loads, (old / "final_results.jsonl" if (old / "final_results.jsonl").exists()
              else old / "iteration_0_results.jsonl").read_text(encoding="utf-8").splitlines()) }
    defn = generator.generate(req, docs, name=generator.load(old / "agent_definition.yaml")["name"])
    generator.save(defn, out / "agent_definition.yaml")
    _write_json(out / "run_meta.json", {"docs_dir": str(Path(docs_dir).as_posix()), "regression_of": str(old.as_posix())})
    results = judge.evaluate(Agent(defn, docs_dir), cases, use_llm_judge, _progress)
    _write_jsonl(out / "final_results.jsonl", results)
    broke = [r for r in results if not r["pass"] and before.get(r["id"], {}).get("pass")]
    fixed = [r for r in results if r["pass"] and not before.get(r["id"], {}).get("pass", True)]
    lines = ["# Regression report", "",
             f"Before: {sum(r['pass'] for r in before.values())}/{len(before)}. "
             f"After: {sum(r['pass'] for r in results)}/{len(results)}.", "",
             "A 'broken' case may also mean the expected fact itself changed in the new documents.", "", "## Broke"]
    lines += [f"- `{r['id']}` {r['question']} - {r['reason']}" for r in broke] or ["- nothing"]
    lines += ["", "## Fixed"] + ([f"- `{r['id']}` {r['question']}" for r in fixed] or ["- nothing"])
    (out / "regression.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"regression: {len(broke)} broke, {len(fixed)} fixed. see {out / 'regression.md'}")
    return {"broke": [r["id"] for r in broke], "fixed": [r["id"] for r in fixed]}
