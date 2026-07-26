import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { RouteState } from "../components/RouteState";
import { useResearchData } from "../lib/api";
import type {
    ReportResponse,
    ResultResponse,
} from "../lib/contracts";

function isOptimizationResult(
    result: ResultResponse,
): result is ResultResponse & {
    payload: Extract<
        ResultResponse["payload"],
        { candidates: unknown }
    >;
} {
    return "candidates" in result.payload;
}

function ratioLine(ratios: readonly number[]): string {
    return ratios
        .map((basisPoints) => `${String(basisPoints / 100)}%`)
        .join(" / ");
}

function percent(value: number): string {
    return new Intl.NumberFormat("zh-TW", {
        style: "percent",
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
    }).format(value);
}

function localDate(value: string): string {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
        ? value
        : new Intl.DateTimeFormat("zh-TW", {
              dateStyle: "medium",
              timeStyle: "short",
          }).format(parsed);
}

function recommendation(
    result: ResultResponse,
    profile: "conservative" | "balanced" | "aggressive",
): string {
    if (!isOptimizationResult(result)) {
        return "舊版";
    }
    const match = result.payload.recommendations.find(
        (item) => item.profile === profile,
    );
    return match === undefined ? "未通過" : ratioLine(match.ratios);
}

function bestCandidate(result: ResultResponse) {
    if (!isOptimizationResult(result)) {
        return null;
    }
    return [...result.payload.candidates].sort(
        (left, right) =>
            right.stability_adjusted_xirr -
            left.stability_adjusted_xirr,
    )[0] ?? null;
}

export function ReportsPage() {
    const { api, capability } = useResearchData();
    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const resultsQuery = useQuery({
        queryKey: ["results"],
        queryFn: api.listResults,
    });
    const reportsQuery = useQuery({
        queryKey: ["reports"],
        queryFn: api.listReports,
    });

    if (resultsQuery.isPending || reportsQuery.isPending) {
        return (
            <RouteState
                kind="loading"
                title="正在整理研究帳本"
                message="讀取正式結果與已建立報告。"
            />
        );
    }
    if (resultsQuery.isError || reportsQuery.isError) {
        return (
            <RouteState
                kind="error"
                title="無法讀取研究帳本"
                message="確認本機資料庫與 API 服務後重試。"
                actionLabel="重新讀取"
                onAction={() => {
                    void resultsQuery.refetch();
                    void reportsQuery.refetch();
                }}
            />
        );
    }

    const results = resultsQuery.data.results;
    const reports = reportsQuery.data.reports;
    const selected = selectedIds
        .map((id) => results.find((result) => result.id === id))
        .filter((result): result is ResultResponse => result !== undefined);
    const toggle = (id: string, checked: boolean) => {
        setSelectedIds((current) => {
            if (!checked) {
                return current.filter((candidate) => candidate !== id);
            }
            return current.length >= 4 || current.includes(id)
                ? current
                : [...current, id];
        });
    };

    return (
        <section className="page reports-ledger">
            <header className="page-heading page-heading--split">
                <div>
                    <p className="eyebrow">Research ledger</p>
                    <h1>報告與比較</h1>
                </div>
                <p className="page-heading__summary">
                    最多並排四個正式結果，先比較穩定性與尾端風險，再決定是否匯出或公開。
                </p>
            </header>

            <div className="report-mode-note">
                <strong>
                    {capability.mode === "static"
                        ? `靜態備援資料日 ${capability.dataDate}`
                        : "本機私人研究帳本"}
                </strong>
                <span>
                    Yahoo 快取、策略設定與未發佈結果不會自動提交 Git。
                </span>
            </div>

            {results.length === 0 ? (
                <div className="research-empty">
                    <span aria-hidden="true">RP</span>
                    <div>
                        <h2>尚無可比較的正式結果</h2>
                        <p>
                            先在 AI 批次完成一個工作；探索模式會保留，但不標示為正式推薦。
                        </p>
                    </div>
                </div>
            ) : (
                <>
                    <section
                        className="result-register"
                        aria-labelledby="stored-results"
                    >
                        <div className="section-heading">
                            <div>
                                <p className="eyebrow">Stored results</p>
                                <h2 id="stored-results">選擇比較結果</h2>
                            </div>
                            <span>
                                已選 {selected.length} / 4
                            </span>
                        </div>
                        <div className="result-register__grid">
                            {results.map((result) => (
                                <ResultChoice
                                    key={result.id}
                                    result={result}
                                    selected={selectedIds.includes(
                                        result.id,
                                    )}
                                    disabled={
                                        selectedIds.length >= 4 &&
                                        !selectedIds.includes(result.id)
                                    }
                                    onToggle={(checked) =>
                                        toggle(result.id, checked)
                                    }
                                />
                            ))}
                        </div>
                    </section>
                    {selected.length === 0 ? (
                        <p className="comparison-prompt">
                            勾選 1—4 個結果後，這裡會建立相同欄位的並排比較。
                        </p>
                    ) : (
                        <ComparisonTable results={selected} />
                    )}
                </>
            )}

            <ReportRegister reports={reports} />
        </section>
    );
}

