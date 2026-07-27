/* eslint-disable react-refresh/only-export-components, no-useless-assignment */

import {
    useEffect,
    type InputHTMLAttributes,
} from "react";

function decimalPlaces(value: number): number {
    const text = String(value);
    const exponent = text.indexOf("e-");
    if (exponent >= 0) {
        return Number(text.slice(exponent + 2));
    }
    const point = text.indexOf(".");
    return point < 0 ? 0 : text.length - point - 1;
}

function constrain(value: number, input: HTMLInputElement): number {
    const min = input.min === "" ? Number.NEGATIVE_INFINITY : Number(input.min);
    const max = input.max === "" ? Number.POSITIVE_INFINITY : Number(input.max);
    return Math.min(max, Math.max(min, value));
}

function dateValue(value: string, delta: number, step: number): string | null {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return null;
    }
    const date = new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(date.valueOf())) {
        return null;
    }
    date.setUTCDate(date.getUTCDate() + delta * step);
    return date.toISOString().slice(0, 10);
}

/** Apply one middle-wheel increment to a focused number/date input. */
export function adjustInputByWheel(input: HTMLInputElement, deltaY: number): boolean {
    if (deltaY === 0 || (input.type !== "number" && input.type !== "date")) {
        return false;
    }
    if (typeof document !== "undefined" && document.activeElement !== input) {
        return false;
    }

    const direction = deltaY < 0 ? 1 : -1;
    const rawStep = input.step === "" || input.step === "any" ? 1 : Number(input.step);
    const step = Number.isFinite(rawStep) && rawStep > 0 ? rawStep : 1;
    let next: string | null = null;

    if (input.type === "date") {
        next = dateValue(input.value, direction, step);
        if (next !== null && input.min !== "" && next < input.min) {
            next = input.min;
        }
        if (next !== null && input.max !== "" && next > input.max) {
            next = input.max;
        }
    } else {
        const current = Number(input.value);
        const base = Number.isFinite(current)
            ? current
            : input.min === ""
              ? 0
              : Number(input.min);
        if (!Number.isFinite(base)) {
            return false;
        }
        const precision = decimalPlaces(step);
        const value = constrain(base + direction * step, input);
        next = value.toFixed(precision).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
    }

    if (next === null || next === input.value) {
        return false;
    }
    input.value = next;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
}

export type MiddleWheelInputProps = InputHTMLAttributes<HTMLInputElement>;

export function MiddleWheelInput({ onWheel, ...props }: MiddleWheelInputProps) {
    return (
        <input
            {...props}
            onWheel={(event) => {
                if (adjustInputByWheel(event.currentTarget, event.deltaY)) {
                    event.preventDefault();
                }
                onWheel?.(event);
            }}
        />
    );
}

/** Enable the same interaction for existing native inputs across all pages. */
export function useMiddleWheelInputs(): void {
    useEffect(() => {
        const listener = (event: WheelEvent) => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement)) {
                return;
            }
            if (adjustInputByWheel(target, event.deltaY)) {
                event.preventDefault();
            }
        };
        document.addEventListener("wheel", listener, {
            capture: true,
            passive: false,
        });
        return () =>
            document.removeEventListener("wheel", listener, { capture: true });
    }, []);
}
