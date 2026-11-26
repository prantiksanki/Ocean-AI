"""Tool registry: csv_lookup, calculator, weather (open-meteo, keyless), current_date.

Each tool declares an `eligible(ctx)` rule so the factory cannot attach a tool the brief
does not need, even if the LLM suggests it.
"""
from __future__ import annotations

import ast
import csv
import datetime as dt
import operator as op
import re
from pathlib import Path

import requests

# ---------- calculator (safe AST evaluator, no eval) ----------
_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
        ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv,
        ast.USub: op.neg, ast.UAdd: op.pos}


def _ev(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        l, r = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and abs(r) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(n.op)](l, r)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_ev(n.operand))
    raise ValueError("unsupported expression")


def calculator(expression: str, **_) -> str:
    expr = str(expression).replace(",", "").replace("×", "*").replace("x", "*") if re.fullmatch(
        r"[\d\s.,+\-*/()%xX×^]+", str(expression)) else str(expression)
    expr = expr.replace("^", "**")
    try:
        val = _ev(ast.parse(expr, mode="eval").body)
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"
    return str(round(val, 6))


# ---------- csv lookup ----------
def csv_lookup(query: str = "", column: str = "", file: str = "", docs_dir: str = ".", **_) -> str:
    """Case-insensitive row search. `query` matches any cell (or only `column` if given)."""
    files = [Path(docs_dir) / file] if file else sorted(Path(docs_dir).rglob("*.csv"))
    hits = []
    for f in files:
        if not f.exists():
            continue
        with open(f, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                cells = [row.get(column, "")] if column and column in row else row.values()
                if any(str(query).lower() in str(c).lower() for c in cells):
                    hits.append({"file": f.name, **row})
    if not hits:
        return "no matching rows"
    return "\n".join(str(h) for h in hits[:10])


# ---------- weather (open-meteo, no API key) ----------
def weather(city: str = "", **_) -> str:
    try:
        g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": city, "count": 1}, timeout=15).json()
        if not g.get("results"):
            return f"unknown city: {city}"
        r = g["results"][0]
        w = requests.get("https://api.open-meteo.com/v1/forecast",
                         params={"latitude": r["latitude"], "longitude": r["longitude"],
                                 "current_weather": "true"}, timeout=15).json()["current_weather"]
        return f"{r['name']}: {w['temperature']}°C, wind {w['windspeed']} km/h"
    except Exception as e:  # noqa: BLE001
        return f"error: weather service unavailable ({e})"


# ---------- current date ----------
def current_date(**_) -> str:
    return dt.date.today().isoformat()


def _has_csv(ctx) -> bool:
    return any(n.lower().endswith(".csv") for n in ctx["doc_names"])


def _kw(*words):
    pat = re.compile("|".join(words), re.I)
    return lambda ctx: bool(pat.search(ctx["text"]))


REGISTRY = {
    "csv_lookup": {
        "description": "Look up rows in a CSV catalogue. args: query (text to find), column (optional).",
        "args": {"query": "text to match", "column": "optional column name"},
        "fn": csv_lookup, "eligible": _has_csv,
    },
    "calculator": {
        "description": "Evaluate an arithmetic expression, e.g. '12*4.5+3'. args: expression.",
        "args": {"expression": "arithmetic expression"},
        "fn": calculator,
        "eligible": _kw(r"calculat", r"\btotal", r"\bcost", r"\bprice", r"\bquote", r"\bsum\b",
                        r"\bquantit", r"\bcompute", r"\bbudget", r"\bconvert", r"\bpercent",
                        r"\bdiscount", r"\bbalance", r"\bprorat"),
    },
    "weather": {
        "description": "Current weather for a city via open-meteo. args: city.",
        "args": {"city": "city name"},
        "fn": weather, "eligible": _kw(r"weather", r"forecast", r"temperature", r"\brain", r"\bwind\b"),
    },
    "current_date": {
        "description": "Today's date (ISO). No args.",
        "args": {},
        "fn": current_date,
        "eligible": _kw(r"today", r"current date", r"\bdeadline", r"days (until|left|since)",
                        r"how long until", r"\bexpir", r"\bwhat day\b", r"\bnotice period"),
    },
}


def eligible_tools(requirements_text: str, doc_names: list[str]) -> list[str]:
    ctx = {"text": requirements_text, "doc_names": doc_names}
    return [n for n, t in REGISTRY.items() if t["eligible"](ctx)]


def describe_tools(names: list[str]) -> str:
    return "\n".join(f"- {n}: {REGISTRY[n]['description']}" for n in names)


def run_tool(name: str, args: dict, docs_dir: str = ".") -> str:
    if name not in REGISTRY:
        return f"error: unknown tool {name}"
    try:
        return str(REGISTRY[name]["fn"](docs_dir=docs_dir, **(args or {})))[:1500]
    except TypeError as e:
        return f"error: bad arguments ({e})"
