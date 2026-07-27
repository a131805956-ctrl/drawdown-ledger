import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { RouteState } from "../components/RouteState";
import {
    ResearchChart,
    type ResearchChartModel,
} from "../features/chart/ResearchChart";
import { useResearchData } from "../lib/api";
import type {
    Instrument,
    MarketSeriesResponse,
} from "../lib/contracts";
import { Link, useNavigate, useSearchParams } from "../lib/router";

const familyNames: Record<string, string> = {
    "taiwan-50": "台灣 50",
    "taiwan-weighted": "台灣加權",
    "nasdaq-100": "NASDAQ-100",
    "sp-500": "S&P 500",
    "dow-jones-industrial-average": "道瓊工業",
    "russell-2000": "Russell 2000",
};

type StartMode = "inception" | "index-earliest" | "custom";

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
            series.synthetic === null ? null : convert(series.synthetic),
    };
}

function filterChartModel(
    model: ResearchChartModel,
    mode: StartMode,
    customStart: string,
    customEnd: string,
): ResearchChartModel {
    const actualStart = model.actual.points.at(0)?.session ?? null;
    const prototypeStart = model.prototype.points.at(0)?.session ?? null;
    const start =
        mode === "custom"
            ? customStart || null
            : mode === "index-earliest"
              ? prototypeStart
              : actualStart;
    const end = mode === "custom" && customEnd ? customEnd : null;
    const filter = <T extends { session: string }>(points: T[]) =>
        points.filter(
            (point) =>
                (start === null || point.session >= start) &&
                (end === null || point.session <= end),
        );
    return {
        ...model,
        prototype: { ...model.prototype, points: filter(model.prototype.points) },
        actual: { ...model.actual, points: filter(model.actual.points) },
        synthetic:
            model.synthetic === null || model.synthetic === undefined
                ? null
                : { ...model.synthetic, points: filter(model.synthetic.points) },
    };
}

function percent(value: number): string {
    return new Intl.NumberFormat("zh-TW", {
        style: "percent",
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
    }).format(value);
}

function currency(value: number, code: string | null): string {
    return new Intl.NumberFormat("zh-TW", {
        style: "currency",
        currency: code ?? "USD",
        maximumFractionDigits: 2,
    }).format(value);
}

function familyCards(
    instruments: readonly Instrument[],
): Array<{ id: string; name: string; instruments: Instrument[] }> {
    const groups = new Map<string, Instrument[]>();
    for (const instrument of instruments) {
        const current = groups.get(instrument.family_id) ?? [];
        current.push(instrument);
        groups.set(instrument.family_id, current);
    }
    return [...groups].map(([id, familyInstruments]) => ({
        id,
        name: familyNames[id] ?? id,
        instruments: familyInstruments,
    }));
}

