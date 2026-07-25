import { Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { DataHealthPage } from "../pages/DataHealthPage";
import { MarketOverviewPage } from "../pages/MarketOverviewPage";

interface PlaceholderPageProps {
    title: string;
    eyebrow: string;
    message: string;
}

function PlaceholderPage({
    title,
    eyebrow,
    message,
}: PlaceholderPageProps) {
    return (
        <section className="page page--quiet">
            <header className="page-heading">
                <p className="eyebrow">{eyebrow}</p>
                <h1>{title}</h1>
            </header>
            <div className="route-state route-state--empty">
                <span className="route-state__index" aria-hidden="true">
                    —
                </span>
                <div>
                    <h2>研究工作區尚未開啟</h2>
                    <p>{message}</p>
                </div>
            </div>
        </section>
    );
}

export function AppRoutes() {
    return (
        <Routes>
            <Route element={<AppShell />}>
                <Route index element={<MarketOverviewPage />} />
                <Route
                    path="evidence"
                    element={
                        <PlaceholderPage
                            title="歷史證據"
                            eyebrow="Evidence workbench"
                            message="下一階段將接入獨立回撤事件、每日重疊樣本與次日開盤證據。"
                        />
                    }
                />
                <Route
                    path="strategy"
                    element={
                        <PlaceholderPage
                            title="策略實驗室"
                            eyebrow="Cash-pool simulator"
                            message="下一階段將接入現金庫規則、門檻階梯與基準比較。"
                        />
                    }
                />
                <Route
                    path="ai"
                    element={
                        <PlaceholderPage
                            title="AI 批次"
                            eyebrow="Parameter search"
                            message="下一階段將接入可取消的參數搜尋與三種風險候選。"
                        />
                    }
                />
                <Route
                    path="reports"
                    element={
                        <PlaceholderPage
                            title="報告與比較"
                            eyebrow="Research ledger"
                            message="完成研究後，可在這裡並排比較與匯出可追溯結果。"
                        />
                    }
                />
                <Route
                    path="data-health"
                    element={<DataHealthPage />}
                />
                <Route
                    path="*"
                    element={
                        <PlaceholderPage
                            title="找不到這個研究頁面"
                            eyebrow="404"
                            message="請使用主要功能導覽回到已定義的研究路徑。"
                        />
                    }
                />
            </Route>
        </Routes>
    );
}
