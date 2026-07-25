# ETF Drawdown Research Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first ETF drawdown evidence, cash-pool backtest, and parameter-search platform with a polished research UI, deterministic AI controls, recoverable operations, GitHub CI, Funnel access, and a static Pages fallback.

**Architecture:** A React/TypeScript Vite client consumes a versioned FastAPI/OpenAPI service. The Python service isolates immutable domain models, Parquet-backed market data, pure analysis/simulation functions, SQLite job/result persistence, and report export. Formal results are computed only in Python; the static Pages build uses committed anonymized fixtures and explicitly published reports.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, pandas, NumPy, SciPy, PyArrow, SQLAlchemy, yfinance provider adapter, pytest, Hypothesis, Ruff, mypy; Node.js 22+, React 19, TypeScript, Vite, TanStack Query, Lightweight Charts 5, Vitest, Testing Library, Playwright; PowerShell 7, Pester, GitHub Actions, Tailscale Funnel.

## Global Constraints

- Signal drawdown uses split-adjusted, dividend-unadjusted close; performance uses total return or explicit share/dividend cash flows.
- A close on trading day `t` can execute no earlier than the next valid session open.
- Each threshold triggers once per ATH-to-new-ATH cycle; a new ATH resets flags but never sells holdings.
- Monthly contributions accumulate in cash, can grow or be overridden by dated events, and are spent only on triggers.
- Each tier spends its configured percentage of cash available immediately before that tier executes.
- Dividend routing is either cash reserve or next-session-open reinvestment and must never be double counted.
- Actual leveraged ETF history and synthetic pre-inception stress history remain separate in UI, APIs, and metrics.
- Policy cutoff is the prior calendar month-end; the last observed session is the latest valid session on or before it.
- Market cache, SQLite data, private strategies, private results, and Funnel state are never committed.
- Formal CI uses fixed local fixtures and never depends on Yahoo availability.
- Primary browser QA sizes are 1440×900, 412×915, and 405×720.
- Every feature is implemented on its named branch, reviewed by PR, and merged only after tests, type checks, lint, and builds pass.

---

### Task 1: Repository Foundation and Market Data Pipeline

**Branch:** `feature/data-pipeline`

**Files:**
- Create: `.gitignore`
- Create: `.gitattributes`
- Create: `.editorconfig`
- Create: `README.md`
- Create: `pyproject.toml`
- Create: `package.json`
- Create: `apps/api/src/drawdown_lab/__init__.py`
- Create: `apps/api/src/drawdown_lab/domain/instruments.py`
- Create: `apps/api/src/drawdown_lab/data/cutoff.py`
- Create: `apps/api/src/drawdown_lab/data/models.py`
- Create: `apps/api/src/drawdown_lab/data/provider.py`
- Create: `apps/api/src/drawdown_lab/data/yahoo.py`
- Create: `apps/api/src/drawdown_lab/data/catalog.py`
- Create: `apps/api/src/drawdown_lab/data/update.py`
- Create: `apps/api/tests/conftest.py`
- Create: `apps/api/tests/data/test_cutoff.py`
- Create: `apps/api/tests/data/test_catalog.py`
- Create: `apps/api/tests/data/test_update.py`
- Create: `apps/api/tests/fixtures/qqq_daily.csv`

**Interfaces:**
- Produces: `Instrument`, `InstrumentFamily`, `INSTRUMENT_FAMILIES`
- Produces: `policy_cutoff(as_of: date) -> date`
- Produces: `last_session_on_or_before(index: DatetimeIndex, cutoff: date) -> date`
- Produces: `MarketDataProvider.fetch(symbol: str, start: date, end: date) -> MarketFrame` with raw OHLC, split-adjusted price OHLC, adjusted close, raw dividend, and split ratio
- Produces: `DataCatalog`, `UpdateCoordinator.ensure_current(as_of: date) -> UpdateSummary`

- [ ] **Step 1: Write failing registry and cutoff tests**

