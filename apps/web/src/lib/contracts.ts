import type { components, paths } from "./openapi.generated";

type ApiSchemas = components["schemas"];

export type Instrument = ApiSchemas["InstrumentResponse"];
export type InstrumentListResponse = ApiSchemas["InstrumentListResponse"];
export type DataCoverage = ApiSchemas["DataCoverageResponse"];
export type DataHealthResponse = ApiSchemas["DataHealthResponse"];
export type MarketOverviewResponse = ApiSchemas["MarketOverviewResponse"];
export type ErrorResponse = ApiSchemas["ErrorResponse"];
export type ValidationIssue = ApiSchemas["ValidationIssue"];
export type EvidenceAnalyzeRequest = ApiSchemas["EvidenceAnalyzeRequest"];
export type EvidenceAnalyzeResponse = ApiSchemas["EvidenceAnalyzeResponse"];
export type MarketSeriesResponse = ApiSchemas["MarketSeriesResponse"];
export type MarketSeriesQuery =
    paths["/api/v1/market/series"]["get"]["parameters"]["query"];
export type StrategyBacktestRequest = ApiSchemas["StrategyBacktestRequest"];
export type StrategyBacktestResponse = ApiSchemas["StrategyBacktestResponse"];
export type OptimizationCreateRequest =
    ApiSchemas["OptimizationCreateRequest"];
export type OptimizationAcceptedResponse =
    ApiSchemas["OptimizationAcceptedResponse"];
export type JobResponse = ApiSchemas["JobResponse"];
export type ResultListResponse = ApiSchemas["ResultListResponse"];
export type ResultResponse = ApiSchemas["ResultResponse"];
export type ReportListResponse = ApiSchemas["ReportListResponse"];
export type ReportResponse = ApiSchemas["ReportResponse"];
export type ReportExportRequest = ApiSchemas["ReportExportRequest"];
export type ReportExportResponse = ApiSchemas["ReportExportResponse"];
