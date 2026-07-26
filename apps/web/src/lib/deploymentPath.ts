export const DEFAULT_PUBLIC_BASE_PATH = "/drawdown-ledger/";

function normalisePublicBasePath(value: string): string {
    const trimmed = value.trim();
    if (
        trimmed === "" ||
        trimmed === "/" ||
        trimmed === "." ||
        trimmed === "./"
    ) {
        return "";
    }
    if (
        trimmed.includes("\\") ||
        trimmed.includes("?") ||
        trimmed.includes("#") ||
        trimmed.includes("%")
    ) {
        throw new TypeError("Invalid public base path");
    }
    const withLeadingSlash = trimmed.startsWith("/")
        ? trimmed
        : `/${trimmed}`;
    const withoutTrailingSlash = withLeadingSlash.replace(/\/+$/, "");
    const segments = withoutTrailingSlash.slice(1).split("/");
    if (
        segments.some(
            (segment) =>
                segment === "" ||
                segment === "." ||
                segment === ".." ||
                !/^[A-Za-z0-9._~-]+$/.test(segment),
        )
    ) {
        throw new TypeError("Invalid public base path");
    }
    return withoutTrailingSlash;
}

export function apiVersionPath(publicBasePath: string): string {
    return `${normalisePublicBasePath(publicBasePath)}/api/v1`;
}
