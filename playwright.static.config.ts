import { defineConfig, devices } from "@playwright/test";

const serverPort = 41874;
const publicBase = "/drawdown-ledger/";
const baseURL = `http://127.0.0.1:${String(serverPort)}${publicBase}`;

export default defineConfig({
    testDir: "./e2e-static",
    outputDir: "test-results/playwright-static",
    fullyParallel: true,
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 2 : 0,
    workers: 1,
    reporter: process.env.CI
        ? [
              ["line"],
              [
                  "html",
                  {
                      open: "never",
                      outputFolder: "playwright-report-static",
                  },
              ],
          ]
        : [
              ["list"],
              [
                  "html",
                  {
                      open: "never",
                      outputFolder: "playwright-report-static",
                  },
              ],
          ],
    use: {
        baseURL,
        trace: "retain-on-failure",
        screenshot: "only-on-failure",
        locale: "zh-TW",
        timezoneId: "Asia/Taipei",
        colorScheme: "light",
    },
    webServer: {
        command:
            `node e2e/fixtures/staticPagesServer.mjs ${String(serverPort)} ${publicBase}`,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
    },
    projects: [
        {
            name: "static-chromium",
            use: {
                ...devices["Desktop Chrome"],
                viewport: { width: 1440, height: 900 },
            },
        },
    ],
});
