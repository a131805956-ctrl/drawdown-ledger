import { useQuery } from "@tanstack/react-query";

import { useResearchData } from "../lib/api";
import { Link } from "../lib/router";

export function DataStatus() {
    const { api, capability } = useResearchData();
    const isStatic = capability.mode === "static";
    const healthQuery = useQuery({
        queryKey: ["data-health"],
        queryFn: api.getDataHealth,
        enabled: !isStatic,
    });
    const statusKind = isStatic
        ? "static"
        : healthQuery.isError
          ? "error"
          : healthQuery.isSuccess
            ? "live"
            : "pending";
    const ariaLabel = isStatic
        ? "靜態備援資料狀態"
        : healthQuery.isError
          ? "本機資料服務無法連線"
          : healthQuery.isSuccess
            ? "本機資料服務可用"
            : "正在檢查本機資料服務";

    return (
        <Link
            to="/data-health"
            className={`data-status is-${statusKind}`}
            aria-label={ariaLabel}
        >
            <span className="data-status__signal" aria-hidden="true" />
            <span>
                <strong>{isStatic ? "靜態備援" : "本機資料服務"}</strong>
                <small>
                    {isStatic
                        ? capability.dataDate
                        : healthQuery.isError
                          ? "檢查 API 服務"
                          : healthQuery.isSuccess
                            ? "API 可用 · /api/v1"
                            : "正在檢查 · /api/v1"}
                </small>
            </span>
        </Link>
    );
}
