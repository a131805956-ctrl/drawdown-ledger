import { useQuery } from "@tanstack/react-query";

import { useResearchData } from "../lib/api";
import { requiredPolicyCutoff } from "../lib/calendar";
import { LIVE_APPLICATION_URL } from "../lib/deploymentPath";
import { Link } from "../lib/router";

export function DataStatus() {
    const { api, capability } = useResearchData();
    const isStatic = capability.mode === "static";
    const healthQuery = useQuery({
        queryKey: ["data-health"],
        queryFn: api.getDataHealth,
        enabled: !isStatic,
    });
    const requiredCutoff = requiredPolicyCutoff(capability);
    const coverage = healthQuery.data?.coverage ?? [];
    const compliantCount = coverage.filter(
        (row) =>
            row.cached &&
            row.actual_last_session !== null &&
            row.policy_cutoff === requiredCutoff,
    ).length;
    const isNotReady =
        !isStatic &&
        healthQuery.isSuccess &&
        coverage.length > 0 &&
        compliantCount < coverage.length;
    const statusKind = isStatic
        ? "static"
        : healthQuery.isError
          ? "error"
          : isNotReady
            ? "warning"
          : healthQuery.isSuccess
            ? "live"
            : "pending";
    const ariaLabel = isStatic
        ? `靜態備援資料狀態，只能檢視；資料日 ${capability.dataDate}；開啟 Live 服務`
        : healthQuery.isError
          ? "本機資料服務無法連線"
          : isNotReady
            ? `本機資料未就緒，${String(compliantCount)} / ${String(coverage.length)} 符合截止`
          : healthQuery.isSuccess
            ? "本機資料服務可用"
            : "正在檢查本機資料服務";
    const content = (
        <>
            <span className="data-status__signal" aria-hidden="true" />
            <span>
                <strong>
                    {isStatic
                        ? "靜態備援"
                        : isNotReady
                          ? "資料未就緒"
                          : "本機資料服務"}
                </strong>
                <small>
                    {isStatic
                        ? `只能檢視 · 資料日 ${capability.dataDate} · 開啟 Live`
                        : healthQuery.isError
                          ? "檢查 API 服務"
                          : isNotReady
                            ? `${String(compliantCount)} / ${String(coverage.length)} 符合截止`
                            : healthQuery.isSuccess
                              ? "API 可用 · /api/v1"
                              : "正在檢查 · /api/v1"}
                </small>
            </span>
        </>
    );

    if (isStatic) {
        return (
            <a
                href={LIVE_APPLICATION_URL}
                className={`data-status is-${statusKind}`}
                aria-label={ariaLabel}
            >
                {content}
            </a>
        );
    }

    return (
        <Link
            to="/data-health"
            className={`data-status is-${statusKind}`}
            aria-label={ariaLabel}
        >
            {content}
        </Link>
    );
}
