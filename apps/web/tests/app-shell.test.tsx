import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "../src/app/App";

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

    it("offers a keyboard bypass to the research content", () => {
        render(
            <MemoryRouter initialEntries={["/evidence"]}>
                <App />
            </MemoryRouter>,
        );

        expect(
            screen.getByRole("link", { name: "跳至主要內容" }),
        ).toHaveAttribute("href", "#main-content");
    });
});
