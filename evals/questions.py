"""Loading and validating the question set."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "questions" / "questions.yaml"

REQUIRED_FIELDS = ("id", "question", "sql")
DIFFICULTIES = frozenset({"easy", "medium", "hard"})


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    sql: str
    difficulty: str = "medium"
    features: list[str] = field(default_factory=list)


def load_questions(path: Path | None = None) -> list[Question]:
    raw = yaml.safe_load((path or QUESTIONS_PATH).read_text(encoding="utf-8")) or []
    questions = [
        Question(
            id=str(entry["id"]),
            question=entry["question"].strip(),
            sql=entry["sql"].strip(),
            difficulty=entry.get("difficulty", "medium"),
            features=list(entry.get("features") or []),
        )
        for entry in raw
    ]
    problems = validate(questions)
    if problems:
        raise ValueError("question set is invalid:\n  " + "\n  ".join(problems))
    return questions


def validate(questions: list[Question]) -> list[str]:
    """Structural checks that would otherwise fail deep inside a paid sweep."""
    problems: list[str] = []

    seen: set[str] = set()
    for question in questions:
        if question.id in seen:
            problems.append(f"duplicate id {question.id!r}")
        seen.add(question.id)

        for name in REQUIRED_FIELDS:
            if not getattr(question, name, None):
                problems.append(f"{question.id}: missing {name}")

        if question.difficulty not in DIFFICULTIES:
            problems.append(
                f"{question.id}: difficulty {question.difficulty!r} "
                f"not one of {sorted(DIFFICULTIES)}"
            )
        # The report groups by feature and the CLI filters on them; a stray comma
        # means someone wrote "[a, b]" as one string and the grouping silently
        # gains a phantom tag.
        for tag in question.features:
            if "," in tag:
                problems.append(f"{question.id}: feature tag {tag!r} contains a comma")

    return problems


def answer_key(questions: list[Question]) -> dict[str, str]:
    """Question text to reference SQL -- what the stub provider answers from."""
    return {q.question: q.sql for q in questions}
