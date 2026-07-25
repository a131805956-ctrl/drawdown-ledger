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
