import {
    createDepthBands,
    createTradeMarker,
    measureChartRange,
    seriesValues,
    type ChartDatum,
} from "../src/features/chart/chartModel";

const points: ChartDatum[] = [
    {
        session: "2020-02-19",
        close: 100,
        totalReturnClose: 200,
        drawdown: 0,
    },
    {
        session: "2020-02-20",
        close: 80,
        totalReturnClose: 164,
        drawdown: -0.2,
    },
    {
        session: "2020-02-24",
        close: 90,
        totalReturnClose: 190,
        drawdown: -0.1,
    },
];

describe("research chart model", () => {
    it("builds ordered, non-overlapping drawdown depth bands", () => {
        expect(createDepthBands([0.3, 0.1, 0.2])).toEqual([
            expect.objectContaining({
                threshold: -0.1,
                top: 0,
                bottom: -0.1,
                label: "-10%",
            }),
            expect.objectContaining({
                threshold: -0.2,
                top: -0.1,
                bottom: -0.2,
                label: "-20%",
            }),
            expect.objectContaining({
                threshold: -0.3,
                top: -0.2,
                bottom: -0.3,
                label: "-30%",
            }),
        ]);
    });

    it("rebases the selected price or total-return window to 100", () => {
        expect(seriesValues(points, "normalized-price")).toEqual([
            { time: "2020-02-19", value: 100 },
            { time: "2020-02-20", value: 80 },
            { time: "2020-02-24", value: 90 },
        ]);
        expect(seriesValues(points, "normalized-total-return")).toEqual([
            { time: "2020-02-19", value: 100 },
            { time: "2020-02-20", value: 82 },
            { time: "2020-02-24", value: 95 },
        ]);
    });

    it("measures calendar time, trading sessions, both returns, and drawdown", () => {
        expect(
            measureChartRange(points, "2020-02-19", "2020-02-24"),
        ).toEqual({
            start: "2020-02-19",
            end: "2020-02-24",
            calendarDays: 5,
            tradingSessions: 2,
            priceReturn: -0.1,
            totalReturn: -0.05,
            drawdownDelta: -0.1,
        });
    });

    it("formats a complete, reproducible trade marker", () => {
        const marker = createTradeMarker({
            date: "2020-03-24",
            signalDate: "2020-03-23",
            threshold: "0.30",
            cashSpent: "2500",
            prototypeDrawdown: "-0.315",
            targetDrawdown: "-0.562",
            postTradeCash: "4200",
            markerProfitLoss: "-380",
            kind: "buy",
            currency: "USD",
        });

        expect(marker.title).toBe("-30% 加碼");
        expect(marker.detail).toContain("原型 -31.5%");
        expect(marker.detail).toContain("標的 -56.2%");
        expect(marker.detail).toContain("投入 US$2,500");
        expect(marker.detail).toContain("現金 US$4,200");
        expect(marker.detail).toContain("損益 -US$380");
        expect(marker.time).toBe("2020-03-24");
    });
});
