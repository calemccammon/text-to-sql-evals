# Text-to-SQL evaluation

**22/72 correct (30.6%)** · $0.0000 · p50 5.7s · p95 8.0s

Fixture: `fixture` · questions: 24 · models: llama3.2:latest · variants: names_only, full, full_with_samples


## Accuracy by model and prompt variant

| Model | Variant | Accuracy |  | Cost | Avg latency |
|---|---|---|---|---|---|
| llama3.2:latest | full | 10/24 | ████████············ | $0.0000 | 4.4s |
| llama3.2:latest | full_with_samples | 11/24 | █████████··········· | $0.0000 | 4.2s |
| llama3.2:latest | names_only | 1/24 | █··················· | $0.0000 | 6.5s |


## Failure modes

Retryable failures are ones the database explained -- the model can act on the error text. The rest are wrong-but-valid queries, where there is nothing to feed back.

| Failure | Count | Share of failures | Retryable |
|---|---|---|---|
| unknown_column | 28 | 56% | yes |
| wrong_shape | 9 | 18% | no |
| wrong_values | 8 | 16% | no |
| syntax_error | 3 | 6% | yes |
| execution_error | 1 | 2% | yes |
| wrong_order | 1 | 2% | no |


## Accuracy by difficulty

| Difficulty | Accuracy |  |
|---|---|---|
| easy | 9/18 | ██████████·········· |
| medium | 9/33 | █████··············· |
| hard | 4/21 | ████················ |


## Accuracy by SQL feature

Which constructs the model actually gets wrong. A question counts toward every feature it requires.

| Feature | Accuracy |  |
|---|---|---|
| cte | 0/3 | ···················· |
| join | 0/9 | ···················· |
| arithmetic | 1/12 | ██·················· |
| date | 1/9 | ██·················· |
| group | 5/33 | ███················· |
| order | 11/54 | ████················ |
| subquery | 4/18 | ████················ |
| window | 2/9 | ████················ |
| aggregate | 14/45 | ██████·············· |
| filter | 7/21 | ███████············· |
| grain | 2/6 | ███████············· |
| limit | 7/21 | ███████············· |


## Retry

42 attempt(s) hit a retryable database error and were re-prompted with it; 2 then succeeded (5% recovery).



## Every question

