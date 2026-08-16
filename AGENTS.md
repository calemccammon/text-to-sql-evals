# Working in this repo

## The invariant

`fixture/*.parquet` is **frozen**. Do not regenerate, refresh, or "update" it.
An eval whose dataset moves cannot distinguish a model regression from a data
change, which is the entire reason the fixture is committed rather than pulled
from the source warehouse at run time. `tests/test_warehouse.py` asserts its
exact date span and row count so a silent replacement fails CI.

## Adding a question

1. Add it to `questions/questions.yaml` with reference SQL, a difficulty, and
   `features` tags.
2. Give the reference an `ORDER BY` **only** if the question asks for an
   ordering — the comparison treats row order as significant exactly when the
   reference is ordered, so a gratuitous `ORDER BY` fails correct candidates.
3. Confirm it returns rows. An empty reference scores every empty candidate as
   correct; `tests/test_harness.py` checks this.

## Changing `evals/compare.py`

This file decides what "correct" means, so a change here moves every number in
every report. Each rule in its docstring has a named test in
`tests/test_compare.py` — change the tests deliberately, never to make a new
behavior pass.

## Model API notes

- `temperature`, `top_p`, and `top_k` are **removed** on Claude Opus 5, Sonnet 5,
  and Opus 4.8/4.7 — sending any of them returns a 400. Do not add a temperature
  knob back to `providers.py`.
- Assistant-turn prefills also 400 on these models, so the SQL cannot be forced
  by prefilling `SELECT`. `extract_sql` handles fences and preamble instead.
- Thinking is on by default on Opus 5, and `max_tokens` caps thinking *plus*
  response text — hence the generous default in `providers.py`.
- Always check `stop_reason` before reading `response.content`; a declined
  request returns HTTP 200 with empty content.

## Running things

- `python main.py run` — offline stub sweep, no key, no cost. This is what CI runs.
- `python main.py run --model claude-opus-5` — a real sweep; needs the `live`
  dependency group and a credential.
- `python main.py report` — rebuild `REPORT.md` from the committed run.
- Never commit a `REPORT.md` that disagrees with `results/latest-run.json`; CI
  regenerates and diffs it.
