import { useQuery } from "@tanstack/react-query";

import { RouteState } from "../components/RouteState";
import { useResearchData } from "../lib/api";

const familyNames: Record<string, string> = {
    "taiwan-50": "台灣 50",
    "taiwan-weighted": "台灣加權",
    "nasdaq-100": "NASDAQ-100",
    "sp-500": "S&P 500",
    "dow-jones-industrial-average": "道瓊工業",
    "russell-2000": "Russell 2000",
};

export function MarketOverviewPage() {
    const { api } = useResearchData();
    const overviewQuery = useQuery({
        queryKey: ["market-overview"],
        queryFn: api.getMarketOverview,
    });
    const instrumentsQuery = useQuery({
        queryKey: ["instruments"],
        queryFn: api.getInstruments,
    });

    if (overviewQuery.isPending || instrumentsQuery.isPending) {
        return (
            <RouteState
                kind="loading"
                title="正在讀取市場總覽"
                message="整理標的登錄、快取覆蓋與正式研究結果。"
            />
        );
    }

    if (overviewQuery.isError || instrumentsQuery.isError) {
        return (
            <RouteState
                kind="error"
                title="無法載入市場總覽"
                message="本機資料服務沒有回應。確認 API 已啟動後再重新讀取。"
                actionLabel="重新讀取市場總覽"
                onAction={() => {
                    void overviewQuery.refetch();
                    void instrumentsQuery.refetch();
                }}
            />
        );
    }

    const overview = overviewQuery.data;
    const instruments = instrumentsQuery.data.instruments;
    if (overview.instrument_count === 0 || instruments.length === 0) {
        return (
            <section className="page">
                <PageHeading />
                <RouteState
                    kind="empty"
                    title="尚無市場總覽資料"
                    message="先到資料健康度確認快取，再開始研究。"
                />
            </section>
        );
    }

    const familyCounts = new Map<string, number>();
    for (const instrument of instruments) {
        familyCounts.set(
            instrument.family_id,
            (familyCounts.get(instrument.family_id) ?? 0) + 1,
        );
    }

    return (
        <section className="page">
            <PageHeading />
            <div className="overview-grid">
                <div className="metric-strip" aria-label="研究資料摘要">
                    <article className="metric-card">
                        <span>登錄標的</span>
                        <strong>{overview.instrument_count}</strong>
                        <small>正向 1×—3×</small>
                    </article>
                    <article className="metric-card">
                        <span>資料覆蓋</span>
                        <strong>
                            {overview.cached_symbols.length} /{" "}
                            {overview.instrument_count}
                        </strong>
                        <small>已快取序列</small>
                    </article>
                    <article className="metric-card">
                        <span>正式結果</span>
                        <strong>{overview.formal_result_count}</strong>
                        <small>可追溯紀錄</small>
                    </article>
                </div>
                <DepthLedger />
                <section className="family-register" aria-labelledby="families">
                    <div className="section-heading">
                        <div>
                            <p className="eyebrow">Instrument register</p>
                            <h2 id="families">研究家族</h2>
                        </div>
                        <span>{familyCounts.size} 個家族已載入</span>
                    </div>
                    <div className="family-register__grid">
                        {[...familyCounts].map(([familyId, count]) => (
                            <article
                                className="family-register__item"
                                key={familyId}
                            >
                                <strong>
                                    {familyNames[familyId] ?? familyId}
                                </strong>
                                <span>{count} 個標的</span>
                            </article>
                        ))}
                    </div>
                </section>
            </div>
        </section>
    );
}

function PageHeading() {
    return (
        <header className="page-heading page-heading--split">
            <div>
                <p className="eyebrow">Market ledger · Overview</p>
                <h1>市場總覽</h1>
            </div>
            <p className="page-heading__summary">
                先確認資料覆蓋，再進入回撤證據。這裡只呈現 API 已確認的登錄與快取狀態。
            </p>
        </header>
    );
}

function DepthLedger() {
    return (
        <figure className="depth-ledger" aria-label="回撤深度帶">
            <figcaption>
                <span>
                    <small>Drawdown depth ledger</small>
                    <strong>回撤深度尺</strong>
                </span>
                <em>原型訊號 · 收盤判定</em>
            </figcaption>
            <div className="depth-ledger__canvas" role="img" aria-label="從前高到負百分之五十的回撤深度帶">
                {[0, -10, -20, -30, -40, -50].map((depth) => (
                    <div className="depth-band" key={depth}>
                        <span>{depth === 0 ? "ATH" : `${String(depth)}%`}</span>
                    </div>
                ))}
                <p>
                    真實走勢將由證據工作台的原型價格序列載入；此處不以示意線替代市場資料。
                </p>
            </div>
        </figure>
    );
}
