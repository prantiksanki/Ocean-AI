"""Loads committed prompt files. Placeholders use {name} and are replaced literally
(prompts contain JSON braces, so str.format is not used)."""
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(name: str, **vars) -> str:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{" + k + "}", str(v))
    return text
