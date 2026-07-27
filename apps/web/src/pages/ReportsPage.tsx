import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { RouteState } from "../components/RouteState";
import { ResearchChart, type ResearchChartModel } from "../features/chart/ResearchChart";
import { useResearchData, type ResearchApi } from "../lib/api";
import type {
    MarketSeriesResponse,
    ReportExportRequest,
    ReportExportResponse,
    ReportResponse,
    ResultResponse,
} from "../lib/contracts";

type ReportFormat = NonNullable<
    ReportExportRequest["formats"]
>[number];

const reportFormats: readonly ReportFormat[] = [
    "html",
    "json",
    "csv",
];

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

function exportedContentSummary(report: ReportResponse): string {
    if (
        "status" in report.content &&
        report.content.status === "exported"
    ) {
        const formats = Object.keys(report.content.artifacts)
            .map((format) => format.toUpperCase())
            .join("、");
        return `${report.content.export_id} · ${formats}`;
    }
    if ("content_type" in report.content) {
        return `舊版 schema ${report.content.stored_schema_version}`;
    }
    return "—";
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

function reportChartModel(series: MarketSeriesResponse): ResearchChartModel {
    const convert = (source: typeof series.actual) => ({
        symbol: source.symbol,
        sourceKind: source.source_kind,
        points: source.points.map((point) => ({
            session: point.session,
            close: point.close,
            totalReturnClose: point.total_return_close,
            drawdown: point.drawdown,
        })),
    });
    return {
        prototype: convert(series.prototype),
        actual: convert(series.actual),
        synthetic: series.synthetic === null ? null : convert(series.synthetic),
    };
}

export function ReportsPage() {
    const { api, capability } = useResearchData();
    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const [expandedResultId, setExpandedResultId] = useState<string | null>(null);
    const [exportResultId, setExportResultId] = useState("");
    const [selectedFormats, setSelectedFormats] =
        useState<ReportFormat[]>([...reportFormats]);
    const resultsQuery = useQuery({
        queryKey: ["results"],
        queryFn: api.listResults,
    });
    const reportsQuery = useQuery({
        queryKey: ["reports"],
        queryFn: api.listReports,
    });
    const exportMutation = useMutation({
        mutationFn: (request: ReportExportRequest) =>
            api.exportReport(request),
        onSuccess: () => reportsQuery.refetch(),
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
    const effectiveExportResultId = results.some(
        (result) => result.id === exportResultId,
    )
        ? exportResultId
        : (results[0]?.id ?? "");
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
                                    expanded={expandedResultId === result.id}
                                    onToggle={(checked) =>
                                        toggle(result.id, checked)
                                    }
                                    onOpen={() =>
                                        setExpandedResultId((current) =>
                                            current === result.id ? null : result.id,
                                        )
                                    }
                                />
                            ))}
                        </div>
                        {expandedResultId === null ? null : (() => {
                            const expanded = results.find(
                                (result) => result.id === expandedResultId,
                            );
                            return expanded === undefined ? null : (
                                <ResultDetail result={expanded} api={api} />
                            );
                        })()}
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

            <ReportExportPanel
                capability={capability}
                results={results}
                resultId={effectiveExportResultId}
                selectedFormats={selectedFormats}
                pending={exportMutation.isPending}
                error={exportMutation.isError}
                exported={exportMutation.data}
                onResultChange={setExportResultId}
                onFormatChange={(format, checked) => {
                    setSelectedFormats((current) =>
                        checked
                            ? reportFormats.filter(
                                  (candidate) =>
                                      current.includes(candidate) ||
                                      candidate === format,
                              )
                            : current.filter(
                                  (candidate) => candidate !== format,
                              ),
                    );
                }}
                onExport={() => {
                    exportMutation.mutate({
                        schema_version: "1.0",
                        result_id: effectiveExportResultId,
                        formats: selectedFormats,
                    });
                }}
            />
            <ReportRegister reports={reports} />
        </section>
    );
}

function ReportExportPanel({
    capability,
    results,
    resultId,
    selectedFormats,
    pending,
    error,
    exported,
    onResultChange,
    onFormatChange,
    onExport,
}: {
    capability: ReturnType<typeof useResearchData>["capability"];
    results: readonly ResultResponse[];
    resultId: string;
    selectedFormats: readonly ReportFormat[];
    pending: boolean;
    error: boolean;
    exported: ReportExportResponse | undefined;
    onResultChange: (resultId: string) => void;
    onFormatChange: (format: ReportFormat, checked: boolean) => void;
    onExport: () => void;
}) {
    if (capability.mode === "static") {
        return (
            <section
                className="report-export-panel"
                aria-labelledby="public-report-heading"
            >
                <div>
                    <p className="eyebrow">Public fallback</p>
                    <h2 id="public-report-heading">已公開報告</h2>
                    <p>
                        靜態備援不連接私人資料庫，只顯示經過隱私與內容一致性驗證的固定報告。
                    </p>
                </div>
                <a
                    className="report-export-panel__public-link"
                    href={`${import.meta.env.BASE_URL}reports/index.html`}
                >
                    開啟已公開報告清單
                </a>
            </section>
        );
    }

    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        onExport();
    };
    return (
        <section
            className="report-export-panel"
            aria-labelledby="private-export-heading"
        >
            <div>
                <p className="eyebrow">Private export</p>
                <h2 id="private-export-heading">建立可驗證報告 bundle</h2>
                <p>
                    此動作只建立私人 bundle；公開仍須經過獨立的發布與隱私檢查。
                </p>
            </div>
            <form onSubmit={submit}>
                <label className="report-export-panel__result">
                    <span>匯出結果</span>
                    <select
                        aria-label="匯出結果"
                        value={resultId}
                        disabled={pending || results.length === 0}
                        onChange={(event) =>
                            onResultChange(event.currentTarget.value)
                        }
                    >
                        {results.map((result) => (
                            <option key={result.id} value={result.id}>
                                {result.id}
                                {isOptimizationResult(result)
                                    ? ` · ${result.payload.provenance.target_symbol}`
                                    : ""}
                            </option>
                        ))}
                    </select>
                </label>
                <fieldset>
                    <legend>格式</legend>
                    {reportFormats.map((format) => (
                        <label key={format}>
                            <input
                                type="checkbox"
                                checked={selectedFormats.includes(format)}
                                disabled={pending}
                                onChange={(event) =>
                                    onFormatChange(
                                        format,
                                        event.currentTarget.checked,
                                    )
                                }
                            />
                            <span>{format.toUpperCase()}</span>
                        </label>
                    ))}
                </fieldset>
                <button
                    type="submit"
                    disabled={
                        pending ||
                        resultId.length === 0 ||
                        selectedFormats.length === 0
                    }
                >
                    {pending ? "正在建立…" : "建立私人匯出"}
                </button>
            </form>
            {error ? (
                <p className="action-status is-error" role="alert">
                    匯出失敗；結果或資料 lineage 不完整時系統會拒絕建立報告。
                </p>
            ) : null}
            {exported === undefined ? null : (
                <p className="action-status" role="status">
                    已建立 {exported.export_id}（
                    {Object.keys(exported.artifacts)
                        .map((format) => format.toUpperCase())
                        .join("、")}
                    ）。仍位於私人報告目錄。
                </p>
            )}
        </section>
    );
}

