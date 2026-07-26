import { expect, test } from "@playwright/test";

import { installResearchApiMocks } from "./fixtures/researchApi";

const viewports = [
    { width: 412, height: 915, label: "412x915" },
    { width: 405, height: 720, label: "405x720" },
] as const;

for (const viewport of viewports) {
    test(`mobile evidence layout fits ${viewport.label}`, async ({
        page,
    }, testInfo) => {
        await page.setViewportSize(viewport);
        await page.emulateMedia({ reducedMotion: "reduce" });
        await installResearchApiMocks(page);

        await page.goto("evidence");
        await page.keyboard.press("Tab");
        await expect(page.getByRole("link", { name: "跳至主要內容" }))
            .toBeFocused();
        await page.getByRole("button", { name: "分析歷史回撤" }).click();
        await expect(
            page.getByRole("note", { name: "核心歷史結論" }),
        ).toBeVisible();

        const geometry = await page.evaluate(() => ({
            viewportWidth: window.innerWidth,
            documentHeight: document.documentElement.scrollHeight,
            offenders: [...document.querySelectorAll<HTMLElement>("body *")]
                .map((element) => ({
                    tag: element.tagName.toLowerCase(),
                    id: element.id,
                    className: element.className,
                    left: Math.round(element.getBoundingClientRect().left),
                    right: Math.round(element.getBoundingClientRect().right),
                    width: Math.round(element.getBoundingClientRect().width),
                }))
                .filter(
                    (entry, index) => {
                        const element =
                            document.querySelectorAll<HTMLElement>("body *")[
                                index
                            ];
                        const intentionallyScrollable = element?.closest(
                            ".instrument-rail__track, .chart-toolbar, .chart-series-toggle, .chart-stage, .data-table-wrap",
                        );
                        return (
                            intentionallyScrollable === null &&
                            (entry.left < -1 ||
                                entry.right > window.innerWidth + 1)
                        );
                    },
                )
                .slice(0, 12),
        }));
        expect(geometry.offenders).toEqual([]);
        expect(geometry.documentHeight).toBeGreaterThan(viewport.height);

        await page.evaluate(() => window.scrollTo({ left: 0, top: window.scrollY }));
        await page.mouse.move(1, 1);
        await page.mouse.wheel(10_000, 0);
        expect(await page.evaluate(() => window.scrollX)).toBe(0);

        const navigation = page.getByRole("navigation", {
            name: "主要功能",
        });
        const navigationBox = await navigation.boundingBox();
        expect(navigationBox).not.toBeNull();
        expect(Math.round((navigationBox?.y ?? 0) + (navigationBox?.height ?? 0)))
            .toBe(viewport.height);

        const image = testInfo.outputPath(
            `mobile-evidence-${viewport.label}.png`,
        );
        await page.screenshot({ path: image });
        await testInfo.attach(`mobile evidence ${viewport.label}`, {
            path: image,
            contentType: "image/png",
        });
    });

    test(`mobile report ledger contains its own grid at ${viewport.label}`, async ({
        page,
    }) => {
        await page.setViewportSize(viewport);
        await page.emulateMedia({ reducedMotion: "reduce" });
        await installResearchApiMocks(page);

        await page.goto("reports");
        await expect(
            page.getByRole("heading", { name: "報告與比較" }),
        ).toBeVisible();

        const geometry = await page
            .locator(".reports-ledger")
            .evaluate((ledger) => {
                const ledgerRect = ledger.getBoundingClientRect();
                const offenders = [
                    ...ledger.querySelectorAll<HTMLElement>(":scope > *"),
                ]
                    .map((element) => {
                        const rect = element.getBoundingClientRect();
                        return {
                            className: element.className,
                            left: Math.round(rect.left),
                            right: Math.round(rect.right),
                        };
                    })
                    .filter(
                        (entry) =>
                            entry.left < ledgerRect.left - 1 ||
                            entry.right > ledgerRect.right + 1,
                    );
                return {
                    clientWidth: ledger.clientWidth,
                    scrollWidth: ledger.scrollWidth,
                    ledgerLeft: Math.round(ledgerRect.left),
                    ledgerRight: Math.round(ledgerRect.right),
                    offenders,
                };
            });

        expect(geometry.scrollWidth).toBeLessThanOrEqual(
            geometry.clientWidth,
        );
        expect(geometry.offenders).toEqual([]);
    });
}
