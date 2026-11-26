import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forgeai import judge
from forgeai.ingest import chunk_text, keyword_overlap
from forgeai.llm import extract_json
from forgeai.tools import eligible_tools
from forgeai.tools.registry import calculator, csv_lookup


def test_calculator_safe():
    assert calculator("12*4.5+3") == "57.0"
    assert calculator("2**3") == "8"
    assert calculator("__import__('os').system('echo hi')").startswith("error")
    assert calculator("9**999").startswith("error")


def test_chunking_overlap_and_size():
    text = "\n".join(f"Line number {i} with some words in it." for i in range(100))
    cs = chunk_text(text, 300, 50)
    assert len(cs) > 3 and all(len(c) < 500 for c in cs)


def test_extract_json_tolerant():
    assert extract_json('Sure! ```json\n{"a": 1}\n``` done') == {"a": 1}
    assert extract_json('<think>x</think>{"a": 2}') == {"a": 2}


def test_tool_eligibility_hr_gets_no_weather():
    txt = "HR policy assistant for shore staff: annual leave, remote work, expense claims"
    assert "weather" not in eligible_tools(txt, ["leave.pdf", "expenses.pdf"])
    assert "csv_lookup" not in eligible_tools(txt, ["leave.pdf"])


def test_tool_eligibility_spares():
    txt = "procurement assistant: look up part prices and calculate the total cost of an order"
    t = eligible_tools(txt, ["catalogue.csv", "supplier.pdf"])
    assert "csv_lookup" in t and "calculator" in t and "weather" not in t


def test_csv_lookup():
    import tempfile
    with tempfile.TemporaryDirectory(dir=str(Path(__file__).parent)) as d:
        (Path(d) / "p.csv").write_text("part,price\nPump,10\nValve,20\n")
        assert "Valve" in csv_lookup(query="valve", docs_dir=d)
        assert csv_lookup(query="zzz", docs_dir=d) == "no matching rows"


def test_keyword_overlap():
    assert keyword_overlap("stock option vesting", ["annual leave is 25 days"]) == 0
    assert keyword_overlap("annual leave", ["annual leave is 25 days"]) == 1


def test_judge_selftest():
    assert judge.selftest()["all_ok"]


def test_judge_thousands_separator_is_grounded():
    assert judge.ungrounded_numbers("Claims up to USD 2,000.", "claims above USD 2,000 need approval") == []
    assert judge.ungrounded_numbers("USD 1000", "allowance of USD 1,000") == []
    assert judge.ungrounded_numbers("USD 3,500", "allowance of USD 1,000") == ["3,500"]


def test_explicit_no_information_counts_as_refusal():
    r = {"refused": False, "sources": ["a.pdf"],
         "answer": "The provided context does not contain information about sea staff."}
    assert judge.looks_like_refusal(r)
    assert not judge.looks_like_refusal({**r, "answer": "You get 25 days."})
