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
    EvidenceAnalyzeRequest,
    EvidenceAnalyzeResponse,
    ErrorResponse,
    InstrumentListResponse,
    JobResponse,
    MarketSeriesQuery,
    MarketSeriesResponse,
    MarketOverviewResponse,
    OptimizationAcceptedResponse,
    OptimizationCreateRequest,
    ReportListResponse,
    ReportResponse,
    ResultListResponse,
    ResultResponse,
    StrategyBacktestRequest,
    StrategyBacktestResponse,
} from "./contracts";
import { apiVersionPath } from "./deploymentPath";

const API_VERSION_PATH = apiVersionPath(import.meta.env.BASE_URL);

export interface ResearchApi {
    getInstruments(this: void): Promise<InstrumentListResponse>;
    getMarketOverview(this: void): Promise<MarketOverviewResponse>;
    getDataHealth(this: void): Promise<DataHealthResponse>;
    getMarketSeries(
        this: void,
        query: MarketSeriesQuery,
    ): Promise<MarketSeriesResponse>;
    analyzeEvidence(
        this: void,
        request: EvidenceAnalyzeRequest,
    ): Promise<EvidenceAnalyzeResponse>;
    backtestStrategy(
        this: void,
        request: StrategyBacktestRequest,
    ): Promise<StrategyBacktestResponse>;
    createOptimization(
        this: void,
        request: OptimizationCreateRequest,
    ): Promise<OptimizationAcceptedResponse>;
    getJob(this: void, jobId: string): Promise<JobResponse>;
    cancelJob(this: void, jobId: string): Promise<JobResponse>;
    listResults(this: void): Promise<ResultListResponse>;
    getResult(this: void, resultId: string): Promise<ResultResponse>;
    listReports(this: void): Promise<ReportListResponse>;
    getReport(this: void, reportId: string): Promise<ReportResponse>;
}

export interface StaticResearchSnapshot {
    instruments: InstrumentListResponse;
    overview: MarketOverviewResponse;
    health: DataHealthResponse;
    evidence?: EvidenceAnalyzeResponse;
    evidenceThreshold?: number;
    marketSeries?: MarketSeriesResponse;
    results?: ResultListResponse;
    reports?: ReportListResponse;
}

export type DataCapability =
    | { mode: "live" }
    | { mode: "static"; dataDate: string };

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
    init: RequestInit = {},
): Promise<T> {
    const response = await fetcher(url, {
        ...init,
        headers: {
            Accept: "application/json",
            ...(init.body === undefined
                ? {}
                : { "Content-Type": "application/json" }),
            ...init.headers,
        },
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

function queryString(query: Record<string, unknown>): string {
    const parameters = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
        if (
            typeof value === "string" ||
            typeof value === "number" ||
            typeof value === "boolean"
        ) {
            parameters.set(key, String(value));
        } else if (value !== null && value !== undefined) {
            throw new TypeError(`Unsupported query parameter: ${key}`);
        }
    }
    return parameters.toString();
}

function jsonRequest<T>(
    fetcher: typeof fetch,
    url: string,
    body: unknown,
): Promise<T> {
    return requestJson<T>(fetcher, url, {
        method: "POST",
        body: JSON.stringify(body),
    });
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
        getMarketSeries: (query) =>
            requestJson<MarketSeriesResponse>(
                fetcher,
                `${baseUrl}/market/series?${queryString(query)}`,
                { method: "GET" },
            ),
        analyzeEvidence: (request) =>
            jsonRequest<EvidenceAnalyzeResponse>(
                fetcher,
                `${baseUrl}/evidence/analyze`,
                request,
            ),
        backtestStrategy: (request) =>
            jsonRequest<StrategyBacktestResponse>(
                fetcher,
                `${baseUrl}/strategies/backtest`,
                request,
            ),
        createOptimization: (request) =>
            jsonRequest<OptimizationAcceptedResponse>(
                fetcher,
                `${baseUrl}/optimizations`,
                request,
            ),
        getJob: (jobId) =>
            requestJson<JobResponse>(
                fetcher,
                `${baseUrl}/jobs/${encodeURIComponent(jobId)}`,
            ),
        cancelJob: (jobId) =>
            jsonRequest<JobResponse>(
                fetcher,
                `${baseUrl}/jobs/${encodeURIComponent(jobId)}/cancel`,
                undefined,
            ),
        listResults: () =>
            requestJson<ResultListResponse>(fetcher, `${baseUrl}/results`),
        getResult: (resultId) =>
            requestJson<ResultResponse>(
                fetcher,
                `${baseUrl}/results/${encodeURIComponent(resultId)}`,
            ),
        listReports: () =>
            requestJson<ReportListResponse>(fetcher, `${baseUrl}/reports`),
        getReport: (reportId) =>
            requestJson<ReportResponse>(
                fetcher,
                `${baseUrl}/reports/${encodeURIComponent(reportId)}`,
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
    results: { schema_version: "1.0", results: [] },
    reports: { schema_version: "1.0", reports: [] },
};

function unavailableInStaticMode<T>(feature: string): Promise<T> {
    return Promise.reject(
        new ResearchApiError(
            `${feature} is unavailable in the static snapshot`,
            405,
            null,
        ),
    );
}

function staticSnapshotMiss<T>(feature: string): Promise<T> {
    return Promise.reject(
        new ResearchApiError(
            `${feature} is not included in the fixed static snapshot`,
            404,
            null,
        ),
    );
}

export function createStaticResearchApi(
    snapshot: StaticResearchSnapshot = emptyStaticSnapshot,
): ResearchApi {
    return {
        getInstruments: () => Promise.resolve(snapshot.instruments),
        getMarketOverview: () => Promise.resolve(snapshot.overview),
        getDataHealth: () => Promise.resolve(snapshot.health),
        getMarketSeries: (query) =>
            snapshot.marketSeries === undefined
                ? unavailableInStaticMode("Market series")
                : snapshot.marketSeries.family_id !== query.family_id ||
                    snapshot.marketSeries.target_symbol !==
                        query.target_symbol
                  ? staticSnapshotMiss("Market series")
                  : Promise.resolve(snapshot.marketSeries),
        analyzeEvidence: (request) =>
            snapshot.evidence === undefined
                ? unavailableInStaticMode("Evidence analysis")
                : snapshot.evidence.family_id !== request.family_id ||
                    snapshot.evidence.target_symbol !==
                        request.target_symbol ||
                    (snapshot.evidenceThreshold !== undefined &&
                        Math.abs(
                            snapshot.evidenceThreshold -
                                request.threshold,
                        ) > 1e-9)
                  ? staticSnapshotMiss("Evidence analysis")
                  : Promise.resolve(snapshot.evidence),
        backtestStrategy: () =>
            unavailableInStaticMode("Strategy backtesting"),
        createOptimization: () =>
            unavailableInStaticMode("Optimization"),
        getJob: () => unavailableInStaticMode("Jobs"),
        cancelJob: () => unavailableInStaticMode("Jobs"),
        listResults: () =>
            Promise.resolve(
                snapshot.results ?? {
                    schema_version: "1.0",
                    results: [],
                },
            ),
        getResult: () => unavailableInStaticMode("Result detail"),
        listReports: () =>
            Promise.resolve(
                snapshot.reports ?? {
                    schema_version: "1.0",
                    reports: [],
                },
            ),
        getReport: () => unavailableInStaticMode("Report detail"),
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
    throw new Error(
        "VITE_STATIC_DATA_DATE is required when VITE_DATA_MODE=static",
    );
}
