# Text-to-SQL evaluation

**63/72 correct (87.5%)** · $0.0000 · p50 0.0s · p95 0.0s

Fixture: `fixture` · questions: 24 · models: stub-v1 · variants: names_only, full, full_with_samples


## Accuracy by model and prompt variant

| Model | Variant | Accuracy |  | Cost | Avg latency |
|---|---|---|---|---|---|
| stub-v1 | full | 21/24 | ██████████████████·· | $0.0000 | 0.0s |
| stub-v1 | full_with_samples | 21/24 | ██████████████████·· | $0.0000 | 0.0s |
| stub-v1 | names_only | 21/24 | ██████████████████·· | $0.0000 | 0.0s |


## Failure modes

Retryable failures are ones the database explained -- the model can act on the error text. The rest are wrong-but-valid queries, where there is nothing to feed back.

| Failure | Count | Share of failures | Retryable |
|---|---|---|---|
| wrong_shape | 3 | 33% | no |
| unknown_table | 3 | 33% | yes |
| syntax_error | 3 | 33% | yes |


## Accuracy by difficulty

| Difficulty | Accuracy |  |
|---|---|---|
| easy | 12/18 | █████████████······· |
| medium | 33/33 | ████████████████████ |
| hard | 18/21 | █████████████████··· |


## Accuracy by SQL feature

Which constructs the model actually gets wrong. A question counts toward every feature it requires.

| Feature | Accuracy |  |
|---|---|---|
| grain | 3/6 | ██████████·········· |
| filter | 18/21 | █████████████████··· |
| limit | 18/21 | █████████████████··· |
| aggregate | 39/45 | █████████████████··· |
| order | 48/54 | ██████████████████·· |
| group | 30/33 | ██████████████████·· |
| arithmetic | 12/12 | ████████████████████ |
| cte | 3/3 | ████████████████████ |
| date | 9/9 | ████████████████████ |
| join | 9/9 | ████████████████████ |
| subquery | 18/18 | ████████████████████ |
| window | 9/9 | ████████████████████ |


## Retry

6 attempt(s) hit a retryable database error and were re-prompted with it; 0 then succeeded (0% recovery).



## Every question

| ID | Difficulty | Model | Variant | Result | Detail |
|---|---|---|---|---|---|
| q01 | easy | stub-v1 | full | correct |  |
| q02 | easy | stub-v1 | full | wrong_shape | expected 3 row(s), got 1 |
| q03 | easy | stub-v1 | full | correct |  |
| q04 | easy | stub-v1 | full | correct |  |
| q05 | easy | stub-v1 | full | unknown_table | Catalog Error: Table with name nonexistent_table does not exist!
Did you mean "s… |
| q06 | easy | stub-v1 | full | correct |  |
| q07 | medium | stub-v1 | full | correct |  |
| q08 | medium | stub-v1 | full | correct |  |
| q09 | medium | stub-v1 | full | correct |  |
| q10 | medium | stub-v1 | full | correct |  |
| q11 | medium | stub-v1 | full | correct |  |
| q12 | medium | stub-v1 | full | correct |  |
| q13 | hard | stub-v1 | full | syntax_error | Parser Error: syntax error at or near "SELECT"

LINE 3:   SELECT DISTINCT tradin… |
| q14 | medium | stub-v1 | full | correct |  |
| q15 | medium | stub-v1 | full | correct |  |
| q16 | medium | stub-v1 | full | correct |  |
| q17 | hard | stub-v1 | full | correct |  |
| q18 | hard | stub-v1 | full | correct |  |
| q19 | hard | stub-v1 | full | correct |  |
| q20 | hard | stub-v1 | full | correct |  |
| q21 | hard | stub-v1 | full | correct |  |
| q22 | medium | stub-v1 | full | correct |  |
| q23 | medium | stub-v1 | full | correct |  |
| q24 | hard | stub-v1 | full | correct |  |
| q01 | easy | stub-v1 | full_with_samples | correct |  |
| q02 | easy | stub-v1 | full_with_samples | wrong_shape | expected 3 row(s), got 1 |
| q03 | easy | stub-v1 | full_with_samples | correct |  |
| q04 | easy | stub-v1 | full_with_samples | correct |  |
| q05 | easy | stub-v1 | full_with_samples | unknown_table | Catalog Error: Table with name nonexistent_table does not exist!
Did you mean "s… |
| q06 | easy | stub-v1 | full_with_samples | correct |  |
| q07 | medium | stub-v1 | full_with_samples | correct |  |
| q08 | medium | stub-v1 | full_with_samples | correct |  |
| q09 | medium | stub-v1 | full_with_samples | correct |  |
| q10 | medium | stub-v1 | full_with_samples | correct |  |
| q11 | medium | stub-v1 | full_with_samples | correct |  |
| q12 | medium | stub-v1 | full_with_samples | correct |  |
| q13 | hard | stub-v1 | full_with_samples | syntax_error | Parser Error: syntax error at or near "SELECT"

LINE 3:   SELECT DISTINCT tradin… |
| q14 | medium | stub-v1 | full_with_samples | correct |  |
| q15 | medium | stub-v1 | full_with_samples | correct |  |
| q16 | medium | stub-v1 | full_with_samples | correct |  |
| q17 | hard | stub-v1 | full_with_samples | correct |  |
| q18 | hard | stub-v1 | full_with_samples | correct |  |
| q19 | hard | stub-v1 | full_with_samples | correct |  |
| q20 | hard | stub-v1 | full_with_samples | correct |  |
| q21 | hard | stub-v1 | full_with_samples | correct |  |
| q22 | medium | stub-v1 | full_with_samples | correct |  |
| q23 | medium | stub-v1 | full_with_samples | correct |  |
| q24 | hard | stub-v1 | full_with_samples | correct |  |
| q01 | easy | stub-v1 | names_only | correct |  |
| q02 | easy | stub-v1 | names_only | wrong_shape | expected 3 row(s), got 1 |
| q03 | easy | stub-v1 | names_only | correct |  |
| q04 | easy | stub-v1 | names_only | correct |  |
| q05 | easy | stub-v1 | names_only | unknown_table | Catalog Error: Table with name nonexistent_table does not exist!
Did you mean "s… |
| q06 | easy | stub-v1 | names_only | correct |  |
| q07 | medium | stub-v1 | names_only | correct |  |
| q08 | medium | stub-v1 | names_only | correct |  |
| q09 | medium | stub-v1 | names_only | correct |  |
| q10 | medium | stub-v1 | names_only | correct |  |
| q11 | medium | stub-v1 | names_only | correct |  |
| q12 | medium | stub-v1 | names_only | correct |  |
| q13 | hard | stub-v1 | names_only | syntax_error | Parser Error: syntax error at or near "SELECT"

LINE 3:   SELECT DISTINCT tradin… |
| q14 | medium | stub-v1 | names_only | correct |  |
| q15 | medium | stub-v1 | names_only | correct |  |
| q16 | medium | stub-v1 | names_only | correct |  |
| q17 | hard | stub-v1 | names_only | correct |  |
| q18 | hard | stub-v1 | names_only | correct |  |
| q19 | hard | stub-v1 | names_only | correct |  |
| q20 | hard | stub-v1 | names_only | correct |  |
| q21 | hard | stub-v1 | names_only | correct |  |
| q22 | medium | stub-v1 | names_only | correct |  |
| q23 | medium | stub-v1 | names_only | correct |  |
| q24 | hard | stub-v1 | names_only | correct |  |


---

*Execution accuracy: a query is correct when its result set matches the reference query's, not when its SQL matches. The comparison policy is documented in `evals/compare.py`.*
