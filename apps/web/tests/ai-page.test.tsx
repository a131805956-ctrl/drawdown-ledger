import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { App } from "../src/app/App";
import { createStaticResearchApi } from "../src/lib/api";
import { MemoryRouter } from "../src/lib/router";
import type {
    JobResponse,
    ResultResponse,
} from "../src/lib/contracts";

const completedJob: JobResponse = {
    schema_version: "1.0",
    id: "job-1",
    kind: "optimization",
    status: "succeeded",
    progress: 66,
    total: 66,
    cancellation_requested: false,
    result_id: "result-1",
    error: null,
    created_at: "2026-07-26T00:00:00Z",
    updated_at: "2026-07-26T00:01:00Z",
    completed_at: "2026-07-26T00:01:00Z",
};

const result: ResultResponse = {
    schema_version: "1.0",
    id: "result-1",
    job_id: "job-1",
    kind: "optimization",
    created_at: "2026-07-26T00:01:00Z",
    payload: {
        schema_version: "1.0",
        mode: "formal",
        exploration_only: false,
        independent_episode_count: 12,
        provenance: {
            family_id: "nasdaq-100",
            prototype_symbol: "^NDX",
            target_symbol: "TQQQ",
            source_kind: "actual",
            strategy_start: "2011-01-03",
            strategy_end: "2026-06-30",
            walk_forward_splits: 3,
            ratio_unit: "basis_points",
        },
        synthetic_stress: {
            requested: true,
            evaluated_candidates: 66,
            passed_candidates: 42,
        },
        recommendations: [
            {
                profile: "conservative",
                ratios: [2000, 3000, 5000],
                oos_xirr: 0.101,
                stability_adjusted_xirr: 0.092,
            },
            {
                profile: "balanced",
                ratios: [2500, 3500, 4000],
                oos_xirr: 0.126,
                stability_adjusted_xirr: 0.115,
            },
            {
                profile: "aggressive",
                ratios: [3000, 3500, 3500],
                oos_xirr: 0.144,
                stability_adjusted_xirr: 0.12,
            },
        ],
        candidates: [
            {
                ratios: [2500, 3500, 4000],
                fold_oos_xirr: [0.09, 0.13, 0.16],
                oos_xirr: 0.126,
                stability_score: 0.91,
                stability_adjusted_xirr: 0.115,
                neighbor_count: 4,
                worst_5_return: -0.18,
                early_depletion_rate: 0.1,
                longest_trap_days: 650,
                synthetic_stress_pass: true,
                pareto_member: true,
                fold_evaluations: [],
                walk_forward_eligible: true,
                recommendation_labels: ["balanced"],
            },
        ],
    },
};

function optimizationApi() {
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
                {
                    symbol: "UPRO",
                    name: "ProShares UltraPro S&P500",
                    family_id: "sp-500",
                    leverage: 3,
                    prototype_symbol: "^GSPC",
                    currency: "USD",
                    timezone: "America/New_York",
                    inception: "2009-06-23",
                },
            ],
        },
        overview: {
            schema_version: "1.0",
            instrument_count: 1,
            cached_symbols: ["^NDX", "TQQQ"],
            formal_result_count: 1,
        },
        health: {
            schema_version: "1.0",
            status: "healthy",
            coverage: [],
        },
    });
    return {
        ...base,
        createOptimization: vi
            .fn()
            .mockResolvedValue({
                schema_version: "1.0",
                job_id: "job-1",
                status: "queued",
            }),
        getJob: vi.fn().mockResolvedValue(completedJob),
        getResult: vi.fn().mockResolvedValue(result),
        cancelJob: vi.fn().mockResolvedValue(completedJob),
    };
}

