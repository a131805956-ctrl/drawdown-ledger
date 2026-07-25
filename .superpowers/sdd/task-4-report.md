# Task 4 Report: Optimizer, Job Persistence, and Versioned FastAPI

## Outcome

- Status: DONE
- Branch: `feature/ai-batch`
- Implementation commit: `bed697c`
- Merge/PR: intentionally not performed
- Python: `C:\Users\10931\.drawdown-ledger\py311\Scripts\python.exe`
- Live source: `PYTHONPATH=apps/api/src`
- Dependency install: non-editable `python -m pip install '.[dev]'`

## RED/GREEN evidence

### Baseline

Command:

```powershell
python -m pytest apps/api/tests -q
```

Result before Task 4 changes: `81 passed in 3.25s`.

### Optimizer RED

Command:

```powershell
python -m pytest apps/api/tests/optimization -q
```

Observed failure: three collection errors with
`ModuleNotFoundError: No module named 'drawdown_lab.optimization'`.
After the first implementation pass, the tests produced three behavioral failures:
stable-plateau selection and two chronological split assertions.

### Optimizer GREEN

Command:

```powershell
python -m pytest apps/api/tests/optimization -q
```

Result: `14 passed in 0.30s`.

### API/storage RED

Command:

```powershell
python -m pytest apps/api/tests/api -q
```

Observed failure: two collection errors with
`ModuleNotFoundError: No module named 'drawdown_lab.api'`.
After the first implementation pass, a contract test failed because the typed
instrument response omitted the persisted domain field `inception`.

A separate app-factory RED test failed with:

```text
TypeError: Settings.__init__() missing 1 required positional argument: 'data_root'
```

### API/storage GREEN

Commands:

```powershell
python -m pytest apps/api/tests/api -q
python -m pytest apps/api/tests/api/test_contract.py::test_settings_default_data_root_is_usable_for_app_factory -q
```

Results: `6 passed in 1.69s` for the first API cycle, then the default-settings
regression passed. A fixed inline market fixture also passed through both
`/evidence/analyze` and `/strategies/backtest`.

## Final verification

Fresh pre-commit command:

```powershell
python -m pytest apps/api/tests -q
python -m ruff check apps/api
python -m mypy apps/api/src
```

Results:

```text
103 passed in 4.20s
All checks passed!
Success: no issues found in 34 source files
```

The output contained no warnings. The 103 tests comprise the preserved 81-test
baseline plus 22 Task 4 tests.

## Implemented files

Runtime:

- `apps/api/src/drawdown_lab/optimization/__init__.py`
- `apps/api/src/drawdown_lab/optimization/grid.py`
- `apps/api/src/drawdown_lab/optimization/walk_forward.py`
- `apps/api/src/drawdown_lab/optimization/scoring.py`
- `apps/api/src/drawdown_lab/optimization/pareto.py`
- `apps/api/src/drawdown_lab/storage/__init__.py`
- `apps/api/src/drawdown_lab/storage/database.py`
- `apps/api/src/drawdown_lab/storage/jobs.py`
- `apps/api/src/drawdown_lab/api/__init__.py`
- `apps/api/src/drawdown_lab/api/schemas.py`
- `apps/api/src/drawdown_lab/api/routes.py`
- `apps/api/src/drawdown_lab/api/app.py`
- `pyproject.toml`

Tests:

- `apps/api/tests/optimization/test_grid.py`
- `apps/api/tests/optimization/test_walk_forward.py`
- `apps/api/tests/optimization/test_scoring.py`
- `apps/api/tests/api/test_contract.py`
- `apps/api/tests/api/test_jobs.py`
- `apps/api/tests/api/test_analysis_routes.py`

## Self-review

- Grid ratios are integer basis points. Four monotone tiers at 10 percentage
  point increments produce exactly 1,001 lexicographically deterministic
  vectors; unrestricted search produces 14,641.
- Walk-forward windows are expanding, contiguous, chronological, deterministic,
  and reject unsorted or insufficient observations.
- Independent episode minimums gate formal recommendations. Insufficient samples
  return `exploration_only`, an empty recommendation list, and no candidate labels.
- Balanced selection applies worst-5%, early-depletion, and long-trap constraints
  before ranking actual OOS XIRR with an isolated-neighbor peak penalty.
  Conservative, balanced, and aggressive recommendations retain separate labels.
