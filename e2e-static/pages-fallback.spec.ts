import { expect, test } from "@playwright/test";

test("Pages fallback stays static and links only to published reports", async ({
    page,
}) => {
    const apiRequests: string[] = [];
    page.on("request", (request) => {
        const pathname = new URL(request.url()).pathname;
        if (pathname.includes("/api/")) {
            apiRequests.push(pathname);
        }
    });

    await page.goto(".");
    await expect(
        page.getByRole("heading", { name: "市場總覽" }),
    ).toBeVisible();
    await expect(
        page.getByRole("link", { name: "靜態備援資料狀態" }),
    ).toContainText("2026-07-31");

    await page.getByRole("link", { name: "報告與比較" }).click();
    await expect(
        page.getByRole("heading", { name: "已公開報告" }),
    ).toBeVisible();
    await expect(
        page.getByRole("button", { name: "建立私人匯出" }),
    ).toHaveCount(0);

    const publicReports = page.getByRole("link", {
        name: "開啟已公開報告清單",
    });
    await expect(publicReports).toHaveAttribute(
        "href",
        "/drawdown-ledger/reports/index.html",
    );
    await publicReports.click();
    await expect(
        page.getByRole("heading", {
            name: "已通過隱私檢查的公開報告",
        }),
    ).toBeVisible();
    await expect(page.getByText("目前沒有已公開報告。")).toBeVisible();
    expect(apiRequests).toEqual([]);
});

test("Pages fallback supports direct research deep links", async ({
    page,
}) => {
    await page.goto("evidence");
    await expect(
        page.getByRole("heading", { name: "歷史證據" }),
    ).toBeVisible();
    await page.reload();
    await expect(
        page.getByRole("heading", { name: "歷史證據" }),
    ).toBeVisible();
    await expect(page).toHaveURL(
        /\/drawdown-ledger\/evidence$/,
    );
});
