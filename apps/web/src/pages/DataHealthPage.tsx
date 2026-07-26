import {
    useMutation,
    useQuery,
    useQueryClient,
} from "@tanstack/react-query";

import { RouteState } from "../components/RouteState";
import {
    researchApiErrorDetails,
    researchApiErrorMessage,
    useResearchData,
} from "../lib/api";
import {
    researchAsOfDate,
    requiredPolicyCutoff,
} from "../lib/calendar";
import type { DataCoverage } from "../lib/contracts";

type CoverageJudgement =
    | "符合截止政策"
    | "資料過期"
    | "資料缺漏";

function coverageJudgement(
    row: DataCoverage,
    requiredCutoff: string,
): CoverageJudgement {
    if (
        !row.cached ||
        row.policy_cutoff === null ||
        row.actual_last_session === null
    ) {
        return "資料缺漏";
    }
    return row.policy_cutoff === requiredCutoff
        ? "符合截止政策"
        : "資料過期";
}

export function DataHealthPage() {
    const { api, capability } = useResearchData();
    const queryClient = useQueryClient();
    const requiredCutoff = requiredPolicyCutoff(capability);
    const updateAsOf = researchAsOfDate();
    const healthQuery = useQuery({
        queryKey: ["data-health"],
        queryFn: api.getDataHealth,
    });
    const updateMutation = useMutation({
        mutationFn: () => api.updateData(updateAsOf),
        onSuccess: async (result) => {
            if (
                result.status === "failed" ||
                result.status === "not_configured"
            ) {
                return;
            }
            const [health, overview] = await Promise.all([
                api.getDataHealth(),
                api.getMarketOverview(),
            ]);
            queryClient.setQueryData(["data-health"], health);
            queryClient.setQueryData(["market-overview"], overview);
        },
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
                message={researchApiErrorMessage(
                    healthQuery.error,
                    "確認本機 API 已啟動，或切換到已發布的靜態資料集。",
                )}
                actionLabel="重新檢查資料"
                onAction={() => {
                    void healthQuery.refetch();
                }}
            />
        );
    }

    const rows = healthQuery.data.coverage;
    const compliantCount = rows.filter(
        (row) =>
            coverageJudgement(row, requiredCutoff) ===
            "符合截止政策",
    ).length;

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

            {capability.mode === "live" ? (
                <section
                    className="data-update-panel"
                    aria-labelledby="data-update-heading"
                >
                    <div>
                        <p className="eyebrow">Live data refresh</p>
                        <h2 id="data-update-heading">
                            更新至要求截止日
                        </h2>
                        <p>
                            以 {updateAsOf} 為基準，補齊本機快取至{" "}
                            <strong>{requiredCutoff}</strong>。既有快取會保留到新資料驗證完成。
                        </p>
                    </div>
                    <button
                        type="button"
                        className="primary-action"
                        disabled={updateMutation.isPending}
                        onClick={() => {
                            updateMutation.mutate();
                        }}
                    >
                        {updateMutation.isPending
                            ? "正在更新市場資料…"
                            : `一鍵更新至 ${requiredCutoff}`}
                    </button>
                    {updateMutation.data?.status === "completed" ||
                    updateMutation.data?.status === "partial" ? (
                        <div
                            className="data-update-result"
                            role="status"
                        >
                            <strong>
                                {updateMutation.data.status === "completed"
                                    ? "更新完成"
                                    : "部分更新完成"}
                            </strong>
                            <span>
                                截止{" "}
                                {updateMutation.data.cutoff ??
                                    requiredCutoff}
                                ，共送出{" "}
                                {updateMutation.data.request_count} 次資料請求。
                            </span>
                            <span>
                                {updateMutation.data.refreshed_symbols
                                    .length > 0
                                    ? updateMutation.data.refreshed_symbols.join(
                                          "、",
                                      )
                                    : "所有序列原本已符合截止。"}
                            </span>
                        </div>
                    ) : null}
                    {updateMutation.data?.status === "not_configured" ? (
                        <div className="inline-alert" role="alert">
                            <strong>市場資料更新服務尚未設定</strong>
                            <span>
                                {updateMutation.data.message ??
                                    "請從 Live 服務執行資料更新。"}
                            </span>
                        </div>
                    ) : null}
                    {updateMutation.data?.status === "failed" ? (
                        <div className="inline-alert" role="alert">
                            <strong>市場資料更新失敗</strong>
                            <span>
                                {updateMutation.data.message ??
                                    "舊快取已保留，請查看逐標的錯誤。"}
                            </span>
                        </div>
                    ) : null}
                    {(updateMutation.data?.failures?.length ?? 0) > 0 ||
                    updateMutation.isError ? (
                        <div
                            className="data-update-errors"
                            role="alert"
                        >
                            <h3>逐標的錯誤</h3>
                            <ul>
                                {updateMutation.data?.failures?.map(
                                    (failure) => (
                                        <li key={failure.symbol}>
                                            {failure.symbol}：
                                            {failure.message}
                                        </li>
                                    ),
                                )}
                                {updateMutation.isError
                                    ? researchApiErrorDetails(
                                          updateMutation.error,
                                          "市場資料更新失敗；舊快取已保留。",
                                      ).map((detail) => (
                                          <li key={detail}>{detail}</li>
                                      ))
                                    : null}
                            </ul>
                        </div>
                    ) : null}
                </section>
            ) : null}

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
                            <span>符合截止</span>
                            <strong>
                                {compliantCount} / {rows.length}
                            </strong>
                            <small>要求 {requiredCutoff}</small>
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
                                    const judgement =
                                        coverageJudgement(
                                            row,
                                            requiredCutoff,
                                        );
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
                                                {judgement}
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