```python
def test_august_uses_july_31_cutoff() -> None:
    assert policy_cutoff(date(2026, 8, 1)) == date(2026, 7, 31)

def test_registry_contains_only_approved_positive_leverage_families() -> None:
    symbols = {item.symbol for family in INSTRUMENT_FAMILIES for item in family.instruments}
    assert {"0050.TW", "00631L.TW", "006204.TW", "00685L.TW"} <= symbols
    assert {"QQQ", "QLD", "TQQQ", "SPY", "SSO", "UPRO", "DIA", "DDM", "UDOW", "IWM", "UWM", "URTY"} <= symbols
    assert {"00662.TW", "00670L.TW", "00646.TW", "00647L.TW"}.isdisjoint(symbols)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest apps/api/tests/data/test_cutoff.py apps/api/tests/data/test_catalog.py -q`
Expected: collection failure because `drawdown_lab` modules do not exist.

- [ ] **Step 3: Implement immutable instrument models and cutoff policy**

```python
@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    family_id: str
    leverage: int
    prototype_symbol: str
    currency: str
    timezone: str
    inception: date | None = None

def policy_cutoff(as_of: date) -> date:
    return as_of.replace(day=1) - timedelta(days=1)
```

- [ ] **Step 4: Write failing incremental-cache tests**

```python
def test_current_cache_performs_no_provider_request(tmp_path: Path) -> None:
    provider = RecordingProvider(frame=market_frame_through("2026-07-31"))
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 31))
    result = UpdateCoordinator(provider, catalog).ensure_current(date(2026, 8, 15))
    assert result.request_count == 0
    assert provider.calls == []

def test_failed_refresh_keeps_last_valid_parquet(tmp_path: Path) -> None:
    original = seed_valid_parquet(tmp_path)
    with pytest.raises(DataUpdateError):
        coordinator_with_failing_provider(tmp_path).ensure_current(date(2026, 8, 15))
    assert original.read_bytes() == market_path(tmp_path).read_bytes()
```

- [ ] **Step 5: Run RED, then implement provider protocol, Parquet writes, SQLite catalog, five-session overlap, validation, and atomic replacement**

Run: `python -m pytest apps/api/tests/data -q`
Expected before implementation: failures for missing `DataCatalog` and `UpdateCoordinator`.
Expected after implementation: all data tests pass.

- [ ] **Step 6: Add lock files and baseline quality commands**

Run:

```powershell
python -m pip install -e ".[dev]"
python -m ruff check apps/api
python -m mypy apps/api/src
python -m pytest apps/api/tests/data -q
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit, push, open PR, wait for CI, and merge**

```powershell
git add .
git commit -m "feat(data): add instrument registry and monthly cache"
git push -u origin feature/data-pipeline
gh pr create --title "feat: add market data pipeline" --body-file .github/pr-bodies/data-pipeline.md
```

---

### Task 2: Drawdown Evidence and Leveraged-History Separation

**Branch:** `feature/evidence-engine`

**Files:**
- Create: `apps/api/src/drawdown_lab/analysis/drawdown.py`
- Create: `apps/api/src/drawdown_lab/analysis/episodes.py`
- Create: `apps/api/src/drawdown_lab/analysis/forward_returns.py`
- Create: `apps/api/src/drawdown_lab/analysis/risk.py`
- Create: `apps/api/src/drawdown_lab/analysis/evidence.py`
- Create: `apps/api/src/drawdown_lab/analysis/leverage.py`
- Create: `apps/api/tests/analysis/test_drawdown.py`
- Create: `apps/api/tests/analysis/test_episodes.py`
- Create: `apps/api/tests/analysis/test_evidence.py`
- Create: `apps/api/tests/analysis/test_leverage.py`

**Interfaces:**
- Consumes: `MarketFrame`, `Instrument`
- Produces: `drawdown_series(close: Series) -> Series`
- Produces: `classify_episodes(frame: MarketFrame, thresholds: tuple[float, ...]) -> tuple[DrawdownEpisode, ...]`
- Produces: `analyze_evidence(request: EvidenceRequest, prototype: MarketFrame, traded: MarketFrame) -> EvidenceReport`
- Produces: `synthetic_daily_reset_nav(...) -> SyntheticSeries`

- [ ] **Step 1: Write failing drawdown and independent-event tests**

```python
def test_overlapping_days_are_not_independent_episodes() -> None:
    frame = frame_from_closes([100, 80, 75, 85, 101, 79, 102])
    report = analyze_threshold(frame, threshold=-0.20)
    assert report.n_day == 3
    assert report.n_episode == 2

