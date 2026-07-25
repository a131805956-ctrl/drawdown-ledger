import { Link } from "react-router-dom";

import { useResearchData } from "../lib/api";

export function DataStatus() {
    const { capability } = useResearchData();
    const isStatic = capability.mode === "static";

    return (
        <Link
            to="/data-health"
            className={`data-status ${isStatic ? "is-static" : "is-live"}`}
            aria-label={
                isStatic ? "靜態備援資料狀態" : "本機資料服務狀態"
            }
        >
            <span className="data-status__signal" aria-hidden="true" />
            <span>
                <strong>{isStatic ? "靜態備援" : "本機資料服務"}</strong>
                <small>
                    {isStatic
                        ? (capability.dataDate ?? "固定資料集")
                        : "同源 API · /api/v1"}
                </small>
            </span>
        </Link>
    );
}
