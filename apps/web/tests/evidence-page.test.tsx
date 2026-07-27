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
    EvidenceAnalyzeResponse,
    MarketSeriesResponse,
} from "../src/lib/contracts";

const evidence: EvidenceAnalyzeResponse = {
    schema_version: "1.0",
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
    n_day: 126,
    n_episode: 10,
    n_executed_episode: 10,
    daily_statistics: [
        {
            horizon_sessions: 252,
            independent: false,
            mean_total_return: 0.42,
            median_total_return: 0.35,
            win_rate: 0.8,
            expected_shortfall_5: -0.31,
            confidence_lower: 0.49,
            confidence_upper: 0.94,
            n: 126,
            overlap_warning: "overlapping observations",
            sample_kind: "daily",
        },
    ],
    episode_statistics: [
        {
            horizon_sessions: 252,
            independent: true,
            mean_total_return: 0.38,
            median_total_return: 0.3,
            win_rate: 0.8,
            expected_shortfall_5: -0.28,
            confidence_lower: 0.49,
            confidence_upper: 0.94,
            n: 10,
            overlap_warning: null,
            sample_kind: "episode",
        },
    ],
    episodes: [
        {
            cycle_id: 1,
            threshold: 0.3,
            peak_date: "2020-02-19",
            peak_price: 100,
            signal_date: "2020-03-16",
            signal_price: 69,
            signal_drawdown: -0.31,
            entry_date: "2020-03-17",
            entry_price: "70",
            recovery_date: "2020-08-06",
            recovery_sessions: 99,
            mae: -0.18,
            mfe: 0.65,
            v_recovered: true,
            forward_returns: [
                {
                    horizon_sessions: 252,
                    exit_date: "2021-03-17",
                    total_return: 0.52,
                },
            ],
        },
    ],
};

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
                session: "2020-02-19",
                open: 100,
                high: 101,
                low: 99,
                close: 100,
                total_return_close: 100,
                normalized_total_return: 100,
                drawdown: 0,
            },
            {
                session: "2020-03-16",
                open: 70,
                high: 72,
                low: 68,
                close: 69,
                total_return_close: 69,
                normalized_total_return: 69,
                drawdown: -0.31,
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
                session: "2020-02-19",
                open: 100,
                high: 101,
                low: 99,
                close: 100,
                total_return_close: 100,
                normalized_total_return: 100,
                drawdown: 0,
            },
            {
                session: "2020-03-16",
                open: 46,
                high: 48,
                low: 44,
                close: 45,
                total_return_close: 45,
                normalized_total_return: 45,
                drawdown: -0.55,
            },
        ],
    },
    synthetic: null,
};

function researchApi() {
    const api = createStaticResearchApi({
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
            cached_symbols: ["TQQQ", "^NDX"],
            formal_result_count: 0,
        },
        health: {
            schema_version: "1.0",
            status: "incomplete",
            coverage: [],
        },
        evidence,
        marketSeries,
    });
    return {
        ...api,
        analyzeEvidence: vi.fn(api.analyzeEvidence),
        getMarketSeries: vi.fn(api.getMarketSeries),
    };
}

describe("historical evidence workbench", () => {
    it("derives the prototype from the selected target and keeps it read-only", async () => {
        render(
            <MemoryRouter initialEntries={["/evidence"]}>
                <App api={researchApi()} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        expect(await screen.findByText("原型指數 ^NDX")).toBeVisible();
        expect(
            screen.queryByRole("combobox", { name: "原型指數" }),
        ).not.toBeInTheDocument();
    });

    it("separates overlapping days from independent episodes and states the actionable result", async () => {
        const user = userEvent.setup();
        const api = researchApi();
        render(
            <MemoryRouter initialEntries={["/evidence"]}>
                <App api={api} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        await user.click(
            await screen.findByRole("button", { name: "分析歷史回撤" }),
        );

        expect(await screen.findByText("126", { selector: "strong" })).toBeVisible();
        expect(screen.getByText("10", { selector: "strong" })).toBeVisible();
        expect(
            screen.getByRole("note", { name: "核心歷史結論" }),
        ).toHaveTextContent(
            "如果原型指數從前高回撤 30% 後於次一交易日買進",
        );
        expect(
            screen.getByRole("note", { name: "核心歷史結論" }),
        ).toHaveTextContent("10 次獨立歷史事件");
        expect(screen.getByText(/2 次在一年後仍未獲利/)).toBeVisible();
        expect(
            screen.getByRole("group", { name: "分析資料來源" }),
        ).toHaveTextContent("基準指數 ^NDX");
        expect(screen.getByRole("table", { name: "獨立回撤事件" })).toBeVisible();
        expect(api.analyzeEvidence).toHaveBeenCalledWith(
            expect.objectContaining({
                family_id: "nasdaq-100",
                target_symbol: "TQQQ",
                threshold: 0.3,
            }),
        );
    });

    it("shows the API detail when trusted market data is missing", async () => {
        const user = userEvent.setup();
        const api = researchApi();
        api.analyzeEvidence.mockRejectedValue(
            new ResearchApiError(
                "Request failed with status 404",
                404,
                "Trusted cache is missing prototype series: ^NDX, QQQ",
            ),
        );
        render(
            <MemoryRouter initialEntries={["/evidence"]}>
                <App api={api} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        await user.click(
            await screen.findByRole("button", { name: "分析歷史回撤" }),
        );

        expect(
            await screen.findByText(
                "Trusted cache is missing prototype series: ^NDX, QQQ",
            ),
        ).toBeVisible();
    });
});
