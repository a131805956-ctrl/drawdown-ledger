import type { StaticResearchSnapshot } from "../lib/api";
import type {
    Instrument,
    MarketSeriesResponse,
} from "../lib/contracts";

const DATA_DATE = "2026-07-31";

function instrument(
    symbol: string,
    name: string,
    familyId: string,
    leverage: number,
    prototypeSymbol: string,
    currency: string,
    timezone: string,
): Instrument {
    return {
        symbol,
        name,
        family_id: familyId,
        leverage,
        prototype_symbol: prototypeSymbol,
        currency,
        timezone,
        inception: null,
    };
}

const instruments: Instrument[] = [
    instrument(
        "0050.TW",
        "元大台灣50",
        "taiwan-50",
        1,
        "0050.TW",
        "TWD",
        "Asia/Taipei",
    ),
    instrument(
        "00631L.TW",
        "元大台灣50正2",
        "taiwan-50",
        2,
        "0050.TW",
        "TWD",
        "Asia/Taipei",
    ),
    instrument(
        "006204.TW",
        "永豐臺灣加權",
        "taiwan-weighted",
        1,
        "^TWII",
        "TWD",
        "Asia/Taipei",
    ),
    instrument(
        "00685L.TW",
        "群益臺灣加權正2",
        "taiwan-weighted",
        2,
        "^TWII",
        "TWD",
        "Asia/Taipei",
    ),
    instrument(
        "QQQ",
        "Invesco QQQ Trust",
        "nasdaq-100",
        1,
        "^NDX",
        "USD",
        "America/New_York",
    ),
    instrument(
        "QLD",
        "ProShares Ultra QQQ",
        "nasdaq-100",
        2,
        "^NDX",
        "USD",
        "America/New_York",
    ),
    instrument(
        "TQQQ",
        "ProShares UltraPro QQQ",
        "nasdaq-100",
        3,
        "^NDX",
        "USD",
        "America/New_York",
    ),
    instrument(
        "SPY",
        "SPDR S&P 500 ETF Trust",
        "sp-500",
        1,
        "^GSPC",
        "USD",
        "America/New_York",
    ),
    instrument(
        "SSO",
        "ProShares Ultra S&P500",
        "sp-500",
        2,
        "^GSPC",
        "USD",
        "America/New_York",
    ),
    instrument(
        "UPRO",
        "ProShares UltraPro S&P500",
        "sp-500",
        3,
        "^GSPC",
        "USD",
        "America/New_York",
    ),
    instrument(
        "DIA",
        "SPDR Dow Jones Industrial Average ETF Trust",
        "dow-jones-industrial-average",
        1,
        "^DJI",
        "USD",
        "America/New_York",
    ),
    instrument(
        "DDM",
        "ProShares Ultra Dow30",
        "dow-jones-industrial-average",
        2,
        "^DJI",
        "USD",
        "America/New_York",
    ),
    instrument(
        "UDOW",
        "ProShares UltraPro Dow30",
        "dow-jones-industrial-average",
        3,
        "^DJI",
        "USD",
        "America/New_York",
    ),
    instrument(
        "IWM",
        "iShares Russell 2000 ETF",
        "russell-2000",
        1,
        "^RUT",
        "USD",
        "America/New_York",
    ),
    instrument(
        "UWM",
        "ProShares Ultra Russell2000",
        "russell-2000",
        2,
        "^RUT",
        "USD",
        "America/New_York",
    ),
    instrument(
        "URTY",
        "ProShares UltraPro Russell2000",
        "russell-2000",
        3,
        "^RUT",
        "USD",
        "America/New_York",
    ),
];

function chartPoint(
    session: string,
    close: number,
    drawdown: number,
    totalReturnClose = close,
): MarketSeriesResponse["actual"]["points"][number] {
    return {
        session,
        open: close * 0.995,
        high: close * 1.01,
        low: close * 0.985,
        close,
        total_return_close: totalReturnClose,
        normalized_total_return: totalReturnClose,
        drawdown,
    };
}

