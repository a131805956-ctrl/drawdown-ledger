import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "../src/app/App";
import { createStaticResearchApi } from "../src/lib/api";
import { MemoryRouter } from "../src/lib/router";
import type {
    ReportListResponse,
    ResultListResponse,
} from "../src/lib/contracts";

function optimizationPayload(target: string, ratio: number) {
    return {
        schema_version: "1.0" as const,
        mode: "formal" as const,
        exploration_only: false,
        independent_episode_count: 12,
        provenance: {
            family_id: "nasdaq-100",
            prototype_symbol: "^NDX",
            target_symbol: target,
            source_kind: "actual" as const,
            strategy_start: "2011-01-03",
            strategy_end: "2026-06-30",
            walk_forward_splits: 3,
            ratio_unit: "basis_points" as const,
        },
        synthetic_stress: {
            requested: true,
            evaluated_candidates: 10,
            passed_candidates: 8,
        },
        recommendations: [
            {
                profile: "balanced" as const,
                ratios: [ratio, 3500, 4000],
                oos_xirr: 0.12,
                stability_adjusted_xirr: 0.11,
            },
        ],
        candidates: [
            {
                ratios: [ratio, 3500, 4000],
                fold_oos_xirr: [0.1, 0.12, 0.14],
                oos_xirr: 0.12,
                stability_score: 0.9,
                stability_adjusted_xirr: 0.11,
                neighbor_count: 3,
                worst_5_return: -0.2,
                early_depletion_rate: 0.1,
                longest_trap_days: 600,
                synthetic_stress_pass: true,
                pareto_member: true,
                fold_evaluations: [],
                walk_forward_eligible: true,
                recommendation_labels: ["balanced" as const],
            },
        ],
    };
}

const results: ResultListResponse = {
    schema_version: "1.0",
    results: [
        {
            schema_version: "1.0",
            id: "result-1",
            job_id: "job-1",
            kind: "optimization",
            created_at: "2026-07-26T00:00:00Z",
            payload: optimizationPayload("TQQQ", 2500),
        },
        {
            schema_version: "1.0",
            id: "result-2",
            job_id: "job-2",
            kind: "optimization",
            created_at: "2026-07-26T01:00:00Z",
            payload: optimizationPayload("QLD", 3000),
        },
    ],
};

const reports: ReportListResponse = {
    schema_version: "1.0",
    reports: [
        {
            schema_version: "1.0",
            id: "report-1",
            result_id: "result-1",
            title: "TQQQ 平衡策略",
            created_at: "2026-07-26T02:00:00Z",
            export_status: "not_yet_exported",
            content: {
                status: "not_yet_exported",
                message: "Export from the report endpoint",
                result_id: "result-1",
                optimization: optimizationPayload("TQQQ", 2500),
            },
        },
    ],
};

describe("report and comparison ledger", () => {
    it("selects up to four trusted results and compares their executable ratios", async () => {
        const user = userEvent.setup();
        const api = createStaticResearchApi({
            instruments: {
                schema_version: "1.0",
                instruments: [],
            },
            overview: {
                schema_version: "1.0",
                instrument_count: 0,
                cached_symbols: [],
                formal_result_count: 2,
            },
            health: {
                schema_version: "1.0",
                status: "healthy",
                coverage: [],
            },
            results,
            reports,
        });
        render(
            <MemoryRouter initialEntries={["/reports"]}>
                <App
                    api={api}
                    capability={{
                        mode: "static",
                        dataDate: "2026-07-31",
                    }}
                />
            </MemoryRouter>,
        );

        await user.click(
            await screen.findByLabelText("選取結果 result-1"),
        );
        await user.click(screen.getByLabelText("選取結果 result-2"));

        expect(
            screen.getByRole("table", { name: "結果並排比較" }),
        ).toHaveTextContent("TQQQ");
        expect(
            screen.getByRole("table", { name: "結果並排比較" }),
        ).toHaveTextContent("QLD");
        expect(screen.getByText("25% / 35% / 40%")).toBeVisible();
        expect(screen.getByText("30% / 35% / 40%")).toBeVisible();
        expect(
            screen.getByRole("table", { name: "已儲存研究報告" }),
        ).toHaveTextContent("TQQQ 平衡策略");
        expect(screen.getByText(/靜態備援資料日 2026-07-31/)).toBeVisible();
    });
});