- Synthetic history is stored only as a separate pass/fail stress field and is
  excluded from OOS XIRR, stability, constraint selection, and Pareto objectives.
- Pareto membership is exposed for every candidate.
- SQLite initializes idempotent version-1 tables for jobs, results, reports, and
  migrations. JSON is serialized with sorted keys and compact deterministic
  separators.
- Job states are `queued`, `running`, `cancelling`, `completed`, `failed`, and
  `cancelled`. Cancellation is observed only at deterministic batch boundaries.
- Result and placeholder report publication occurs in one `BEGIN IMMEDIATE`
  transaction after all batches. The transaction rechecks cancellation; a
  cancelled job cannot publish a partial formal result.
- The FastAPI app exposes schema version `1.0`, has an app factory, and includes
  all required versioned endpoints for instruments, data, evidence, strategies,
  optimization jobs, market overview, results, and reports.
- Evidence, strategy, and optimizer calculations remain in analysis/optimization
  modules; routes perform validation, domain conversion, invocation, and response
  mapping only.
- API tests use fixed in-memory/inline fixtures and an unconfigured update
  coordinator. They never call Yahoo.
- Dependency ranges are CI-installable and intentionally pin FastAPI to the
  compatible `>=0.115,<0.116` line. The install was non-editable to avoid the
  known Windows Chinese-path `.pth` encoding failure.

## Concerns

None.

---

## Formal trust-boundary correction

This section supersedes the initial Task 4 API/optimizer trust-boundary design
above. The correction was required after review found that callers could submit
their own candidate scores, independent-event counts, and market bars.

### Outcome

- Status: DONE
- Correction implementation commit: `4c1a291`
- Branch: `feature/ai-batch`
- Merge/PR: intentionally not performed
- Python: `C:\Users\10931\.drawdown-ledger\py311\Scripts\python.exe`
- Live source: `PYTHONPATH=apps/api/src`

### Cycle A: trusted symbols and simulator-backed optimizer

RED command:

```powershell
python -m pytest apps/api/tests/optimization/test_grid.py apps/api/tests/optimization/test_evaluator.py -q
```

Observed RED:

```text
ImportError: cannot import name 'generate_ratio_grid'
ModuleNotFoundError: No module named 'drawdown_lab.optimization.evaluator'
```

After the domain evaluator was introduced, the focused simulator-backed cycle
became:

```text
10 passed in 0.80s
```

The API trust-boundary RED command was:

```powershell
python -m pytest apps/api/tests/api/test_trusted_optimizer.py -q
```

Observed RED included:

- a valid trusted-symbol request returned 422 because the old schema still
  required caller-provided candidate metrics;
- fabricated-score errors were not schema-versioned;
- a family/target mismatch was not resolved against the approved registry;
- missing trusted target history returned 422 instead of typed 404.

The full Section A focused GREEN command was:

```powershell
python -m pytest apps/api/tests/api/test_trusted_optimizer.py `
  apps/api/tests/optimization/test_evaluator.py `
  apps/api/tests/optimization/test_grid.py -q
```

Result:

```text
14 passed in 1.58s
```

Verified behaviors:

- requests contain approved family/target and strategy/search settings only;
- `candidates`, fold metrics, risk metrics, and
  `independent_episode_count` are rejected as extra inputs;
- prototype symbol and target leverage come from `INSTRUMENT_FAMILIES`;
- prototype and target frames are loaded from `DataCatalog`;
- ratio vectors and chronological folds are generated internally;
- every candidate/fold is evaluated by the existing `simulate_strategy`;
- independent events are derived from prototype drawdown history;
- a rising target path recommends 10,000 bps while a falling path recommends
  0 bps using the same request/prototype;
- progress checkpoints were exactly `(1, 4)`, `(2, 4)`, `(3, 4)`, `(4, 4)`
  for four real candidate-fold simulations;
- cancellation stops at a real evaluation boundary;
- enabled synthetic stress evaluates every candidate separately while leaving
  actual-history recommendations unchanged.

### Cycle B: symbol-driven evidence and strategy routes

RED command:

```powershell
python -m pytest apps/api/tests/api/test_analysis_routes.py -q
```

Observed RED:

- trusted symbol-only evidence/backtest requests returned 422 because the old
  schema required caller-supplied frames;
- missing cache returned schema validation 422 instead of typed 404;
- validation errors containing domain `ValueError` context were not JSON
  serializable and escaped as server errors.

GREEN result:

```text
5 passed in 1.53s
```

