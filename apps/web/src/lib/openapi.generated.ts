/**
 * AUTO-GENERATED from FastAPI app.openapi(). Do not edit by hand.
 * Run `python scripts/generate_openapi_types.py` after API changes.
 */

export interface components {
    "schemas": {
        "DataCoverageResponse": {
            "actual_last_session": string | null;
            "cached": boolean;
            "policy_cutoff": string | null;
            "symbol": string;
        };
        "DataHealthResponse": {
            "coverage": Array<components["schemas"]["DataCoverageResponse"]>;
            "schema_version"?: "1.0";
            "status": "healthy";
        };
        "DataUpdateRequest": {
            "as_of": string;
            "schema_version"?: "1.0";
        };
        "DataUpdateResponse": {
            "cutoff": string | null;
            "message"?: string | null;
            "refreshed_symbols": Array<string>;
            "request_count": number;
            "schema_version"?: "1.0";
            "status": "completed" | "not_configured";
        };
        "ErrorResponse": {
            "detail": string | Array<components["schemas"]["ValidationIssue"]>;
            "schema_version"?: "1.0";
        };
        "EvidenceAnalyzeRequest": {
            "family_id": string;
            "horizons"?: Array<number>;
            "schema_version"?: "1.0";
            "target_symbol": string;
            "threshold": number;
        };
        "EvidenceAnalyzeResponse": {
            "daily_statistics": Array<components["schemas"]["HorizonStatisticsResponse"]>;
            "episode_statistics": Array<components["schemas"]["HorizonStatisticsResponse"]>;
            "n_day": number;
            "n_episode": number;
            "n_executed_episode": number;
            "schema_version"?: "1.0";
        };
        "HorizonStatisticsResponse": {
            "confidence_lower": number | null;
            "confidence_upper": number | null;
            "expected_shortfall_5": number | null;
            "horizon_sessions": number;
            "independent": boolean;
            "mean_total_return": number | null;
            "median_total_return": number | null;
            "n": number;
            "overlap_warning": string | null;
            "sample_kind": string;
            "win_rate": number | null;
        };
        "InstrumentListResponse": {
            "instruments": Array<components["schemas"]["InstrumentResponse"]>;
            "schema_version"?: "1.0";
        };
        "InstrumentResponse": {
            "currency": string;
            "family_id": string;
            "inception": string | null;
            "leverage": number;
            "name": string;
            "prototype_symbol": string;
            "symbol": string;
            "timezone": string;
        };
        "JobResponse": {
            "cancellation_requested": boolean;
            "completed_at": string | null;
            "created_at": string;
            "error": string | null;
            "id": string;
            "kind": string;
            "progress": number;
            "result_id": string | null;
            "schema_version"?: "1.0";
            "status": "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
            "total": number;
            "updated_at": string;
        };
        "LegacyOptimizationPayload": {
            "payload_type"?: "legacy";
            "raw_json": string;
            "stored_schema_version": string;
        };
        "LegacyReportContent": {
            "content_type"?: "legacy";
            "raw_json": string;
            "stored_schema_version": string;
        };
        "MarketOverviewResponse": {
            "cached_symbols": Array<string>;
            "formal_result_count": number;
            "instrument_count": number;
            "schema_version"?: "1.0";
        };
        "OptimizationAcceptedResponse": {
            "job_id": string;
            "schema_version"?: "1.0";
            "status": "queued" | "running" | "cancelling";
        };
        "OptimizationCandidateResponse": {
            "early_depletion_rate": number;
            "fold_evaluations": Array<components["schemas"]["WalkForwardFoldEvaluationResponse"]>;
            "fold_oos_xirr": Array<number>;
            "longest_trap_days": number;
            "neighbor_count": number;
            "oos_xirr": number;
            "pareto_member": boolean;
            "ratios": Array<number>;
            "recommendation_labels": Array<"conservative" | "balanced" | "aggressive">;
            "stability_adjusted_xirr": number;
            "stability_score": number;
            "synthetic_stress_pass": boolean | null;
            "walk_forward_eligible": boolean;
            "worst_5_return": number;
        };
        "OptimizationCreateRequest": {
            "aggressive"?: components["schemas"]["ProfileConstraintsInput"];
            "balanced"?: components["schemas"]["ProfileConstraintsInput"];
            "conservative"?: components["schemas"]["ProfileConstraintsInput"];
            "depths": Array<number | string>;
            "family_id": string;
            "isolated_peak_penalty"?: number;
            "max_candidates"?: number;
            "max_depth_levels"?: number;
            "minimum_independent_episodes"?: number;
            "neighbor_radius_basis_points"?: number;
            "ratio_search"?: components["schemas"]["RatioSearchInput"];
            "schema_version"?: "1.0";
            "strategy": components["schemas"]["StrategyTemplateInput"];
            "synthetic_stress"?: components["schemas"]["SyntheticStressRequest"];
            "target_symbol": string;
            "walk_forward"?: components["schemas"]["WalkForwardInput"];
        };
        "OptimizationProvenanceResponse": {
            "family_id": string;
            "prototype_symbol": string;
            "ratio_unit": "basis_points";
            "source_kind": "actual";
            "strategy_end": string;
            "strategy_start": string;
            "target_symbol": string;
            "walk_forward_splits": number;
        };
        "OptimizationResultPayload": {
            "candidates": Array<components["schemas"]["OptimizationCandidateResponse"]>;
            "exploration_only": boolean;
            "independent_episode_count": number;
            "mode": "formal" | "exploration_only";
            "provenance": components["schemas"]["OptimizationProvenanceResponse"];
            "recommendations": Array<components["schemas"]["RecommendationResponse"]>;
            "schema_version"?: "1.0";
            "synthetic_stress": components["schemas"]["SyntheticStressSummaryResponse"];
        };
        "PerformanceResponse": {
            "cash_depletion_date": string | null;
            "deepest_tier_missed": string | null;
            "expected_shortfall_5": number;
            "longest_underwater_days": number;
            "max_drawdown": number;
            "twr": number;
            "xirr": number | null;
        };
        "ProfileConstraintsInput": {
            "max_early_depletion_rate": number;
            "max_longest_trap_days": number;
            "worst_5_floor": number;
        };
        "RatioSearchInput": {
            "maximum_basis_points"?: number;
            "minimum_basis_points"?: number;
            "monotone"?: boolean;
            "step_basis_points"?: number;
        };
        "RecommendationResponse": {
            "oos_xirr": number;
            "profile": "conservative" | "balanced" | "aggressive";
            "ratios": Array<number>;
            "stability_adjusted_xirr": number;
        };
        "ReportContentResponse": {
            "message": string;
            "optimization": components["schemas"]["OptimizationResultPayload"];
            "result_id": string;
            "status": "not_yet_exported";
        };
        "ReportListResponse": {
            "reports": Array<components["schemas"]["ReportResponse"]>;
            "schema_version"?: "1.0";
        };
        "ReportResponse": {
            "content": components["schemas"]["ReportContentResponse"] | components["schemas"]["LegacyReportContent"];
            "created_at": string;
            "export_status": "not_yet_exported" | "exported";
            "id": string;
            "result_id": string | null;
            "schema_version"?: "1.0";
            "title": string;
        };
        "ResultListResponse": {
            "results": Array<components["schemas"]["ResultResponse"]>;
            "schema_version"?: "1.0";
        };
        "ResultResponse": {
            "created_at": string;
            "id": string;
            "job_id": string;
            "kind": string;
            "payload": components["schemas"]["OptimizationResultPayload"] | components["schemas"]["LegacyOptimizationPayload"];
            "schema_version"?: "1.0";
        };
        "StrategyBacktestRequest": {
            "annual_contribution_growth"?: number | string;
            "cash_interest_rate"?: number | string;
            "contribution_day"?: number;
            "dividend_policy"?: "cash" | "reinvest";
            "end": string;
            "family_id": string;
            "fee_rate"?: number | string;
            "fixed_fee"?: number | string;
            "initial_cash": number | string;
            "initial_shares"?: number | string;
            "monthly_contribution"?: number | string;
            "name"?: string;
            "schema_version"?: "1.0";
            "slippage"?: number | string;
            "start": string;
            "target_symbol": string;
            "tiers": Array<components["schemas"]["StrategyTierInput"]>;
        };
        "StrategyBacktestResponse": {
            "ending_cash": string;
            "ending_shares": string;
            "metrics": components["schemas"]["PerformanceResponse"] | null;
            "missed_thresholds": Array<string>;
            "name": string;
            "pending_thresholds": Array<string>;
            "schema_version"?: "1.0";
            "trade_count": number;
        };
        "StrategyTemplateInput": {
            "annual_contribution_growth"?: number | string;
            "cash_interest_rate"?: number | string;
            "contribution_day"?: number;
            "dividend_policy"?: "cash" | "reinvest";
            "end": string;
            "fee_rate"?: number | string;
            "fixed_fee"?: number | string;
            "initial_cash": number | string;
            "initial_shares"?: number | string;
            "monthly_contribution"?: number | string;
            "slippage"?: number | string;
            "start": string;
        };
        "StrategyTierInput": {
            "cash_fraction": number | string;
            "depth": number | string;
        };
        "SyntheticStressRequest": {
            "annual_expense_ratio"?: number;
            "enabled"?: boolean;
            "max_longest_trap_days"?: number;
            "max_portfolio_drawdown"?: number;
        };
        "SyntheticStressSummaryResponse": {
            "evaluated_candidates": number;
            "passed_candidates": number;
            "requested": boolean;
        };
        "ValidationIssue": {
            "input_json"?: string | null;
            "loc": Array<string | number>;
            "msg": string;
            "type": string;
        };
        "WalkForwardFoldEvaluationResponse": {
            "fold_number": number;
            "test_end": string;
            "test_independent_episode_count": number;
            "test_start": string;
            "test_xirr": number;
            "train_end": string;
            "train_independent_episode_count": number;
            "train_start": string;
            "train_xirr": number;
            "training_selected": boolean;
        };
        "WalkForwardInput": {
            "minimum_test_independent_episodes"?: number;
            "minimum_train_independent_episodes"?: number;
            "minimum_train_sessions"?: number | null;
            "n_splits"?: number;
            "test_size_sessions"?: number | null;
        };
    };
}

