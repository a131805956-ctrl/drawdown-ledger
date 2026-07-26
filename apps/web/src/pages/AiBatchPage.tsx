import { useMutation, useQuery } from "@tanstack/react-query";
import {
    useMemo,
    useState,
    type ChangeEvent,
    type FormEvent,
} from "react";

import { useResearchData } from "../lib/api";
import type {
    OptimizationCreateRequest,
    ResultResponse,
} from "../lib/contracts";

const familyNames: Record<string, string> = {
    "taiwan-50": "台灣 50",
    "taiwan-weighted": "台灣加權",
    "nasdaq-100": "NASDAQ-100",
    "sp-500": "S&P 500",
    "dow-jones-industrial-average": "道瓊工業",
    "russell-2000": "Russell 2000",
};

const profileNames = {
    conservative: "保守",
    balanced: "平衡",
    aggressive: "積極",
} as const;

function priorCalendarMonthEnd(reference = new Date()): string {
    return new Date(
        Date.UTC(
            reference.getUTCFullYear(),
            reference.getUTCMonth(),
            0,
        ),
    )
        .toISOString()
        .slice(0, 10);
}

function decimalPercent(value: string): string {
    return (Number(value) / 100).toFixed(2);
}

function parseDepths(value: string): string[] {
    return value
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part.length > 0)
        .map(decimalPercent);
}

function percent(value: number, digits = 1): string {
    return new Intl.NumberFormat("zh-TW", {
        style: "percent",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    }).format(value);
}

function ratioLine(ratios: readonly number[]): string {
    return ratios
        .map((basisPoints) => `${String(basisPoints / 100)}%`)
        .join(" / ");
}

function isOptimizationPayload(
    payload: ResultResponse["payload"],
): payload is Extract<
    ResultResponse["payload"],
    { candidates: unknown }
> {
    return "candidates" in payload;
}

function copyText(value: string): Promise<void> {
    if (navigator.clipboard === undefined) {
        return Promise.reject(new Error("Clipboard is unavailable"));
    }
    return navigator.clipboard.writeText(value);
}

