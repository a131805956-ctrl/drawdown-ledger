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
import type { TradeMarkerInput } from "../features/chart/chartModel";
import {
    researchApiErrorMessage,
    useResearchData,
} from "../lib/api";
import type {
    MarketSeriesResponse,
    StrategyBacktestRequest,
    StrategyBacktestResponse,
} from "../lib/contracts";
import { priorCalendarMonthEnd } from "../lib/calendar";
import { useSearchParams } from "../lib/router";

interface StrategyBundle {
    result: StrategyBacktestResponse;
    series: MarketSeriesResponse;
}

interface TierDraft {
    id: number;
    depthPercent: string;
    cashPercent: string;
}

type EventKind = "bonus" | "override" | "pause" | "resume";

interface ContributionEventDraft {
    id: number;
    kind: EventKind;
    month: string;
    amount: string;
}

const defaultTiers: TierDraft[] = [
    { id: 1, depthPercent: "20", cashPercent: "25" },
    { id: 2, depthPercent: "30", cashPercent: "35" },
    { id: 3, depthPercent: "40", cashPercent: "40" },
];

const familyNames: Record<string, string> = {
    "taiwan-50": "台灣 50",
    "taiwan-weighted": "台灣加權",
    "nasdaq-100": "NASDAQ-100",
    "sp-500": "S&P 500",
    "dow-jones-industrial-average": "道瓊工業",
    "russell-2000": "Russell 2000",
};

function decimalPercent(value: string): string {
    return (Number(value) / 100).toFixed(2);
}

function percent(value: number | null, digits = 1): string {
    if (value === null || !Number.isFinite(value)) {
        return "—";
    }
    return new Intl.NumberFormat("zh-TW", {
        style: "percent",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    }).format(value);
}

function integer(value: string | number): string {
    return new Intl.NumberFormat("zh-TW", {
        maximumFractionDigits: 0,
    }).format(Number(value));
}

function money(value: string | number, currency: string): string {
    return new Intl.NumberFormat("zh-TW", {
        style: "currency",
        currency,
        maximumFractionDigits: 0,
    }).format(Number(value));
}

function contributionEvents(
    drafts: readonly ContributionEventDraft[],
): NonNullable<StrategyBacktestRequest["contribution_events"]> {
    return drafts.map((event) => {
        if (event.kind === "bonus") {
            return {
                month: event.month,
                kind: "bonus",
                amount: event.amount,
            };
        }
        if (event.kind === "override") {
            return {
                month: event.month,
                kind: "override",
                amount: event.amount,
            };
        }
        if (event.kind === "pause") {
            return event.amount.length === 0
                ? { month: event.month, kind: "pause" }
                : {
                      month: event.month,
                      kind: "pause",
                      amount: event.amount,
                  };
        }
        return event.amount.length === 0
            ? { month: event.month, kind: "resume" }
            : {
                  month: event.month,
                  kind: "resume",
                  amount: event.amount,
              };
    });
}

