import { Link, useLocation, useSearchParams } from "react-router-dom";

const families = [
    { id: "taiwan-50", label: "台灣 50", ticker: "0050" },
    { id: "taiwan-weighted", label: "台灣加權", ticker: "TWII" },
    { id: "nasdaq-100", label: "NASDAQ-100", ticker: "NDX" },
    { id: "sp-500", label: "S&P 500", ticker: "SPX" },
    {
        id: "dow-jones-industrial-average",
        label: "道瓊工業",
        ticker: "DJI",
    },
    { id: "russell-2000", label: "Russell 2000", ticker: "RUT" },
] as const;

export function InstrumentRail() {
    const location = useLocation();
    const [searchParams] = useSearchParams();
    const selectedFamily = searchParams.get("family") ?? "nasdaq-100";

    return (
        <nav className="instrument-rail" aria-label="標的家族">
            <span className="instrument-rail__label">家族</span>
            <div className="instrument-rail__track">
                {families.map((family) => (
                    <Link
                        key={family.id}
                        to={`${location.pathname}?family=${family.id}`}
                        className={
                            selectedFamily === family.id
                                ? "instrument-chip is-selected"
                                : "instrument-chip"
                        }
                        aria-current={
                            selectedFamily === family.id ? "true" : undefined
                        }
                    >
                        <span>{family.label}</span>
                        <small>{family.ticker}</small>
                    </Link>
                ))}
            </div>
        </nav>
    );
}