def test_gap_can_trigger_multiple_tiers_once_in_one_cycle() -> None:
    frame = frame_from_closes([100, 65, 60, 101])
    episodes = classify_episodes(frame, (-0.20, -0.30, -0.40))
    assert [(event.threshold, event.cycle_id) for event in episodes] == [
        (-0.20, 1), (-0.30, 1), (-0.40, 1)
    ]
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest apps/api/tests/analysis/test_drawdown.py apps/api/tests/analysis/test_episodes.py -q`
Expected: missing analysis modules.

- [ ] **Step 3: Implement pure drawdown and episode state machine; run GREEN**

Expected: both test files pass without database or API fixtures.

- [ ] **Step 4: Write failing next-open, horizon, MAE/MFE, ES5%, repair-time, and V-recovery tests**

```python
def test_signal_at_close_executes_next_open() -> None:
    report = analyze_evidence(request_for_threshold(-0.20), fixture_market_frame())
    assert report.episodes[0].signal_date == date(2020, 3, 12)
    assert report.episodes[0].entry_date == date(2020, 3, 13)
    assert report.episodes[0].entry_price == Decimal("8.25")

def test_v_recovery_means_prior_high_within_126_sessions() -> None:
    event = episode_with_recovery_sessions(126)
    assert event.v_recovered is True
    assert replace(event, recovery_sessions=127).v_recovered is False
```

- [ ] **Step 5: Implement evidence metrics and block-bootstrap intervals**

Use deterministic `numpy.random.Generator` injection. Never use daily rows as independent Bernoulli trials.

- [ ] **Step 6: Write failing actual/synthetic boundary test, then implement daily-reset synthetic NAV**

```python
def test_synthetic_observations_never_count_as_actual_etf_evidence() -> None:
    report = analyze_leveraged_history(actual=actual_after("2010-02-11"), synthetic=synthetic_before("2010-02-11"))
    assert all(row.source_kind == "actual" for row in report.actual_statistics.rows)
    assert all(row.source_kind == "synthetic" for row in report.stress_statistics.rows)
```

- [ ] **Step 7: Run all Python quality gates, commit, PR, and merge**

Run: `python -m pytest apps/api/tests/analysis -q && python -m ruff check apps/api && python -m mypy apps/api/src`
Expected: exit 0.

---

### Task 3: Cash-Pool Strategy Simulator and Baselines

**Branch:** `feature/cash-strategy`

**Files:**
- Create: `apps/api/src/drawdown_lab/domain/money.py`
- Create: `apps/api/src/drawdown_lab/analysis/cashflows.py`
- Create: `apps/api/src/drawdown_lab/analysis/strategy.py`
- Create: `apps/api/src/drawdown_lab/analysis/baselines.py`
- Create: `apps/api/src/drawdown_lab/analysis/performance.py`
- Create: `apps/api/tests/strategy/test_contributions.py`
- Create: `apps/api/tests/strategy/test_triggers.py`
- Create: `apps/api/tests/strategy/test_dividends.py`
- Create: `apps/api/tests/strategy/test_performance.py`
- Create: `apps/api/tests/strategy/test_properties.py`

**Interfaces:**
- Produces: `StrategyConfig`, `ContributionSchedule`, `ThresholdTier`, `DividendPolicy`
- Produces: `simulate_strategy(config, prototype, traded) -> StrategyResult`
- Produces: `build_baselines(config, prototype, traded) -> tuple[StrategyResult, ...]`
- Produces: `xirr(cashflows: Sequence[CashFlow]) -> float`

- [ ] **Step 1: Write failing contribution and ACT/365 interest tests**

```python
def test_salary_growth_and_bonus_are_applied_on_effective_month() -> None:
    schedule = ContributionSchedule(monthly=10_000, annual_growth=0.10, events=(bonus("2027-03", 50_000),))
    assert schedule.amount_for(date(2027, 1, 1)) == Decimal("11000")
    assert schedule.amount_for(date(2027, 3, 1)) == Decimal("61000")

