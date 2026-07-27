import { useMutation, useQuery } from "@tanstack/react-query";
import {
    useMemo,
    useState,
    type FormEvent,
} from "react";

import {
    ResearchChart,
    type ResearchChartModel,
} from "../features/chart/ResearchChart";
import {
    researchApiErrorMessage,
    useResearchData,
} from "../lib/api";
import type {
    EvidenceAnalyzeResponse,
    MarketSeriesResponse,
} from "../lib/contracts";
import { useSearchParams } from "../lib/router";

interface EvidenceBundle {
    evidence: EvidenceAnalyzeResponse;
    series: MarketSeriesResponse;
}

const familyNames: Record<string, string> = {
    "taiwan-50": "台灣 50",
    "taiwan-weighted": "台灣加權",
    "nasdaq-100": "NASDAQ-100",
    "sp-500": "S&P 500",
    "dow-jones-industrial-average": "道瓊工業",
    "russell-2000": "Russell 2000",
};

function percent(
    value: number | null,
    digits = 1,
): string {
    if (value === null || !Number.isFinite(value)) {
        return "—";
    }
    return new Intl.NumberFormat("zh-TW", {
        style: "percent",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    }).format(value);
}

function date(value: string | null): string {
    return value ?? "尚未";
}

function toChartModel(series: MarketSeriesResponse): ResearchChartModel {
    const convert = (
        source: MarketSeriesResponse["prototype"],
    ) => ({
        symbol: source.symbol,
        sourceKind: source.source_kind,
        points: source.points.map((point) => ({
            session: point.session,
            close: point.close,
            totalReturnClose: point.total_return_close,
            drawdown: point.drawdown,
        })),
    });

    return {
        prototype: convert(series.prototype),
        actual: convert(series.actual),
        synthetic:
            series.synthetic === null
                ? null
                : convert(series.synthetic),
    };
}

function horizonLabel(sessions: number): string {
    if (sessions === 21) {
        return "1 個月";
    }
    if (sessions === 63) {
        return "3 個月";
    }
    if (sessions === 126) {
        return "6 個月";
    }
    if (sessions === 252) {
        return "1 年";
    }
    return `${String(sessions)} 交易日`;
}

function EvidenceSentence({
    evidence,
    threshold,
}: {
    evidence: EvidenceAnalyzeResponse;
    threshold: number;
}) {
    const annual =
        evidence.episode_statistics.find(
            (statistic) => statistic.horizon_sessions === 252,
        ) ?? evidence.episode_statistics.at(-1);
    const losses =
        annual?.win_rate === null || annual?.win_rate === undefined
            ? null
            : Math.max(
                  0,
                  annual.n - Math.round(annual.n * annual.win_rate),
              );

    return (
        <blockquote
            className="evidence-sentence"
            role="note"
            aria-label="核心歷史結論"
        >
            <p>
                如果原型指數從前高回撤{" "}
                <strong>{percent(Math.abs(threshold), 0)}</strong>{" "}
                後於次一交易日買進，在過去{" "}
                <strong>{evidence.n_episode} 次獨立歷史事件</strong>
                中，一年後平均總報酬為{" "}
                <strong>{percent(annual?.mean_total_return ?? null)}</strong>
                、勝率{" "}
                <strong>{percent(annual?.win_rate ?? null)}</strong>
                ；其中{" "}
                <strong>
                    {losses === null
                        ? "尚無完整樣本"
                        : `${String(losses)} 次在一年後仍未獲利`}
                </strong>
                。
            </p>
            <footer>
                這是歷史條件分布，不是報酬保證；門檻以原型收盤判定，交易以次一交易日開盤執行。
            </footer>
        </blockquote>
    );
}

