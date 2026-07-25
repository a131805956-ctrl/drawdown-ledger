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
