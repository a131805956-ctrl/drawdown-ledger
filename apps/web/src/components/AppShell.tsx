import { NavLink, Outlet } from "react-router-dom";

import { DataStatus } from "./DataStatus";
import { InstrumentRail } from "./InstrumentRail";

const destinations = [
    { to: "/", label: "市場總覽", shortLabel: "總覽", mark: "OV" },
    { to: "/evidence", label: "歷史證據", shortLabel: "證據", mark: "EV" },
    {
        to: "/strategy",
        label: "策略實驗室",
        shortLabel: "策略",
        mark: "ST",
    },
    { to: "/ai", label: "AI 批次", shortLabel: "AI", mark: "AI" },
    {
        to: "/reports",
        label: "報告與比較",
        shortLabel: "報告",
        mark: "RP",
    },
    {
        to: "/data-health",
        label: "資料健康度",
        shortLabel: "資料",
        mark: "DH",
    },
] as const;

export function AppShell() {
    return (
        <div className="app-shell">
            <a className="skip-link" href="#main-content">
                跳至主要內容
            </a>
            <aside className="sidebar">
                <div className="brand-lockup">
                    <span className="brand-mark" aria-hidden="true">
                        DL
                    </span>
                    <span className="brand-copy">
                        <strong>Drawdown Ledger</strong>
                        <small>回撤帳本</small>
                    </span>
                </div>
                <nav className="primary-nav" aria-label="主要功能">
                    {destinations.map((destination) => (
                        <NavLink
                            key={destination.to}
                            to={destination.to}
                            end={destination.to === "/"}
                            className={({ isActive }) =>
                                isActive
                                    ? "primary-nav__link is-active"
                                    : "primary-nav__link"
                            }
                        >
                            <span
                                className="primary-nav__mark"
                                aria-hidden="true"
                            >
                                {destination.mark}
                            </span>
                            <span className="primary-nav__full">
                                {destination.label}
                            </span>
                            <span
                                className="primary-nav__short"
                                aria-hidden="true"
                            >
                                {destination.shortLabel}
                            </span>
                        </NavLink>
                    ))}
                </nav>
                <p className="sidebar-note">
                    歷史研究與決策紀律工具
                    <span>不提供即時喊單</span>
                </p>
            </aside>
            <div className="workspace">
                <header className="workspace-header">
                    <div>
                        <p className="workspace-header__kicker">Research desk</p>
                        <p className="workspace-header__title">
                            每一筆結論，都能回到資料與假設
                        </p>
                    </div>
                    <DataStatus />
                </header>
                <InstrumentRail />
                <main id="main-content" className="main-content">
                    <Outlet />
                </main>
            </div>
        </div>
    );
}
