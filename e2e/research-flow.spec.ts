import { expect, test } from "@playwright/test";

import { installResearchApiMocks } from "./fixtures/researchApi";

test("researcher can inspect evidence and run a cash-pool strategy", async ({
    page,
}, testInfo) => {
    const api = await installResearchApiMocks(page);

    await page.goto(".");
    await expect(
        page.getByRole("heading", { name: "市場總覽" }),
    ).toBeVisible();
    await expect(page.getByText("16", { exact: true })).toBeVisible();

    await page.getByRole("link", { name: "歷史證據" }).click();
    await page.getByLabel("指數家族").selectOption("nasdaq-100");
    await page.getByLabel("分析標的").selectOption("TQQQ");
    await page.locator("#evidence-threshold").fill("30");
    await page.getByRole("button", { name: "分析歷史回撤" }).click();

    const conclusion = page.getByRole("note", {
        name: "核心歷史結論",
    });
    await expect(conclusion).toContainText("2 次獨立歷史事件");
    await expect(conclusion).toContainText("一年後平均總報酬");
    await expect(
        page.getByRole("region", { name: "同步研究線圖" }),
    ).toBeVisible();
    await expect(
        page.getByRole("table", { name: "前瞻報酬統計" }),
    ).toBeVisible();

    const evidenceRequest = api.requests.find((request) =>
        request.pathname.endsWith("/evidence/analyze"),
    );
    expect(evidenceRequest?.body).toMatchObject({
        family_id: "nasdaq-100",
        target_symbol: "TQQQ",
        threshold: 0.3,
    });

    await page
        .getByRole("region", { name: "同步研究線圖" })
        .scrollIntoViewIfNeeded();
    const evidenceImage = testInfo.outputPath("desktop-evidence-1440x900.png");
    await page.screenshot({ path: evidenceImage });
    await testInfo.attach("desktop evidence 1440x900", {
        path: evidenceImage,
        contentType: "image/png",
    });

    await page.getByRole("link", { name: "策略實驗室" }).click();
    await page.getByLabel("買進標的").selectOption("TQQQ");
    await page
        .getByRole("button", { name: "執行現金庫回測" })
        .click();

    await expect(
        page.getByRole("heading", { name: "回測結果" }),
    ).toBeVisible();
    await expect(page.getByText("12.4%", { exact: true })).toBeVisible();
    await expect(
        page.getByRole("table", { name: "策略交易紀錄" }),
    ).toContainText("2020-03-17");

    const strategyRequest = api.requests.find((request) =>
        request.pathname.endsWith("/strategies/backtest"),
    );
    expect(strategyRequest?.body).toMatchObject({
        family_id: "nasdaq-100",
        target_symbol: "TQQQ",
        tiers: [
            { depth: "0.20", cash_fraction: "0.25" },
            { depth: "0.30", cash_fraction: "0.35" },
            { depth: "0.40", cash_fraction: "0.40" },
        ],
    });
});

test("deep links survive a direct load", async ({ page }) => {
    await installResearchApiMocks(page);

    await page.goto("evidence");
    await expect(
        page.getByRole("heading", { name: "歷史證據" }),
    ).toBeVisible();
    await page.reload();
    await expect(
        page.getByRole("heading", { name: "歷史證據" }),
    ).toBeVisible();
});
