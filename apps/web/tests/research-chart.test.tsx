import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
    ResearchChart,
    type ResearchChartModel,
} from "../src/features/chart/ResearchChart";

const model: ResearchChartModel = {
    prototype: {
        symbol: "^NDX",
        sourceKind: "actual",
        points: [
            {
                session: "2020-01-02",
                close: 100,
                totalReturnClose: 100,
                drawdown: 0,
            },
            {
                session: "2020-02-03",
                close: 110,
                totalReturnClose: 120,
                drawdown: -0.1,
            },
        ],
    },
    actual: {
        symbol: "TQQQ",
        sourceKind: "actual",
        points: [
            {
                session: "2020-01-02",
                close: 50,
                totalReturnClose: 50,
                drawdown: 0,
            },
            {
                session: "2020-02-03",
                close: 100,
                totalReturnClose: 75,
                drawdown: -0.5,
            },
        ],
    },
    synthetic: {
        symbol: "TQQQ-synthetic-3x",
        sourceKind: "synthetic",
        points: [
            {
                session: "2020-01-02",
                close: 40,
                totalReturnClose: 40,
                drawdown: 0,
            },
            {
                session: "2020-02-03",
                close: 20,
                totalReturnClose: 20,
                drawdown: -0.5,
            },
        ],
    },
};

describe("research chart measurement controls", () => {
    it("lets keyboard users choose two dates and measures the explicitly selected visible series", async () => {
        const user = userEvent.setup();
        render(<ResearchChart model={model} height={320} />);

        const series = screen.getByLabelText("量測序列");
        expect(series).toHaveValue("prototype");
        await user.selectOptions(series, "actual");
        const start = screen.getByLabelText("量測起點");
        const end = screen.getByLabelText("量測終點");
        expect(start).toHaveAttribute("type", "date");
        expect(end).toHaveAttribute("type", "date");
        await user.type(start, "2020-01-02");
        await user.type(end, "2020-02-03");

        const readout = screen.getByRole("group", {
            name: "實際 TQQQ 兩點量測結果",
        });
        expect(readout).toHaveTextContent("100.0%");
        expect(readout).toHaveTextContent("50.0%");
        expect(readout).not.toHaveTextContent("10.0%");

        await user.click(
            screen.getByRole("checkbox", { name: "實際 TQQQ" }),
        );

        expect(series).toHaveValue("prototype");
        expect(
            within(series).queryByRole("option", { name: "實際 TQQQ" }),
        ).not.toBeInTheDocument();
    });
});
