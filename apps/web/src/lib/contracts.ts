/**
 * Central aliases for the current FastAPI `/api/v1` OpenAPI contract.
 *
 * Keep route consumers on these names so the generated OpenAPI mapping can
 * replace the declarations without touching page components.
 */
export type SchemaVersion = "1.0";

export interface VersionedResponse {
    schema_version: SchemaVersion;
}

export interface Instrument {
    symbol: string;
    name: string;
    family_id: string;
    leverage: number;
    prototype_symbol: string;
    currency: string;
    timezone: string;
    inception: string | null;
}

export interface InstrumentListResponse extends VersionedResponse {
    instruments: Instrument[];
}

export interface DataCoverage {
    symbol: string;
    cached: boolean;
    actual_last_session: string | null;
    policy_cutoff: string | null;
}

export interface DataHealthResponse extends VersionedResponse {
    status: "healthy";
    coverage: DataCoverage[];
}

export interface MarketOverviewResponse extends VersionedResponse {
    instrument_count: number;
    cached_symbols: string[];
    formal_result_count: number;
}

export interface ErrorResponse extends VersionedResponse {
    detail: string | ValidationIssue[];
}

export interface ValidationIssue {
    type: string;
    loc: Array<string | number>;
    msg: string;
    input_json: string | null;
}