export function AiBatchPage() {
    const { api, capability } = useResearchData();
    const [familyId, setFamilyId] = useState("nasdaq-100");
    const [targetChoice, setTargetChoice] = useState("");
    const [start, setStart] = useState("2011-01-03");
    const [end, setEnd] = useState(priorCalendarMonthEnd);
    const [initialCash, setInitialCash] = useState("10000");
    const [monthlyContribution, setMonthlyContribution] =
        useState("1000");
    const [annualGrowth, setAnnualGrowth] = useState("3");
    const [cashInterest, setCashInterest] = useState("1.5");
    const [dividendPolicy, setDividendPolicy] =
        useState<"cash" | "reinvest">("cash");
    const [depths, setDepths] = useState("20, 30, 40");
    const [minimumRatio, setMinimumRatio] = useState("0");
    const [maximumRatio, setMaximumRatio] = useState("100");
    const [ratioStep, setRatioStep] = useState("10");
    const [monotone, setMonotone] = useState(true);
    const [walkForwardSplits, setWalkForwardSplits] = useState("3");
    const [minimumEpisodes, setMinimumEpisodes] = useState("5");
    const [maxCandidates, setMaxCandidates] = useState("14641");
    const [syntheticStress, setSyntheticStress] = useState(true);
    const [jobId, setJobId] = useState<string | null>(null);
    const [copyStatus, setCopyStatus] = useState("");
    const [importStatus, setImportStatus] = useState("");
    const instrumentsQuery = useQuery({
        queryKey: ["instruments"],
        queryFn: api.getInstruments,
    });
    const instruments = instrumentsQuery.data?.instruments;
    const familyIds = useMemo(
        () => [
            ...new Set(
                (instruments ?? []).map(
                    (instrument) => instrument.family_id,
                ),
            ),
        ],
        [instruments],
    );
    const familyInstruments = useMemo(
        () =>
            (instruments ?? []).filter(
                (instrument) => instrument.family_id === familyId,
            ),
        [familyId, instruments],
    );
    const targetSymbol = familyInstruments.some(
        (instrument) => instrument.symbol === targetChoice,
    )
        ? targetChoice
        : (familyInstruments[0]?.symbol ?? "");

    const buildRequest = (): OptimizationCreateRequest => ({
        schema_version: "1.0",
        family_id: familyId,
        target_symbol: targetSymbol,
        depths: parseDepths(depths),
        ratio_search: {
            minimum_basis_points: Math.round(
                Number(minimumRatio) * 100,
            ),
            maximum_basis_points: Math.round(
                Number(maximumRatio) * 100,
            ),
            step_basis_points: Math.round(Number(ratioStep) * 100),
            monotone,
        },
        walk_forward: {
            n_splits: Number(walkForwardSplits),
            minimum_train_independent_episodes: 1,
            minimum_test_independent_episodes: 1,
        },
        synthetic_stress: {
            enabled: syntheticStress,
            annual_expense_ratio: 0.01,
            max_portfolio_drawdown: 0.85,
            max_longest_trap_days: 2_520,
        },
        max_depth_levels: 8,
        max_candidates: Number(maxCandidates),
        minimum_independent_episodes: Number(minimumEpisodes),
        neighbor_radius_basis_points: 1_000,
        isolated_peak_penalty: 1.25,
        strategy: {
            start,
            end,
            initial_cash: initialCash,
            initial_shares: "0",
            monthly_contribution: monthlyContribution,
            annual_contribution_growth:
                decimalPercent(annualGrowth),
            contribution_day: 1,
            contribution_events: [],
            cash_interest_rate: decimalPercent(cashInterest),
            dividend_policy: dividendPolicy,
            fixed_fee: "0",
            fee_rate: "0",
            slippage: "0",
        },
    });

    const createJob = useMutation({
        mutationFn: () => api.createOptimization(buildRequest()),
        onSuccess: (accepted) => {
            setJobId(accepted.job_id);
        },
    });
    const job = useQuery({
        queryKey: ["optimization-job", jobId],
        queryFn: () => api.getJob(jobId ?? ""),
        enabled: jobId !== null,
        refetchInterval: (query) => {
            const status = query.state.data?.status;
            return status === "succeeded" ||
                status === "failed" ||
                status === "cancelled"
                ? false
                : 900;
        },
    });
    const resultId =
        job.data?.status === "succeeded"
            ? job.data.result_id
            : null;
    const result = useQuery({
        queryKey: ["optimization-result", resultId],
        queryFn: () => api.getResult(resultId ?? ""),
        enabled: resultId !== null,
    });
    const cancelJob = useMutation({
        mutationFn: () => api.cancelJob(jobId ?? ""),
    });

    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setJobId(null);
        createJob.mutate();
    };
    const downloadConfiguration = () => {
        const contents = JSON.stringify(buildRequest(), null, 2);
        const objectUrl = URL.createObjectURL(
            new Blob([contents], { type: "application/json" }),
        );
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = "drawdown-optimization-request.json";
        anchor.click();
        URL.revokeObjectURL(objectUrl);
    };
    const importConfiguration = async (
        event: ChangeEvent<HTMLInputElement>,
    ) => {
        const file = event.currentTarget.files?.[0];
        if (file === undefined) {
            return;
        }
        try {
            const parsed = JSON.parse(
                await file.text(),
            ) as Partial<OptimizationCreateRequest>;
            if (
                typeof parsed.family_id !== "string" ||
                typeof parsed.target_symbol !== "string" ||
                parsed.strategy === undefined ||
                parsed.ratio_search === undefined ||
                parsed.walk_forward === undefined ||
                !Array.isArray(parsed.depths)
            ) {
                throw new Error("Incomplete optimization request");
            }
            setFamilyId(parsed.family_id);
            setTargetChoice(parsed.target_symbol);
            setStart(parsed.strategy.start);
            setEnd(parsed.strategy.end);
            setInitialCash(String(parsed.strategy.initial_cash));
            setMonthlyContribution(
                String(parsed.strategy.monthly_contribution ?? 0),
            );
            setAnnualGrowth(
                String(
                    Number(
                        parsed.strategy
                            .annual_contribution_growth ?? 0,
                    ) * 100,
                ),
            );
            setCashInterest(
                String(
                    Number(
                        parsed.strategy.cash_interest_rate ?? 0,
                    ) * 100,
                ),
            );
            setDividendPolicy(
                parsed.strategy.dividend_policy ?? "cash",
            );
            setDepths(
                parsed.depths
                    .map((value) => String(Number(value) * 100))
                    .join(", "),
            );
            setMinimumRatio(
                String(
                    (parsed.ratio_search
                        .minimum_basis_points ?? 0) / 100,
                ),
            );
            setMaximumRatio(
                String(
                    (parsed.ratio_search
                        .maximum_basis_points ?? 10_000) / 100,
                ),
            );
            setRatioStep(
                String(
                    (parsed.ratio_search.step_basis_points ??
                        1_000) / 100,
                ),
            );
            setMonotone(parsed.ratio_search.monotone ?? true);
            setWalkForwardSplits(
                String(parsed.walk_forward.n_splits ?? 3),
            );
            setMinimumEpisodes(
                String(parsed.minimum_independent_episodes ?? 5),
            );
            setMaxCandidates(
                String(parsed.max_candidates ?? 14_641),
            );
            setSyntheticStress(
                parsed.synthetic_stress?.enabled ?? false,
            );
            setImportStatus("設定已匯入；請檢查後再執行。");
        } catch {
            setImportStatus("匯入失敗：請選擇完整的設定 JSON。");
        } finally {
            event.currentTarget.value = "";
        }
    };
    const aiInstructions = [
        "Drawdown Ledger AI 操作模式",
        "1. 前往 /ai。",
        "2. 以 [data-ai-field] 讀寫欄位；不要依畫面座標。",
        "3. 依序設定 family_id、target_symbol、depths_percent、ratio_step_percent。",
        "4. 點擊 [data-ai-action='run-optimization']。",
        "5. 監看 [data-ai-status='optimization-job']，直到 succeeded、failed 或 cancelled。",
        "6. 讀取 [data-ai-result='recommendations'] 與 [data-ai-result='pareto-table']。",
        "7. 先比較 walk-forward、最差 5%、現金耗盡率與鄰域穩定性，再選比例。",
        "8. 禁止把 exploration_only 結果描述成正式推薦。",
        "此流程不需要 API key，也不應輸入任何密鑰。",
    ].join("\n");

    return (
        <section className="page ai-workbench">
            <header className="page-heading page-heading--split">
                <div>
                    <p className="eyebrow">Browser-operable optimizer</p>
                    <h1>AI 批次</h1>
                </div>
                <p className="page-heading__summary">
                    以固定網格窮舉現金比例，使用 walk-forward
                    樣本外結果、鄰域穩定性與壓力測試篩選，而不是只挑歷史最高報酬。
                </p>
            </header>

            <div className="ai-mode-banner">
                <span aria-hidden="true">AI</span>
                <div>
                    <strong>專屬瀏覽器操作模式</strong>
                    <p>
                        不需要 API key。每個核心欄位與動作都有固定
                        id、name、aria-label 與 data-ai-* 標記。
                    </p>
                </div>
                <button
                    type="button"
                    data-ai-action="copy-ai-instructions"
                    onClick={() => {
                        void copyText(aiInstructions)
                            .then(() => {
                                setCopyStatus("AI 操作說明已複製。");
                            })
                            .catch(() => {
                                setCopyStatus(
                                    "瀏覽器未允許剪貼簿，請改用設定 JSON。",
                                );
                            });
                    }}
                >
                    複製 AI 操作說明
                </button>
            </div>
            {copyStatus.length > 0 ? (
                <p className="action-status" role="status">
                    {copyStatus}
                </p>
            ) : null}

            <form className="optimizer-form" onSubmit={submit}>
                <section className="optimizer-panel">
                    <div className="optimizer-panel__heading">
                        <span>UNIVERSE</span>
                        <h2>研究範圍</h2>
                    </div>
                    <div className="field-grid field-grid--four">
                        <label>
                            <span>指數家族</span>
                            <select
                                id="ai-family-id"
                                name="family_id"
                                aria-label="AI 指數家族"
                                data-ai-field="family_id"
                                value={familyId}
                                onChange={(event) => {
                                    setFamilyId(
                                        event.currentTarget.value,
                                    );
                                    setTargetChoice("");
                                }}
                            >
                                {familyIds.map((id) => (
                                    <option key={id} value={id}>
                                        {familyNames[id] ?? id}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label>
                            <span>分析標的</span>
                            <select
                                id="ai-target-symbol"
                                name="target_symbol"
                                aria-label="AI 分析標的"
                                data-ai-field="target_symbol"
                                value={targetSymbol}
                                onChange={(event) =>
                                    setTargetChoice(
                                        event.currentTarget.value,
                                    )
                                }
                            >
                                {familyInstruments.map((instrument) => (
                                    <option
                                        key={instrument.symbol}
                                        value={instrument.symbol}
                                    >
                                        {instrument.symbol} ·{" "}
                                        {instrument.leverage}×
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label>
                            <span>開始日</span>
                            <input
                                id="ai-start"
                                name="start"
                                aria-label="AI 回測開始日"
                                data-ai-field="start"
                                type="date"
                                value={start}
                                onChange={(event) =>
                                    setStart(event.currentTarget.value)
                                }
                            />
                        </label>
                        <label>
                            <span>結束日</span>
                            <input
                                id="ai-end"
                                name="end"
                                aria-label="AI 回測結束日"
                                data-ai-field="end"
                                type="date"
                                value={end}
                                onChange={(event) =>
                                    setEnd(event.currentTarget.value)
                                }
                            />
                        </label>
                    </div>
                </section>

                <section className="optimizer-panel">
                    <div className="optimizer-panel__heading">
                        <span>GRID</span>
                        <h2>窮舉網格</h2>
                    </div>
                    <div className="field-grid field-grid--six">
                        <label>
                            <span>回撤層級（%）</span>
                            <input
                                id="ai-depths"
                                name="depths_percent"
                                aria-label="AI 回撤層級百分比"
                                data-ai-field="depths_percent"
                                value={depths}
                                onChange={(event) =>
                                    setDepths(event.currentTarget.value)
                                }
                                placeholder="20, 30, 40"
                            />
                        </label>
                        <label>
                            <span>最小比例（%）</span>
                            <input
                                id="ai-min-ratio"
                                name="minimum_ratio_percent"
                                aria-label="AI 最小現金比例"
                                data-ai-field="minimum_ratio_percent"
                                type="number"
                                min="0"
                                max="100"
                                value={minimumRatio}
                                onChange={(event) =>
                                    setMinimumRatio(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>最大比例（%）</span>
                            <input
                                id="ai-max-ratio"
                                name="maximum_ratio_percent"
                                aria-label="AI 最大現金比例"
                                data-ai-field="maximum_ratio_percent"
                                type="number"
                                min="0"
                                max="100"
                                value={maximumRatio}
                                onChange={(event) =>
                                    setMaximumRatio(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>比例步長（%）</span>
                            <input
                                id="ai-ratio-step"
                                name="ratio_step_percent"
                                aria-label="AI 現金比例步長"
                                data-ai-field="ratio_step_percent"
                                type="number"
                                min="0.01"
                                max="100"
                                step="0.01"
                                value={ratioStep}
                                onChange={(event) =>
                                    setRatioStep(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>Walk-forward 分割</span>
                            <input
                                id="ai-walk-forward-splits"
                                name="walk_forward_splits"
                                aria-label="AI Walk-forward 分割數"
                                data-ai-field="walk_forward_splits"
                                type="number"
                                min="1"
                                value={walkForwardSplits}
                                onChange={(event) =>
                                    setWalkForwardSplits(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>最多候選</span>
                            <input
                                id="ai-max-candidates"
                                name="max_candidates"
                                aria-label="AI 最多候選數"
                                data-ai-field="max_candidates"
                                type="number"
                                min="1"
                                max="100000"
                                value={maxCandidates}
                                onChange={(event) =>
                                    setMaxCandidates(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                    </div>
                    <div className="optimizer-switches">
                        <label>
                            <input
                                id="ai-monotone"
                                name="monotone"
                                aria-label="AI 比例隨跌幅不遞減"
                                data-ai-field="monotone"
                                type="checkbox"
                                checked={monotone}
                                onChange={(event) =>
                                    setMonotone(
                                        event.currentTarget.checked,
                                    )
                                }
                            />
                            深跌層級的比例不得低於淺跌層級
                        </label>
                        <label>
                            <input
                                id="ai-synthetic-stress"
                                name="synthetic_stress"
                                aria-label="AI 執行合成槓桿壓力測試"
                                data-ai-field="synthetic_stress"
                                type="checkbox"
                                checked={syntheticStress}
                                onChange={(event) =>
                                    setSyntheticStress(
                                        event.currentTarget.checked,
                                    )
                                }
                            />
                            納入上市前合成槓桿壓力測試
                        </label>
                    </div>
                </section>

                <section className="optimizer-panel">
                    <div className="optimizer-panel__heading">
                        <span>CASH</span>
                        <h2>現金庫假設</h2>
                    </div>
                    <div className="field-grid field-grid--six">
                        <label>
                            <span>起始現金</span>
                            <input
                                id="ai-initial-cash"
                                name="initial_cash"
                                aria-label="AI 起始現金"
                                data-ai-field="initial_cash"
                                type="number"
                                min="0"
                                value={initialCash}
                                onChange={(event) =>
                                    setInitialCash(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>每月入庫</span>
                            <input
                                id="ai-monthly-contribution"
                                name="monthly_contribution"
                                aria-label="AI 每月入庫金額"
                                data-ai-field="monthly_contribution"
                                type="number"
                                min="0"
                                value={monthlyContribution}
                                onChange={(event) =>
                                    setMonthlyContribution(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>每年投入成長（%）</span>
                            <input
                                id="ai-annual-growth"
                                name="annual_growth_percent"
                                aria-label="AI 每年投入成長率"
                                data-ai-field="annual_growth_percent"
                                type="number"
                                step="0.1"
                                value={annualGrowth}
                                onChange={(event) =>
                                    setAnnualGrowth(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>現金年利率（%）</span>
                            <input
                                id="ai-cash-interest"
                                name="cash_interest_percent"
                                aria-label="AI 現金年利率"
                                data-ai-field="cash_interest_percent"
                                type="number"
                                min="0"
                                step="0.1"
                                value={cashInterest}
                                onChange={(event) =>
                                    setCashInterest(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>最少獨立事件</span>
                            <input
                                id="ai-minimum-episodes"
                                name="minimum_independent_episodes"
                                aria-label="AI 最少獨立事件"
                                data-ai-field="minimum_independent_episodes"
                                type="number"
                                min="1"
                                value={minimumEpisodes}
                                onChange={(event) =>
                                    setMinimumEpisodes(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>股息處理</span>
                            <select
                                id="ai-dividend-policy"
                                name="dividend_policy"
                                aria-label="AI 股息處理"
                                data-ai-field="dividend_policy"
                                value={dividendPolicy}
                                onChange={(event) =>
                                    setDividendPolicy(
                                        event.currentTarget.value as
                                            | "cash"
                                            | "reinvest",
                                    )
                                }
                            >
                                <option value="cash">留在現金庫</option>
                                <option value="reinvest">次日投入</option>
                            </select>
                        </label>
                    </div>
                </section>

                <div className="optimizer-actions">
                    <div className="json-actions">
                        <button
                            type="button"
                            data-ai-action="export-configuration"
                            onClick={downloadConfiguration}
                        >
                            匯出設定 JSON
                        </button>
                        <label className="file-action">
                            <span>匯入設定 JSON</span>
                            <input
                                id="ai-import-json"
                                name="configuration_file"
                                aria-label="匯入 AI 設定 JSON"
                                data-ai-action="import-configuration"
                                type="file"
                                accept="application/json,.json"
                                onChange={(event) => {
                                    void importConfiguration(event);
                                }}
                            />
                        </label>
                        {importStatus.length > 0 ? (
                            <span role="status">{importStatus}</span>
                        ) : null}
                    </div>
                    <button
                        type="submit"
                        className="primary-action"
                        data-ai-action="run-optimization"
                        disabled={
                            capability.mode === "static" ||
                            createJob.isPending ||
                            targetSymbol.length === 0
                        }
                    >
                        {createJob.isPending
                            ? "建立工作中…"
                            : "開始窮舉分析"}
                    </button>
                </div>
            </form>

            {capability.mode === "static" ? (
                <div className="inline-alert" role="alert">
                    <strong>靜態備援為唯讀模式</strong>
                    <span>AI 批次必須由本機計算服務執行。</span>
                </div>
            ) : null}
            {createJob.isError || job.isError || result.isError ? (
                <div className="inline-alert" role="alert">
                    <strong>最佳化工作失敗</strong>
                    <span>
                        請縮小比例網格、檢查資料覆蓋或修正設定 JSON。
                    </span>
                </div>
            ) : null}
            {job.data === undefined ? null : (
                <JobStatus
                    job={job.data}
                    cancelling={cancelJob.isPending}
                    onCancel={() => cancelJob.mutate()}
                />
            )}
            {result.data === undefined ? null : (
                <OptimizationResult result={result.data} />
            )}
        </section>
    );
}

function JobStatus({
    job,
    cancelling,
    onCancel,
}: {
    job: Awaited<ReturnType<ReturnType<typeof useResearchData>["api"]["getJob"]>>;
    cancelling: boolean;
    onCancel: () => void;
}) {
    const progress =
        job.total <= 0 ? 0 : Math.min(100, (job.progress / job.total) * 100);
    const terminal =
        job.status === "succeeded" ||
        job.status === "failed" ||
        job.status === "cancelled";
    return (
        <section
            className="job-status"
            data-ai-status="optimization-job"
            aria-label="最佳化工作狀態"
            aria-live="polite"
        >
            <div>
                <span>工作 {job.id}</span>
                <strong>{job.status}</strong>
            </div>
            <progress
                max={100}
                value={progress}
                aria-label="最佳化進度"
            />
            <span>
                {job.progress} / {job.total}
            </span>
            {!terminal ? (
                <button
                    type="button"
                    data-ai-action="cancel-optimization"
                    disabled={cancelling}
                    onClick={onCancel}
                >
                    取消工作
                </button>
            ) : null}
        </section>
    );
}

function OptimizationResult({ result }: { result: ResultResponse }) {
    if (!isOptimizationPayload(result.payload)) {
        return (
            <div className="inline-alert" role="alert">
                <strong>舊版結果只能下載原始 JSON</strong>
                <span>重新執行即可取得完整候選比較。</span>
            </div>
        );
    }
    const payload = result.payload;
    const candidates = [...payload.candidates].sort(
        (left, right) =>
            Number(right.pareto_member) -
                Number(left.pareto_member) ||
            right.stability_adjusted_xirr -
                left.stability_adjusted_xirr,
    );
    return (
        <section className="optimization-result" aria-live="polite">
            {payload.exploration_only ? (
                <div className="inline-alert" role="alert">
                    <strong>探索結果，不構成正式推薦</strong>
                    <span>
                        獨立事件只有 {payload.independent_episode_count}{" "}
                        次，未達正式門檻。
                    </span>
                </div>
            ) : null}
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Out-of-sample selection</p>
                    <h2>三種可執行方案</h2>
                </div>
                <span>
                    {payload.independent_episode_count} 次獨立事件 ·{" "}
                    {payload.provenance.walk_forward_splits} folds
                </span>
            </div>
            <div
                className="recommendation-grid"
                data-ai-result="recommendations"
            >
                {payload.recommendations.map((recommendation) => (
                    <article
                        key={recommendation.profile}
                        className={`recommendation-card recommendation-card--${recommendation.profile}`}
                    >
                        <span>
                            {profileNames[recommendation.profile]}
                        </span>
                        <strong>
                            {ratioLine(recommendation.ratios)}
                        </strong>
                        <dl>
                            <div>
                                <dt>樣本外 XIRR</dt>
                                <dd>
                                    {percent(
                                        recommendation.oos_xirr,
                                    )}
                                </dd>
                            </div>
                            <div>
                                <dt>穩定性調整</dt>
                                <dd>
                                    {percent(
                                        recommendation
                                            .stability_adjusted_xirr,
                                    )}
                                </dd>
                            </div>
                        </dl>
                    </article>
                ))}
            </div>
            <div className="optimization-provenance">
                <span>
                    原型{" "}
                    <strong>{payload.provenance.prototype_symbol}</strong>
                </span>
                <span>
                    標的{" "}
                    <strong>{payload.provenance.target_symbol}</strong>
                </span>
                <span>
                    候選 <strong>{payload.candidates.length}</strong>
                </span>
                <span>
                    合成壓力通過{" "}
                    <strong>
                        {payload.synthetic_stress.passed_candidates}/
                        {payload.synthetic_stress.evaluated_candidates}
                    </strong>
                </span>
            </div>
            <div
                className="data-table-wrap"
                data-ai-result="pareto-table"
            >
                <table aria-label="Pareto 候選策略">
                    <caption>Pareto 與穩定候選</caption>
                    <thead>
                        <tr>
                            <th scope="col">比例</th>
                            <th scope="col">Pareto</th>
                            <th scope="col">樣本外 XIRR</th>
                            <th scope="col">穩定性調整</th>
                            <th scope="col">穩定分數</th>
                            <th scope="col">鄰域數</th>
                            <th scope="col">最差 5%</th>
                            <th scope="col">提早耗盡率</th>
                            <th scope="col">最長套牢</th>
                            <th scope="col">合成壓力</th>
                        </tr>
                    </thead>
                    <tbody>
                        {candidates.slice(0, 100).map((candidate) => (
                            <tr key={candidate.ratios.join("-")}>
                                <th scope="row">
                                    {ratioLine(candidate.ratios)}
                                </th>
                                <td>
                                    {candidate.pareto_member ? "是" : "否"}
                                </td>
                                <td>{percent(candidate.oos_xirr)}</td>
                                <td>
                                    {percent(
                                        candidate.stability_adjusted_xirr,
                                    )}
                                </td>
                                <td>
                                    {percent(candidate.stability_score)}
                                </td>
                                <td>{candidate.neighbor_count}</td>
                                <td>
                                    {percent(candidate.worst_5_return)}
                                </td>
                                <td>
                                    {percent(
                                        candidate.early_depletion_rate,
                                    )}
                                </td>
                                <td>
                                    {candidate.longest_trap_days} 日
                                </td>
                                <td>
                                    {candidate.synthetic_stress_pass ===
                                    null
                                        ? "未要求"
                                        : candidate.synthetic_stress_pass
                                          ? "通過"
                                          : "未通過"}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </section>
    );
}
