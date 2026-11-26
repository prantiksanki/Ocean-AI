"""Generic chat runner: loads ANY agent_definition.yaml.

    python -m runner.chat path/to/agent_definition.yaml --docs path/to/docs
"""
import argparse

from forgeai.agent import Agent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("definition")
    ap.add_argument("--docs", required=True)
    ap.add_argument("--debug", action="store_true", help="show retrieval and tool calls")
    ap.add_argument("--ask", help="single question, non-interactive")
    a = ap.parse_args()
    agent = Agent.from_file(a.definition, a.docs)
    print(f"Loaded '{agent.defn['name']}' | tools: {agent.tool_names or 'none'} | type 'exit' to quit")
    history: list[dict] = []

    def turn(q):
        r = agent.answer(q, history)
        print(f"\nagent> {r['answer']}")
        if r["sources"]:
            print(f"       sources: {', '.join(r['sources'])}")
        if a.debug:
            print(f"       retrieved: {[h['id'] for h in r['retrieved']]}  tools: {r['tool_calls']}")
        history.extend([{"role": "user", "content": q}, {"role": "assistant", "content": r["answer"]}])

    if a.ask:
        return turn(a.ask)
    while True:
        try:
            q = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"exit", "quit"}:
            break
        if q:
            turn(q)


if __name__ == "__main__":
    main()