def test_cash_interest_uses_actual_days_over_365() -> None:
    assert accrue_cash(Decimal("100000"), Decimal("0.02"), 31) == Decimal("100169.86")
```

- [ ] **Step 2: Run RED, implement immutable money/cashflow types, then run GREEN**

- [ ] **Step 3: Write failing trigger state-machine tests**

```python
def test_starting_mid_drawdown_triggers_all_satisfied_tiers_next_open() -> None:
    result = simulate_strategy(
        config(start="2020-03-12", cash=1_000_000, tiers=[(-0.20, 0.25), (-0.30, 0.40)]),
        prototype=prototype_fixture(),
        traded=traded_fixture(),
    )
    assert [(trade.threshold, trade.cash_spent) for trade in result.trades[:2]] == [
        (-0.20, Decimal("250000")),
        (-0.30, Decimal("300000")),
    ]

def test_new_high_resets_flags_without_selling() -> None:
    result = simulate_strategy(config_for_two_cycles(), prototype_two_cycles(), traded_two_cycles())
    assert len(result.trades_for(-0.20)) == 2
    assert result.sell_trades == ()
    assert result.ending_shares > result.shares_after_first_cycle
```

- [ ] **Step 4: Implement close-signal/next-open execution queue and cycle flags**

Process multiple same-day tiers shallow-to-deep. Quantize money only at transaction boundaries, not intermediate returns.

- [ ] **Step 5: Write failing dividend and split tests**

```python
@pytest.mark.parametrize("policy, expected_cash, expected_shares", [
    ("cash", Decimal("1020"), Decimal("10")),
    ("reinvest", Decimal("1000"), Decimal("12")),
])
def test_dividend_routes_once(policy: str, expected_cash: Decimal, expected_shares: Decimal) -> None:
    result = simulate_dividend_fixture(policy)
    assert result.cash == expected_cash
    assert result.shares == expected_shares
    assert result.dividend_income == Decimal("20")
```

- [ ] **Step 6: Implement dividends, splits, fees, slippage, XIRR, drawdown, ES5%, underwater duration, and baselines**

- [ ] **Step 7: Add Hypothesis invariants**

Assert no unexplained negative cash/shares and zero-cost accounting identity across generated paths.

- [ ] **Step 8: Run gates, commit, PR, and merge**

Run: `python -m pytest apps/api/tests/strategy -q`
Expected: all tests pass.

---

### Task 4: Optimizer, Job Persistence, and Versioned FastAPI

**Branch:** `feature/ai-batch`

**Files:**
- Create: `apps/api/src/drawdown_lab/optimization/grid.py`
- Create: `apps/api/src/drawdown_lab/optimization/walk_forward.py`
- Create: `apps/api/src/drawdown_lab/optimization/scoring.py`
- Create: `apps/api/src/drawdown_lab/optimization/pareto.py`
- Create: `apps/api/src/drawdown_lab/storage/database.py`
- Create: `apps/api/src/drawdown_lab/storage/jobs.py`
- Create: `apps/api/src/drawdown_lab/api/schemas.py`
- Create: `apps/api/src/drawdown_lab/api/routes.py`
- Create: `apps/api/src/drawdown_lab/api/app.py`
- Create: `apps/api/tests/optimization/test_grid.py`
- Create: `apps/api/tests/optimization/test_walk_forward.py`
- Create: `apps/api/tests/optimization/test_scoring.py`
- Create: `apps/api/tests/api/test_contract.py`
- Create: `apps/api/tests/api/test_jobs.py`

**Interfaces:**
- Produces: `generate_monotone_grid(levels=4, step=10) -> Iterator[tuple[int, ...]]`
- Produces: `optimize(request: OptimizationRequest, frames: AnalysisFrames) -> OptimizationResult`
- Produces: `create_app(settings: Settings) -> FastAPI`
- Produces: persisted `JobRecord` with queued/running/succeeded/failed/cancelled states

- [ ] **Step 1: Write failing 1,001/14,641 grid tests**

```python
def test_default_monotone_four_tier_grid_has_1001_combinations() -> None:
    assert len(list(generate_grid(levels=4, step=10, monotone=True))) == 1001

