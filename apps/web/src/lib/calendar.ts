const RESEARCH_TIME_ZONE = "Asia/Taipei";

export type CutoffCapability =
    | { mode: "live" }
    | { mode: "static"; dataDate: string };

function calendarPart(
    parts: readonly Intl.DateTimeFormatPart[],
    type: "year" | "month" | "day",
): number {
    const value = parts.find((part) => part.type === type)?.value;
    if (value === undefined) {
        throw new RangeError(`Missing ${type} in calendar date`);
    }
    return Number(value);
}

export function researchAsOfDate(reference = new Date()): string {
    const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: RESEARCH_TIME_ZONE,
        year: "numeric",
        month: "numeric",
        day: "numeric",
    }).formatToParts(reference);
    const year = calendarPart(parts, "year");
    const month = calendarPart(parts, "month");
    const day = calendarPart(parts, "day");
    return [
        String(year).padStart(4, "0"),
        String(month).padStart(2, "0"),
        String(day).padStart(2, "0"),
    ].join("-");
}

export function priorCalendarMonthEnd(reference = new Date()): string {
    const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: RESEARCH_TIME_ZONE,
        year: "numeric",
        month: "numeric",
    }).formatToParts(reference);
    const year = calendarPart(parts, "year");
    const month = calendarPart(parts, "month");
    return new Date(Date.UTC(year, month - 1, 0))
        .toISOString()
        .slice(0, 10);
}

export function requiredPolicyCutoff(
    capability: CutoffCapability,
    reference = new Date(),
): string {
    return capability.mode === "static"
        ? capability.dataDate
        : priorCalendarMonthEnd(reference);
}