Verified behaviors:

- evidence/backtest requests contain family, target, and formal parameters only;
- fixed tests seed `DataCatalog`; none call Yahoo;
- caller-supplied `prototype`/`traded` bars are rejected;
- reversed dates, invalid thresholds/fractions, negative costs, rates above one,
  duplicate/non-positive horizons, and invalid grid ranges return
  schema-versioned 422;
- family mismatch returns typed 422 and missing trusted cache returns typed 404;
- route/domain `ValueError` is converted to a typed client response rather than
  leaking as 500.

### Cycle C: persistence, restart, and state machine

RED command:

```powershell
python -m pytest apps/api/tests/api/test_jobs.py -q
```

Observed RED:

```text
ImportError: cannot import name 'historical_request_from_payload'
```

GREEN result:

```text
8 passed in 1.86s
```

Verified behaviors:

- persisted optimization JSON round-trips to an equal validated domain request;
- queued and running jobs are safely requeued and completed after app restart;
- a restarting cancelling job becomes cancelled without a result;
- cancellation wins an atomic cancel/fail race;
- a version-1 `completed` row migrates to `succeeded`;
- job state is consistently `queued`, `running`, `cancelling`, `succeeded`,
  `failed`, or `cancelled`;
- cancelling a real simulator-backed search publishes no result row;
- insufficient events succeed with an explicit exploration-only result.

### Cycle D: explicit formal output models

RED command:

```powershell
python -m pytest apps/api/tests/api/test_typed_results.py -q
```

Observed RED:

- OpenAPI exposed `ResultResponse.payload` and report content as opaque objects;
- persisted results had no explicit schema, exploration flag, provenance, or
  synthetic-stress summary.

GREEN result:

```text
2 passed in 1.41s
```

Verified behaviors:

- OpenAPI points result payloads to `OptimizationResultPayload`;
- OpenAPI points report content to `ReportContentResponse`;
- candidate schema explicitly exposes ratios, fold OOS XIRRs, actual OOS XIRR,
  worst-tail return, depletion rate, trap duration, stability values, Pareto
  membership, labels, and separate synthetic stress pass/fail;
- persisted formal output includes schema `1.0`, exploration flag, independent
  event count, approved-symbol provenance, actual source label, date range,
  fold count, basis-point unit, recommendations, and synthetic summary;
- persisted not-yet-exported reports contain the same typed optimization payload.

### Final correction verification

Fresh pre-commit command:

```powershell
python -m pytest apps/api/tests -q
python -m ruff check apps/api
python -m mypy apps/api/src
git diff --check
```

Result:

```text
123 passed in 5.59s
All checks passed!
Success: no issues found in 35 source files
```

The output was pristine and contained no warnings.

### Correction files

Runtime additions/changes:

- `apps/api/src/drawdown_lab/optimization/evaluator.py`
- `apps/api/src/drawdown_lab/optimization/grid.py`
- `apps/api/src/drawdown_lab/optimization/scoring.py`
- `apps/api/src/drawdown_lab/domain/instruments.py`
- `apps/api/src/drawdown_lab/api/schemas.py`
- `apps/api/src/drawdown_lab/api/routes.py`
- `apps/api/src/drawdown_lab/api/app.py`
- `apps/api/src/drawdown_lab/storage/database.py`
- `apps/api/src/drawdown_lab/storage/jobs.py`

Test additions/changes:

- `apps/api/tests/optimization/test_evaluator.py`
- `apps/api/tests/optimization/test_grid.py`
- `apps/api/tests/api/test_trusted_optimizer.py`
- `apps/api/tests/api/test_analysis_routes.py`
- `apps/api/tests/api/test_jobs.py`
- `apps/api/tests/api/test_typed_results.py`

### Correction self-review

- No formal route accepts market bars, candidate metrics, independent counts, or
  synthetic outcomes from the caller.
- All formal frame loading uses approved registry resolution plus `DataCatalog`.
- Optimization result publication remains one atomic transaction after all
  evaluator batches; cancellation is rechecked inside that transaction.
- Job failure transition uses `BEGIN IMMEDIATE` and honors an existing
  cancellation request, removing the cancel/fail terminal race.
- Startup reconciliation occurs before the app accepts requests.
- Reports/results are persisted only for `succeeded` jobs.
- Synthetic simulations affect only the separately labelled stress fields.
- API tests use deterministic local cache fixtures and no external provider.

### Correction concerns

None.