function ResultDetail({
    result,
    api,
}: {
    result: ResultResponse;
    api: ResearchApi;
}) {
    if (!isOptimizationResult(result)) {
        return (
            <section className="result-detail" aria-label={`${result.id} 唯讀詳情`}>
                <p>此結果為舊版格式，沒有可重建的策略曲線。</p>
            </section>
        );
    }
    const provenance = result.payload.provenance;
    // All persisted results use one immutable payload shape for the detail panel.
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const seriesQuery = useQuery({
        queryKey: ["report-detail-series", result.id, provenance.target_symbol],
        queryFn: () => api.getMarketSeries({
            family_id: provenance.family_id,
            target_symbol: provenance.target_symbol,
            include_synthetic: true,
            max_points: 15_000,
            start: provenance.strategy_start,
            end: provenance.strategy_end,
        }),
    });
    const best = bestCandidate(result);
    return (
        <section className="result-detail" aria-label={`${result.id} 唯讀詳情`}>
            <div className="result-detail__heading">
                <div>
                    <p className="eyebrow">Read-only result dossier</p>
                    <h3>{result.id} · {provenance.target_symbol}</h3>
                </div>
                <span>{provenance.strategy_start} → {provenance.strategy_end}</span>
            </div>
            <div className="result-detail__facts">
                <span>獨立事件<strong>{result.payload.independent_episode_count}</strong></span>
                <span>模式<strong>{result.payload.mode}</strong></span>
                <span>資料來源<strong>{provenance.source_kind} / {provenance.prototype_symbol}</strong></span>
                <span>最佳穩定 XIRR<strong>{best === null ? "—" : percent(best.stability_adjusted_xirr)}</strong></span>
            </div>
            <div className="result-detail__ratios">
                {result.payload.recommendations.map((item) => (
                    <article key={item.profile}>
                        <span>{item.profile}</span>
                        <strong>{ratioLine(item.ratios)}</strong>
                        <small>OOS {percent(item.oos_xirr)} · 穩定 {percent(item.stability_adjusted_xirr)}</small>
                    </article>
                ))}
            </div>
            {seriesQuery.isPending ? <p className="form-empty">載入實體 K 線資料…</p> : null}
            {seriesQuery.isError ? (
                <p className="inline-alert" role="alert">此結果的實體 K 線暫時無法載入，統計與參數仍可唯讀檢視。</p>
            ) : null}
            {seriesQuery.data === undefined ? null : <ResearchChart model={reportChartModel(seriesQuery.data)} height={460} />}
            <div className="data-table-wrap result-detail__candidate-table">
                <table aria-label={`${result.id} 候選方案明細`}>
                    <caption>候選比例與穩定性明細（唯讀）</caption>
                    <thead><tr><th>比例</th><th>OOS XIRR</th><th>穩定分數</th><th>最差 5%</th><th>早期耗盡率</th><th>最長套牢</th></tr></thead>
                    <tbody>{result.payload.candidates.map((candidate) => (
                        <tr key={candidate.ratios.join("-")}>
                            <td>{ratioLine(candidate.ratios)}</td>
                            <td>{percent(candidate.oos_xirr)}</td>
                            <td>{candidate.stability_score.toFixed(2)}</td>
                            <td>{percent(candidate.worst_5_return)}</td>
                            <td>{percent(candidate.early_depletion_rate)}</td>
                            <td>{candidate.longest_trap_days} 天</td>
                        </tr>
                    ))}</tbody>
                </table>
            </div>
        </section>
    );
}

function ResultChoice({
    result,
    selected,
    disabled,
    expanded,
    onToggle,
    onOpen,
}: {
    result: ResultResponse;
    selected: boolean;
    disabled: boolean;
    expanded: boolean;
    onToggle: (checked: boolean) => void;
    onOpen: () => void;
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
            <button
                type="button"
                className="result-choice__detail"
                aria-label={`${result.id} 開啟完整詳情`}
                aria-expanded={expanded}
                onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    onOpen();
                }}
            >
                {expanded ? "收合詳情" : "開啟完整詳情"}
            </button>
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
                                <th scope="col">匯出內容</th>
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
                                    <td>
                                        {exportedContentSummary(report)}
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
