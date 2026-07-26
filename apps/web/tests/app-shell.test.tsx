import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "../src/app/App";
import { MemoryRouter } from "../src/lib/router";

describe("research application shell", () => {
    it("exposes all six research destinations", () => {
        render(
            <MemoryRouter initialEntries={["/"]}>
                <App />
            </MemoryRouter>,
        );

        expect(
            screen.getByRole("navigation", { name: "主要功能" }),
        ).toBeVisible();

        for (const name of [
            "市場總覽",
            "歷史證據",
            "策略實驗室",
            "AI 批次",
            "報告與比較",
            "資料健康度",
        ]) {
            expect(screen.getByRole("link", { name })).toBeVisible();
        }
    });

    it("moves keyboard focus into the research content", async () => {
        const user = userEvent.setup();
        render(
            <MemoryRouter initialEntries={["/evidence"]}>
                <App />
            </MemoryRouter>,
        );

        const skipLink = screen.getByRole("link", {
            name: "跳至主要內容",
        });
        expect(skipLink).toHaveAttribute("href", "#main-content");

        await user.click(skipLink);

        expect(screen.getByRole("main")).toHaveFocus();
    });

    it("navigates between workbench routes without a third-party router", async () => {
        const user = userEvent.setup();
        render(
            <MemoryRouter initialEntries={["/"]}>
                <App />
            </MemoryRouter>,
        );

        await user.click(screen.getByRole("link", { name: "歷史證據" }));

        expect(
            screen.getByRole("heading", { name: "歷史證據" }),
        ).toBeVisible();
        expect(
            screen.getByRole("link", { name: "歷史證據" }),
        ).toHaveAttribute("aria-current", "page");
    });
});
