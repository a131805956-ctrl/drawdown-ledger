export interface ChartDatum {
    session: string;
    close: number;
    totalReturnClose: number;
    drawdown: number;
}

export type SeriesMode =
    | "price"
    | "total-return"
    | "normalized-price"
    | "normalized-total-return";

export interface SeriesValue {
    time: string;
    value: number;
}

export interface DepthBand {
    threshold: number;
    top: number;
    bottom: number;
    label: string;
    tone: "shallow" | "watch" | "action" | "severe";
}

export interface ChartMeasurement {
    start: string;
    end: string;
    calendarDays: number;
    tradingSessions: number;
    priceReturn: number;
    totalReturn: number;
    drawdownDelta: number;
}

export interface TradeMarkerInput {
    date: string;
    signalDate: string;
    threshold: string | number | null;
    cashSpent: string | number;
    prototypeDrawdown: string | number | null;
    targetDrawdown: string | number | null;
    postTradeCash: string | number;
    markerProfitLoss: string | number;
    kind: "buy" | "reinvest" | "dca" | "buy-and-hold";
    currency: string;
}

export interface TradeMarkerModel {
    time: string;
    signalDate: string;
    title: string;
    detail: string;
    tone: "signal" | "cash";
}

function finiteNumber(value: string | number, label: string): number {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
        throw new Error(`${label} must be a finite number`);
    }
    return parsed;
}

function rounded(value: number): number {
    return Number(value.toFixed(12));
}

function percent(value: string | number | null): string {
    if (value === null) {
        return "—";
    }
    return new Intl.NumberFormat("zh-TW", {
        style: "percent",
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
    }).format(finiteNumber(value, "percentage"));
}

function currency(value: string | number, code: string): string {
    return new Intl.NumberFormat("zh-TW", {
        style: "currency",
        currency: code,
        maximumFractionDigits: 0,
    }).format(finiteNumber(value, "currency value"));
}

export function createDepthBands(depths: readonly number[]): DepthBand[] {
    const ordered = [...new Set(depths)]
        .map((depth) => Math.abs(depth))
        .filter((depth) => Number.isFinite(depth) && depth > 0 && depth <= 1)
        .sort((left, right) => left - right);
    let previous = 0;
    return ordered.map((depth, index) => {
        const threshold = -depth;
        const band: DepthBand = {
            threshold,
            top: previous === 0 ? 0 : -previous,
            bottom: threshold,
            label: new Intl.NumberFormat("zh-TW", {
                style: "percent",
                maximumFractionDigits: 0,
            }).format(threshold),
            tone:
                index === 0
                    ? "shallow"
                    : index === 1
                      ? "watch"
                      : index === 2
                        ? "action"
                        : "severe",
        };
        previous = depth;
        return band;
    });
}

export function seriesValues(
    points: readonly ChartDatum[],
    mode: SeriesMode,
): SeriesValue[] {
    if (points.length === 0) {
        return [];
    }
    const source =
        mode === "total-return" || mode === "normalized-total-return"
            ? "totalReturnClose"
            : "close";
    const normalize = mode.startsWith("normalized-");
    const first = points[0];
    if (first === undefined) {
        return [];
    }
    const baseline = first[source];
    if (!Number.isFinite(baseline) || baseline <= 0) {
        throw new Error("The selected chart baseline must be positive");
    }

    return points.map((point) => ({
        time: point.session,
        value: rounded(
            normalize ? (point[source] / baseline) * 100 : point[source],
        ),
    }));
}

export function measureChartRange(
    points: readonly ChartDatum[],
    firstSession: string,
    secondSession: string,
): ChartMeasurement {
    const firstIndex = points.findIndex(
        (point) => point.session === firstSession,
    );
    const secondIndex = points.findIndex(
        (point) => point.session === secondSession,
    );
    if (firstIndex < 0 || secondIndex < 0) {
        throw new Error("Both measurement sessions must exist in the series");
    }
    const startIndex = Math.min(firstIndex, secondIndex);
    const endIndex = Math.max(firstIndex, secondIndex);
    const start = points[startIndex];
    const end = points[endIndex];
    if (start === undefined || end === undefined) {
        throw new Error("Measurement range is outside the chart series");
    }
    if (
        start.close <= 0 ||
        start.totalReturnClose <= 0 ||
        !Number.isFinite(start.close) ||
        !Number.isFinite(start.totalReturnClose)
    ) {
        throw new Error("Measurement baselines must be positive");
    }
    const calendarMilliseconds =
        Date.parse(`${end.session}T00:00:00Z`) -
        Date.parse(`${start.session}T00:00:00Z`);

    return {
        start: start.session,
        end: end.session,
        calendarDays: Math.round(calendarMilliseconds / 86_400_000),
        tradingSessions: endIndex - startIndex,
        priceReturn: rounded(end.close / start.close - 1),
        totalReturn: rounded(
            end.totalReturnClose / start.totalReturnClose - 1,
        ),
        drawdownDelta: rounded(end.drawdown - start.drawdown),
    };
}

export function createTradeMarker(
    trade: TradeMarkerInput,
): TradeMarkerModel {
    const threshold =
        trade.threshold === null
            ? null
            : finiteNumber(trade.threshold, "threshold");
    const kindLabel =
        trade.kind === "reinvest"
            ? "股息再投入"
            : trade.kind === "dca"
              ? "定期投入"
              : trade.kind === "buy-and-hold"
                ? "基準買進"
                : "加碼";
    const title =
        threshold === null
            ? kindLabel
            : `${new Intl.NumberFormat("zh-TW", {
                  style: "percent",
                  maximumFractionDigits: 0,
              }).format(-Math.abs(threshold))} ${kindLabel}`;

    return {
        time: trade.date,
        signalDate: trade.signalDate,
        title,
        detail: [
            `原型 ${percent(trade.prototypeDrawdown)}`,
            `標的 ${percent(trade.targetDrawdown)}`,
            `投入 ${currency(trade.cashSpent, trade.currency)}`,
            `現金 ${currency(trade.postTradeCash, trade.currency)}`,
            `損益 ${currency(trade.markerProfitLoss, trade.currency)}`,
        ].join("｜"),
        tone: trade.kind === "reinvest" ? "cash" : "signal",
    };
}
