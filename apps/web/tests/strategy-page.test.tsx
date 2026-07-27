import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { App } from "../src/app/App";
import {
    createStaticResearchApi,
    ResearchApiError,
} from "../src/lib/api";
import { MemoryRouter } from "../src/lib/router";
import type {
    MarketSeriesResponse,
    StrategyBacktestResponse,
} from "../src/lib/contracts";

const marketSeries: MarketSeriesResponse = {
    schema_version: "1.0",
    family_id: "nasdaq-100",
    target_symbol: "TQQQ",
    prototype_symbol: "^NDX",
    prototype_source: "benchmark",
    handoff_session: null,
    source_label: "trusted_local_cache",
    prototype: {
        symbol: "^NDX",
        leverage: 1,
        source_kind: "actual",
        unit: "index",
        currency: "USD",
        actual_last_session: "2026-06-30",
        policy_cutoff: "2026-06-30",
        points: [
            {
                session: "2020-01-02",
                open: 100,
                high: 101,
                low: 99,
                close: 100,
                total_return_close: 100,
                normalized_total_return: 100,
                drawdown: 0,
            },
            {
                session: "2020-03-17",
                open: 70,
                high: 72,
                low: 69,
                close: 71,
                total_return_close: 71,
                normalized_total_return: 71,
                drawdown: -0.29,
            },
            {
                session: "2026-06-30",
                open: 180,
                high: 182,
                low: 179,
                close: 181,
                total_return_close: 190,
                normalized_total_return: 190,
                drawdown: 0,
            },
        ],
    },
    actual: {
        symbol: "TQQQ",
        leverage: 3,
        source_kind: "actual",
        unit: "price",
        currency: "USD",
        actual_last_session: "2026-06-30",
        policy_cutoff: "2026-06-30",
        points: [
            {
                session: "2020-01-02",
                open: 50,
                high: 51,
                low: 49,
                close: 50,
                total_return_close: 50,
                normalized_total_return: 100,
                drawdown: 0,
            },
            {
                session: "2020-03-17",
                open: 20,
                high: 22,
                low: 19,
                close: 21,
                total_return_close: 21,
                normalized_total_return: 42,
                drawdown: -0.58,
            },
            {
                session: "2026-06-30",
                open: 130,
                high: 132,
                low: 129,
                close: 131,
                total_return_close: 145,
                normalized_total_return: 290,
                drawdown: 0,
            },
        ],
    },
    synthetic: null,
};

const strategyResult: StrategyBacktestResponse = {
    schema_version: "1.0",
    name: "現金庫門檻策略",
    family_id: "nasdaq-100",
    target_symbol: "TQQQ",
    prototype_symbol: "^NDX",
    prototype_source: "benchmark",
    prototype_actual_last_session: "2026-06-30",
    prototype_policy_cutoff: "2026-06-30",
    target_actual_last_session: "2026-06-30",
    target_policy_cutoff: "2026-06-30",
    source_kind: "actual",
    source_label: "trusted_local_cache",
    contribution_total: "80000",
    dividend_income: "3200",
    interest_income: "1700",
    ending_cash: "12400",
    ending_shares: "1180.25",
    total_fees: "86",
    trade_count: 1,
    missed_thresholds: [],
    pending_thresholds: ["0.30", "0.40"],
    metrics: {
        xirr: 0.124,
        twr: 0.91,
        max_drawdown: -0.48,
        expected_shortfall_5: -0.22,
        longest_underwater_days: 420,
        cash_depletion_date: null,
        deepest_tier_missed: null,
    },
    equity_curve: [
        {
            date: "2020-01-02",
            close: "50",
            shares: "0",
            cash: "10000",
            value: "10000",
            external_flow: "10000",
            net_contributions: "10000",
            profit_loss: "0",
        },
        {
            date: "2020-03-17",
            close: "21",
            shares: "250",
            cash: "5000",
            value: "10250",
            external_flow: "0",
            net_contributions: "10000",
            profit_loss: "250",
        },
    ],
    trades: [
        {
            date: "2020-03-17",
            signal_date: "2020-03-16",
            kind: "buy",
            threshold: "0.20",
            raw_price: "20",
            execution_price: "20",
            shares_bought: "250",
            cash_spent: "5000",
            fee: "0",
            post_trade_cash: "5000",
            prototype_drawdown: "-0.25",
            target_drawdown: "-0.58",
            marker_profit_loss: "250",
        },
    ],
};

