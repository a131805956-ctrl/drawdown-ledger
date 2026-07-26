import {
    Route,
    Routes,
    useSearchParams,
} from "../lib/router";

import { AppShell } from "../components/AppShell";
import { AiBatchPage } from "../pages/AiBatchPage";
import { DataHealthPage } from "../pages/DataHealthPage";
import { EvidencePage } from "../pages/EvidencePage";
import { MarketOverviewPage } from "../pages/MarketOverviewPage";
import { StrategyPage } from "../pages/StrategyPage";

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

function EvidenceRoute() {
    const [parameters] = useSearchParams();
    const family = parameters.get("family") ?? "nasdaq-100";
    return <EvidencePage key={family} />;
}

function StrategyRoute() {
    const [parameters] = useSearchParams();
    const family = parameters.get("family") ?? "nasdaq-100";
    return <StrategyPage key={family} />;
}

export function AppRoutes() {
    return (
        <Routes>
            <Route element={<AppShell />}>
                <Route index element={<MarketOverviewPage />} />
                <Route
                    path="evidence"
                    element={<EvidenceRoute />}
                />
                <Route
                    path="strategy"
                    element={<StrategyRoute />}
                />
                <Route
                    path="ai"
                    element={<AiBatchPage />}
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
