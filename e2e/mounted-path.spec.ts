import { expect, test } from "@playwright/test";

import { installResearchApiMocks } from "./fixtures/researchApi";

test("all browser requests stay inside the owned public mount", async ({
    page,
}) => {
    const escapedRequests: string[] = [];
    page.on("request", (request) => {
        const url = new URL(request.url());
        if (
            url.hostname === "127.0.0.1" &&
            !url.pathname.startsWith("/drawdown-ledger/")
        ) {
            escapedRequests.push(`${request.resourceType()}: ${url.pathname}`);
        }
    });
    const api = await installResearchApiMocks(page);

    await page.goto("evidence");
    await expect(
        page.getByRole("heading", { name: "歷史證據" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "分析歷史回撤" }).click();
    await expect(
        page.getByRole("note", { name: "核心歷史結論" }),
    ).toBeVisible();

    expect(
        api.requests.some(
            (request) =>
                request.pathname ===
                "/drawdown-ledger/api/v1/evidence/analyze",
        ),
    ).toBe(true);
    expect(escapedRequests).toEqual([]);
    await expect(page).toHaveURL(
        /\/drawdown-ledger\/evidence$/,
    );

    await page.reload();
    await expect(
        page.getByRole("heading", { name: "歷史證據" }),
    ).toBeVisible();
});
