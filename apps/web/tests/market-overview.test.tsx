import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { App } from "../src/app/App";
import { MemoryRouter } from "../src/lib/router";
import type {
    DataHealthResponse,
    InstrumentListResponse,
    MarketOverviewResponse,
} from "../src/lib/contracts";
import {
    createStaticResearchApi,
    type DataCapability,
    type ResearchApi,
} from "../src/lib/api";

const instruments: InstrumentListResponse = {
    schema_version: "1.0",
    instruments: [
        {
            symbol: "QQQ",
            name: "Invesco QQQ Trust",
            family_id: "nasdaq-100",
            leverage: 1,
            prototype_symbol: "QQQ",
            currency: "USD",
            timezone: "America/New_York",
            inception: null,
        },
        {
            symbol: "TQQQ",
            name: "ProShares UltraPro QQQ",
            family_id: "nasdaq-100",
            leverage: 3,
            prototype_symbol: "QQQ",
            currency: "USD",
            timezone: "America/New_York",
            inception: null,
        },
    ],
};

const overview: MarketOverviewResponse = {
    schema_version: "1.0",
    instrument_count: 16,
    cached_symbols: ["QQQ", "TQQQ"],
    formal_result_count: 4,
};

const health: DataHealthResponse = {
    schema_version: "1.0",
    status: "incomplete",
    coverage: [
        {
            symbol: "QQQ",
            cached: true,
            actual_last_session: "2026-06-30",
            policy_cutoff: "2026-06-30",
            roles: ["tradable", "prototype_proxy"],
        },
        {
            symbol: "TQQQ",
            cached: false,
            actual_last_session: null,
            policy_cutoff: "2026-06-30",
            roles: ["tradable"],
        },
    ],
};

function apiWith(
    values: {
        instruments?: InstrumentListResponse;
        overview?: MarketOverviewResponse;
        health?: DataHealthResponse;
    } = {},
): ResearchApi {
    return {
        ...createStaticResearchApi({
            instruments: values.instruments ?? instruments,
            overview: values.overview ?? overview,
            health: values.health ?? health,
        }),
        getInstruments: vi
            .fn()
            .mockResolvedValue(values.instruments ?? instruments),
        getMarketOverview: vi
            .fn()
            .mockResolvedValue(values.overview ?? overview),
        getDataHealth: vi.fn().mockResolvedValue(values.health ?? health),
    };
}

function renderPath(
    path: string,
    api: ResearchApi,
    capability: DataCapability = { mode: "live" },
) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <App api={api} capability={capability} />
        </MemoryRouter>,
    );
}

describe("market overview route", () => {
    it("summarizes the real API overview contract", async () => {
        renderPath("/", apiWith());

        expect(
            await screen.findByRole("heading", { name: "市場總覽" }),
        ).toBeVisible();
        expect(screen.getByText("16")).toBeVisible();
        expect(screen.getByText("2")).toBeVisible();
        expect(screen.getByText("含原型與代理序列")).toBeVisible();
        expect(screen.getByText("4")).toBeVisible();
        expect(screen.getAllByText("NASDAQ-100").length).toBeGreaterThan(0);
    });

    it("offers direction when the API has no overview data", async () => {
        renderPath(
            "/",
            apiWith({
                instruments: {
                    schema_version: "1.0",
                    instruments: [],
                },
                overview: {
                    schema_version: "1.0",
                    instrument_count: 0,
                    cached_symbols: [],
                    formal_result_count: 0,
                },
            }),
        );

        expect(
            await screen.findByText("尚無市場總覽資料"),
        ).toBeVisible();
        expect(
            screen.getByText("先到資料健康度確認快取，再開始研究。"),
        ).toBeVisible();
    });

    it("shows a route-level error with a retry action", async () => {
        const api = apiWith();
        vi.mocked(api.getMarketOverview).mockRejectedValue(
            new Error("service unavailable"),
        );
        renderPath("/", api);

        expect(
            await screen.findByRole("alert", { name: "無法載入市場總覽" }),
        ).toBeVisible();
        expect(
            screen.getByRole("button", { name: "重新讀取市場總覽" }),
        ).toBeEnabled();
    });
});