function strategyApi() {
    const base = createStaticResearchApi({
        instruments: {
            schema_version: "1.0",
            instruments: [
                {
                    symbol: "TQQQ",
                    name: "ProShares UltraPro QQQ",
                    family_id: "nasdaq-100",
                    leverage: 3,
                    prototype_symbol: "^NDX",
                    currency: "USD",
                    timezone: "America/New_York",
                    inception: "2010-02-11",
                },
            ],
        },
        overview: {
            schema_version: "1.0",
            instrument_count: 1,
            cached_symbols: ["^NDX", "TQQQ"],
            formal_result_count: 0,
        },
        health: {
            schema_version: "1.0",
            status: "incomplete",
            coverage: [],
        },
    });
    return {
        ...base,
        backtestStrategy: vi.fn().mockResolvedValue(strategyResult),
        getMarketSeries: vi.fn().mockResolvedValue(marketSeries),
    };
}

describe("cash-pool strategy laboratory", () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it("uses the previous calendar month in Asia/Taipei at the local month boundary", () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date("2026-07-31T16:30:00.000Z"));

        render(
            <MemoryRouter initialEntries={["/strategy"]}>
                <App api={strategyApi()} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        expect(screen.getByLabelText("結束日")).toHaveValue("2026-07-31");
    });

    it("submits an executable no-sell ladder and renders cash, trades, and performance", async () => {
        const user = userEvent.setup();
        const api = strategyApi();
        render(
            <MemoryRouter initialEntries={["/strategy"]}>
                <App api={api} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        const monthly = await screen.findByLabelText("每月存入現金庫");
        await user.clear(monthly);
        await user.type(monthly, "1500");
        await user.click(
            screen.getByRole("button", { name: "執行現金庫回測" }),
        );

        expect(
            await screen.findByRole("heading", { name: "回測結果" }),
        ).toBeVisible();
        expect(screen.getByText("12.4%")).toBeVisible();
        expect(screen.getByText("12,400", { exact: false })).toBeVisible();
        expect(
            screen.getByRole("table", { name: "策略交易紀錄" }),
        ).toHaveTextContent("2020-03-17");
        expect(screen.getByText("持有規則：不賣出")).toBeVisible();
        expect(screen.getByText(/新高只重置門檻/)).toBeVisible();
        expect(api.backtestStrategy).toHaveBeenCalledWith(
            expect.objectContaining({
                family_id: "nasdaq-100",
                target_symbol: "TQQQ",
                monthly_contribution: "1500",
                dividend_policy: "cash",
                tiers: [
                    { depth: "0.20", cash_fraction: "0.25" },
                    { depth: "0.30", cash_fraction: "0.35" },
                    { depth: "0.40", cash_fraction: "0.40" },
                ],
            }),
        );
    });

    it("exposes starting investment and monthly allocation controls and maps starting investment to shares", async () => {
        const user = userEvent.setup();
        const api = strategyApi();
        render(
            <MemoryRouter initialEntries={["/strategy"]}>
                <App api={api} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        expect(screen.getByTestId("strategy-initial-investment")).toBeVisible();
        expect(screen.getByTestId("strategy-monthly-invest-percent")).toBeVisible();
        expect(screen.getByTestId("strategy-monthly-reserve-percent")).toBeVisible();
        await user.clear(screen.getByTestId("strategy-initial-investment"));
        await user.type(screen.getByTestId("strategy-initial-investment"), "2500");
        await user.click(screen.getByRole("button", { name: /執行現金庫回測/ }));

        expect(api.backtestStrategy).toHaveBeenCalledWith(
            expect.objectContaining({
                initial_cash: "10000",
                initial_shares: "50.00000000",
            }),
        );
    });

    it("shows validation detail returned by the research API", async () => {
        const user = userEvent.setup();
        const api = strategyApi();
        api.backtestStrategy.mockRejectedValue(
            new ResearchApiError(
                "Request failed with status 422",
                422,
                [
                    {
                        type: "date_from_datetime_parsing",
                        loc: ["body", "contribution_events", 0, "bonus", "month"],
                        msg: "Input should be a valid date",
                        input_json: "\"2020-06\"",
                    },
                ],
            ),
        );
        render(
            <MemoryRouter initialEntries={["/strategy"]}>
                <App api={api} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        await user.click(
            await screen.findByRole("button", {
                name: "執行現金庫回測",
            }),
        );

        expect(
            await screen.findByText(
                "body.contribution_events.0.bonus.month：Input should be a valid date",
            ),
        ).toBeVisible();
    });
});
