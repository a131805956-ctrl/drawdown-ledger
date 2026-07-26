import { expect, vi } from "vitest";

import {
    createLiveResearchApi,
    createStaticResearchApi,
} from "../src/lib/api";

describe("research API clients", () => {
    it("uses a relative API base for same-origin deployments", async () => {
        const fetcher = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    schema_version: "1.0",
                    instrument_count: 0,
                    cached_symbols: [],
                    formal_result_count: 0,
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        );

        await createLiveResearchApi({ fetcher }).getMarketOverview();

        expect(fetcher).toHaveBeenCalledWith(
            "/api/v1/market/overview",
            expect.objectContaining({ headers: { Accept: "application/json" } }),
        );
    });

    it("keeps configured API requests inside a nested public mount", async () => {
        const fetcher = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    schema_version: "1.0",
                    instrument_count: 0,
                    cached_symbols: [],
                    formal_result_count: 0,
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        );

        await createLiveResearchApi({
            fetcher,
            baseUrl: "/drawdown-ledger/api/v1",
        }).getMarketOverview();

        expect(fetcher).toHaveBeenCalledWith(
            "/drawdown-ledger/api/v1/market/overview",
            expect.objectContaining({
                headers: { Accept: "application/json" },
            }),
        );
    });

    it("encodes market-series queries and JSON research requests", async () => {
        const fetcher = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({}), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({}), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        const api = createLiveResearchApi({ fetcher });

        await api.getMarketSeries({
            family_id: "nasdaq-100",
            target_symbol: "TQQQ",
            include_synthetic: true,
            max_points: 5_000,
            start: null,
            end: "2026-06-30",
        });
        await api.analyzeEvidence({
            schema_version: "1.0",
            family_id: "nasdaq-100",
            target_symbol: "TQQQ",
            threshold: 0.3,
            horizons: [21, 252],
        });

        expect(fetcher).toHaveBeenNthCalledWith(
            1,
            "/api/v1/market/series?family_id=nasdaq-100&target_symbol=TQQQ&include_synthetic=true&max_points=5000&end=2026-06-30",
            expect.objectContaining({ method: "GET" }),
        );
        expect(fetcher).toHaveBeenNthCalledWith(
            2,
            "/api/v1/evidence/analyze",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({
                    schema_version: "1.0",
                    family_id: "nasdaq-100",
                    target_symbol: "TQQQ",
                    threshold: 0.3,
                    horizons: [21, 252],
                }),
            }),
        );
    });

    it("posts a market-data update with the requested as-of date", async () => {
        const fetcher = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    schema_version: "1.0",
                    status: "completed",
                    cutoff: "2026-06-30",
                    request_count: 21,
                    refreshed_symbols: ["QQQ", "^NDX"],
                    message: null,
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        );
        const api = createLiveResearchApi({ fetcher });

        await api.updateData("2026-07-26");

        expect(fetcher).toHaveBeenCalledWith(
            "/api/v1/data/update",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({
                    schema_version: "1.0",
                    as_of: "2026-07-26",
                }),
            }),
        );
    });

    it("exports a trusted result with explicit report formats", async () => {
        const fetcher = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    schema_version: "1.0",
                    export_id: "export-0123456789abcdef01234567",
                    result_id: "result-1",
                    artifacts: {},
                    lineage: {},
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        );
        const api = createLiveResearchApi({ fetcher });

        await api.exportReport({
            schema_version: "1.0",
            result_id: "result-1",
            formats: ["html", "json"],
        });

        expect(fetcher).toHaveBeenCalledWith(
            "/api/v1/reports/export",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({
                    schema_version: "1.0",
                    result_id: "result-1",
                    formats: ["html", "json"],
                }),
            }),
        );
    });

    it("serves static capability data without any network request", async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch");
        const api = createStaticResearchApi({
            instruments: { schema_version: "1.0", instruments: [] },
            overview: {
                schema_version: "1.0",
                instrument_count: 0,
                cached_symbols: [],
                formal_result_count: 0,
            },
            health: {
                schema_version: "1.0",
                status: "incomplete",
                coverage: [],
            },
        });

        await Promise.all([
            api.getInstruments(),
            api.getMarketOverview(),
            api.getDataHealth(),
        ]);

        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("never substitutes a fixed static study for a different requested target", async () => {
        const api = createStaticResearchApi({
            instruments: { schema_version: "1.0", instruments: [] },
            overview: {
                schema_version: "1.0",
                instrument_count: 0,
                cached_symbols: [],
                formal_result_count: 0,
            },
            health: {
                schema_version: "1.0",
                status: "incomplete",
                coverage: [],
            },
            evidence: {
                schema_version: "1.0",
                family_id: "nasdaq-100",
                target_symbol: "TQQQ",
                prototype_symbol: "^NDX",
                prototype_source: "benchmark",
                prototype_actual_last_session: "2026-07-31",
                prototype_policy_cutoff: "2026-07-31",
                target_actual_last_session: "2026-07-31",
                target_policy_cutoff: "2026-07-31",
                n_day: 0,
                n_episode: 0,
                n_executed_episode: 0,
                daily_statistics: [],
                episode_statistics: [],
                episodes: [],
            },
        });

        await expect(
            api.analyzeEvidence({
                schema_version: "1.0",
                family_id: "sp-500",
                target_symbol: "UPRO",
                threshold: 0.3,
            }),
        ).rejects.toMatchObject({ status: 404 });
    });

    it("never exports private results from static backup mode", async () => {
        const api = createStaticResearchApi();

        await expect(
            api.exportReport({
                schema_version: "1.0",
                result_id: "result-1",
                formats: ["json"],
            }),
        ).rejects.toMatchObject({ status: 405 });
    });
});
