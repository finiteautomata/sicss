#!/usr/bin/env python3
"""
Auto-label a JSONL file of tweet comments using an LLM via litellm + instructor.

Usage:
    uv run python autolabel.py
    uv run python autolabel.py --model claude-haiku-4-5-20251001 --concurrency 10
    uv run python autolabel.py --input data.json --output out.json --model ollama/llama3.2
"""

import argparse
import asyncio
import json
from pathlib import Path
from enum import Enum
import instructor
import litellm
from pydantic import BaseModel, Field


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Auto-label tweet comments with an LLM.")
    p.add_argument("--input", "-i", type=Path, default=Path("sample.json"),
                   help="Input JSONL file (default: sample.json)")
    p.add_argument("--output", "-o", type=Path, default=None,
                   help="Output JSON file (default: <input stem>_labeled_llm.json)")
    p.add_argument("--model", "-m", 
                   help="litellm model string (default: gpt-4o-mini)")
    p.add_argument("--concurrency", "-c", type=int, default=5,
                   help="Max parallel requests (default: 5)")
    return p.parse_args()

# ── Pydantic schema ───────────────────────────────────────────────────────────

class HateCategories(str, Enum):
    WOMEN = "WOMEN"
    LGBTI = "LGBTI"
    RACISM = "RACISM"
    CLASS = "CLASS"
    POLITICS = "POLITICS"
    DISABLED = "DISABLED"
    APPEARANCE = "APPEARANCE"
    CRIMINAL = "CRIMINAL"

class CommentLabel(BaseModel):
    HATEFUL: bool = Field(
        description="El comentario contiene discurso de odio explícito hacia un grupo."
    )
    OFFENSIVE: bool = Field(
        description=(
            "El comentario contiene lenguaje ofensivo, insultos o agresividad, "
            "independientemente de si es discurso de odio."
        )
    )
    CALLS: bool = Field(
        description="Incita a actuar en contra de alguien. Solo aplica si HATEFUL=True."
    )
    categories: list[HateCategories] 

# ── LLM ───────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu tarea es detectar discurso de odio en comentarios de Twitter a noticias periodísticas.

Definiciones:
- HATEFUL: discurso de odio explícito hacia un grupo (por género, raza, orientación sexual, etc.)
- OFFENSIVE: lenguaje ofensivo, insultos o agresividad, independientemente de si es discurso de odio.
- CALLS: incitación a actuar en contra de alguien (solo si HATEFUL=True)
- Las categorías WOMEN/LGBTI/RACISM/CLASS/POLITICS/DISABLED/APPEARANCE/CRIMINAL
  solo aplican si HATEFUL=True; marcalas en False si HATEFUL=False.
  
Definiciones de las categorías:
- WOMEN: Sexismo o misoginia
- LGBTI: Homofobia o transfobia
- RACISM: Racismo o xenofobia
- CLASS: Discriminación por clase social
- POLITICS: Odio por afiliación política
- DISABLED: Discriminación por discapacidad
- APPEARANCE: Ataque a la apariencia física
- CRIMINAL: discurso de odio contra personas privadas de libertad

Responder con un JSON con los siguientes campos:
{{
    "HATEFUL": bool,
    "OFFENSIVE": bool,
    "CALLS": bool,
    "categories": list[str]
}}
"""

aclient = instructor.from_litellm(litellm.acompletion)


async def label_item(item: dict, model: str, sem: asyncio.Semaphore) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Contexto: {item["context_tweet"]}\n"
                f"Comentario:\n{item['text']}"
            ),
        },
    ]
    async with sem:
        label: CommentLabel = await aclient.chat.completions.create(
            model=model,
            response_model=CommentLabel,
            messages=messages,
        )
    return {
        "id": item["id"],
        "tweet_id": item["tweet_id"],
        "article_id": item["article_id"],
        "text": item["text"],
        "annotator": f"llm:{model}",
        **label.model_dump(),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    output = args.output or args.input.with_stem(args.input.stem + "_labeled_llm").with_suffix(".json")

    with open(args.input, encoding="utf-8") as f:
        data = [json.loads(line) for line in f if line.strip()]

    print(f"Etiquetando {len(data)} comentarios con {args.model}…")

    sem = asyncio.Semaphore(args.concurrency)
    tasks = [label_item(item, args.model, sem) for item in data]

    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        results.append(result)
        hateful = "🔴" if result["HATEFUL"] else "⚪"
        offensive = "🟡" if result["OFFENSIVE"] else "⚪"
        print(f"  [{i:>3}/{len(data)}] {hateful}HATEFUL {offensive}OFFENSIVE — {result['text'][:60]}")

    # Sort back to original order
    id_order = {item["id"]: i for i, item in enumerate(data)}
    results.sort(key=lambda r: id_order[r["id"]])

    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    hateful_n = sum(1 for r in results if r["HATEFUL"])
    offensive_n = sum(1 for r in results if r["OFFENSIVE"])
    print(f"\nListo → {output}")
    print(f"  HATEFUL:   {hateful_n}/{len(results)}")
    print(f"  OFFENSIVE: {offensive_n}/{len(results)}")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args))