const marketSeries: MarketSeriesResponse = {
    schema_version: "1.0",
    family_id: "nasdaq-100",
    target_symbol: "TQQQ",
    prototype_symbol: "^NDX",
    prototype_source: "benchmark",
    handoff_session: "2010-02-11",
    source_label: "trusted_local_cache",
    prototype: {
        symbol: "^NDX",
        leverage: 1,
        source_kind: "actual",
        unit: "index",
        currency: "USD",
        actual_last_session: DATA_DATE,
        policy_cutoff: DATA_DATE,
        points: [
            chartPoint("2019-12-31", 100, 0, 100),
            chartPoint("2020-02-19", 118, 0, 118),
            chartPoint("2020-03-16", 81.2, -0.312, 81.5),
            chartPoint("2020-03-23", 78, -0.339, 78.4),
            chartPoint("2020-08-06", 119, 0, 119.8),
            chartPoint("2021-03-17", 145, 0, 147),
            chartPoint(DATA_DATE, 220, 0, 228),
        ],
    },
    actual: {
        symbol: "TQQQ",
        leverage: 3,
        source_kind: "actual",
        unit: "price",
        currency: "USD",
        actual_last_session: DATA_DATE,
        policy_cutoff: DATA_DATE,
        points: [
            chartPoint("2019-12-31", 100, 0, 100),
            chartPoint("2020-02-19", 132, 0, 132),
            chartPoint("2020-03-16", 51, -0.614, 51.3),
            chartPoint("2020-03-23", 43, -0.674, 43.4),
            chartPoint("2020-08-06", 142, 0, 143),
            chartPoint("2021-03-17", 183, 0, 186),
            chartPoint(DATA_DATE, 380, 0, 410),
        ],
    },
    synthetic: {
        symbol: "TQQQ-synthetic-3x",
        leverage: 3,
        source_kind: "synthetic",
        unit: "price",
        currency: null,
        actual_last_session: DATA_DATE,
        policy_cutoff: DATA_DATE,
        points: [
            chartPoint("2008-08-29", 100, 0, 100),
            chartPoint("2008-10-10", 31, -0.69, 31),
            chartPoint("2009-03-09", 18, -0.82, 18),
            chartPoint("2010-02-10", 87, -0.13, 87),
        ],
    },
};

const optimizationPayload = {
    schema_version: "1.0" as const,
    mode: "formal" as const,
    exploration_only: false,
    independent_episode_count: 12,
    provenance: {
        family_id: "nasdaq-100",
        prototype_symbol: "^NDX",
        target_symbol: "TQQQ",
        source_kind: "actual" as const,
        strategy_start: "2011-01-03",
        strategy_end: DATA_DATE,
        walk_forward_splits: 3,
        ratio_unit: "basis_points" as const,
    },
    synthetic_stress: {
        requested: true,
        evaluated_candidates: 66,
        passed_candidates: 42,
    },
    recommendations: [
        {
            profile: "conservative" as const,
            ratios: [2000, 3000, 5000],
            oos_xirr: 0.101,
            stability_adjusted_xirr: 0.092,
        },
        {
            profile: "balanced" as const,
            ratios: [2500, 3500, 4000],
            oos_xirr: 0.126,
            stability_adjusted_xirr: 0.115,
        },
        {
            profile: "aggressive" as const,
            ratios: [3000, 3500, 3500],
            oos_xirr: 0.144,
            stability_adjusted_xirr: 0.12,
        },
    ],
    candidates: [
        {
            ratios: [2500, 3500, 4000],
            fold_oos_xirr: [0.09, 0.13, 0.16],
            oos_xirr: 0.126,
            stability_score: 0.91,
            stability_adjusted_xirr: 0.115,
            neighbor_count: 4,
            worst_5_return: -0.18,
            early_depletion_rate: 0.1,
            longest_trap_days: 650,
            synthetic_stress_pass: true,
            pareto_member: true,
            fold_evaluations: [],
            walk_forward_eligible: true,
            recommendation_labels: ["balanced" as const],
        },
    ],
};

const rolesBySymbol = new Map<
    string,
    Array<"tradable" | "prototype" | "prototype_proxy">