def test_unrestricted_four_tier_grid_has_14641_combinations() -> None:
    assert len(list(generate_grid(levels=4, step=10, monotone=False))) == 14641
```

- [ ] **Step 2: Implement deterministic grid and chronological walk-forward splits**

- [ ] **Step 3: Write failing stable-plateau and insufficient-sample tests**

```python
def test_isolated_peak_loses_to_stable_neighbor_plateau() -> None:
    result = choose_balanced_candidate(optimizer_fixture_with_spike())
    assert result.ratios == (20, 30, 40, 50)

def test_too_few_independent_episodes_has_no_best_badge() -> None:
    assert optimize(fixture_with_three_episodes()).recommendations == ()
```

- [ ] **Step 4: Implement profile constraints, Pareto frontier, neighbor stability, and actual/synthetic score separation**

- [ ] **Step 5: Write failing API contract/job tests**

```python
def test_openapi_exposes_versioned_ai_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/v1/optimizations" in schema["paths"]
    assert "/api/v1/jobs/{job_id}" in schema["paths"]

def test_cancelled_job_never_publishes_partial_result(client: TestClient) -> None:
    job_id = create_slow_job(client)
    client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert wait_for_job(client, job_id)["status"] == "cancelled"
    assert result_rows_for(job_id) == []
```

- [ ] **Step 6: Implement API, SQLite migrations, background executor, cancellation checkpoints, and OpenAPI export**

- [ ] **Step 7: Run gates, commit, PR, and merge**

Run: `python -m pytest apps/api/tests -q`
Expected: all Python tests pass.

---

### Task 5: React Foundation and C-Style Research Shell

**Branch:** `feature/research-ui`

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/eslint.config.js`
- Create: `apps/web/index.html`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/app/App.tsx`
- Create: `apps/web/src/app/routes.tsx`
- Create: `apps/web/src/styles/tokens.css`
- Create: `apps/web/src/styles/global.css`
- Create: `apps/web/src/lib/api.ts`
- Create: `apps/web/src/lib/contracts.ts`
- Create: `apps/web/src/components/AppShell.tsx`
- Create: `apps/web/src/components/InstrumentRail.tsx`
- Create: `apps/web/src/components/DataStatus.tsx`
- Create: `apps/web/src/pages/MarketOverviewPage.tsx`
- Create: `apps/web/src/pages/DataHealthPage.tsx`
- Create: `apps/web/tests/app-shell.test.tsx`
- Create: `apps/web/tests/market-overview.test.tsx`

**Interfaces:**
- Consumes: generated `/api/v1` OpenAPI types
- Produces: route shell for `/`, `/evidence`, `/strategy`, `/ai`, `/reports`, `/data-health`
- Produces: design tokens matching approved palette and typography

- [ ] **Step 1: Generate Vite configuration, then write failing semantic-shell test**

```tsx
it("exposes all six research destinations", async () => {
  render(<App />, { wrapper: testRouter("/") });
  expect(screen.getByRole("navigation", { name: "主要功能" })).toBeVisible();
  for (const name of ["市場總覽", "歷史證據", "策略實驗室", "AI 批次", "報告與比較", "資料健康度"]) {
    expect(screen.getByRole("link", { name })).toBeVisible();
  }
});
```

- [ ] **Step 2: Run RED**

Run: `npm --prefix apps/web test -- --run tests/app-shell.test.tsx`
Expected: failure because `App` and shell do not exist.

- [ ] **Step 3: Implement accessible shell, family rail, status banner, route-level error/empty/loading states**

Use `#EDF1F5` shell, `#17263C` research canvas, cobalt signal, coral risk, teal cash. Keep the depth-band chart as the single visual signature.

