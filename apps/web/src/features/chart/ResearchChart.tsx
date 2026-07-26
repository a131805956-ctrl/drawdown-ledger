import {
    AreaSeries,
    ColorType,
    createChart,
    createSeriesMarkers,
    CrosshairMode,
    LineSeries,
    LineStyle,
    PriceScaleMode,
    type Time,
} from "lightweight-charts";
import {
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import { DepthBands } from "./DepthBands";
import {
    aggregateChartPoints,
    measureChartRange,
    seriesValues,
    type ChartAggregation,
    type ChartDatum,
    type ChartMeasurement,
    type SeriesMode,
    type TradeMarkerInput,
} from "./chartModel";
import { tradeMarkerSet } from "./TradeMarkers";

export interface ResearchSeriesModel {
    symbol: string;
    sourceKind: "actual" | "synthetic";
    points: ChartDatum[];
}

export interface PortfolioDatum {
    date: string;
    value: number;
    cash: number;
}

export interface ResearchChartModel {
    prototype: ResearchSeriesModel;
    actual: ResearchSeriesModel;
    synthetic?: ResearchSeriesModel | null;
    portfolio?: PortfolioDatum[];
    trades?: TradeMarkerInput[];
}

type DateRange = "1y" | "3y" | "5y" | "all";
type ScaleMode = "linear" | "log";
type MeasurementSeriesKey = "prototype" | "actual" | "synthetic";

interface MeasurementSeriesOption {
    key: MeasurementSeriesKey;
    label: string;
    points: ChartDatum[];
    renderedPoints: ChartDatum[];
}

interface ResearchChartProps {
    model: ResearchChartModel;
    height?: number;
}

function timeKey(value: Time | undefined): string | null {
    if (value === undefined) {
        return null;
    }
    if (typeof value === "string") {
        return value;
    }
    if (typeof value === "number") {
        return new Date(value * 1000).toISOString().slice(0, 10);
    }
    return [
        String(value.year).padStart(4, "0"),
        String(value.month).padStart(2, "0"),
        String(value.day).padStart(2, "0"),
    ].join("-");
}

function cutoffForRange(
    points: readonly ChartDatum[],
    range: DateRange,
): string | null {
    if (range === "all") {
        return null;
    }
    const finalPoint = points.at(-1);
    if (finalPoint === undefined) {
        return null;
    }
    const years = range === "1y" ? 1 : range === "3y" ? 3 : 5;
    const cutoff = new Date(`${finalPoint.session}T00:00:00Z`);
    cutoff.setUTCFullYear(cutoff.getUTCFullYear() - years);
    return cutoff.toISOString().slice(0, 10);
}

function selectedPoints(
    points: readonly ChartDatum[],
    cutoff: string | null,
): ChartDatum[] {
    return cutoff === null
        ? [...points]
        : points.filter((point) => point.session >= cutoff);
}

function formatPercent(value: number): string {
    return new Intl.NumberFormat("zh-TW", {
        style: "percent",
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
    }).format(value);
}

function MeasurementReadout({
    measurement,
    seriesLabel,
}: {
    measurement: ChartMeasurement | null;
    seriesLabel: string | null;
}) {
    if (measurement === null) {
        return (
            <p className="chart-measurement chart-measurement--empty">
                可點線圖或使用日期欄位選兩個交易日，比較價格、總報酬與回撤。
            </p>
        );
    }
    return (
        <dl
            className="chart-measurement"
            role="group"
            aria-label={`${seriesLabel ?? "所選序列"} 兩點量測結果`}
        >
            <div>
                <dt>期間</dt>
                <dd>
                    {measurement.calendarDays} 日／
                    {measurement.tradingSessions} 交易日
                </dd>
            </div>
            <div>
                <dt>價格</dt>
                <dd>{formatPercent(measurement.priceReturn)}</dd>
            </div>
            <div>
                <dt>總報酬</dt>
                <dd>{formatPercent(measurement.totalReturn)}</dd>
            </div>
            <div>
                <dt>回撤差</dt>
                <dd>{formatPercent(measurement.drawdownDelta)}</dd>
            </div>
        </dl>
    );
}

export function ResearchChart({
    model,
    height = model.portfolio === undefined ? 560 : 680,
}: ResearchChartProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [seriesMode, setSeriesMode] =
        useState<SeriesMode>("normalized-total-return");
    const [scaleMode, setScaleMode] = useState<ScaleMode>("linear");
    const [dateRange, setDateRange] = useState<DateRange>("all");
    const [aggregation, setAggregation] =
        useState<ChartAggregation>("daily");
    const [showPrototype, setShowPrototype] = useState(true);
    const [showActual, setShowActual] = useState(true);
    const [showSynthetic, setShowSynthetic] = useState(
        model.synthetic !== undefined && model.synthetic !== null,
    );
    const [measurementSeries, setMeasurementSeries] =
        useState<MeasurementSeriesKey>("prototype");
    const [measurementSessions, setMeasurementSessions] = useState<string[]>(
        [],
    );

    const cutoff = useMemo(
        () => cutoffForRange(model.prototype.points, dateRange),
        [dateRange, model.prototype.points],
    );
    const prototypePoints = useMemo(
        () => selectedPoints(model.prototype.points, cutoff),
        [cutoff, model.prototype.points],
    );
    const actualPoints = useMemo(
        () => selectedPoints(model.actual.points, cutoff),
        [cutoff, model.actual.points],
    );
    const syntheticPoints = useMemo(
        () =>
            model.synthetic === undefined || model.synthetic === null
                ? []
                : selectedPoints(model.synthetic.points, cutoff),
        [cutoff, model.synthetic],
    );
    const renderedPrototypePoints = useMemo(
        () => aggregateChartPoints(prototypePoints, aggregation),
        [aggregation, prototypePoints],
    );
    const renderedActualPoints = useMemo(
        () => aggregateChartPoints(actualPoints, aggregation),
        [actualPoints, aggregation],
    );
    const renderedSyntheticPoints = useMemo(
        () => aggregateChartPoints(syntheticPoints, aggregation),
        [aggregation, syntheticPoints],
    );
    const measurementOptions = useMemo(() => {
        const options: MeasurementSeriesOption[] = [];
        if (showPrototype) {
            options.push({
                key: "prototype",
                label: `原型 ${model.prototype.symbol}`,
                points: prototypePoints,
                renderedPoints: renderedPrototypePoints,
            });
        }
        if (showActual) {
            options.push({
                key: "actual",
                label: `實際 ${model.actual.symbol}`,
                points: actualPoints,
                renderedPoints: renderedActualPoints,
            });
        }
        if (
            showSynthetic &&
            model.synthetic !== undefined &&
            model.synthetic !== null
        ) {
            options.push({
                key: "synthetic",
                label: `合成 ${model.synthetic.symbol}`,
                points: syntheticPoints,
                renderedPoints: renderedSyntheticPoints,
            });
        }
        return options;
    }, [
        actualPoints,
        model.actual.symbol,
        model.prototype.symbol,
        model.synthetic,
        prototypePoints,
        renderedActualPoints,
        renderedPrototypePoints,
        renderedSyntheticPoints,
        showActual,
        showPrototype,
        showSynthetic,
        syntheticPoints,
    ]);
    const selectedMeasurementOption =
        measurementOptions.find(
            (option) => option.key === measurementSeries,
        ) ??
        measurementOptions[0] ??
        null;
    const measurement = useMemo(() => {
        const first = measurementSessions[0];
        const second = measurementSessions[1];
        if (
            first === undefined ||
            second === undefined ||
            selectedMeasurementOption === null
        ) {
            return null;
        }
        try {
            return measureChartRange(
                selectedMeasurementOption.points,
                first,
                second,
            );
        } catch {
            return null;
        }
    }, [measurementSessions, selectedMeasurementOption]);

    const updateSeriesVisibility = (
        key: MeasurementSeriesKey,
        visible: boolean,
    ) => {
        if (key === "prototype") {
            setShowPrototype(visible);
        } else if (key === "actual") {
            setShowActual(visible);
        } else {
            setShowSynthetic(visible);
        }
        if (!visible && selectedMeasurementOption?.key === key) {
            const fallback = measurementOptions.find(
                (option) => option.key !== key,
            );
            if (fallback !== undefined) {
                setMeasurementSeries(fallback.key);
            }
            setMeasurementSessions([]);
        }
    };

    useEffect(() => {
        const container = containerRef.current;
        if (
            container === null ||
            renderedPrototypePoints.length === 0 ||
            typeof globalThis.ResizeObserver === "undefined"
        ) {
            return;
        }
        const chart = createChart(container, {
            width: container.clientWidth,
            height,
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#B7C4D4",
                attributionLogo: true,
            },
            grid: {
                vertLines: { color: "rgba(183, 196, 212, 0.08)" },
                horzLines: { color: "rgba(183, 196, 212, 0.08)" },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: {
                    color: "rgba(237, 241, 245, 0.55)",
                    labelBackgroundColor: "#3F72DF",
                },
                horzLine: {
                    color: "rgba(237, 241, 245, 0.28)",
                    labelBackgroundColor: "#17263C",
                },
            },
            rightPriceScale: {
                borderColor: "rgba(183, 196, 212, 0.22)",
            },
            timeScale: {
                borderColor: "rgba(183, 196, 212, 0.22)",
                timeVisible: false,
                rightOffset: 2,
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: false,
            },
        });

        const prototypeSeries = chart.addSeries(
            LineSeries,
            {
                color: "#A9B8CB",
                lineWidth: 2,
                title: model.prototype.symbol,
                visible: showPrototype,
                priceLineVisible: false,
            },
            0,
        );
        const actualSeries = chart.addSeries(
            LineSeries,
            {
                color: "#3F72DF",
                lineWidth: 3,
                title: model.actual.symbol,
                visible: showActual,
                priceLineVisible: false,
            },
            0,
        );
        const syntheticSeries =
            model.synthetic === undefined || model.synthetic === null
                ? null
                : chart.addSeries(
                      LineSeries,
                      {
                          color: "#ED6859",
                          lineWidth: 2,
                          lineStyle: LineStyle.Dashed,
                          title: `${model.synthetic.symbol}（合成）`,
                          visible: showSynthetic,
                          priceLineVisible: false,
                      },
                      0,
                  );
        const underwaterSeries = chart.addSeries(
            AreaSeries,
            {
                title: "原型回撤",
                lineColor: "#ED6859",
                topColor: "rgba(237, 104, 89, 0.38)",
                bottomColor: "rgba(237, 104, 89, 0.03)",
                priceLineVisible: false,
                autoscaleInfoProvider: () => ({
                    priceRange: { minValue: -0.6, maxValue: 0 },
                }),
            },
            1,
        );
        prototypeSeries.setData(
            seriesValues(renderedPrototypePoints, seriesMode),
        );
        actualSeries.setData(seriesValues(renderedActualPoints, seriesMode));
        syntheticSeries?.setData(
            seriesValues(renderedSyntheticPoints, seriesMode),
        );
        underwaterSeries.setData(
            renderedPrototypePoints.map((point) => ({
                time: point.session,
                value: point.drawdown,
            })),
        );

        if (model.trades !== undefined && model.trades.length > 0) {
            createSeriesMarkers(
                actualSeries,
                tradeMarkerSet(model.trades).markers,
                { autoScale: false },
            );
        }

        if (model.portfolio !== undefined && model.portfolio.length > 0) {
            const valueSeries = chart.addSeries(
                LineSeries,
                {
                    title: "策略資產",
                    color: "#EDF1F5",
                    lineWidth: 2,
                    priceLineVisible: false,
                },
                2,
            );
            const cashSeries = chart.addSeries(
                AreaSeries,
                {
                    title: "現金庫",
                    lineColor: "#2D9D8F",
                    topColor: "rgba(45, 157, 143, 0.34)",
                    bottomColor: "rgba(45, 157, 143, 0.02)",
                    priceLineVisible: false,
                },
                2,
            );
            valueSeries.setData(
                model.portfolio.map((point) => ({
                    time: point.date,
                    value: point.value,
                })),
            );
            cashSeries.setData(
                model.portfolio.map((point) => ({
                    time: point.date,
                    value: point.cash,
                })),
            );
        }

        chart.priceScale("right", 0).applyOptions({
            mode:
                scaleMode === "log"
                    ? PriceScaleMode.Logarithmic
                    : PriceScaleMode.Normal,
        });
        const panes = chart.panes();
        panes[0]?.setStretchFactor(model.portfolio === undefined ? 4 : 5);
        panes[1]?.setStretchFactor(2);
        panes[2]?.setStretchFactor(2);
        chart.timeScale().fitContent();

        const clickHandler = (parameter: { time?: Time }) => {
            const session = timeKey(parameter.time);
            if (
                session === null ||
                selectedMeasurementOption === null ||
                !selectedMeasurementOption.renderedPoints.some(
                    (point) => point.session === session,
                )
            ) {
                return;
            }
            setMeasurementSessions((current) =>
                current.length >= 2
                    ? [session]
                    : [...current, session],
            );
        };
        chart.subscribeClick(clickHandler);
        const observer = new globalThis.ResizeObserver((entries) => {
            const width = entries[0]?.contentRect.width;
            if (width !== undefined && width > 0) {
                chart.resize(width, height);
            }
        });
        observer.observe(container);

        return () => {
            observer.disconnect();
            chart.unsubscribeClick(clickHandler);
            chart.remove();
        };
    }, [
        actualPoints,
        height,
        model.actual.symbol,
        model.portfolio,
        model.prototype.symbol,
        model.synthetic,
        model.trades,
        renderedActualPoints,
        renderedPrototypePoints,
        renderedSyntheticPoints,
        scaleMode,
        selectedMeasurementOption,
        seriesMode,
        showActual,
        showPrototype,
        showSynthetic,
    ]);

    return (
        <section className="research-chart" aria-label="同步研究線圖">
            <div className="chart-toolbar">
                <fieldset>
                    <legend>資料</legend>
                    {(
                        [
                            ["price", "價格"],
                            ["total-return", "總報酬"],
                            ["normalized-total-return", "起點 100"],
                        ] as const
                    ).map(([value, label]) => (
                        <button
                            key={value}
                            type="button"
                            className={seriesMode === value ? "is-active" : ""}
                            aria-pressed={seriesMode === value}
                            onClick={() => setSeriesMode(value)}
                        >
                            {label}
                        </button>
                    ))}
                </fieldset>
                <fieldset>
                    <legend>尺度</legend>
                    {(
                        [
                            ["linear", "線性"],
                            ["log", "對數"],
                        ] as const
                    ).map(([value, label]) => (
                        <button
                            key={value}
                            type="button"
                            className={scaleMode === value ? "is-active" : ""}
                            aria-pressed={scaleMode === value}
                            onClick={() => setScaleMode(value)}
                        >
                            {label}
                        </button>
                    ))}
                </fieldset>
                <fieldset>
                    <legend>期間</legend>
                    {(
                        [
                            ["1y", "1 年"],
                            ["3y", "3 年"],
                            ["5y", "5 年"],
                            ["all", "全部"],
                        ] as const
                    ).map(([value, label]) => (
                        <button
                            key={value}
                            type="button"
                            className={dateRange === value ? "is-active" : ""}
                            aria-pressed={dateRange === value}
                            onClick={() => {
                                setDateRange(value);
                                setMeasurementSessions([]);
                            }}
                        >
                            {label}
                        </button>
                    ))}
                </fieldset>
                <fieldset>
                    <legend>顯示頻率</legend>
                    {(
                        [
                            ["daily", "日"],
                            ["weekly", "週"],
                            ["monthly", "月"],
                        ] as const
                    ).map(([value, label]) => (
                        <button
                            key={value}
                            type="button"
                            className={aggregation === value ? "is-active" : ""}
                            aria-pressed={aggregation === value}
                            onClick={() => {
                                setAggregation(value);
                                setMeasurementSessions([]);
                            }}
                        >
                            {label}
                        </button>
                    ))}
                </fieldset>
            </div>
            <div className="chart-series-toggle" aria-label="顯示序列">
                <label>
                    <input
                        type="checkbox"
                        checked={showPrototype}
                        onChange={(event) =>
                            updateSeriesVisibility(
                                "prototype",
                                event.currentTarget.checked,
                            )
                        }
                    />
                    原型 {model.prototype.symbol}
                </label>
                <label>
                    <input
                        type="checkbox"
                        checked={showActual}
                        onChange={(event) =>
                            updateSeriesVisibility(
                                "actual",
                                event.currentTarget.checked,
                            )
                        }
                    />
                    實際 {model.actual.symbol}
                </label>
                {model.synthetic === undefined ||
                model.synthetic === null ? null : (
                    <label>
                        <input
                            type="checkbox"
                            checked={showSynthetic}
                            onChange={(event) =>
                                updateSeriesVisibility(
                                    "synthetic",
                                    event.currentTarget.checked,
                                )
                            }
                        />
                        合成壓力序列
                    </label>
                )}
            </div>
            <div
                className="chart-measurement-controls"
                role="group"
                aria-label="兩點量測控制"
            >
                <label>
                    <span>量測序列</span>
                    <select
                        value={selectedMeasurementOption?.key ?? ""}
                        disabled={measurementOptions.length === 0}
                        onChange={(event) => {
                            setMeasurementSeries(
                                event.currentTarget
                                    .value as MeasurementSeriesKey,
                            );
                            setMeasurementSessions([]);
                        }}
                    >
                        {measurementOptions.map((option) => (
                            <option key={option.key} value={option.key}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </label>
                <label>
                    <span>量測起點</span>
                    <input
                        type="date"
                        min={
                            selectedMeasurementOption?.renderedPoints.at(0)
                                ?.session
                        }
                        max={
                            selectedMeasurementOption?.renderedPoints.at(-1)
                                ?.session
                        }
                        value={measurementSessions[0] ?? ""}
                        disabled={selectedMeasurementOption === null}
                        onChange={(event) => {
                            const session = event.currentTarget.value;
                            setMeasurementSessions((current) =>
                                session.length === 0
                                    ? []
                                    : current[1] === undefined
                                      ? [session]
                                      : [session, current[1]],
                            );
                        }}
                    />
                </label>
                <label>
                    <span>量測終點</span>
                    <input
                        type="date"
                        min={
                            selectedMeasurementOption?.renderedPoints.at(0)
                                ?.session
                        }
                        max={
                            selectedMeasurementOption?.renderedPoints.at(-1)
                                ?.session
                        }
                        value={measurementSessions[1] ?? ""}
                        disabled={measurementSessions[0] === undefined}
                        onChange={(event) => {
                            const session = event.currentTarget.value;
                            setMeasurementSessions((current) =>
                                session.length === 0
                                    ? current.slice(0, 1)
                                    : current[0] === undefined
                                      ? []
                                      : [current[0], session],
                            );
                        }}
                    />
                </label>
                <button
                    type="button"
                    disabled={measurementSessions.length === 0}
                    onClick={() => setMeasurementSessions([])}
                >
                    清除量測
                </button>
            </div>
            <div
                className={`chart-stage ${model.portfolio === undefined ? "chart-stage--two-pane" : "chart-stage--three-pane"}`}
                style={{ minHeight: `${String(height)}px` }}
            >
                <DepthBands />
                <div ref={containerRef} className="chart-canvas" />
            </div>
            <MeasurementReadout
                measurement={measurement}
                seriesLabel={selectedMeasurementOption?.label ?? null}
            />
        </section>
    );
}