>();
for (const item of instruments) {
    rolesBySymbol.set(item.symbol, ["tradable"]);
}
rolesBySymbol.set("0050.TW", ["tradable", "prototype"]);
rolesBySymbol.set("006204.TW", ["tradable", "prototype_proxy"]);
rolesBySymbol.set("QQQ", ["tradable", "prototype_proxy"]);
rolesBySymbol.set("SPY", ["tradable", "prototype_proxy"]);
rolesBySymbol.set("DIA", ["tradable", "prototype_proxy"]);
rolesBySymbol.set("IWM", ["tradable", "prototype_proxy"]);
for (const benchmark of ["^TWII", "^NDX", "^GSPC", "^DJI", "^RUT"]) {
    rolesBySymbol.set(benchmark, ["prototype"]);
}

export const staticResearchSnapshot: StaticResearchSnapshot = {
    instruments: {
        schema_version: "1.0",
        instruments,
    },
    overview: {
        schema_version: "1.0",
        instrument_count: 16,
        cached_symbols: [...rolesBySymbol.keys()],
        formal_result_count: 1,
    },
    health: {
        schema_version: "1.0",
        status: "healthy",
        coverage: [...rolesBySymbol].map(([symbol, roles]) => ({
            symbol,
            cached: true,
            actual_last_session: DATA_DATE,
            policy_cutoff: DATA_DATE,
            roles,
        })),
    },
    evidenceThreshold: 0.3,
    evidence: {
        schema_version: "1.0",
        family_id: "nasdaq-100",
        target_symbol: "TQQQ",
        prototype_symbol: "^NDX",
        prototype_source: "benchmark",
        prototype_actual_last_session: DATA_DATE,
        prototype_policy_cutoff: DATA_DATE,
        target_actual_last_session: DATA_DATE,
        target_policy_cutoff: DATA_DATE,
        source_kind: "actual",
        source_label: "trusted_local_cache",
        n_day: 1,
        n_episode: 1,
        n_executed_episode: 1,
        daily_statistics: [
            {
                horizon_sessions: 252,
                independent: false,
                mean_total_return: 0.82,
                median_total_return: 0.82,
                win_rate: 1,
                expected_shortfall_5: 0.82,
                confidence_lower: 0.21,
                confidence_upper: 1,
                n: 1,
                overlap_warning: "Single illustrative observation",
                sample_kind: "daily",
            },
        ],
        episode_statistics: [
            {
                horizon_sessions: 252,
                independent: true,
                mean_total_return: 0.82,
                median_total_return: 0.82,
                win_rate: 1,
                expected_shortfall_5: 0.82,
                confidence_lower: 0.21,
                confidence_upper: 1,
                n: 1,
                overlap_warning: null,
                sample_kind: "episode",
            },
        ],
        episodes: [
            {
                cycle_id: 1,
                threshold: 0.3,
                peak_date: "2020-02-19",
                peak_price: 118,
                signal_date: "2020-03-16",
                signal_price: 81.2,
                signal_drawdown: -0.312,
                entry_date: "2020-03-17",
                entry_price: "54.00",
                recovery_date: "2020-08-06",
                recovery_sessions: 99,
                mae: -0.16,
                mfe: 0.61,
                v_recovered: true,
                forward_returns: [
                    {
                        horizon_sessions: 252,
                        exit_date: "2021-03-17",
                        total_return: 0.82,
                    },
                ],
            },
        ],
    },
    marketSeries,
    results: {
        schema_version: "1.0",
        results: [
            {
                schema_version: "1.0",
                id: "illustrative-result-2026-07-31",
                job_id: "illustrative-job",
                kind: "optimization",
                created_at: "2026-07-31T00:00:00Z",
                payload: optimizationPayload,
            },
        ],
    },
    reports: {
        schema_version: "1.0",
        reports: [
            {
                schema_version: "1.0",
                id: "illustrative-report-2026-07-31",
                result_id: "illustrative-result-2026-07-31",
                title: "固定示例｜TQQQ 30% 原型回撤研究",
                created_at: "2026-07-31T00:00:00Z",
                export_status: "not_yet_exported",
                content: {
                    status: "not_yet_exported",
                    message:
                        "Bundled illustrative report; not live market data.",
                    result_id: "illustrative-result-2026-07-31",
                    optimization: optimizationPayload,
                },
            },
        ],
    },
};