- [ ] **Step 4: Write failing responsive and data-state tests, then implement overview/data-health pages**

- [ ] **Step 5: Run type, lint, unit, and build gates**

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web run lint
npm --prefix apps/web run test -- --run
npm --prefix apps/web run build
```

- [ ] **Step 6: Commit UI foundation; keep PR open until Tasks 6 and 7 complete on the same feature branch**

---

### Task 6: Evidence Workbench and Synchronized Charts

**Branch:** continue `feature/research-ui`

**Files:**
- Create: `apps/web/src/features/chart/ResearchChart.tsx`
- Create: `apps/web/src/features/chart/chartModel.ts`
- Create: `apps/web/src/features/chart/DepthBands.ts`
- Create: `apps/web/src/features/chart/TradeMarkers.ts`
- Create: `apps/web/src/features/evidence/EvidenceSentence.tsx`
- Create: `apps/web/src/features/evidence/EpisodeTable.tsx`
- Create: `apps/web/src/pages/EvidencePage.tsx`
- Create: `apps/web/tests/chart-model.test.ts`
- Create: `apps/web/tests/evidence-page.test.tsx`

**Interfaces:**
- Produces: synchronized price, underwater, and portfolio panes
- Produces: line/log/normalized modes, date range, two-point measurement, and event selection

- [ ] **Step 1: Write failing chart-model tests for depth bands, normalization, two-point measurement, and marker labels**

- [ ] **Step 2: Implement pure chart model; verify RED becomes GREEN before mounting Lightweight Charts**

- [ ] **Step 3: Write failing evidence-page test for `N_day`/`N_episode`, actual/synthetic labels, and next-open wording**

- [ ] **Step 4: Implement chart adapter and evidence workbench**

The chart adapter owns all Lightweight Charts imperative objects and disposes them on unmount. React components receive serializable models only.

- [ ] **Step 5: Add keyboard focus, 44px controls, reduced-motion CSS, and mobile bottom drawer**

- [ ] **Step 6: Run frontend gates**

---

### Task 7: Strategy Lab, AI Mode, and Report Comparison UI

**Branch:** continue `feature/research-ui`, followed by integration commit on `feature/ai-batch` if API contract changes

**Files:**
- Create: `apps/web/src/features/strategy/StrategyForm.tsx`
- Create: `apps/web/src/features/strategy/CashTimeline.tsx`
- Create: `apps/web/src/features/strategy/ThresholdLadder.tsx`
- Create: `apps/web/src/features/strategy/BenchmarkTable.tsx`
- Create: `apps/web/src/pages/StrategyPage.tsx`
- Create: `apps/web/src/features/ai/AiControlPanel.tsx`
- Create: `apps/web/src/features/ai/ParetoPlot.tsx`
- Create: `apps/web/src/features/ai/RecommendationCards.tsx`
- Create: `apps/web/src/pages/AiPage.tsx`
- Create: `apps/web/src/pages/ReportsPage.tsx`
- Create: `apps/web/tests/strategy-page.test.tsx`
- Create: `apps/web/tests/ai-page.test.tsx`
- Create: `apps/web/tests/reports-page.test.tsx`

**Interfaces:**
- Produces: schema-valid strategy and optimization requests
- Produces: stable `id`, `name`, `aria-label`, and `data-ai-field` attributes
- Produces: JSON import/export and copied browser-control instructions

- [ ] **Step 1: Write failing strategy form test for salary growth, dated events, cash interest, dividend policy, and tier semantics**

- [ ] **Step 2: Implement controlled form and result panels**

- [ ] **Step 3: Write failing AI accessibility/schema test**

```tsx
it("exposes deterministic controls for browser-operated AI", () => {
  render(<AiPage />);
  expect(screen.getByLabelText("標的家族")).toHaveAttribute("data-ai-field", "family");
  expect(screen.getByLabelText("完整搜尋")).toHaveAttribute("data-ai-action", "run-grid");
  expect(screen.getByRole("button", { name: "匯出設定 JSON" })).toBeEnabled();
});
```

- [ ] **Step 4: Implement AI job progress, cancellation, profile cards, Pareto table/plot, JSON flow, and instructions**

- [ ] **Step 5: Implement up-to-four strategy report comparison**

- [ ] **Step 6: Run all frontend gates, commit, push, PR, and merge**

---

### Task 8: Traceable Report Export and Static Pages Fallback

**Branch:** `feature/ops-deployment`

**Files:**
- Create: `apps/api/src/drawdown_lab/reports/models.py`
- Create: `apps/api/src/drawdown_lab/reports/render.py`
- Create: `apps/api/src/drawdown_lab/reports/privacy.py`
- Create: `apps/api/templates/report.html.j2`
- Create: `apps/api/tests/reports/test_render.py`
- Create: `apps/api/tests/reports/test_privacy.py`
- Create: `apps/web/public/demo/manifest.json`
- Create: `apps/web/public/demo/qqq-evidence.json`
- Create: `scripts/Publish-Report.ps1`
- Create: `scripts/Test-PublishedPrivacy.ps1`

**Interfaces:**
- Produces: `export_report(result_id, formats=("html", "json", "csv")) -> ExportManifest`
- Produces: `privacy_scan(path: Path) -> PrivacyScanResult`

- [ ] **Step 1: Write failing report provenance and privacy tests**

```python
def test_report_contains_data_and_engine_lineage(tmp_path: Path) -> None:
    manifest = export_fixture_report(tmp_path)
    assert manifest.engine_version
    assert manifest.git_commit
    assert manifest.data_hashes["QQQ"]
    assert manifest.policy_cutoff == date(2026, 7, 31)

