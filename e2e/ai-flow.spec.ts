import { expect, test } from "@playwright/test";

import { installResearchApiMocks } from "./fixtures/researchApi";

test("AI mode exposes deterministic controls and completes a grid search", async ({
    page,
}) => {
    const api = await installResearchApiMocks(page);

    await page.goto("ai");
    const runButton = page.getByRole("button", {
        name: "開始窮舉分析",
    });
    await expect(runButton).toHaveAttribute(
        "data-ai-action",
        "run-optimization",
    );
    await expect(page.locator("#ai-depths")).toHaveAttribute(
        "data-ai-field",
        "depths_percent",
    );

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "匯出設定 JSON" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(
        "drawdown-optimization-request.json",
    );

    await runButton.click();
    await expect(
        page.getByRole("heading", { name: "三種可執行方案" }),
    ).toBeVisible();
    await expect(
        page.getByRole("table", { name: "Pareto 候選策略" }),
    ).toContainText("25% / 35% / 40%");
    await expect(
        page.getByRole("table", { name: "Pareto 候選策略" }),
    ).toContainText("合格");

    const machineResult = JSON.parse(
        await page
            .locator("[data-ai-result='result-json']")
            .inputValue(),
    ) as {
        id: string;
        payload: {
            candidates: Array<{
                walk_forward_eligible: boolean;
            }>;
        };
    };
    expect(machineResult.id).toBe("result-e2e");
    expect(
        machineResult.payload.candidates[0]?.walk_forward_eligible,
    ).toBe(true);

    const createRequest = api.requests.find((request) =>
        request.pathname.endsWith("/optimizations"),
    );
    expect(createRequest?.body).toMatchObject({
        family_id: "nasdaq-100",
        target_symbol: "TQQQ",
        depths: ["0.20", "0.30", "0.40"],
        ratio_search: {
            minimum_basis_points: 0,
            maximum_basis_points: 10_000,
            step_basis_points: 5_000,
            monotone: true,
        },
        walk_forward: {
            n_splits: 3,
        },
        synthetic_stress: {
            enabled: true,
        },
    });
});
