import {
    apiVersionPath,
    DEFAULT_PUBLIC_BASE_PATH,
} from "../src/lib/deploymentPath";

describe("deployment paths", () => {
    it("uses the owned Funnel and Pages mount by default", () => {
        expect(DEFAULT_PUBLIC_BASE_PATH).toBe("/drawdown-ledger/");
    });

    it.each([
        ["/", "/api/v1"],
        ["", "/api/v1"],
        ["./", "/api/v1"],
        ["/drawdown-ledger/", "/drawdown-ledger/api/v1"],
        ["drawdown-ledger", "/drawdown-ledger/api/v1"],
    ])("resolves API requests within public base %s", (base, expected) => {
        expect(apiVersionPath(base)).toBe(expected);
    });

    it("rejects a public base containing traversal or a query", () => {
        expect(() => apiVersionPath("/../private/")).toThrow(
            "Invalid public base path",
        );
        expect(() => apiVersionPath("/drawdown-ledger/?admin=true")).toThrow(
            "Invalid public base path",
        );
    });
});
