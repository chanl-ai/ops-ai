"""Where the meaning lane's threshold should sit: a labelled set of pieces and questions (meaning_threshold_set.json)
embedded with OpenAI's embedding models, then each question's cosine to the piece that answers it compared with the
best cosine of questions nothing answers. Two calls per model (the pieces, then the questions); the set is embedded as
kb-service embeds a unit (heading, a blank line, the text: ops_kb.embedding.unit_text).

    OPENAI_API_KEY=... uv run python experiments/meaning_threshold.py [model ...]

Prints, per model, the distributions and, for each threshold, the share of answerable questions whose answering piece
passes it and the share of unanswerable ones whose best piece stays below it. Write-up:
docs/services/kb-service/experiments/meaning-threshold.md."""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any, cast

import httpx

from ops_kb.embedding import unit_text

SET = Path(__file__).with_name("meaning_threshold_set.json")
WIDTH = 1536
MODELS = ("text-embedding-3-small", "text-embedding-3-large")


def embed(http: httpx.Client, model: str, texts: list[str]) -> list[list[float]]:
    r = http.post("/v1/embeddings", json={"model": model, "input": texts, "dimensions": WIDTH})
    r.raise_for_status()
    rows = cast(list[dict[str, Any]], r.json()["data"])
    return [cast(list[float], d["embedding"]) for d in sorted(rows, key=lambda d: int(d["index"]))]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (math.hypot(*a) * math.hypot(*b))


def summary(xs: list[float]) -> str:
    q = statistics.quantiles(xs, n=10)
    return f"min {min(xs):.3f} p10 {q[0]:.3f} median {statistics.median(xs):.3f} p90 {q[-1]:.3f} max {max(xs):.3f}"


def main(models: list[str]) -> None:
    data = cast(dict[str, Any], json.loads(SET.read_text()))
    pieces = cast(list[dict[str, str]], data["pieces"])
    answerable = cast(list[tuple[str, str]], data["answerable"])
    unanswerable = cast(list[str], data["unanswerable"])
    ids = [p["id"] for p in pieces]
    key = os.environ["OPENAI_API_KEY"]
    with httpx.Client(base_url="https://api.openai.com", headers={"Authorization": f"Bearer {key}"}, timeout=60) as h:
        for model in models:
            vectors = embed(h, model, [unit_text(p["heading"], p["text"]) for p in pieces])
            qv = embed(h, model, [q for q, _ in answerable] + unanswerable)
            gold: list[float] = []
            rival: list[float] = []
            unanswered: list[float] = []
            top1 = 0
            for (_, want), v in zip(answerable, qv, strict=False):
                scores = {i: cosine(v, pv) for i, pv in zip(ids, vectors, strict=True)}
                gold.append(scores[want])
                rival.append(max(s for i, s in scores.items() if i != want))
                top1 += max(scores, key=lambda i: scores[i]) == want
            for v in qv[len(answerable) :]:
                unanswered.append(max(cosine(v, pv) for pv in vectors))
            print(f"\n{model} at {WIDTH}: {len(gold)} answerable, {len(unanswered)} unanswerable, 2 calls")
            print(f"  answering piece first: {top1} of {len(gold)}")
            print(f"  answering piece:          {summary(gold)}")
            print(f"  best other piece:         {summary(rival)}")
            print(f"  unanswerable, best piece: {summary(unanswered)}")
            print("  threshold, answerable kept, unanswerable withheld")
            best = max(
                (t / 100 for t in range(15, 71)),
                key=lambda t: sum(g >= t for g in gold) / len(gold) + sum(u < t for u in unanswered) / len(unanswered),
            )
            for t in [x / 100 for x in range(15, 71, 5)] + [best]:
                kept = sum(g >= t for g in gold) / len(gold)
                withheld = sum(u < t for u in unanswered) / len(unanswered)
                mark = "  <- best balanced" if t == best else ""
                print(
                    f"  {t:.2f}  {kept:6.0%} kept  {withheld:6.0%} withheld  balanced {(kept + withheld) / 2:.2f}{mark}"
                )


if __name__ == "__main__":
    main(sys.argv[1:] or list(MODELS))