function StatisticsTable({
    evidence,
}: {
    evidence: EvidenceAnalyzeResponse;
}) {
    const dailyByHorizon = new Map(
        evidence.daily_statistics.map((statistic) => [
            statistic.horizon_sessions,
            statistic,
        ]),
    );
    return (
        <div className="data-table-wrap">
            <table aria-label="前瞻報酬統計">
                <caption>獨立事件與每日重疊樣本</caption>
                <thead>
                    <tr>
                        <th scope="col">期間</th>
                        <th scope="col">獨立 N</th>
                        <th scope="col">平均</th>
                        <th scope="col">中位數</th>
                        <th scope="col">勝率</th>
                        <th scope="col">95% 勝率區間</th>
                        <th scope="col">最差 5% 均值</th>
                        <th scope="col">每日重疊 N</th>
                    </tr>
                </thead>
                <tbody>
                    {evidence.episode_statistics.map((statistic) => {
                        const daily = dailyByHorizon.get(
                            statistic.horizon_sessions,
                        );
                        return (
                            <tr key={statistic.horizon_sessions}>
                                <th scope="row">
                                    {horizonLabel(
                                        statistic.horizon_sessions,
                                    )}
                                </th>
                                <td>{statistic.n}</td>
                                <td>{percent(statistic.mean_total_return)}</td>
                                <td>
                                    {percent(statistic.median_total_return)}
                                </td>
                                <td>{percent(statistic.win_rate)}</td>
                                <td>
                                    {percent(statistic.confidence_lower)}—
                                    {percent(statistic.confidence_upper)}
                                </td>
                                <td>
                                    {percent(statistic.expected_shortfall_5)}
                                </td>
                                <td>{daily?.n ?? "—"}</td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}

function EpisodeTable({
    evidence,
}: {
    evidence: EvidenceAnalyzeResponse;
}) {
    return (
        <div className="data-table-wrap">
            <table aria-label="獨立回撤事件">
                <caption>獨立回撤事件帳本</caption>
                <thead>
                    <tr>
                        <th scope="col">週期</th>
                        <th scope="col">前高</th>
                        <th scope="col">訊號</th>
                        <th scope="col">進場</th>
                        <th scope="col">訊號回撤</th>
                        <th scope="col">恢復前高</th>
                        <th scope="col">V 轉</th>
                        <th scope="col">MAE</th>
                        <th scope="col">MFE</th>
                        <th scope="col">1 年總報酬</th>
                    </tr>
                </thead>
                <tbody>
                    {evidence.episodes.map((episode) => {
                        const annual = episode.forward_returns.find(
                            (forward) =>
                                forward.horizon_sessions === 252,
                        );
                        return (
                            <tr key={episode.cycle_id}>
                                <th scope="row">#{episode.cycle_id}</th>
                                <td><time>{episode.peak_date}</time></td>
                                <td><time>{episode.signal_date}</time></td>
                                <td><time>{date(episode.entry_date)}</time></td>
                                <td>{percent(episode.signal_drawdown)}</td>
                                <td><time>{date(episode.recovery_date)}</time></td>
                                <td>{episode.v_recovered ? "是" : "否"}</td>
                                <td>{percent(episode.mae)}</td>
                                <td>{percent(episode.mfe)}</td>
                                <td>
                                    {percent(annual?.total_return ?? null)}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}

export function EvidencePage() {
    const { api, capability } = useResearchData();
    const [searchParameters] = useSearchParams();
    const requestedFamily =
        searchParameters.get("family") ?? "nasdaq-100";
    const [familyId, setFamilyId] = useState(requestedFamily);
    const [targetChoice, setTargetChoice] = useState(
        searchParameters.get("instrument") ?? "",
    );
    const [thresholdPercent, setThresholdPercent] = useState("30");
    const instrumentsQuery = useQuery({
        queryKey: ["instruments"],
        queryFn: api.getInstruments,
    });
    const instruments = instrumentsQuery.data?.instruments;
    const familyIds = useMemo(
        () => [
            ...new Set(
                (instruments ?? []).map((item) => item.family_id),
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
        : (familyInstruments.at(-1)?.symbol ?? "");
    const targetInstrument = familyInstruments.find(
        (instrument) => instrument.symbol === targetSymbol,
    );

    const analysis = useMutation({
        mutationFn: async (): Promise<EvidenceBundle> => {
            const threshold = Number(thresholdPercent) / 100;
            const [evidence, series] = await Promise.all([
                api.analyzeEvidence({
                    schema_version: "1.0",
                    family_id: familyId,
                    target_symbol: targetSymbol,
                    threshold,
                    horizons: [21, 63, 126, 252],
                }),
                api.getMarketSeries({
                    family_id: familyId,
                    target_symbol: targetSymbol,
                    include_synthetic: true,
                    max_points: 15_000,
                    start: null,
                    end: null,
                }),
            ]);
            return { evidence, series };
        },
    });

    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        analysis.mutate();
    };
    const selectedThreshold = Number(thresholdPercent) / 100;

    return (
        <section className="page evidence-workbench">
            <header className="page-heading page-heading--split">
                <div>
                    <p className="eyebrow">Evidence workbench</p>
                    <h1>歷史證據</h1>
                </div>
                <p className="page-heading__summary">
                    把「跌多少該買」拆成獨立事件、每日重疊樣本與次日開盤結果，避免用重複資料放大信心。
                </p>
            </header>

            <form
                className="research-controls"
                autoComplete="off"
                onSubmit={submit}
            >
                <label>
                    <span>指數家族</span>
                    <select
                        id="evidence-family"
                        name="family_id"
                        data-ai-field="family_id"
                        value={familyId}
                        onChange={(event) => {
                            setFamilyId(event.currentTarget.value);
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
                <div className="derived-prototype" aria-label="原型指數">
                    原型指數 {targetInstrument?.prototype_symbol ?? "—"}
                    <small>由分析標的自動帶入</small>
                </div>
                <label>
                    <span>分析標的</span>
                    <select
                        id="evidence-target"
                        name="target_symbol"
                        data-ai-field="target_symbol"
                        value={targetSymbol}
                        onChange={(event) =>
                            setTargetChoice(event.currentTarget.value)
                        }
                    >
                        {familyInstruments.map((instrument) => (
                            <option
                                key={instrument.symbol}
                                value={instrument.symbol}
                            >
                                {instrument.symbol} · {instrument.leverage}×
                            </option>
                        ))}
                    </select>
                </label>
                <label>
                    <span>原型回撤門檻</span>
                    <span className="input-suffix">
                        <input
                            id="evidence-threshold"
                            name="threshold"
                            data-ai-field="threshold_percent"
                            type="number"
                            min="1"
                            max="90"
                            step="1"
                            required
                            value={thresholdPercent}
                            onChange={(event) =>
                                setThresholdPercent(
                                    event.currentTarget.value,
                                )
                            }
                        />
                        <b>%</b>
                    </span>
                </label>
                <button
                    type="submit"
                    className="primary-action"
                    data-ai-action="analyze-evidence"
                    disabled={
                        instrumentsQuery.isPending ||
                        analysis.isPending ||
                        targetSymbol.length === 0
                    }
                >
                    {analysis.isPending
                        ? "分析中…"
                        : "分析歷史回撤"}
                </button>
                <p className="control-note">
                    {capability.mode === "static"
                        ? `靜態示例 · 資料日 ${capability.dataDate}`
                        : "本機資料 · 自動採前一個日曆月截止"}
                </p>
            </form>

            {analysis.isError ? (
                <div className="inline-alert" role="alert">
                    <strong>無法完成分析</strong>
                    <span>
                        {researchApiErrorMessage(
                            analysis.error,
                            "請先更新原型與標的資料，或調整標的後重試。",
                        )}
                    </span>
                </div>
            ) : null}

            {analysis.data === undefined ? (
                <div className="research-empty">
                    <span aria-hidden="true">EV</span>
                    <div>
                        <h2>選一個門檻，建立可檢驗的歷史句子</h2>
                        <p>
                            結果會同時列出事件次數、每日樣本、V
                            轉、套牢風險、前瞻報酬與逐次事件。
                        </p>
                    </div>
                </div>
            ) : (
                <EvidenceResult
                    bundle={analysis.data}
                    threshold={selectedThreshold}
                />
            )}
        </section>
    );
}

function EvidenceResult({
    bundle,
    threshold,
}: {
    bundle: EvidenceBundle;
    threshold: number;
}) {
    const { evidence, series } = bundle;
    const chartModel = useMemo(() => toChartModel(series), [series]);
    const vRecovered = evidence.episodes.filter(
        (episode) => episode.v_recovered,
    ).length;

    return (
        <div className="evidence-result" aria-live="polite">
            <div
                className="result-provenance"
                role="group"
                aria-label="分析資料來源"
            >
                <span>
                    {evidence.prototype_source === "benchmark"
                        ? "基準指數"
                        : "ETF 代理"}{" "}
                    <strong>{evidence.prototype_symbol}</strong>
                </span>
                <span>
                    標的 <strong>{evidence.target_symbol}</strong>
                </span>
                <span>
                    截止{" "}
                    <strong>
                        {evidence.target_policy_cutoff ?? "資料未齊"}
                    </strong>
                </span>
                <span>次日開盤執行</span>
            </div>
            <EvidenceSentence
                evidence={evidence}
                threshold={threshold}
            />
            <div className="metric-strip metric-strip--four">
                <article className="metric-card">
                    <span>每日重疊樣本 N_day</span>
                    <strong>{evidence.n_day}</strong>
                    <small>只描述條件分布，不當成獨立次數</small>
                </article>
                <article className="metric-card">
                    <span>獨立事件 N_episode</span>
                    <strong>{evidence.n_episode}</strong>
                    <small>{evidence.n_executed_episode} 次有次日進場</small>
                </article>
                <article className="metric-card">
                    <span>V 轉事件</span>
                    <strong>
                        {vRecovered} / {evidence.episodes.length}
                    </strong>
                    <small>依事件引擎的恢復定義</small>
                </article>
                <article className="metric-card">
                    <span>原型來源</span>
                    <strong className="metric-card__symbol">
                        {evidence.prototype_symbol}
                    </strong>
                    <small>
                        {evidence.prototype_source === "benchmark"
                            ? "直接基準序列"
                            : "代理序列，解讀須保守"}
                    </small>
                </article>
            </div>
            <div className="research-warning" role="note">
                <strong>解讀紀律</strong>
                <p>
                    每日樣本彼此高度重疊；正式判斷以獨立事件為主。
                    {evidence.n_episode < 30
                        ? " 目前獨立樣本少於 30 次，信賴區間通常較寬。"
                        : ""}
                    {" "}槓桿標的以原型跌幅觸發，實際與合成序列分開呈現。
                </p>
            </div>
            <ResearchChart model={chartModel} />
            <StatisticsTable evidence={evidence} />
            <EpisodeTable evidence={evidence} />
        </div>
    );
}
