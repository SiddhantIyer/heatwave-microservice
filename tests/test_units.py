"""Unit tests (pytest) for the risk index and the data validator - no running services needed.
Run from repo root:  pytest -q tests
"""
import sys, importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


analytics = load("analytics_main", "services/analytics_service/main.py")
data = load("data_main", "services/data_service/main.py")


@pytest.mark.parametrize("tmax,anom,terrain,expected", [
    (35.0, 1.0, "plains", 0),   # below threshold
    (41.0, 1.0, "plains", 1),   # above 40 but small departure -> Moderate
    (42.0, 5.0, "plains", 2),   # above 40 and >=4.5 departure -> High
    (43.5, 7.0, "plains", 3),   # >=6.5 departure -> Severe
    (45.5, 2.0, "plains", 2),   # absolute 45 -> High
    (47.2, 0.0, "plains", 3),   # absolute 47 -> Severe
    (38.0, 5.0, "coastal", 2),  # coastal threshold 37
    (31.0, 5.0, "hill", 2),     # hill threshold 30
    (36.0, 0.5, "hill", 1),     # hill above threshold
])
def test_risk_levels(tmax, anom, terrain, expected):
    assert int(analytics.classify([tmax], [anom], np.array([terrain]))[0]) == expected


def test_missing_input_gives_minus_one():
    assert int(analytics.classify([np.nan], [1.0], np.array(["plains"]))[0]) == -1


def test_validator_cleans_bad_rows(tmp_path):
    csv = tmp_path / "t.csv"
    pd.DataFrame({"timestamp": ["2024-01-01", "bad-date", "2024-01-02", "2024-01-02", "2024-01-03", "2024-01-04"],
                  "station_id": ["A"] * 6, "latitude": [20, 20, 20, 20, 20, 99], "longitude": [78] * 6,
                  "tmax_c": [30, 31, 99.9, 99.9, 120, 33]}).to_csv(csv, index=False)
    df, st, q = data.load_and_validate(csv)
    assert q["dropped_invalid_timestamp"] == 1
    assert q["dropped_invalid_coordinates"] == 1
    assert q["sentinel_values_set_to_missing"] >= 1
    assert q["out_of_range_set_to_missing"] == 1
    assert q["duplicates_dropped"] == 1
    assert df["tmax_c"].isna().sum() == 2


def test_validator_requires_columns(tmp_path):
    csv = tmp_path / "x.csv"; pd.DataFrame({"a": [1]}).to_csv(csv, index=False)
    with pytest.raises(ValueError):
        data.load_and_validate(csv)