export interface paths {
    "/api/v1/data/health": {
            get: {
                parameters: Record<string, never>;
                requestBody: never;
                responses: {
                    "200": components["schemas"]["DataHealthResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/data/update": {
            post: {
                parameters: Record<string, never>;
                requestBody: components["schemas"]["DataUpdateRequest"];
                responses: {
                    "200": components["schemas"]["DataUpdateResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/evidence/analyze": {
            post: {
                parameters: Record<string, never>;
                requestBody: components["schemas"]["EvidenceAnalyzeRequest"];
                responses: {
                    "200": components["schemas"]["EvidenceAnalyzeResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/instruments": {
            get: {
                parameters: Record<string, never>;
                requestBody: never;
                responses: {
                    "200": components["schemas"]["InstrumentListResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/jobs/{job_id}": {
            get: {
                parameters: {
                "path": {
                        "job_id": string;
                    };
            };
                requestBody: never;
                responses: {
                    "200": components["schemas"]["JobResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/jobs/{job_id}/cancel": {
            post: {
                parameters: {
                "path": {
                        "job_id": string;
                    };
            };
                requestBody: never;
                responses: {
                    "202": components["schemas"]["JobResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/market/overview": {
            get: {
                parameters: Record<string, never>;
                requestBody: never;
                responses: {
                    "200": components["schemas"]["MarketOverviewResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/optimizations": {
            post: {
                parameters: Record<string, never>;
                requestBody: components["schemas"]["OptimizationCreateRequest"];
                responses: {
                    "202": components["schemas"]["OptimizationAcceptedResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/reports": {
            get: {
                parameters: Record<string, never>;
                requestBody: never;
                responses: {
                    "200": components["schemas"]["ReportListResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/reports/{report_id}": {
            get: {
                parameters: {
                "path": {
                        "report_id": string;
                    };
            };
                requestBody: never;
                responses: {
                    "200": components["schemas"]["ReportResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/results": {
            get: {
                parameters: Record<string, never>;
                requestBody: never;
                responses: {
                    "200": components["schemas"]["ResultListResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/results/{result_id}": {
            get: {
                parameters: {
                "path": {
                        "result_id": string;
                    };
            };
                requestBody: never;
                responses: {
                    "200": components["schemas"]["ResultResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
    "/api/v1/strategies/backtest": {
            post: {
                parameters: Record<string, never>;
                requestBody: components["schemas"]["StrategyBacktestRequest"];
                responses: {
                    "200": components["schemas"]["StrategyBacktestResponse"];
                    "404": components["schemas"]["ErrorResponse"];
                    "409": components["schemas"]["ErrorResponse"];
                    "422": components["schemas"]["ErrorResponse"];
                };
            };
        };
}
