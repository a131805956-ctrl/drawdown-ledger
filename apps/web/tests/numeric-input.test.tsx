import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { MiddleWheelInput } from "../src/components/MiddleWheelInput";

describe("middle wheel numeric controls", () => {
    it("increments a focused number input with wheel up and decrements with wheel down", () => {
        function Harness() {
            const [value, setValue] = useState("10");
            return (
                <MiddleWheelInput
                    aria-label="allocation"
                    type="number"
                    min={0}
                    max={12}
                    step={1}
                    value={value}
                    onChange={(event) => setValue(event.currentTarget.value)}
                />
            );
        }

        render(<Harness />);
        const input = screen.getByRole("spinbutton", {
            name: "allocation",
        });
        input.focus();
        fireEvent.wheel(input, { deltaY: -100 });
        expect(input).toHaveValue(11);
        fireEvent.wheel(input, { deltaY: 100 });
        expect(input).toHaveValue(10);
    });

    it("moves a focused date input by one step without scrolling the page", () => {
        function Harness() {
            const [value, setValue] = useState("2026-07-27");
            return (
                <MiddleWheelInput
                    aria-label="start date"
                    type="date"
                    step={1}
                    value={value}
                    onChange={(event) => setValue(event.currentTarget.value)}
                />
            );
        }

        render(<Harness />);
        const input = screen.getByLabelText("start date");
        input.focus();
        fireEvent.wheel(input, { deltaY: -1 });
        expect(input).toHaveValue("2026-07-28");
    });
});
