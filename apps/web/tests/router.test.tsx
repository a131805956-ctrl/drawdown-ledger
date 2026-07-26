import { render, screen } from "@testing-library/react";

import { App } from "../src/app/App";
import { BrowserRouter } from "../src/lib/router";

describe("browser router base path", () => {
    afterEach(() => {
        window.history.replaceState(null, "", "/");
    });

    it("routes a deployment nested beneath the public application path", () => {
        window.history.replaceState(
            null,
            "",
            "/drawdown-ledger/evidence?family=nasdaq-100",
        );

        render(
            <BrowserRouter basename="/drawdown-ledger/">
                <App />
            </BrowserRouter>,
        );

        expect(
            screen.getByRole("heading", { name: "歷史證據" }),
        ).toBeVisible();
        expect(
            screen.getByRole("link", { name: "歷史證據" }),
        ).toHaveAttribute("href", "/drawdown-ledger/evidence");
    });
});