def test_private_absolute_path_blocks_publication(tmp_path: Path) -> None:
    report = write_report(tmp_path, {"note": r"C:\Users\10931\private"})
    assert privacy_scan(report).allowed is False
```

- [ ] **Step 2: Implement deterministic HTML/JSON/CSV rendering and privacy scanner**

- [ ] **Step 3: Write PowerShell test first, then implement explicit publish command**

The script copies only a passed export ID after the API privacy scan succeeds.

- [ ] **Step 4: Configure Vite base path and static demo fallback**

Static mode never calls localhost and clearly labels its fixed data date.

---

### Task 9: One-Click Windows Operations and Funnel Safety

**Branch:** continue `feature/ops-deployment`

**Files:**
- Create: `scripts/Start.ps1`
- Create: `scripts/Update-Data.ps1`
- Create: `scripts/Open-Funnel.ps1`
- Create: `scripts/Backup.ps1`
- Create: `scripts/Restore.ps1`
- Create: `scripts/Stop.ps1`
- Create: `scripts/Analyze.ps1`
- Create: `scripts/lib/ProcessState.psm1`
- Create: `scripts/lib/FunnelState.psm1`
- Create: `tests/powershell/Operations.Tests.ps1`
- Create: `tests/powershell/Funnel.Tests.ps1`

**Interfaces:**
- Produces: idempotent local lifecycle commands and recoverable Funnel switching

- [ ] **Step 1: Write failing Pester test that refuses to overwrite an occupied Funnel**

```powershell
It 'does not replace another Funnel without ReplaceExisting' {
  Mock Get-FunnelStatus { @{ Target = '127.0.0.1:4174'; PublicUrl = 'https://existing.example' } }
  { Open-DrawdownFunnel -Target '127.0.0.1:8787' } | Should -Throw '*already routes*'
  Should -Invoke Set-FunnelTarget -Times 0
}
```

- [ ] **Step 2: Implement process-state module and Start/Stop scripts**

Use explicit PID/state files under ignored `.runtime`; validate every PID belongs to this project before stopping it.

- [ ] **Step 3: Implement Funnel snapshot/switch/restore with `-ReplaceExisting`**

- [ ] **Step 4: Write and implement atomic SQLite/Parquet backup and restore verification**

- [ ] **Step 5: Implement Update-Data and Analyze JSON wrappers without printing secrets/private strategy content**

- [ ] **Step 6: Run Pester and manual dry-run checks**

---

### Task 10: CI, GitHub Pages, Documentation, End-to-End QA, and Release

**Branch:** continue `feature/ops-deployment`

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/pages.yml`
- Create: `.github/workflows/release.yml`
- Create: `.github/ISSUE_TEMPLATE/feature.yml`
- Create: `.github/pull_request_template.md`
- Create: `playwright.config.ts`
- Create: `e2e/research-flow.spec.ts`
- Create: `e2e/ai-flow.spec.ts`
- Create: `e2e/mobile.spec.ts`
- Create: `docs/operations/deployment.md`
- Create: `docs/operations/backup-and-restore.md`
- Create: `docs/operations/maintenance.md`
- Create: `docs/operations/rollback.md`
- Create: `LICENSE`

