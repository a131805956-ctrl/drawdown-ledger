from drawdown_lab.domain.instruments import INSTRUMENT_FAMILIES


def test_registry_contains_only_approved_positive_leverage_families() -> None:
    symbols = {item.symbol for family in INSTRUMENT_FAMILIES for item in family.instruments}

    assert {"0050.TW", "00631L.TW", "006204.TW", "00685L.TW"} <= symbols
    assert {
        "QQQ",
        "QLD",
        "TQQQ",
        "SPY",
        "SSO",
        "UPRO",
        "DIA",
        "DDM",
        "UDOW",
        "IWM",
        "UWM",
        "URTY",
    } <= symbols
    assert {"00662.TW", "00670L.TW", "00646.TW", "00647L.TW"}.isdisjoint(symbols)
