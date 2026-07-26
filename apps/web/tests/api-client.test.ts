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
                status: "healthy",
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
});
