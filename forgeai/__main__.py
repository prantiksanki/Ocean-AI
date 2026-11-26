import argparse
from pathlib import Path

from . import llm, pipeline


def main():
    ap = argparse.ArgumentParser(prog="forgeai", description="The agent that builds agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="build, test and improve an agent from a brief + docs")
    r.add_argument("--brief", help="one-paragraph brief (or use --brief-file)")
    r.add_argument("--brief-file")
    r.add_argument("--name", default="agent")
    r.add_argument("--interactive", action="store_true", help="ask the intake questions on the CLI")
    r.add_argument("--answers", help="JSON list of answers to the intake questions")
    r.add_argument("--requirements", help="approved requirements.json (skips intake and guard)")
    r.add_argument("--requirements-only", action="store_true", help="stop after requirements (human checkpoint)")
    r.add_argument("--max-iters", type=int, default=3, choices=range(0, 4))
    r.add_argument("--target", type=float, default=0.9)
    r.add_argument("--cases", type=int, default=24)
    r.add_argument("--budget-seconds", type=float)
    r.add_argument("--checkpoint", action="store_true", help="human approves/edits requirements first")
    r.add_argument("--tournament", type=int, default=1, help="number of candidate system prompts (1-3)")
    r.add_argument("--fast", action="store_true", help="20 cases, 1 optimizer iteration")
    g = sub.add_parser("regress", help="re-run an old eval set against an agent rebuilt on changed documents")
    g.add_argument("--run", required=True, help="folder of the earlier run")
    for p in (r, g):
        p.add_argument("--docs", required=True, help="folder of documents")
        p.add_argument("--out", required=True, help="output folder for all artifacts")
        p.add_argument("--model", help="Ollama model for generation and the agent")
        p.add_argument("--judge-model", help="Ollama model for the judge")
        p.add_argument("--no-llm-judge", action="store_true")
    a = ap.parse_args()
    llm.DEFAULT_MODEL = a.model or llm.DEFAULT_MODEL
    llm.JUDGE_MODEL = a.judge_model or llm.JUDGE_MODEL

    if a.cmd == "regress":
        pipeline.regress(a.run, a.docs, a.out, not a.no_llm_judge)
        return
    brief = a.brief or (Path(a.brief_file).read_text(encoding="utf-8").strip() if a.brief_file else None)
    if not brief:
        ap.error("give --brief or --brief-file")
    mode = "interactive" if a.interactive else ("file" if a.answers else "defaults")
    if a.requirements_only:
        docs = pipeline.ingest.load_documents(a.docs)
        pipeline.save_requirements(pipeline.build_requirements(brief, docs, mode, a.answers), Path(a.out))
        pipeline.log(f"requirements written to {a.out}")
        return
    pipeline.run(brief, a.docs, a.out, a.name, mode, a.answers, min(a.max_iters, 1) if a.fast else a.max_iters,
                 a.target, 20 if a.fast else a.cases, a.budget_seconds, a.checkpoint, not a.no_llm_judge,
                 a.requirements, a.tournament)


main()