function ResultChoice({
    result,
    selected,
    disabled,
    onToggle,
}: {
    result: ResultResponse;
    selected: boolean;
    disabled: boolean;
    onToggle: (checked: boolean) => void;
}) {
    const target = isOptimizationResult(result)
        ? result.payload.provenance.target_symbol
        : "Legacy";
    const mode = isOptimizationResult(result)
        ? result.payload.mode
        : "legacy";
    const episodes = isOptimizationResult(result)
        ? result.payload.independent_episode_count
        : null;
    return (
        <label
            className={`result-choice ${selected ? "is-selected" : ""}`}
        >
            <input
                type="checkbox"
                aria-label={`選取結果 ${result.id}`}
                checked={selected}
                disabled={disabled}
                onChange={(event) =>
                    onToggle(event.currentTarget.checked)
                }
            />
            <span className="result-choice__target">{target}</span>
            <strong>{result.id}</strong>
            <small>
                {mode} · {episodes === null ? "—" : `${String(episodes)} events`}
            </small>
            <time>{localDate(result.created_at)}</time>
        </label>
    );
}

function ComparisonTable({
    results,
}: {
    results: readonly ResultResponse[];
}) {
    return (
        <div className="data-table-wrap">
            <table aria-label="結果並排比較">
                <caption>結果並排比較</caption>
                <thead>
                    <tr>
                        <th scope="col">結果</th>
                        <th scope="col">標的</th>
                        <th scope="col">模式 / 事件</th>
                        <th scope="col">保守</th>
                        <th scope="col">平衡</th>
                        <th scope="col">積極</th>
                        <th scope="col">最佳穩定調整 XIRR</th>
                        <th scope="col">最差 5%</th>
                        <th scope="col">提早耗盡率</th>
                        <th scope="col">最長套牢</th>
                    </tr>
                </thead>
                <tbody>
                    {results.map((result) => {
                        const best = bestCandidate(result);
                        const target = isOptimizationResult(result)
                            ? result.payload.provenance.target_symbol
                            : "Legacy";
                        const mode = isOptimizationResult(result)
                            ? `${result.payload.mode} / ${String(result.payload.independent_episode_count)}`
                            : "legacy";
                        return (
                            <tr key={result.id}>
                                <th scope="row">{result.id}</th>
                                <td>{target}</td>
                                <td>{mode}</td>
                                <td>
                                    {recommendation(
                                        result,
                                        "conservative",
                                    )}
                                </td>
                                <td>
                                    {recommendation(
                                        result,
                                        "balanced",
                                    )}
                                </td>
                                <td>
                                    {recommendation(
                                        result,
                                        "aggressive",
                                    )}
                                </td>
                                <td>
                                    {best === null
                                        ? "—"
                                        : percent(
                                              best.stability_adjusted_xirr,
                                          )}
                                </td>
                                <td>
                                    {best === null
                                        ? "—"
                                        : percent(best.worst_5_return)}
                                </td>
                                <td>
                                    {best === null
                                        ? "—"
                                        : percent(
                                              best.early_depletion_rate,
                                          )}
                                </td>
                                <td>
                                    {best === null
                                        ? "—"
                                        : `${String(best.longest_trap_days)} 日`}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}

function ReportRegister({
    reports,
}: {
    reports: readonly ReportResponse[];
}) {
    return (
        <section
            className="published-register"
            aria-labelledby="saved-reports"
        >
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Export ledger</p>
                    <h2 id="saved-reports">已儲存報告</h2>
                </div>
                <span>{reports.length} 份</span>
            </div>
            {reports.length === 0 ? (
                <p className="form-empty">
                    尚無報告。匯出是明確動作，結果不會自動公開。
                </p>
            ) : (
                <div className="data-table-wrap">
                    <table aria-label="已儲存研究報告">
                        <caption>已儲存研究報告</caption>
                        <thead>
                            <tr>
                                <th scope="col">標題</th>
                                <th scope="col">報告 ID</th>
                                <th scope="col">結果 ID</th>
                                <th scope="col">建立時間</th>
                                <th scope="col">匯出狀態</th>
                            </tr>
                        </thead>
                        <tbody>
                            {reports.map((report) => (
                                <tr key={report.id}>
                                    <th scope="row">{report.title}</th>
                                    <td>{report.id}</td>
                                    <td>{report.result_id ?? "—"}</td>
                                    <td>
                                        <time>
                                            {localDate(report.created_at)}
                                        </time>
                                    </td>
                                    <td>
                                        <span
                                            className={`status-pill ${
                                                report.export_status ===
                                                "exported"
                                                    ? "is-ready"
                                                    : "is-missing"
                                            }`}
                                        >
                                            {report.export_status ===
                                            "exported"
                                                ? "已匯出"
                                                : "尚未匯出"}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    );
}
