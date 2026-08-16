"""Turning a run into a report.

Accuracy alone says a model got 62% and nothing about what to do next, so every
table here answers a follow-up question: which SQL constructs it gets wrong,
which failure classes dominate, and what each point of accuracy cost.
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .taxonomy import Failure, is_retryable


@dataclass(frozen=True)
class Group:
    label: str
    total: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def _group(rows: list[dict], key) -> list[Group]:
    totals: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    for row in rows:
        for label in key(row):
            totals[label] += 1
            correct[label] += bool(row["correct"])
    return [Group(label, totals[label], correct[label]) for label in sorted(totals)]


def _bar(fraction: float, width: int = 20) -> str:
    filled = round(fraction * width)
    return "█" * filled + "·" * (width - filled)


def _table(header: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    header = list(header)
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def build_report(run: dict[str, Any]) -> str:
    rows: list[dict] = run["attempts"]
    total = len(rows)
    correct = sum(r["correct"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    latencies = sorted(r["latency_ms"] for r in rows)

    def percentile(p: float) -> float:
        if not latencies:
            return 0.0
        return latencies[min(int(len(latencies) * p), len(latencies) - 1)]

    parts: list[str] = []
    parts.append("# Text-to-SQL evaluation\n")
    parts.append(
        f"**{correct}/{total} correct ({correct / total if total else 0:.1%})** · "
        f"${cost:.4f} · p50 {percentile(0.5) / 1000:.1f}s · p95 {percentile(0.95) / 1000:.1f}s\n"
    )
    parts.append(
        f"Fixture: `{run['fixture']}` · questions: {run['question_count']} · "
        f"models: {', '.join(run['models'])} · variants: {', '.join(run['variants'])}\n"
    )

    # ── by model × variant ────────────────────────────────────────────────────
    parts.append("\n## Accuracy by model and prompt variant\n")
    combos: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        combos[(row["model"], row["variant"])].append(row)
    parts.append(_table(
        ["Model", "Variant", "Accuracy", "", "Cost", "Avg latency"],
        [
            [
                model, variant,
                f"{sum(r['correct'] for r in group)}/{len(group)}",
                _bar(sum(r["correct"] for r in group) / len(group)),
                f"${sum(r['cost_usd'] for r in group):.4f}",
                f"{sum(r['latency_ms'] for r in group) / len(group) / 1000:.1f}s",
            ]
            for (model, variant), group in sorted(combos.items())
        ],
    ))

    # ── failure taxonomy ──────────────────────────────────────────────────────
    parts.append("\n\n## Failure modes\n")
    failures = Counter(r["failure"] for r in rows if not r["correct"])
    if failures:
        parts.append(
            "Retryable failures are ones the database explained -- the model can "
            "act on the error text. The rest are wrong-but-valid queries, where "
            "there is nothing to feed back.\n"
        )
        parts.append(_table(
            ["Failure", "Count", "Share of failures", "Retryable"],
            [
                [
                    name, count, f"{count / sum(failures.values()):.0%}",
                    "yes" if is_retryable(Failure(name)) else "no",
                ]
                for name, count in failures.most_common()
            ],
        ))
    else:
        parts.append("No failures.\n")

    # ── by difficulty and feature ─────────────────────────────────────────────
    parts.append("\n\n## Accuracy by difficulty\n")
    parts.append(_table(
        ["Difficulty", "Accuracy", ""],
        [
            [g.label, f"{g.correct}/{g.total}", _bar(g.accuracy)]
            for g in sorted(
                _group(rows, lambda r: [r["difficulty"]]),
                key=lambda g: ["easy", "medium", "hard"].index(g.label)
                if g.label in ("easy", "medium", "hard") else 99,
            )
        ],
    ))

    parts.append("\n\n## Accuracy by SQL feature\n")
    parts.append(
        "Which constructs the model actually gets wrong. A question counts "
        "toward every feature it requires.\n"
    )
    feature_groups = sorted(
        _group(rows, lambda r: r["features"]), key=lambda g: (g.accuracy, g.label)
    )
    parts.append(_table(
        ["Feature", "Accuracy", ""],
        [[g.label, f"{g.correct}/{g.total}", _bar(g.accuracy)] for g in feature_groups],
    ))

    # ── retries ───────────────────────────────────────────────────────────────
    retried = [r for r in rows if r["attempts"] > 1]
    if retried:
        recovered = sum(r["correct"] for r in retried)
        parts.append("\n\n## Retry\n")
        parts.append(
            f"{len(retried)} attempt(s) hit a retryable database error and were "
            f"re-prompted with it; {recovered} then succeeded "
            f"({recovered / len(retried):.0%} recovery).\n"
        )

    # ── per-question detail ───────────────────────────────────────────────────
    parts.append("\n\n## Every question\n")
    parts.append(_table(
        ["ID", "Difficulty", "Model", "Variant", "Result", "Detail"],
        [
            [
                r["question_id"], r["difficulty"], r["model"], r["variant"],
                "correct" if r["correct"] else r["failure"],
                (r["detail"][:80] + "…") if len(r["detail"]) > 80 else (r["detail"] or ""),
            ]
            for r in sorted(rows, key=lambda r: (r["model"], r["variant"], r["question_id"]))
        ],
    ))

    parts.append(
        "\n\n---\n\n*Execution accuracy: a query is correct when its result set "
        "matches the reference query's, not when its SQL matches. The comparison "
        "policy is documented in `evals/compare.py`.*\n"
    )
    return "\n".join(parts)


def write_report(run_path: Path, out_path: Path) -> Path:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_report(run), encoding="utf-8")
    return out_path
