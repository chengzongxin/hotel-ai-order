import json
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@lru_cache
def load_prompt(relative_path: str) -> str:
    return (PROMPTS_DIR / relative_path).read_text(encoding="utf-8")


def render_prompt(relative_path: str, **variables: object) -> str:
    prompt = load_prompt(relative_path)
    for key, value in variables.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", to_prompt_text(value))
    return prompt


def to_prompt_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)