| ID | Difficulty | Model | Variant | Result | Detail |
|---|---|---|---|---|---|
| q01 | easy | llama3.2:latest | full | correct |  |
| q02 | easy | llama3.2:latest | full | correct |  |
| q03 | easy | llama3.2:latest | full | correct |  |
| q04 | easy | llama3.2:latest | full | correct |  |
| q05 | easy | llama3.2:latest | full | wrong_values | row 0 differs: expected ('Technology', 3), got ('Technology', 1503) |
| q06 | easy | llama3.2:latest | full | wrong_shape | expected 2 column(s), got 1 |
| q07 | medium | llama3.2:latest | full | correct |  |
| q08 | medium | llama3.2:latest | full | wrong_values | row 0 differs: expected ('Communication Services', 37.165350000000004), got ('Co… |
| q09 | medium | llama3.2:latest | full | unknown_column | Binder Error: Table "T1" does not have a column named "year_month_key"

Candidat… |
| q10 | medium | llama3.2:latest | full | correct |  |
| q11 | medium | llama3.2:latest | full | wrong_values | row 0 differs: expected ('AAPL', 143.68619999999999), got ('AMZN', 3.18999999999… |
| q12 | medium | llama3.2:latest | full | correct |  |
| q13 | hard | llama3.2:latest | full | correct |  |
| q14 | medium | llama3.2:latest | full | wrong_shape | expected 3 row(s), got 5010 |
| q15 | medium | llama3.2:latest | full | wrong_shape | expected 1 column(s), got 33 |
| q16 | medium | llama3.2:latest | full | execution_error | Binder Error: No function matches the given name and argument types '~~(DATE, ST… |
| q17 | hard | llama3.2:latest | full | wrong_values | row 0 differs: expected ('AAPL', 55.0), got ('AAPL', 0.5489021956087824) |
| q18 | hard | llama3.2:latest | full | unknown_column | Binder Error: Referenced column "day_name" not found in FROM clause!
Candidate b… |
| q19 | hard | llama3.2:latest | full | unknown_column | Binder Error: Table "fct_daily_trading" does not have a column named "quarter_nu… |
| q20 | hard | llama3.2:latest | full | correct |  |
| q21 | hard | llama3.2:latest | full | syntax_error | Parser Error: syntax error at or near "SELECT"

LINE 56: SELECT 
         ^ |
| q22 | medium | llama3.2:latest | full | correct |  |
| q23 | medium | llama3.2:latest | full | unknown_column | Binder Error: Table "fct_daily_trading" does not have a column named "market_cap… |
| q24 | hard | llama3.2:latest | full | unknown_column | Binder Error: column "close_price" must appear in the GROUP BY clause or must be… |
| q01 | easy | llama3.2:latest | full_with_samples | correct |  |
| q02 | easy | llama3.2:latest | full_with_samples | correct |  |
| q03 | easy | llama3.2:latest | full_with_samples | correct |  |
| q04 | easy | llama3.2:latest | full_with_samples | correct |  |
| q05 | easy | llama3.2:latest | full_with_samples | correct |  |
| q06 | easy | llama3.2:latest | full_with_samples | wrong_shape | expected 2 column(s), got 1 |
| q07 | medium | llama3.2:latest | full_with_samples | correct |  |
| q08 | medium | llama3.2:latest | full_with_samples | wrong_values | row 0 differs: expected ('Communication Services', 37.165350000000004), got ('Co… |
| q09 | medium | llama3.2:latest | full_with_samples | wrong_shape | expected 1 row(s), got 501 |
| q10 | medium | llama3.2:latest | full_with_samples | wrong_values | row 0 differs: expected (359,), got (141,) |
| q11 | medium | llama3.2:latest | full_with_samples | wrong_shape | expected 10 row(s), got 5010 |
| q12 | medium | llama3.2:latest | full_with_samples | correct |  |
| q13 | hard | llama3.2:latest | full_with_samples | correct |  |
| q14 | medium | llama3.2:latest | full_with_samples | wrong_shape | expected 3 row(s), got 5010 |
| q15 | medium | llama3.2:latest | full_with_samples | wrong_shape | expected 1 column(s), got 3 |
| q16 | medium | llama3.2:latest | full_with_samples | correct |  |
| q17 | hard | llama3.2:latest | full_with_samples | wrong_values | row 0 differs: expected ('AAPL', 55.0), got ('AAPL', 0.5361916167664671) |
| q18 | hard | llama3.2:latest | full_with_samples | unknown_column | Binder Error: Table "T1" does not have a column named "day_name"

Candidate bind… |
| q19 | hard | llama3.2:latest | full_with_samples | unknown_column | Binder Error: Table "fct_daily_trading" does not have a column named "year"

Can… |
| q20 | hard | llama3.2:latest | full_with_samples | correct |  |
| q21 | hard | llama3.2:latest | full_with_samples | wrong_order | correct rows in the wrong order |
| q22 | medium | llama3.2:latest | full_with_samples | correct |  |
| q23 | medium | llama3.2:latest | full_with_samples | wrong_values | row 0 differs: expected ('Communication Services', 2, 5956141187072), got ('Comm… |
| q24 | hard | llama3.2:latest | full_with_samples | unknown_column | Binder Error: column "close_price" must appear in the GROUP BY clause or must be… |
| q01 | easy | llama3.2:latest | names_only | unknown_column | Binder Error: Table "t" does not have a column named "company"

Candidate bindin… |
| q02 | easy | llama3.2:latest | names_only | unknown_column | Binder Error: Table "t" does not have a column named "date"

Candidate bindings:… |
| q03 | easy | llama3.2:latest | names_only | unknown_column | Binder Error: Table "t" does not have a column named "date"

Candidate bindings:… |
| q04 | easy | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "company" not found in FROM clause!
Candidate bi… |
| q05 | easy | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "company_id" not found in FROM clause!
Candidate… |
| q06 | easy | llama3.2:latest | names_only | wrong_shape | expected 2 column(s), got 1 |
| q07 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Table "fct_daily_trading" does not have a column named "date"

Can… |
| q08 | medium | llama3.2:latest | names_only | syntax_error | Parser Error: syntax error at end of input |
| q09 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Table "T1" does not have a column named "date"

Candidate bindings… |
| q10 | medium | llama3.2:latest | names_only | syntax_error | Parser Error: syntax error at or near "ROWS"

LINE 10: ...trading.symbol = 'AAPL… |
| q11 | medium | llama3.2:latest | names_only | correct |  |
| q12 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "date" not found in FROM clause!
Candidate bindi… |
| q13 | hard | llama3.2:latest | names_only | unknown_column | Binder Error: Table "T1" does not have a column named "date_id"

Candidate bindi… |
| q14 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "date" not found in FROM clause!
Candidate bindi… |
| q15 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "date" not found in FROM clause!
Candidate bindi… |
| q16 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "date" not found in FROM clause!
Candidate bindi… |
| q17 | hard | llama3.2:latest | names_only | unknown_column | Binder Error: Table "f" does not have a column named "date"

Candidate bindings:… |
| q18 | hard | llama3.2:latest | names_only | unknown_column | Binder Error: Table "ft" does not have a column named "date_key"

Candidate bind… |
| q19 | hard | llama3.2:latest | names_only | unknown_column | Binder Error: Table "f" does not have a column named "date_key"

Candidate bindi… |
| q20 | hard | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "symbol" not found in FROM clause!
Candidate bin… |
| q21 | hard | llama3.2:latest | names_only | unknown_column | Binder Error: Table "f" does not have a column named "date"

Candidate bindings:… |
| q22 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "date" not found in FROM clause!
Candidate bindi… |
| q23 | medium | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "market_cap" not found in FROM clause!
Candidate… |
| q24 | hard | llama3.2:latest | names_only | unknown_column | Binder Error: Referenced column "date" not found in FROM clause!
Candidate bindi… |


---

*Execution accuracy: a query is correct when its result set matches the reference query's, not when its SQL matches. The comparison policy is documented in `evals/compare.py`.*