function strategyChartModel(
    result: StrategyBacktestResponse,
    series: MarketSeriesResponse,
): ResearchChartModel {
    const convert = (
        source: MarketSeriesResponse["actual"],
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
    const currency = series.actual.currency ?? "USD";
    const trades: TradeMarkerInput[] = result.trades.map((trade) => ({
        date: trade.date,
        signalDate: trade.signal_date,
        threshold: trade.threshold,
        cashSpent: trade.cash_spent,
        prototypeDrawdown: trade.prototype_drawdown,
        targetDrawdown: trade.target_drawdown,
        postTradeCash: trade.post_trade_cash,
        markerProfitLoss: trade.marker_profit_loss,
        kind: trade.kind,
        currency,
    }));
    return {
        prototype: convert(series.prototype),
        actual: convert(series.actual),
        synthetic:
            series.synthetic === null
                ? null
                : convert(series.synthetic),
        portfolio: result.equity_curve.map((point) => ({
            date: point.date,
            value: Number(point.value),
            cash: Number(point.cash),
        })),
        trades,
    };
}

function benchmarkReturn(series: MarketSeriesResponse): number | null {
    const first = series.actual.points.at(0);
    const last = series.actual.points.at(-1);
    if (
        first === undefined ||
        last === undefined ||
        first.total_return_close <= 0
    ) {
        return null;
    }
    return last.total_return_close / first.total_return_close - 1;
}

export function StrategyPage() {
    const { api, capability } = useResearchData();
    const [parameters] = useSearchParams();
    const [familyId, setFamilyId] = useState(
        parameters.get("family") ?? "nasdaq-100",
    );
    const [targetChoice, setTargetChoice] = useState("");
    const [start, setStart] = useState("2011-01-03");
    const [end, setEnd] = useState(priorCalendarMonthEnd);
    const [initialCash, setInitialCash] = useState("10000");
    const [monthlyContribution, setMonthlyContribution] =
        useState("1000");
    const [annualGrowthPercent, setAnnualGrowthPercent] =
        useState("3");
    const [cashInterestPercent, setCashInterestPercent] =
        useState("1.5");
    const [contributionDay, setContributionDay] = useState("1");
    const [dividendPolicy, setDividendPolicy] =
        useState<"cash" | "reinvest">("cash");
    const [tiers, setTiers] = useState<TierDraft[]>(defaultTiers);
    const [events, setEvents] = useState<ContributionEventDraft[]>([]);
    const [nextDraftId, setNextDraftId] = useState(10);
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
        : (familyInstruments.at(-1)?.symbol ?? "");

    const backtest = useMutation({
        mutationFn: async (): Promise<StrategyBundle> => {
            const request: StrategyBacktestRequest = {
                schema_version: "1.0",
                name: "現金庫門檻策略",
                family_id: familyId,
                target_symbol: targetSymbol,
                start,
                end,
                initial_cash: initialCash,
                initial_shares: "0",
                monthly_contribution: monthlyContribution,
                annual_contribution_growth:
                    decimalPercent(annualGrowthPercent),
                contribution_day: Number(contributionDay),
                contribution_events: contributionEvents(events),
                cash_interest_rate:
                    decimalPercent(cashInterestPercent),
                dividend_policy: dividendPolicy,
                fee_rate: "0",
                fixed_fee: "0",
                slippage: "0",
                tiers: tiers.map((tier) => ({
                    depth: decimalPercent(tier.depthPercent),
                    cash_fraction: decimalPercent(tier.cashPercent),
                })),
            };
            const [result, series] = await Promise.all([
                api.backtestStrategy(request),
                api.getMarketSeries({
                    family_id: familyId,
                    target_symbol: targetSymbol,
                    include_synthetic: true,
                    max_points: 5_000,
                    start,
                    end,
                }),
            ]);
            return { result, series };
        },
    });

    const updateTier = (
        id: number,
        field: "depthPercent" | "cashPercent",
        value: string,
    ) => {
        setTiers((current) =>
            current.map((tier) =>
                tier.id === id ? { ...tier, [field]: value } : tier,
            ),
        );
    };
    const updateEvent = (
        id: number,
        field: "kind" | "month" | "amount",
        value: string,
    ) => {
        setEvents((current) =>
            current.map((event) =>
                event.id === id
                    ? {
                          ...event,
                          [field]: value,
                      }
                    : event,
            ),
        );
    };
    const addTier = () => {
        setTiers((current) => [
            ...current,
            {
                id: nextDraftId,
                depthPercent: "50",
                cashPercent: "0",
            },
        ]);
        setNextDraftId((value) => value + 1);
    };
    const addEvent = () => {
        setEvents((current) => [
            ...current,
            {
                id: nextDraftId,
                kind: "bonus",
                month: start.slice(0, 7),
                amount: "0",
            },
        ]);
        setNextDraftId((value) => value + 1);
    };
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        backtest.mutate();
    };

    return (
        <section className="page strategy-lab">
            <header className="page-heading page-heading--split">
                <div>
                    <p className="eyebrow">Cash-pool simulator</p>
                    <h1>策略實驗室</h1>
                </div>
                <p className="page-heading__summary">
                    每月資金先累積在現金庫，只有原型回撤觸發才按比例投入；未觸發的錢持續保留並計息。
                </p>
            </header>

            <form
                className="strategy-form"
                autoComplete="off"
                onSubmit={submit}
            >
                <section
                    className="form-section"
                    aria-labelledby="strategy-universe"
                >
                    <div className="form-section__heading">
                        <span>01</span>
                        <div>
                            <h2 id="strategy-universe">標的與期間</h2>
                            <p>任一交易日都能作為回測開始日。</p>
                        </div>
                    </div>
                    <div className="field-grid field-grid--four">
                        <label>
                            <span>指數家族</span>
                            <select
                                id="strategy-family"
                                name="family_id"
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
                            <span>買進標的</span>
                            <select
                                id="strategy-target"
                                name="target_symbol"
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
                                id="strategy-start"
                                name="start"
                                data-ai-field="start"
                                type="date"
                                required
                                value={start}
                                onChange={(event) =>
                                    setStart(event.currentTarget.value)
                                }
                            />
                        </label>
                        <label>
                            <span>結束日</span>
                            <input
                                id="strategy-end"
                                name="end"
                                data-ai-field="end"
                                type="date"
                                required
                                value={end}
                                onChange={(event) =>
                                    setEnd(event.currentTarget.value)
                                }
                            />
                        </label>
                    </div>
                </section>

                <section
                    className="form-section"
                    aria-labelledby="strategy-cash"
                >
                    <div className="form-section__heading">
                        <span>02</span>
                        <div>
                            <h2 id="strategy-cash">現金庫</h2>
                            <p>薪資成長、現金利息與股息去向都可調整。</p>
                        </div>
                    </div>
                    <div className="field-grid field-grid--six">
                        <label>
                            <span>起始現金</span>
                            <input
                                id="strategy-initial-cash"
                                name="initial_cash"
                                data-ai-field="initial_cash"
                                type="number"
                                min="0"
                                step="1"
                                required
                                value={initialCash}
                                onChange={(event) =>
                                    setInitialCash(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>每月存入現金庫</span>
                            <input
                                id="strategy-monthly-contribution"
                                name="monthly_contribution"
                                data-ai-field="monthly_contribution"
                                aria-label="每月存入現金庫"
                                type="number"
                                min="0"
                                step="1"
                                required
                                value={monthlyContribution}
                                onChange={(event) =>
                                    setMonthlyContribution(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>每年投入成長</span>
                            <span className="input-suffix">
                                <input
                                    id="strategy-growth"
                                    name="annual_growth"
                                    data-ai-field="annual_growth_percent"
                                    type="number"
                                    min="-100"
                                    step="0.1"
                                    value={annualGrowthPercent}
                                    onChange={(event) =>
                                        setAnnualGrowthPercent(
                                            event.currentTarget.value,
                                        )
                                    }
                                />
                                <b>%</b>
                            </span>
                        </label>
                        <label>
                            <span>現金年利率</span>
                            <span className="input-suffix">
                                <input
                                    id="strategy-cash-rate"
                                    name="cash_interest"
                                    data-ai-field="cash_interest_percent"
                                    type="number"
                                    min="0"
                                    step="0.1"
                                    value={cashInterestPercent}
                                    onChange={(event) =>
                                        setCashInterestPercent(
                                            event.currentTarget.value,
                                        )
                                    }
                                />
                                <b>%</b>
                            </span>
                        </label>
                        <label>
                            <span>每月入庫日</span>
                            <input
                                id="strategy-contribution-day"
                                name="contribution_day"
                                data-ai-field="contribution_day"
                                type="number"
                                min="1"
                                max="28"
                                step="1"
                                value={contributionDay}
                                onChange={(event) =>
                                    setContributionDay(
                                        event.currentTarget.value,
                                    )
                                }
                            />
                        </label>
                        <label>
                            <span>股息處理</span>
                            <select
                                id="strategy-dividend-policy"
                                name="dividend_policy"
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
                                <option value="reinvest">
                                    次一開盤立即投入
                                </option>
                            </select>
                        </label>
                    </div>
                </section>

                <section
                    className="form-section"
                    aria-labelledby="strategy-events"
                >
                    <div className="form-section__heading form-section__heading--action">
                        <span>03</span>
                        <div>
                            <h2 id="strategy-events">每月投入事件</h2>
                            <p>
                                可模擬加薪、獎金、暫停與恢復；同月份衝突會由 API
                                明確拒絕。
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={addEvent}
                            data-ai-action="add-contribution-event"
                        >
                            ＋ 新增事件
                        </button>
                    </div>
                    {events.length === 0 ? (
                        <p className="form-empty">
                            尚未加入特殊事件；仍會依每月基準金額入庫。
                        </p>
                    ) : (
                        <div className="event-editor">
                            {events.map((event) => (
                                <div
                                    className="event-editor__row"
                                    key={event.id}
                                >
                                    <label>
                                        <span>月份</span>
                                        <input
                                            aria-label={`事件 ${String(event.id)} 月份`}
                                            data-ai-field={`contribution_event_${String(event.id)}_month`}
                                            type="month"
                                            required
                                            value={event.month}
                                            onChange={(input) =>
                                                updateEvent(
                                                    event.id,
                                                    "month",
                                                    input.currentTarget
                                                        .value,
                                                )
                                            }
                                        />
                                    </label>
                                    <label>
                                        <span>類型</span>
                                        <select
                                            aria-label={`事件 ${String(event.id)} 類型`}
                                            data-ai-field={`contribution_event_${String(event.id)}_kind`}
                                            value={event.kind}
                                            onChange={(input) =>
                                                updateEvent(
                                                    event.id,
                                                    "kind",
                                                    input.currentTarget
                                                        .value,
                                                )
                                            }
                                        >
                                            <option value="bonus">
                                                額外獎金
                                            </option>
                                            <option value="override">
                                                覆寫當月金額
                                            </option>
                                            <option value="pause">
                                                從本月暫停
                                            </option>
                                            <option value="resume">
                                                從本月恢復
                                            </option>
                                        </select>
                                    </label>
                                    <label>
                                        <span>
                                            {event.kind === "bonus"
                                                ? "額外金額"
                                                : event.kind ===
                                                    "override"
                                                  ? "當月總額"
                                                  : "恢復後金額（可空）"}
                                        </span>
                                        <input
                                            aria-label={`事件 ${String(event.id)} 金額`}
                                            data-ai-field={`contribution_event_${String(event.id)}_amount`}
                                            type="number"
                                            min="0"
                                            required={
                                                event.kind === "bonus" ||
                                                event.kind === "override"
                                            }
                                            value={event.amount}
                                            onChange={(input) =>
                                                updateEvent(
                                                    event.id,
                                                    "amount",
                                                    input.currentTarget
                                                        .value,
                                                )
                                            }
                                        />
                                    </label>
                                    <button
                                        type="button"
                                        className="danger-action"
                                        aria-label={`刪除事件 ${String(event.id)}`}
                                        onClick={() =>
                                            setEvents((current) =>
                                                current.filter(
                                                    (item) =>
                                                        item.id !==
                                                        event.id,
                                                ),
                                            )
                                        }
                                    >
                                        移除
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </section>

                <section
                    className="form-section"
                    aria-labelledby="strategy-ladder"
                >
                    <div className="form-section__heading form-section__heading--action">
                        <span>04</span>
                        <div>
                            <h2 id="strategy-ladder">回撤加碼階梯</h2>
                            <p>
                                比例是「觸發當下剩餘現金」的占比；每層在同一前高週期只執行一次。
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={addTier}
                            data-ai-action="add-tier"
                        >
                            ＋ 新增門檻
                        </button>
                    </div>
                    <div className="tier-editor">
                        {tiers.map((tier, index) => (
                            <div className="tier-editor__row" key={tier.id}>
                                <span className="tier-editor__index">
                                    {String(index + 1).padStart(2, "0")}
                                </span>
                                <label>
                                    <span>原型回撤</span>
                                    <span className="input-suffix">
                                        <input
                                            aria-label={`第 ${String(index + 1)} 層回撤`}
                                            data-ai-field={`tier_${String(index + 1)}_depth_percent`}
                                            type="number"
                                            min="1"
                                            max="95"
                                            step="1"
                                            required
                                            value={tier.depthPercent}
                                            onChange={(input) =>
                                                updateTier(
                                                    tier.id,
                                                    "depthPercent",
                                                    input.currentTarget
                                                        .value,
                                                )
                                            }
                                        />
                                        <b>%</b>
                                    </span>
                                </label>
                                <label>
                                    <span>使用現金</span>
                                    <span className="input-suffix">
                                        <input
                                            aria-label={`第 ${String(index + 1)} 層現金比例`}
                                            data-ai-field={`tier_${String(index + 1)}_cash_percent`}
                                            type="number"
                                            min="0"
                                            max="100"
                                            step="1"
                                            required
                                            value={tier.cashPercent}
                                            onChange={(input) =>
                                                updateTier(
                                                    tier.id,
                                                    "cashPercent",
                                                    input.currentTarget
                                                        .value,
                                                )
                                            }
                                        />
                                        <b>%</b>
                                    </span>
                                </label>
                                <button
                                    type="button"
                                    className="danger-action"
                                    disabled={tiers.length <= 1}
                                    aria-label={`刪除第 ${String(index + 1)} 層`}
                                    onClick={() =>
                                        setTiers((current) =>
                                            current.filter(
                                                (item) =>
                                                    item.id !== tier.id,
                                            ),
                                        )
                                    }
                                >
                                    移除
                                </button>
                            </div>
                        ))}
                    </div>
                </section>

                <div className="strategy-submit">
                    <div>
                        <strong>持有規則：不賣出</strong>
                        <span>
                            新高只重置門檻，不補滿現金；月投入與股息照規則持續累積。
                        </span>
                    </div>
                    <button
                        type="submit"
                        className="primary-action"
                        data-ai-action="run-strategy"
                        disabled={
                            backtest.isPending ||
                            targetSymbol.length === 0 ||
                            tiers.length === 0 ||
                            capability.mode === "static"
                        }
                    >
                        {backtest.isPending
                            ? "回測中…"
                            : "執行現金庫回測"}
                    </button>
                </div>
            </form>

            {capability.mode === "static" ? (
                <div className="inline-alert" role="alert">
                    <strong>靜態備援為唯讀模式</strong>
                    <span>
                        可檢視已匯出的報告；啟動本機服務後才能執行新回測。
                    </span>
                </div>
            ) : null}
            {backtest.isError ? (
                <div className="inline-alert" role="alert">
                    <strong>回測無法完成</strong>
                    <span>
                        {researchApiErrorMessage(
                            backtest.error,
                            "請檢查日期、資料覆蓋、同月份事件衝突與門檻順序。",
                        )}
                    </span>
                </div>
            ) : null}
            {backtest.data === undefined ? null : (
                <StrategyResult bundle={backtest.data} tiers={tiers} />
            )}
        </section>
    );
}

function StrategyResult({
    bundle,
    tiers,
}: {
    bundle: StrategyBundle;
    tiers: readonly TierDraft[];
}) {
    const { result, series } = bundle;
    const metrics = result.metrics;
    const currency = series.actual.currency ?? "USD";
    const chartModel = useMemo(
        () => strategyChartModel(result, series),
        [result, series],
    );
    const passiveReturn = benchmarkReturn(series);
    const executedDepths = new Set(
        result.trades
            .map((trade) =>
                trade.threshold === null
                    ? null
                    : Number(trade.threshold),
            )
            .filter((value): value is number => value !== null),
    );
    const pendingDepths = new Set(
        result.pending_thresholds.map(Number),
    );
    const missedDepths = new Set(
        result.missed_thresholds.map(Number),
    );

    return (
        <section className="strategy-result" aria-live="polite">
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Backtest result</p>
                    <h2>回測結果</h2>
                </div>
                <span>
                    {result.prototype_symbol} 訊號 →{" "}
                    {result.target_symbol} 次日開盤
                </span>
            </div>
            <div className="metric-strip metric-strip--four">
                <article className="metric-card">
                    <span>資金加權年化 XIRR</span>
                    <strong>{percent(metrics?.xirr ?? null)}</strong>
                    <small>含每月外部投入</small>
                </article>
                <article className="metric-card">
                    <span>時間加權報酬 TWR</span>
                    <strong>{percent(metrics?.twr ?? null)}</strong>
                    <small>對照標的總報酬 {percent(passiveReturn)}</small>
                </article>
                <article className="metric-card">
                    <span>最大回撤</span>
                    <strong>{percent(metrics?.max_drawdown ?? null)}</strong>
                    <small>
                        最長水下 {metrics?.longest_underwater_days ?? "—"} 日
                    </small>
                </article>
                <article className="metric-card">
                    <span>期末現金庫</span>
                    <strong>{money(result.ending_cash, currency)}</strong>
                    <small>
                        {integer(result.ending_shares)} 股 ·{" "}
                        {result.trade_count} 筆操作
                    </small>
                </article>
            </div>
            <div className="strategy-ledger-summary">
                <span>
                    累積投入
                    <strong>
                        {money(result.contribution_total, currency)}
                    </strong>
                </span>
                <span>
                    股息
                    <strong>
                        {money(result.dividend_income, currency)}
                    </strong>
                </span>
                <span>
                    現金利息
                    <strong>
                        {money(result.interest_income, currency)}
                    </strong>
                </span>
                <span>
                    交易成本
                    <strong>{money(result.total_fees, currency)}</strong>
                </span>
            </div>
            <div className="tier-status-grid" aria-label="門檻執行狀態">
                {tiers.map((tier) => {
                    const depth = Number(tier.depthPercent) / 100;
                    const state = missedDepths.has(depth)
                        ? "missed"
                        : executedDepths.has(depth)
                          ? "executed"
                          : pendingDepths.has(depth)
                            ? "pending"
                            : "not-reached";
                    const label =
                        state === "executed"
                            ? "已執行"
                            : state === "missed"
                              ? "現金不足"
                              : state === "pending"
                                ? "週期待觸發"
                                : "未觸及";
                    return (
                        <article
                            key={tier.id}
                            className={`tier-status tier-status--${state}`}
                        >
                            <span>
                                -{tier.depthPercent}% /{" "}
                                {tier.cashPercent}% 現金
                            </span>
                            <strong>{label}</strong>
                        </article>
                    );
                })}
            </div>
            <div className="research-warning" role="note">
                <strong>策略語意</strong>
                <p>
                    不賣出；嚴格創新高只重置各層觸發資格，不把現金庫補回
                    100%。若回測從回撤途中開始，已滿足的層級會依次日開盤規則處理。
                </p>
            </div>
            <ResearchChart model={chartModel} />
            <TradeTable result={result} currency={currency} />
        </section>
    );
}

function TradeTable({
    result,
    currency,
}: {
    result: StrategyBacktestResponse;
    currency: string;
}) {
    return (
        <div className="data-table-wrap">
            <table aria-label="策略交易紀錄">
                <caption>策略交易與標記</caption>
                <thead>
                    <tr>
                        <th scope="col">訊號日</th>
                        <th scope="col">執行日</th>
                        <th scope="col">類型</th>
                        <th scope="col">門檻</th>
                        <th scope="col">原型回撤</th>
                        <th scope="col">標的回撤</th>
                        <th scope="col">投入</th>
                        <th scope="col">股數</th>
                        <th scope="col">執行價</th>
                        <th scope="col">交易後現金</th>
                        <th scope="col">當日損益</th>
                    </tr>
                </thead>
                <tbody>
                    {result.trades.map((trade, index) => (
                        <tr
                            key={`${trade.date}-${trade.kind}-${String(index)}`}
                        >
                            <td><time>{trade.signal_date}</time></td>
                            <td><time>{trade.date}</time></td>
                            <td>{trade.kind}</td>
                            <td>
                                {trade.threshold === null
                                    ? "—"
                                    : percent(
                                          -Math.abs(
                                              Number(trade.threshold),
                                          ),
                                          0,
                                      )}
                            </td>
                            <td>
                                {percent(
                                    trade.prototype_drawdown === null
                                        ? null
                                        : Number(
                                              trade.prototype_drawdown,
                                          ),
                                )}
                            </td>
                            <td>
                                {percent(
                                    trade.target_drawdown === null
                                        ? null
                                        : Number(
                                              trade.target_drawdown,
                                          ),
                                )}
                            </td>
                            <td>
                                {money(trade.cash_spent, currency)}
                            </td>
                            <td>{integer(trade.shares_bought)}</td>
                            <td>
                                {money(trade.execution_price, currency)}
                            </td>
                            <td>
                                {money(trade.post_trade_cash, currency)}
                            </td>
                            <td>
                                {money(
                                    trade.marker_profit_loss,
                                    currency,
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
