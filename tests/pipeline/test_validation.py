import pandas as pd

from pipeline.config import Config
from pipeline.validation.checks import check_coverage, check_stale, has_error, validate_symbol
from tests.helpers import make_prices
from datetime import date

CFG = Config(large_move_pct={"HOSE": 7.0, "default": 15.0})


def codes(issues):
    return {i.check_code for i in issues}


def test_clean_data_has_no_errors():
    assert not has_error(validate_symbol("A", make_prices("A"), CFG))


def test_each_error_check():
    base = make_prices("A", n=250)
    assert codes(validate_symbol("A", base.iloc[0:0], CFG)) == {"EMPTY"}
    d = pd.concat([base, base.iloc[[5]]]); assert "DUPLICATE_DATE" in codes(validate_symbol("A", d, CFG))
    d = base.copy(); d.loc[3, "open"] = 0; assert "NON_POSITIVE_PRICE" in codes(validate_symbol("A", d, CFG))
    d = base.copy(); d.loc[3, ["high", "low", "close"]] = [100.0, 200.0, 150.0]; assert "HIGH_LT_LOW" in codes(validate_symbol("A", d, CFG))
    d = base.copy(); d.loc[3, "close"] = d.loc[3, "high"] * 2; assert "CLOSE_OUT_OF_RANGE" in codes(validate_symbol("A", d, CFG))
    d = base.copy(); d.loc[3, "volume"] = -1; assert "NEGATIVE_VOLUME" in codes(validate_symbol("A", d, CFG))


def test_warn_checks_do_not_exclude():
    base = make_prices("A", n=250)
    d = base.copy(); d.loc[100, ["open", "high", "low", "close"]] = [base.close[99] * 1.3] * 4
    iss = validate_symbol("A", d, CFG, "HOSE")
    assert "LARGE_DAILY_MOVE" in codes(iss) and not has_error(iss)
    d = base.copy(); d["volume"] = 0
    assert "ZERO_VOLUME_DAYS" in codes(validate_symbol("A", d, CFG))
    assert "SHORT_HISTORY" in codes(validate_symbol("A", make_prices("A", n=100), CFG))


def test_exchange_specific_threshold():
    base = make_prices("A", n=250)
    d = base.copy(); d.loc[100, ["open", "high", "low", "close"]] = [base.close[99] * 1.10] * 4
    assert "LARGE_DAILY_MOVE" in codes(validate_symbol("A", d, CFG, "HOSE"))   # 10% > 7%
    assert "LARGE_DAILY_MOVE" not in codes(validate_symbol("A", d, CFG, None))  # 10% < 15%


def test_run_level_checks():
    assert check_stale(date(2026, 11, 1), date(2026, 11, 9), CFG) is not None
    assert check_stale(date(2026, 11, 6), date(2026, 11, 9), CFG) is None
    assert check_coverage(100, 5, 5, CFG) is None
    assert check_coverage(100, 6, 5, CFG).severity == "error"