**Interfaces:**
- Produces: required CI checks, Pages artifact, version tags, and user maintenance runbooks

- [ ] **Step 1: Add CI jobs for Python, Web, E2E, PowerShell, build, and privacy scan**

Use Ubuntu for Python/Web and Windows for Pester. Cache dependencies, not user market data.

- [ ] **Step 2: Add Pages workflow that uploads only `apps/web/dist` plus passed `reports/published`**

- [ ] **Step 3: Write failing Playwright flows before completing selectors**

```ts
test("researcher can inspect evidence and run a strategy", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "歷史證據" }).click();
  await page.getByLabel("標的家族").selectOption("nasdaq-100");
  await expect(page.getByTestId("evidence-sentence")).toContainText("獨立回撤");
  await page.getByRole("link", { name: "策略實驗室" }).click();
  await page.getByRole("button", { name: "執行回測" }).click();
  await expect(page.getByTestId("strategy-result")).toBeVisible();
});
```

- [ ] **Step 4: Run desktop/mobile visual and accessibility QA**

Capture 1440×900, 412×915, and 405×720 screenshots; inspect layout, chart geometry, horizontal overflow, visible focus, and reduced-motion behavior.

- [ ] **Step 5: Complete deployment, backup, maintenance, rollback, and AI-operation documentation**

- [ ] **Step 6: Push PR and wait for all checks**

- [ ] **Step 7: Enable main branch protection**

Require PR, one approval when account policy permits, required CI contexts, conversation resolution, no force pushes, and no deletion.

- [ ] **Step 8: Merge, deploy Pages, create release tag, and verify public artifacts**

```powershell
git tag -a v0.1.0 -m "Drawdown Ledger v0.1.0"
git push origin v0.1.0
gh release create v0.1.0 --generate-notes
```

- [ ] **Step 9: Final verification**

Run:

```powershell
python -m pytest apps/api/tests -q
python -m ruff check apps/api
python -m mypy apps/api/src
npm --prefix apps/web run typecheck
npm --prefix apps/web run lint
npm --prefix apps/web run test -- --run
npm --prefix apps/web run build
npx playwright test
Invoke-Pester tests/powershell
git status --short
gh pr checks
```

Expected: all checks pass, worktree is clean, Pages returns HTTP 200, the local API health endpoint reports the correct prior-month cutoff, and the existing Funnel remains unchanged unless explicitly switched.
