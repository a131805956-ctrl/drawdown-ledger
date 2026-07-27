import type { Page, Route } from "@playwright/test";

import { staticResearchSnapshot } from "../../apps/web/src/demo/staticSnapshot";
import type {
    JobResponse,
    ReportExportResponse,
    ResultResponse,
    StrategyBacktestResponse,
} from "../../apps/web/src/lib/contracts";

export interface ResearchApiMockLog {
    requests: Array<{
        method: string;
        pathname: string;
        body: unknown;
    }>;
}

const strategyResult: StrategyBacktestResponse = {
    schema_version: "1.0",
    name: "現金庫門檻策略",
    family_id: "nasdaq-100",
    target_symbol: "TQQQ",
    prototype_symbol: "^NDX",
    prototype_source: "benchmark",
    prototype_actual_last_session: "2026-06-30",
    prototype_policy_cutoff: "2026-06-30",
    target_actual_last_session: "2026-06-30",
    target_policy_cutoff: "2026-06-30",
    source_kind: "actual",
    source_label: "trusted_local_cache",
    contribution_total: "80000",
    dividend_income: "3200",
    interest_income: "1700",
    ending_cash: "12400",
    ending_shares: "1180.25",
    total_fees: "86",
    trade_count: 1,
    missed_thresholds: [],
    pending_thresholds: ["0.30", "0.40"],
    metrics: {
        xirr: 0.124,
        twr: 0.91,
        max_drawdown: -0.48,
        expected_shortfall_5: -0.22,
        longest_underwater_days: 420,
        cash_depletion_date: null,
        deepest_tier_missed: null,
    },
    equity_curve: [
        {
            date: "2020-01-02",
            close: "50",
            shares: "0",
            cash: "10000",
            value: "10000",
            external_flow: "10000",
            external_contribution: "10000",
            cash_pool_inflow: "10000",
            immediate_investment: "0",
            cash_pool_balance: "10000",
            net_contributions: "10000",
            profit_loss: "0",
        },
        {
            date: "2020-03-17",
            close: "21",
            shares: "250",
            cash: "5000",
            value: "10250",
            external_flow: "0",
            external_contribution: "0",
            cash_pool_inflow: "0",
            immediate_investment: "0",
            cash_pool_balance: "5000",
            net_contributions: "10000",
            profit_loss: "250",
        },
    ],
    trades: [
        {
            date: "2020-03-17",
            signal_date: "2020-03-16",
            kind: "buy",
            threshold: "0.20",
            raw_price: "20",
            execution_price: "20",
            shares_bought: "250",
            cash_spent: "5000",
            fee: "0",
            post_trade_cash: "5000",
            prototype_drawdown: "-0.25",
            target_drawdown: "-0.58",
            marker_profit_loss: "250",
        },
    ],
};

const completedJob: JobResponse = {
    schema_version: "1.0",
    id: "job-e2e",
    kind: "optimization",
    status: "succeeded",
    progress: 66,
    total: 66,
    cancellation_requested: false,
    result_id: "result-e2e",
    error: null,
    created_at: "2026-07-26T00:00:00Z",
    updated_at: "2026-07-26T00:01:00Z",
    completed_at: "2026-07-26T00:01:00Z",
};

const reportExportResult: ReportExportResponse = {
    schema_version: "1.0",
    export_id: "export-0123456789abcdef01234567",
    result_id: "illustrative-result-2026-07-31",
    artifacts: {
        html: {
            relative_path: "report.html",
            media_type: "text/html; charset=utf-8",
            sha256: "a".repeat(64),
            size_bytes: 200,
        },
        json: {
            relative_path: "report.json",
            media_type: "application/json",
            sha256: "b".repeat(64),
            size_bytes: 300,
        },
        csv: {
            relative_path: "candidates.csv",
            media_type: "text/csv; charset=utf-8",
            sha256: "c".repeat(64),
            size_bytes: 400,
        },
    },
    lineage: {
        engine_version: "0.1.0",
        git_commit: "d".repeat(40),
        code_state: "clean",
        data_hashes: { TQQQ: "e".repeat(64) },
        data_lineage: {},
        policy_cutoff: "2026-06-30",
        actual_session_cutoff: "2026-06-30",
        result_sha256: "f".repeat(64),
        generated_at: "2026-07-26T02:00:00Z",
        timezone: "Asia/Taipei",
        parameters: {},
        parameters_sha256: "0".repeat(64),
        analysis_boundary: {},
        assumptions: [],
        limitations: [],
    },
};

