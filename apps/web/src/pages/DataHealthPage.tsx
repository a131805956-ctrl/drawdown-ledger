import { useQuery } from "@tanstack/react-query";

import { RouteState } from "../components/RouteState";
import { useResearchData } from "../lib/api";

export function DataHealthPage() {
    const { api, capability } = useResearchData();
    const healthQuery = useQuery({
        queryKey: ["data-health"],
        queryFn: api.getDataHealth,
    });

    if (healthQuery.isPending) {
        return (
            <RouteState
                kind="loading"
                title="正在檢查資料健康度"
                message="核對每個序列的政策截止與實際最後交易日。"
            />
        );
    }

    if (healthQuery.isError) {
        return (
            <RouteState
                kind="error"
                title="無法讀取資料健康度"
                message="確認本機 API 已啟動，或切換到已發布的靜態資料集。"
                actionLabel="重新檢查資料"
                onAction={() => {
                    void healthQuery.refetch();
                }}
            />
        );
    }

    const rows = healthQuery.data.coverage;
    const cachedCount = rows.filter((row) => row.cached).length;

    return (
        <section className="page">
            <header className="page-heading page-heading--split">
                <div>
                    <p className="eyebrow">Data lineage · Coverage</p>
                    <h1>資料健康度</h1>
                </div>
                <p className="page-heading__summary">
                    政策截止日與實際最後交易日分開顯示；缺少快取時，不假裝資料已更新。
                </p>
            </header>

            {rows.length === 0 ? (
                <RouteState
                    kind="empty"
                    title="目前沒有可檢查的資料序列"
                    message={
                        capability.mode === "static"
                            ? "這份靜態備援尚未附帶資料健康度清單。"
                            : "啟動資料服務並完成第一次市場資料更新。"
                    }
                />
            ) : (
                <>
                    <div className="health-summary">
                        <article>
                            <span>API 狀態</span>
                            <strong>可用</strong>
                            <small>schema 1.0</small>
                        </article>
                        <article>
                            <span>已快取</span>
                            <strong>
                                {cachedCount} / {rows.length}
                            </strong>
                            <small>逐代碼追蹤</small>
                        </article>
                        <article>
                            <span>資料模式</span>
                            <strong>
                                {capability.mode === "live" ? "本機" : "靜態"}
                            </strong>
                            <small>
                                {capability.mode === "live"
                                    ? "同源 API"
                                    : "固定快照"}
                            </small>
                        </article>
                    </div>
                    <div className="data-table-wrap">
                        <table>
                            <caption>
                                市場序列覆蓋與政策截止狀態
                            </caption>
                            <thead>
                                <tr>
                                    <th scope="col">代碼</th>
                                    <th scope="col">快取</th>
                                    <th scope="col">政策截止日</th>
                                    <th scope="col">實際最後交易日</th>
                                    <th scope="col">判讀</th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows.map((row) => {
                                    const current =
                                        row.cached &&
                                        row.policy_cutoff !== null &&
                                        row.policy_cutoff ===
                                            row.actual_last_session;
                                    return (
                                        <tr key={row.symbol}>
                                            <th scope="row">{row.symbol}</th>
                                            <td>
                                                <span
                                                    className={`status-pill ${row.cached ? "is-ready" : "is-missing"}`}
                                                >
                                                    {row.cached
                                                        ? "已快取"
                                                        : "尚未快取"}
                                                </span>
                                            </td>
                                            <td>
                                                <DateValue
                                                    value={row.policy_cutoff}
                                                />
                                            </td>
                                            <td>
                                                <DateValue
                                                    value={
                                                        row.actual_last_session
                                                    }
                                                />
                                            </td>
                                            <td>
                                                {current
                                                    ? "符合截止政策"
                                                    : "需要檢查"}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </section>
    );
}

function DateValue({ value }: { value: string | null }) {
    return value ? (
        <time dateTime={value}>{value}</time>
    ) : (
        <span className="muted-value">—</span>
    );
}
