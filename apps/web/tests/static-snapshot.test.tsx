import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "../src/app/App";
import { staticResearchSnapshot } from "../src/demo/staticSnapshot";
import { createStaticResearchApi } from "../src/lib/api";
import { MemoryRouter } from "../src/lib/router";

describe("published illustrative snapshot", () => {
    it("keeps pre-inception TQQQ history out of top-level actual evidence", () => {
        const evidence = staticResearchSnapshot.evidence;
        expect(evidence).toBeDefined();
        if (evidence === undefined) {
            return;
        }

        expect(evidence.n_episode).toBe(1);
        expect(evidence.n_executed_episode).toBe(1);
        expect(evidence.episodes).toHaveLength(1);
        expect(
            evidence.episodes.every(
                (episode) =>
                    episode.entry_date !== null &&
                    episode.entry_date >= "2010-02-11",
            ),
        ).toBe(true);
        expect(evidence.episode_statistics[0]).toEqual(
            expect.objectContaining({
                n: 1,
                mean_total_return: 0.82,
                median_total_return: 0.82,
                win_rate: 1,
            }),
        );
        expect(staticResearchSnapshot.marketSeries?.synthetic).toEqual(
            expect.objectContaining({
                source_kind: "synthetic",
                symbol: "TQQQ-synthetic-3x",
            }),
        );
    });

    it("renders a conclusion whose count and annual statistics match the actual episode ledger", async () => {
        const user = userEvent.setup();
        render(
            <MemoryRouter initialEntries={["/evidence"]}>
                <App
                    api={createStaticResearchApi(staticResearchSnapshot)}
                    capability={{
                        mode: "static",
                        dataDate: "2026-07-31",
                    }}
                />
            </MemoryRouter>,
        );

        await user.click(
            await screen.findByRole("button", {
                name: "分析歷史回撤",
            }),
        );

        const conclusion = await screen.findByRole("note", {
            name: "核心歷史結論",
        });
        expect(conclusion).toHaveTextContent("1 次獨立歷史事件");
        expect(conclusion).toHaveTextContent("一年後平均總報酬為 82.0%");
        expect(conclusion).toHaveTextContent("勝率 100.0%");
        expect(conclusion).toHaveTextContent("0 次在一年後仍未獲利");
        expect(
            screen.getByRole("table", { name: "獨立回撤事件" }),
        ).not.toHaveTextContent("2008");
    });
});
