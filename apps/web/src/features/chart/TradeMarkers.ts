import type { SeriesMarker, Time } from "lightweight-charts";

import {
    createTradeMarker,
    type TradeMarkerInput,
    type TradeMarkerModel,
} from "./chartModel";

export interface TradeMarkerSet {
    labels: TradeMarkerModel[];
    markers: SeriesMarker<Time>[];
}

export function tradeMarkerSet(
    trades: readonly TradeMarkerInput[],
): TradeMarkerSet {
    const labels = trades.map(createTradeMarker);
    return {
        labels,
        markers: labels.map((marker) => ({
            time: marker.time,
            position: "belowBar",
            color: marker.tone === "cash" ? "#2D9D8F" : "#3F72DF",
            shape: "arrowUp",
            text: `${marker.title}｜${marker.detail}`,
        })),
    };
}
