import type { components } from "./openapi.generated";

type ApiSchemas = components["schemas"];

export type Instrument = ApiSchemas["InstrumentResponse"];
export type InstrumentListResponse = ApiSchemas["InstrumentListResponse"];
export type DataCoverage = ApiSchemas["DataCoverageResponse"];
export type DataHealthResponse = ApiSchemas["DataHealthResponse"];
export type MarketOverviewResponse = ApiSchemas["MarketOverviewResponse"];
export type ErrorResponse = ApiSchemas["ErrorResponse"];
export type ValidationIssue = ApiSchemas["ValidationIssue"];
