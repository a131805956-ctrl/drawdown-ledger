import { expect, test } from "@playwright/test";

import { installResearchApiMocks } from "./fixtures/researchApi";

test("researcher explicitly exports a private report bundle", async ({
    page,
}) => {
    const api = await installResearchApiMocks(page);

    await page.goto("reports");
    await expect(
        page.getByRole("heading", { name: "報告與比較" }),
    ).toBeVisible();
    await expect(
        page.getByRole("heading", {
            name: "建立可驗證報告 bundle",
        }),
    ).toBeVisible();

    await page
        .getByRole("button", { name: "建立私人匯出" })
        .click();
    await expect(
        page.getByRole("status"),
    ).toContainText("export-0123456789abcdef01234567");

    const request = api.requests.find(
        (candidate) =>
            candidate.method === "POST" &&
            candidate.pathname.endsWith("/reports/export"),
    );
    expect(request?.pathname).toBe(
        "/drawdown-ledger/api/v1/reports/export",
    );
    expect(request?.body).toEqual({
        schema_version: "1.0",
        result_id: "illustrative-result-2026-07-31",
        formats: ["html", "json", "csv"],
    });
});