describe("AI-operable optimization workbench", () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it("uses the previous calendar month in Asia/Taipei at the local month boundary", () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date("2026-07-31T16:30:00.000Z"));

        render(
            <MemoryRouter initialEntries={["/ai"]}>
                <App
                    api={optimizationApi()}
                    capability={{ mode: "live" }}
                />
            </MemoryRouter>,
        );

        expect(screen.getByLabelText("AI 回測結束日")).toHaveValue(
            "2026-07-31",
        );
    });

    it("initializes from the family query and follows family-rail navigation", async () => {
        const user = userEvent.setup();
        render(
            <MemoryRouter initialEntries={["/ai?family=sp-500"]}>
                <App
                    api={optimizationApi()}
                    capability={{ mode: "live" }}
                />
            </MemoryRouter>,
        );

        await screen.findByRole("option", { name: "S&P 500" });
        expect(screen.getByLabelText("AI 指數家族")).toHaveValue(
            "sp-500",
        );
        expect(screen.getByLabelText("AI 分析標的")).toHaveValue("UPRO");
        expect(
            screen.getByRole("link", { name: /S&P 500/ }),
        ).toHaveAttribute("aria-current", "true");

        await user.click(
            screen.getByRole("link", { name: /NASDAQ-100/ }),
        );

        expect(screen.getByLabelText("AI 指數家族")).toHaveValue(
            "nasdaq-100",
        );
        expect(screen.getByLabelText("AI 分析標的")).toHaveValue("TQQQ");
    });

    it("syncs form and imported family changes back to the URL-backed rail", async () => {
        const user = userEvent.setup();
        render(
            <MemoryRouter initialEntries={["/ai?family=nasdaq-100"]}>
                <App
                    api={optimizationApi()}
                    capability={{ mode: "live" }}
                />
            </MemoryRouter>,
        );

        await screen.findByRole("option", { name: "S&P 500" });
        await user.selectOptions(
            screen.getByLabelText("AI 指數家族"),
            "sp-500",
        );
        expect(screen.getByLabelText("AI 分析標的")).toHaveValue("UPRO");
        expect(
            screen.getByRole("link", { name: /S&P 500/ }),
        ).toHaveAttribute("aria-current", "true");

        const request = {
            schema_version: "1.0",
            family_id: "nasdaq-100",
            target_symbol: "TQQQ",
            depths: ["0.20", "0.30", "0.40"],
            ratio_search: {
                minimum_basis_points: 0,
                maximum_basis_points: 10_000,
                step_basis_points: 1_000,
                monotone: true,
            },
            walk_forward: {
                n_splits: 3,
                minimum_train_independent_episodes: 1,
                minimum_test_independent_episodes: 1,
            },
            strategy: {
                start: "2011-01-03",
                end: "2026-07-31",
                initial_cash: "10000",
                monthly_contribution: "1000",
                annual_contribution_growth: "0.03",
                cash_interest_rate: "0.015",
                dividend_policy: "cash",
            },
        };
        const importInput = screen.getByLabelText("匯入 AI 設定 JSON");
        await user.upload(
            importInput,
            new File([JSON.stringify(request)], "request.json", {
                type: "application/json",
            }),
        );

        expect(await screen.findByRole("status")).toHaveTextContent(
            "設定已匯入",
        );
        expect(importInput).toHaveValue("");
        expect(screen.getByLabelText("AI 指數家族")).toHaveValue(
            "nasdaq-100",
        );
        expect(screen.getByLabelText("AI 分析標的")).toHaveValue("TQQQ");
        expect(
            screen.getByRole("link", { name: /NASDAQ-100/ }),
        ).toHaveAttribute("aria-current", "true");
    });

    it("submits a deterministic grid, polls the job, and exposes profile recommendations", async () => {
        const user = userEvent.setup();
        const api = optimizationApi();
        render(
            <MemoryRouter initialEntries={["/ai"]}>
                <App api={api} capability={{ mode: "live" }} />
            </MemoryRouter>,
        );

        await user.click(
            await screen.findByRole("button", {
                name: "開始窮舉分析",
            }),
        );

        expect(
            await screen.findByRole("heading", {
                name: "三種可執行方案",
            }),
        ).toBeVisible();
        expect(screen.getByText("保守")).toBeVisible();
        expect(screen.getByText("平衡")).toBeVisible();
        expect(screen.getByText("積極")).toBeVisible();
        expect(
            screen.getByRole("table", { name: "Pareto 候選策略" }),
        ).toHaveTextContent("25% / 35% / 40%");
        expect(api.createOptimization).toHaveBeenCalledWith(
            expect.objectContaining({
                family_id: "nasdaq-100",
                target_symbol: "TQQQ",
                depths: ["0.20", "0.30", "0.40"],
                ratio_search: {
                    minimum_basis_points: 0,
                    maximum_basis_points: 10000,
                    step_basis_points: 1000,
                    monotone: true,
                },
                walk_forward: {
                    n_splits: 3,
                    minimum_train_independent_episodes: 1,
                    minimum_test_independent_episodes: 1,
                },
                synthetic_stress: {
                    enabled: true,
                    annual_expense_ratio: 0.01,
                    max_portfolio_drawdown: 0.85,
                    max_longest_trap_days: 2520,
                },
            }),
        );
        expect(
            screen.getByRole("button", { name: "複製 AI 操作說明" }),
        ).toHaveAttribute("data-ai-action", "copy-ai-instructions");
    });
});
