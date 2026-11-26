"""ForgeAI web UI:  streamlit run app.py"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
import streamlit as st

from forgeai import ingest, intake, llm
from forgeai.agent import Agent

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"

st.set_page_config(page_title="ForgeAI", layout="wide")
st.title("ForgeAI - the agent that builds agents")


@st.cache_data(ttl=30)
def installed_models() -> list[str]:
    try:
        tags = requests.get(f"{llm.OLLAMA_URL}/api/tags", timeout=3).json()["models"]
        return [m["name"].removesuffix(":latest") for m in tags if "embed" not in m["name"]]
    except Exception:  # noqa: BLE001
        return []


def find_runs() -> list[Path]:
    found = [p.parent for base in (RUNS, ROOT / "demos") if base.exists()
             for p in base.rglob("run_meta.json")]
    found += [p.parent for p in (ROOT / "demos").rglob("scorecard.json") if p.parent not in found]
    return sorted(set(found), key=lambda p: p.stat().st_mtime, reverse=True)


def label(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def stream_cli(args: list[str]) -> bool:
    """Run the factory as a subprocess and show its log live."""
    box, lines = st.empty(), []
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "forgeai", *args], cwd=ROOT, env=env, text=True,
                            encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for line in proc.stdout:
            lines.append(line.rstrip())
            box.code("\n".join(lines[-25:]))
        proc.wait()
    finally:
        if proc.poll() is None:  # the user stopped the page: do not leave an orphan using the CPU
            proc.kill()
    return proc.returncode == 0


models = installed_models()
with st.sidebar:
    st.header("Settings")
    if not models:
        st.error("Ollama is not reachable. Start it, then reload.")
    options = models or [llm.DEFAULT_MODEL]
    model = st.selectbox("Model", options, index=options.index(llm.DEFAULT_MODEL) if llm.DEFAULT_MODEL in options else 0)
    llm.DEFAULT_MODEL = model
    st.caption("Without a GPU a full run can take hours. Use fast mode to try things out.")

build_tab, results_tab, chat_tab = st.tabs(["1. Build", "2. Results", "3. Chat"])

with build_tab:
    brief = st.text_area("Brief: describe the assistant you want (one paragraph)", height=110)
    uploads = st.file_uploader("Documents (PDF, CSV, TXT, MD)", type=["pdf", "csv", "txt", "md"],
                               accept_multiple_files=True)
    folder = st.text_input("...or a folder path on this computer", placeholder="demos/hr/docs")
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", st.text_input("Run name", "my_agent")).strip("_") or "my_agent"
    out = RUNS / name

    def prepare_docs() -> Path | None:
        if uploads:
            d = out / "docs"
            d.mkdir(parents=True, exist_ok=True)
            for old in d.iterdir():
                old.unlink()
            for f in uploads:
                (d / Path(f.name).name).write_bytes(f.getbuffer())
            return d
        if folder and (ROOT / folder).is_dir():
            return (ROOT / folder).resolve()
        st.error("Upload documents or give an existing folder.")
        return None

    if st.button("Step 1: get clarifying questions", disabled=not models):
        if not brief.strip():
            st.error("Write a brief first.")
        elif docs_dir := prepare_docs():
            with st.spinner("Reading the brief and documents..."):
                st.session_state.questions = intake.propose_questions(brief.strip(), ingest.load_documents(docs_dir))
            st.session_state.docs_dir = str(docs_dir)

    questions = st.session_state.get("questions")
    if questions is not None:
        answers = [st.text_input(q, key=f"a{i}") for i, q in enumerate(questions)]
        if not questions:
            st.info("No clarifying questions needed.")
        if st.button("Step 2: write requirements (with groundability check)"):
            out.mkdir(parents=True, exist_ok=True)
            ans_file = out / "answers.json"
            ans_file.write_text(json.dumps([a or "(no preference)" for a in answers]), encoding="utf-8")
            if stream_cli(["run", "--brief", brief.strip(), "--docs", st.session_state.docs_dir, "--out", str(out),
                           "--answers", str(ans_file), "--requirements-only", "--model", model]):
                st.session_state.req_text = read(out / "requirements.json")
            else:
                st.error("Failed - see the log above.")

    if st.session_state.get("req_text"):
        req = json.loads(st.session_state.req_text)
        for u in req.get("unsupported", []):
            st.warning(f"The documents cannot support: **{u['topic']}** - {u['reason']}")
        edited = st.text_area("Step 3: approve or edit the requirements", st.session_state.req_text, height=300)
        c1, c2, c3 = st.columns(3)
        fast = c1.checkbox("Fast mode (20 cases, 1 iteration)", value=True)
        n_prompts = c2.number_input("Candidate prompts (tournament)", 1, 3, 1)
        budget = c3.number_input("Time budget in seconds (0 = none)", 0, step=600)
        if st.button("Step 4: build, test and improve the agent", type="primary"):
            try:
                json.loads(edited)
            except json.JSONDecodeError as e:
                st.error(f"Requirements are not valid JSON: {e}")
            else:
                req_file = out / "requirements.json"
                req_file.write_text(edited, encoding="utf-8")
                args = ["run", "--brief", req["brief"], "--docs", st.session_state.docs_dir, "--out", str(out),
                        "--name", name, "--requirements", str(req_file), "--model", model,
                        "--tournament", str(int(n_prompts))]
                args += ["--fast"] if fast else []
                args += ["--budget-seconds", str(int(budget))] if budget else []
                if stream_cli(args):
                    st.success("Done. Open the Results and Chat tabs.")
                else:
                    st.error("Failed - see the log above.")

with results_tab:
    runs = find_runs()
    if not runs:
        st.info("No runs yet.")
    else:
        run = st.selectbox("Run", runs, format_func=label, key="results_run")
        card = read(run / "scorecard.json")
        if card:
            card = json.loads(card)
            best = max(card, key=lambda s: (s["passed"], -s["iteration"]))
            a, b = st.columns(2)
            a.metric("Final", f"{best['passed']}/{best['total']}", f"{best['passed'] - card[0]['passed']:+d} vs baseline")
            b.metric("Iterations", len(card) - 1)
            st.table([{"iteration": s["iteration"], "passed": f"{s['passed']}/{s['total']}", "note": s["note"]}
                      for s in card])
        else:
            st.info("This run has no scorecard yet.")
        for title, fname, kind in [("Quality report", "report.md", "md"), ("Requirements", "requirements.md", "md"),
                                   ("Regression report", "regression.md", "md"),
                                   ("Agent definition", "agent_definition.yaml", "yaml"),
                                   ("Change log", "iterations.json", "json"), ("Eval set", "evalset.jsonl", "json")]:
            text = read(run / fname)
            if text:
                with st.expander(title, expanded=fname == "report.md"):
                    st.markdown(text) if kind == "md" else st.code(text, language=kind)
                    st.download_button(f"Download {fname}", text, fname, key=f"dl_{fname}")

with chat_tab:
    ready = [r for r in find_runs() if (r / "agent_definition.yaml").exists()]
    if not ready:
        st.info("Build an agent first.")
    else:
        run = st.selectbox("Agent", ready, format_func=label, key="chat_run")
        meta = json.loads(read(run / "run_meta.json") or "{}")
        default_docs = meta.get("docs_dir") or (run.parent / "docs").as_posix()
        docs_dir = st.text_input("Documents folder", default_docs, key=f"docs_{label(run)}")
        history = st.session_state.setdefault(f"chat_{label(run)}", [])
        for m in history:
            st.chat_message(m["role"]).write(m["content"])
        q = st.chat_input("Ask the agent")
        if q:
            st.chat_message("user").write(q)
            try:
                with st.spinner("Thinking..."):
                    res = Agent.from_file(run / "agent_definition.yaml", ROOT / docs_dir).answer(q, history)
                with st.chat_message("assistant"):
                    st.write(res["answer"])
                    if res["refused"]:
                        st.caption("Refused")
                    elif res["sources"]:
                        st.caption("Sources: " + ", ".join(res["sources"]))
                    with st.expander("What happened"):
                        st.write({"retrieved": [h["id"] for h in res["retrieved"]], "tools": res["tool_calls"]})
                history += [{"role": "user", "content": q}, {"role": "assistant", "content": res["answer"]}]
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not answer: {e}")
