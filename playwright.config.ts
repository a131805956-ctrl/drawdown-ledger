import { defineConfig, devices } from "@playwright/test";

const serverPort = 41873;
const publicBase = "/drawdown-ledger/";
const baseURL = `http://127.0.0.1:${serverPort}${publicBase}`;

export default defineConfig({
    testDir: "./e2e",
    outputDir: "test-results/playwright",
    fullyParallel: true,
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 2 : 0,
    workers: process.env.CI ? 2 : undefined,
    reporter: process.env.CI
        ? [["line"], ["html", { open: "never" }]]
        : [["list"], ["html", { open: "never" }]],
    use: {
        baseURL,
        trace: "retain-on-failure",
        screenshot: "only-on-failure",
        video: "retain-on-failure",
        locale: "zh-TW",
        timezoneId: "Asia/Taipei",
        colorScheme: "light",
    },
    webServer: {
        command:
            `npm --prefix apps/web run build && node e2e/fixtures/mountedSpaServer.mjs ${String(serverPort)} ${publicBase} apps/web/dist`,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
            VITE_DATA_MODE: "live",
            VITE_PUBLIC_BASE: publicBase,
        },
    },
    projects: [
        {
            name: "chromium",
            use: {
                ...devices["Desktop Chrome"],
                viewport: { width: 1440, height: 900 },
            },
        },
    ],
});