describe("data health route", () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it("distinguishes the policy cutoff from the observed session", async () => {
        renderPath(
            "/data-health",
            apiWith({
                health: {
                    schema_version: "1.0",
                    status: "ready",
                    coverage: [
                        {
                            symbol: "QQQ",
                            cached: true,
                            actual_last_session: "2026-02-27",
                            policy_cutoff: "2026-02-28",
                            roles: ["tradable", "prototype_proxy"],
                        },
                    ],
                },
            }),
            { mode: "static", dataDate: "2026-02-28" },
        );

        expect(
            await screen.findByRole("heading", { name: "資料健康度" }),
        ).toBeVisible();
        expect(screen.getByRole("row", { name: /^QQQ / })).toHaveTextContent(
            "符合截止政策",
        );
        expect(screen.getByText("政策截止日")).toBeVisible();
        expect(screen.getByText("實際最後交易日")).toBeVisible();
    });

    it("counts only rows matching the required cutoff and labels stale or missing data", async () => {
        renderPath(
            "/data-health",
            apiWith({
                health: {
                    schema_version: "1.0",
                    status: "incomplete",
                    coverage: [
                        {
                            symbol: "QQQ",
                            cached: true,
                            actual_last_session: "2026-07-31",
                            policy_cutoff: "2026-07-31",
                            roles: ["tradable", "prototype_proxy"],
                        },
                        {
                            symbol: "TQQQ",
                            cached: true,
                            actual_last_session: "2026-06-30",
                            policy_cutoff: "2026-06-30",
                            roles: ["tradable"],
                        },
                        {
                            symbol: "^NDX",
                            cached: false,
                            actual_last_session: null,
                            policy_cutoff: null,
                            roles: ["prototype"],
                        },
                    ],
                },
            }),
            { mode: "static", dataDate: "2026-07-31" },
        );

        expect(
            await screen.findByRole("heading", { name: "資料健康度" }),
        ).toBeVisible();
        expect(screen.getByText("1 / 3")).toBeVisible();
        expect(screen.getByRole("row", { name: /^QQQ / })).toHaveTextContent(
            "符合截止政策",
        );
        expect(screen.getByRole("row", { name: /^TQQQ / })).toHaveTextContent(
            "資料過期",
        );
        expect(screen.getByRole("row", { name: /^\^NDX / })).toHaveTextContent(
            "資料缺漏",
        );
    });

    it("does not paint a failed live API as healthy", async () => {
        const api = apiWith();
        vi.mocked(api.getDataHealth).mockRejectedValue(
            new Error("service unavailable"),
        );
        renderPath("/", api);

        const status = await screen.findByRole("link", {
            name: "本機資料服務無法連線",
        });
        expect(status).toHaveClass("is-error");
        expect(status).toHaveTextContent("檢查 API 服務");
    });

    it("labels an empty live cache as not ready instead of merely API available", async () => {
        renderPath(
            "/",
            apiWith({
                health: {
                    schema_version: "1.0",
                    status: "incomplete",
                    coverage: [
                        {
                            symbol: "QQQ",
                            cached: false,
                            actual_last_session: null,
                            policy_cutoff: null,
                            roles: ["tradable", "prototype_proxy"],
                        },
                        {
                            symbol: "^NDX",
                            cached: false,
                            actual_last_session: null,
                            policy_cutoff: null,
                            roles: ["prototype"],
                        },
                    ],
                },
            }),
        );

        const status = await screen.findByRole("link", {
            name: "本機資料未就緒，0 / 2 符合截止",
        });
        expect(status).toHaveClass("is-warning");
        expect(status).toHaveTextContent("資料未就緒");
        expect(status).toHaveTextContent("0 / 2 符合截止");
    });

    it("updates live data to the required cutoff and refetches health and overview", async () => {
        vi.useFakeTimers({ toFake: ["Date"] });
        vi.setSystemTime(new Date("2026-07-26T04:00:00.000Z"));
        const user = userEvent.setup();
        const initialHealth: DataHealthResponse = {
            schema_version: "1.0",
            status: "incomplete",
            coverage: [
                {
                    symbol: "QQQ",
                    cached: false,
                    actual_last_session: null,
                    policy_cutoff: null,
                    roles: ["tradable", "prototype_proxy"],
                },
                {
                    symbol: "^NDX",
                    cached: false,
                    actual_last_session: null,
                    policy_cutoff: null,
                    roles: ["prototype"],
                },
            ],
        };
        const updatedHealth: DataHealthResponse = {
            schema_version: "1.0",
            status: "ready",
            coverage: initialHealth.coverage.map((row) => ({
                ...row,
                cached: true,
                actual_last_session: "2026-06-30",
                policy_cutoff: "2026-06-30",
            })),
        };
        const api = apiWith({ health: initialHealth });
        api.getDataHealth = vi
            .fn()
            .mockResolvedValueOnce(initialHealth)
            .mockResolvedValue(updatedHealth);
        api.getMarketOverview = vi.fn().mockResolvedValue(overview);
        const updateData = vi.fn().mockResolvedValue({
            schema_version: "1.0" as const,
            status: "completed" as const,
            cutoff: "2026-06-30",
            request_count: 2,
            refreshed_symbols: ["QQQ", "^NDX"],
            message: null,
        });
        Object.assign(api, { updateData });

        renderPath("/data-health", api);

        await user.click(
            await screen.findByRole("button", {
                name: "一鍵更新至 2026-06-30",
            }),
        );

        expect(updateData).toHaveBeenCalledWith("2026-07-26");
        expect(await screen.findByText("更新完成")).toBeVisible();
        expect(screen.getByText("QQQ、^NDX")).toBeVisible();
        expect(screen.getByText("2 / 2")).toBeVisible();
        expect(api.getDataHealth).toHaveBeenCalledTimes(2);
        expect(api.getMarketOverview).toHaveBeenCalledTimes(1);
    });

    it("shows the provider detail under per-symbol update errors", async () => {
        const user = userEvent.setup();
        const api = apiWith();
        Object.assign(api, {
            updateData: vi.fn().mockResolvedValue({
                schema_version: "1.0" as const,
                status: "partial" as const,
                cutoff: "2026-06-30",
                request_count: 2,
                refreshed_symbols: ["^NDX"],
                failures: [
                    {
                        symbol: "QQQ",
                        message: "Yahoo 暫時拒絕連線；舊快取已保留。",
                    },
                ],
                message: "部分標的更新失敗。",
            }),
        });

        renderPath("/data-health", api);

        await user.click(
            await screen.findByRole("button", {
                name: /一鍵更新至/,
            }),
        );

        expect(
            await screen.findByRole("heading", {
                name: "逐標的錯誤",
            }),
        ).toBeVisible();
        expect(
            screen.getByText("QQQ：Yahoo 暫時拒絕連線；舊快取已保留。"),
        ).toBeVisible();
    });

    it("marks Pages as view-only and links to the live application", async () => {
        renderPath(
            "/",
            apiWith(),
            { mode: "static", dataDate: "2026-07-31" },
        );

        const liveLink = await screen.findByRole("link", {
            name: "靜態備援資料狀態，只能檢視；資料日 2026-07-31；開啟 Live 服務",
        });
        expect(liveLink).toHaveTextContent("只能檢視");
        expect(liveLink).toHaveAttribute(
            "href",
            "https://desktop-loi23mp.tail9c076e.ts.net/drawdown-ledger/",
        );
    });
});
