import {
    QueryClient,
    QueryClientProvider,
} from "@tanstack/react-query";
import {
    createContext,
    createElement,
    useContext,
    useState,
    type PropsWithChildren,
} from "react";

import type {
    DataHealthResponse,
    ErrorResponse,
    InstrumentListResponse,
    MarketOverviewResponse,
} from "./contracts";

const API_VERSION_PATH = "/api/v1";

export interface ResearchApi {
    getInstruments(this: void): Promise<InstrumentListResponse>;
    getMarketOverview(this: void): Promise<MarketOverviewResponse>;
    getDataHealth(this: void): Promise<DataHealthResponse>;
}

export interface StaticResearchSnapshot {
    instruments: InstrumentListResponse;
    overview: MarketOverviewResponse;
    health: DataHealthResponse;
}

export interface DataCapability {
    mode: "live" | "static";
    dataDate?: string;
}

interface LiveResearchApiOptions {
    baseUrl?: string;
    fetcher?: typeof fetch;
}

export class ResearchApiError extends Error {
    readonly status: number;
    readonly detail: ErrorResponse["detail"] | null;

    constructor(
        message: string,
        status: number,
        detail: ErrorResponse["detail"] | null,
    ) {
        super(message);
        this.name = "ResearchApiError";
        this.status = status;
        this.detail = detail;
    }
}

async function requestJson<T>(
    fetcher: typeof fetch,
    url: string,
): Promise<T> {
    const response = await fetcher(url, {
        headers: { Accept: "application/json" },
    });
    if (!response.ok) {
        let detail: ErrorResponse["detail"] | null = null;
        try {
            const payload = (await response.json()) as Partial<ErrorResponse>;
            detail = payload.detail ?? null;
        } catch {
            // The status and route remain enough to offer a useful retry.
        }
        throw new ResearchApiError(
            `Request failed with status ${String(response.status)}`,
            response.status,
            detail,
        );
    }
    return (await response.json()) as T;
}

export function createLiveResearchApi(
    options: LiveResearchApiOptions = {},
): ResearchApi {
    const baseUrl = options.baseUrl ?? API_VERSION_PATH;
    const fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);

    return {
        getInstruments: () =>
            requestJson<InstrumentListResponse>(
                fetcher,
                `${baseUrl}/instruments`,
            ),
        getMarketOverview: () =>
            requestJson<MarketOverviewResponse>(
                fetcher,
                `${baseUrl}/market/overview`,
            ),
        getDataHealth: () =>
            requestJson<DataHealthResponse>(
                fetcher,
                `${baseUrl}/data/health`,
            ),
    };
}

const emptyStaticSnapshot: StaticResearchSnapshot = {
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
};

export function createStaticResearchApi(
    snapshot: StaticResearchSnapshot = emptyStaticSnapshot,
): ResearchApi {
    return {
        getInstruments: () => Promise.resolve(snapshot.instruments),
        getMarketOverview: () => Promise.resolve(snapshot.overview),
        getDataHealth: () => Promise.resolve(snapshot.health),
    };
}

interface DataContextValue {
    api: ResearchApi;
    capability: DataCapability;
}

const DataContext = createContext<DataContextValue | null>(null);

interface DataCapabilityProviderProps extends PropsWithChildren {
    api: ResearchApi;
    capability: DataCapability;
}

export function DataCapabilityProvider({
    api,
    capability,
    children,
}: DataCapabilityProviderProps) {
    const [queryClient] = useState(
        () =>
            new QueryClient({
                defaultOptions: {
                    queries: {
                        retry: false,
                        staleTime: 30_000,
                    },
                },
            }),
    );

    return createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(
            DataContext.Provider,
            { value: { api, capability } },
            children,
        ),
    );
}

export function useResearchData(): DataContextValue {
    const value = useContext(DataContext);
    if (value === null) {
        throw new Error(
            "useResearchData must be used inside DataCapabilityProvider",
        );
    }
    return value;
}

export function capabilityFromEnvironment(): DataCapability {
    const dataMode: unknown = import.meta.env.VITE_DATA_MODE;
    const dataDate: unknown = import.meta.env.VITE_STATIC_DATA_DATE;

    if (dataMode !== "static") {
        return { mode: "live" };
    }
    if (typeof dataDate === "string" && dataDate.length > 0) {
        return { mode: "static", dataDate };
    }
    return { mode: "static" };
}