function optimizationResult(): ResultResponse {
    const template = staticResearchSnapshot.results?.results[0];
    if (template === undefined) {
        throw new Error("The committed static snapshot needs an optimization result.");
    }
    return {
        ...template,
        id: "result-e2e",
        job_id: "job-e2e",
        created_at: completedJob.completed_at ?? completedJob.updated_at,
    };
}

async function jsonBody(route: Route): Promise<unknown> {
    const raw = route.request().postData();
    return raw === null || raw.length === 0 ? null : JSON.parse(raw);
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
    await route.fulfill({
        status,
        contentType: "application/json; charset=utf-8",
        body: JSON.stringify(body),
    });
}

export async function installResearchApiMocks(
    page: Page,
): Promise<ResearchApiMockLog> {
    const log: ResearchApiMockLog = { requests: [] };

    await page.route("**/api/v1/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const pathname = url.pathname;
        const body =
            request.method() === "GET" ? null : await jsonBody(route);
        log.requests.push({ method: request.method(), pathname, body });

        if (request.method() === "GET" && pathname.endsWith("/instruments")) {
            await fulfillJson(route, staticResearchSnapshot.instruments);
            return;
        }
        if (
            request.method() === "GET" &&
            pathname.endsWith("/market/overview")
        ) {
            await fulfillJson(route, staticResearchSnapshot.overview);
            return;
        }
        if (request.method() === "GET" && pathname.endsWith("/data/health")) {
            await fulfillJson(route, staticResearchSnapshot.health);
            return;
        }
        if (
            request.method() === "GET" &&
            pathname.endsWith("/market/series")
        ) {
            await fulfillJson(route, staticResearchSnapshot.marketSeries);
            return;
        }
        if (
            request.method() === "POST" &&
            pathname.endsWith("/evidence/analyze")
        ) {
            await fulfillJson(route, staticResearchSnapshot.evidence);
            return;
        }
        if (
            request.method() === "POST" &&
            pathname.endsWith("/strategies/backtest")
        ) {
            await fulfillJson(route, strategyResult);
            return;
        }
        if (
            request.method() === "POST" &&
            pathname.endsWith("/optimizations")
        ) {
            await fulfillJson(route, {
                schema_version: "1.0",
                job_id: "job-e2e",
                status: "queued",
            });
            return;
        }
        if (
            request.method() === "GET" &&
            pathname.endsWith("/jobs/job-e2e")
        ) {
            await fulfillJson(route, completedJob);
            return;
        }
        if (
            request.method() === "POST" &&
            pathname.endsWith("/jobs/job-e2e/cancel")
        ) {
            await fulfillJson(route, completedJob);
            return;
        }
        if (request.method() === "GET" && pathname.endsWith("/results")) {
            await fulfillJson(route, staticResearchSnapshot.results);
            return;
        }
        if (
            request.method() === "GET" &&
            pathname.endsWith("/results/result-e2e")
        ) {
            await fulfillJson(route, optimizationResult());
            return;
        }
        if (request.method() === "GET" && pathname.endsWith("/reports")) {
            await fulfillJson(route, staticResearchSnapshot.reports);
            return;
        }
        if (
            request.method() === "POST" &&
            pathname.endsWith("/reports/export")
        ) {
            await fulfillJson(route, reportExportResult, 201);
            return;
        }

        await fulfillJson(
            route,
            {
                detail: {
                    code: "e2e_route_not_mocked",
                    message: `No E2E fixture for ${request.method()} ${pathname}`,
                },
            },
            404,
        );
    });

    return log;
}