export function MarketOverviewPage() {
    const { api } = useResearchData();
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const requestedFamily = searchParams.get("family");
    const requestedInstrument = searchParams.get("instrument");
    const overviewQuery = useQuery({
        queryKey: ["market-overview"],
        queryFn: api.getMarketOverview,
    });
    const instrumentsQuery = useQuery({
        queryKey: ["instruments"],
        queryFn: api.getInstruments,
    });
    const instruments = instrumentsQuery.data?.instruments;
    const cards = useMemo(() => familyCards(instruments ?? []), [instruments]);
    const selectedFamily =
        cards.find((card) => card.id === requestedFamily) ?? cards[0] ?? null;
    const selectedInstrument =
        selectedFamily?.instruments.find(
            (instrument) => instrument.symbol === requestedInstrument,
        ) ?? selectedFamily?.instruments[0] ?? null;
    const hasSelection = requestedFamily !== null || requestedInstrument !== null;
    const requestedMode = searchParams.get("mode");
    const startMode: StartMode =
        requestedMode === "index-earliest" || requestedMode === "custom"
            ? requestedMode
            : "inception";
    const customStart = searchParams.get("start") ?? "";
    const customEnd = searchParams.get("end") ?? "";
    const updateChartQuery = (mode: StartMode, start = "", end = "") => {
        const next = new URLSearchParams(searchParams);
        next.set("mode", mode);
        if (mode === "custom" && start.length > 0) {
            next.set("start", start);
        } else {
            next.delete("start");
        }
        if (mode === "custom" && end.length > 0) {
            next.set("end", end);
        } else {
            next.delete("end");
        }
        navigate(`/?${next.toString()}`, true);
    };
    const seriesQuery = useQuery({
        queryKey: [
            "market-series",
            selectedFamily?.id,
            selectedInstrument?.symbol,
            startMode,
            customStart,
            customEnd,
        ],
        queryFn: () =>
            api.getMarketSeries({
                family_id: selectedFamily?.id ?? "",
                target_symbol: selectedInstrument?.symbol ?? "",
                include_synthetic: true,
                max_points: 15_000,
                start: startMode === "custom" ? customStart || null : null,
                end: startMode === "custom" ? customEnd || null : null,
                history_mode:
                    startMode === "custom"
                        ? "custom"
                        : startMode === "index-earliest"
                          ? "prototype_earliest"
                          : "target_inception",
            }),
        enabled: hasSelection && selectedFamily !== null && selectedInstrument !== null,
    });

    if (overviewQuery.isPending || instrumentsQuery.isPending) {
        return (
            <RouteState
                kind="loading"
                title="正在載入市場總覽"
                message="正在讀取標的登錄與本機資料快取。"
            />
        );
    }
    if (overviewQuery.isError || instrumentsQuery.isError) {
        return (
            <RouteState
                kind="error"
                title="無法載入市場總覽"
                message="請檢查 API 與資料健康度後重試。"
                actionLabel="重新讀取市場總覽"
                onAction={() => {
                    void overviewQuery.refetch();
                    void instrumentsQuery.refetch();
                }}
            />
        );
    }

    const overview = overviewQuery.data;
    if (overview.instrument_count === 0 || cards.length === 0) {
        return (
            <section className="page">
                <PageHeading />
                <RouteState
                    kind="empty"
                    title="尚無市場總覽資料"
                    message="先到資料健康度確認快取，再開始研究。"
                />
            </section>
        );
    }

    const chartModel =
        seriesQuery.data === undefined
            ? null
            : filterChartModel(
                  toChartModel(seriesQuery.data),
                  startMode,
                  customStart,
                  customEnd,
              );
    const currentPoint = chartModel?.actual.points.at(-1);
    const prototypePoints = chartModel?.prototype.points ?? [];
    const prototypeAth = prototypePoints.reduce(
        (highest, point) => Math.max(highest, point.close),
        Number.NEGATIVE_INFINITY,
    );
    const prototypeLast = prototypePoints.at(-1)?.close ?? null;
    const athDistance =
        prototypeLast === null || !Number.isFinite(prototypeAth) || prototypeAth === 0
            ? null
            : prototypeLast / prototypeAth - 1;

    return (
        <section className="page market-overview">
            <PageHeading />
            <div className="metric-strip" aria-label="研究資料摘要">
                <article className="metric-card">
                    <span>登錄標的</span>
                    <strong>{overview.instrument_count}</strong>
                    <small>正向 1×—3×</small>
                </article>
                <article className="metric-card">
                    <span>資料序列</span>
                    <strong>{overview.cached_symbols.length}</strong>
                    <small>含原型與代理序列</small>
                </article>
                <article className="metric-card">
                    <span>正式結果</span>
                    <strong>{overview.formal_result_count}</strong>
                    <small>可追溯紀錄</small>
                </article>
            </div>
            <section className="family-register" aria-labelledby="families">
                <div className="section-heading">
                    <div>
                        <p className="eyebrow">Instrument register</p>
                        <h2 id="families">研究家族</h2>
                    </div>
                    <span>{cards.length} 個家族</span>
                </div>
                <div className="family-register__grid">
                    {cards.map((card) => {
                        const primary = card.instruments[0];
                        if (primary === undefined) {
                            return null;
                        }
                        return (
                            <Link
                                key={card.id}
                                className={`family-register__item ${
                                    selectedFamily?.id === card.id ? "is-selected" : ""
                                }`}
                                to={`/?family=${card.id}&instrument=${encodeURIComponent(primary.symbol)}`}
                                aria-label={`${card.name} ${primary.symbol}`}
                            >
                                <strong>{card.name}</strong>
                                <span>
                                    {card.instruments.map((instrument) => instrument.symbol).join(" · ")}
                                </span>
                                <small>點擊查看實體 K 線</small>
                            </Link>
                        );
                    })}
                </div>
            </section>

            {hasSelection && selectedFamily !== null && selectedInstrument !== null ? (
                <section className="overview-chart-panel" aria-labelledby="selected-instrument-chart">
                    <div className="section-heading section-heading--chart">
                        <div>
                            <p className="eyebrow">Selected instrument</p>
                            <h2 id="selected-instrument-chart">
                                {selectedInstrument.symbol} 走勢
                            </h2>
                            <p>{selectedInstrument.name} · 原型 {selectedInstrument.prototype_symbol}</p>
                        </div>
                        {seriesQuery.isPending ? <span>載入 K 線…</span> : null}
                    </div>
                    {seriesQuery.isError ? (
                        <div className="inline-alert" role="alert">
                            <strong>無法載入走勢</strong>
                            <span>請確認該標的已完成資料快取。</span>
                        </div>
                    ) : chartModel === null ? null : (
                        <>
                            <div className="overview-chart-controls" role="group" aria-label="圖表日期設定">
                                <label>
                                    <span>起始模式</span>
                                    <select
                                        aria-label="圖表起始模式"
                                        value={startMode}
                                        onChange={(event) =>
                                            updateChartQuery(
                                                event.currentTarget.value as StartMode,
                                                customStart,
                                                customEnd,
                                            )
                                        }
                                    >
                                        <option value="inception">ETF 發行日</option>
                                        <option value="index-earliest">指數最早</option>
                                        <option value="custom">自訂日期</option>
                                    </select>
                                </label>
                                <label>
                                    <span>開始日期</span>
                                    <input
                                        type="date"
                                        value={customStart}
                                        disabled={startMode !== "custom"}
                                        onChange={(event) =>
                                            updateChartQuery(
                                                "custom",
                                                event.currentTarget.value,
                                                customEnd,
                                            )
                                        }
                                    />
                                </label>
                                <label>
                                    <span>結束日期</span>
                                    <input
                                        type="date"
                                        value={customEnd}
                                        disabled={startMode !== "custom"}
                                        onChange={(event) =>
                                            updateChartQuery(
                                                "custom",
                                                customStart,
                                                event.currentTarget.value,
                                            )
                                        }
                                    />
                                </label>
                                <div className="overview-chart-stats" aria-label="即時價格摘要">
                                    <span>目前 ETF 價格 <strong>{currentPoint === undefined ? "—" : currency(currentPoint.close, seriesQuery.data?.actual.currency ?? null)}</strong></span>
                                    <span>原型指數 ATH 距離 <strong>{athDistance === null ? "—" : percent(athDistance)}</strong></span>
                                    {seriesQuery.data?.model_assumptions === null ||
                                    seriesQuery.data?.model_assumptions === undefined ? null : (
                                        <span>
                                            模擬成本 <strong>
                                                管理費 {percent(seriesQuery.data.model_assumptions.annual_management_fee)} · 日拖累 {percent(
                                                    seriesQuery.data.model_assumptions.daily_financing_drag +
                                                    seriesQuery.data.model_assumptions.daily_roll_drag +
                                                    seriesQuery.data.model_assumptions.daily_transaction_drag,
                                                )}
                                            </strong>
                                        </span>
                                    )}
                                </div>
                            </div>
                            <ResearchChart model={chartModel} height={680} />
                        </>
                    )}
                </section>
            ) : null}
        </section>
    );
}

function PageHeading() {
    return (
        <header className="page-heading page-heading--split">
            <div>
                <p className="eyebrow">Market ledger · Overview</p>
                <h1>市場總覽</h1>
            </div>
            <p className="page-heading__summary">
                先選擇研究家族與標的，直接檢視同尺度的 ETF、原型指數與模擬走勢。
            </p>
        </header>
    );
}
