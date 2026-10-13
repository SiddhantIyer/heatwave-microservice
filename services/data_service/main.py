"""Meteorological Data Service  (Phase I: data acquisition, validation, AWS ingest).

Loads a historical Tmax CSV, validates it, and serves clean data over REST.
Also hosts the *simulated* IoT-AWS ingest endpoints (Phase III).
"""
import logging, os, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [data] %(levelname)s %(message)s")
log = logging.getLogger("data")

def _default_csv() -> Path:
    if os.getenv("DATA_CSV"):
        return Path(os.environ["DATA_CSV"])
    here = Path(__file__).resolve()
    root = here.parents[2] if len(here.parents) > 2 else here.parent
    return root / "data" / "sample_tmax.csv"


DATA_CSV = _default_csv()
LAT_RANGE, LON_RANGE, T_RANGE = (6.0, 38.0), (67.0, 98.5), (-10.0, 55.0)
SENTINELS = {99.9, -99.9, 999.0, -999.0, 99.0}
REQUIRED = ["timestamp", "station_id", "latitude", "longitude", "tmax_c"]

app = FastAPI(title="Meteorological Data Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])

STATE = {"df": None, "stations": None, "quality": None, "loaded_at": None, "error": None}
_lock = threading.Lock()


def _approx_region(lat, lon):
    """Fallback region assignment (only if the CSV has no 'region' column). Approximate boxes."""
    if lat >= 30: return "Western Himalaya & Hills"
    if lon >= 89: return "Northeast India"
    if lat >= 24 and lon < 82: return "Northwest Plains"
    if lat >= 24: return "East India"
    if lat >= 16 and lon < 74.5: return "West Coast & Gujarat"
    if lat >= 16.5 and lon >= 82: return "East India"
    if lat >= 17: return "Central India"
    return "South Peninsula"


def load_and_validate(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}. Run scripts/generate_sample_data.py or set DATA_CSV.")
    raw = pd.read_csv(path)
    missing_cols = [c for c in REQUIRED if c not in raw.columns]
    if missing_cols:
        raise ValueError(f"CSV missing required columns: {missing_cols}")
    q = {"file": path.name, "rows_read": int(len(raw))}
    df = raw.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for c in ("latitude", "longitude", "tmax_c"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad_ts = df["timestamp"].isna()
    bad_geo = ~df["latitude"].between(*LAT_RANGE) | ~df["longitude"].between(*LON_RANGE)
    drop = bad_ts | bad_geo
    q["dropped_invalid_timestamp"] = int(bad_ts.sum())
    q["dropped_invalid_coordinates"] = int((bad_geo & ~bad_ts).sum())
    df = df[~drop].copy()
    sentinel = df["tmax_c"].isin(SENTINELS)
    q["sentinel_values_set_to_missing"] = int(sentinel.sum())
    df.loc[sentinel, "tmax_c"] = np.nan
    out_rng = df["tmax_c"].notna() & ~df["tmax_c"].between(*T_RANGE)
    q["out_of_range_set_to_missing"] = int(out_rng.sum())
    df.loc[out_rng, "tmax_c"] = np.nan
    before = len(df)
    df = df.drop_duplicates(["station_id", "timestamp"], keep="first")
    q["duplicates_dropped"] = int(before - len(df))
    q["missing_tmax_after_cleaning"] = int(df["tmax_c"].isna().sum())
    q["missing_pct"] = round(100 * q["missing_tmax_after_cleaning"] / max(len(df), 1), 3)
    if "station_name" not in df: df["station_name"] = df["station_id"]
    if "terrain" not in df: df["terrain"] = "plains"
    if "data_source" not in df: df["data_source"] = "UNSPECIFIED"
    if "region" not in df:
        df["region"] = [_approx_region(a, b) for a, b in zip(df["latitude"], df["longitude"])]
        q["region_assigned_by"] = "approximate lat/lon rules (no region column in CSV)"
    else:
        q["region_assigned_by"] = "CSV column"
    df = df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)
    q["rows_valid"] = int(len(df))
    q["stations"] = int(df["station_id"].nunique())
    q["date_min"] = df["timestamp"].min().strftime("%Y-%m-%d")
    q["date_max"] = df["timestamp"].max().strftime("%Y-%m-%d")
    q["data_sources"] = sorted(df["data_source"].astype(str).unique().tolist())
    g = df.groupby("station_id")
    st = g.agg(station_name=("station_name", "first"), latitude=("latitude", "first"), longitude=("longitude", "first"),
               region=("region", "first"), terrain=("terrain", "first"), n_obs=("tmax_c", "count"),
               first_date=("timestamp", "min"), last_date=("timestamp", "max")).reset_index()
    st["first_date"] = st["first_date"].dt.strftime("%Y-%m-%d")
    st["last_date"] = st["last_date"].dt.strftime("%Y-%m-%d")
    return df, st, q


def ensure_loaded():
    with _lock:
        if STATE["df"] is None:
            try:
                df, st, q = load_and_validate(DATA_CSV)
                STATE.update(df=df, stations=st, quality=q, loaded_at=datetime.now(timezone.utc).isoformat(), error=None)
                log.info("Loaded %s rows, %s stations", q["rows_valid"], q["stations"])
            except Exception as e:  # keep service up, report error on /health
                STATE["error"] = str(e)
                log.exception("Load failed")
    if STATE["df"] is None:
        raise HTTPException(503, f"Dataset unavailable: {STATE['error']}")
    return STATE["df"]


@app.on_event("startup")
def _startup():
    try:
        ensure_loaded()
    except HTTPException:
        pass


@app.get("/health")
def health():
    ok = STATE["df"] is not None
    return {"service": "data_service", "status": "ok" if ok else "degraded", "data_loaded": ok,
            "data_source": (STATE["quality"] or {}).get("data_sources"), "dataset": str(DATA_CSV.name),
            "loaded_at": STATE["loaded_at"], "error": STATE["error"]}


@app.get("/quality")
def quality():
    ensure_loaded()
    return STATE["quality"]


@app.get("/summary")
def summary():
    df = ensure_loaded()
    valid = df.dropna(subset=["tmax_c"])
    last_day = valid["timestamp"].max()
    latest = valid[valid["timestamp"] == last_day]
    hottest = latest.sort_values("tmax_c", ascending=False).iloc[0]
    q = STATE["quality"]
    return {"n_stations": q["stations"], "n_observations": int(len(valid)), "date_min": q["date_min"], "date_max": q["date_max"],
            "latest_timestamp": last_day.strftime("%Y-%m-%d"),
            "latest_max_tmax_c": float(hottest["tmax_c"]), "latest_max_station": hottest["station_name"],
            "latest_mean_tmax_c": round(float(latest["tmax_c"].mean()), 1),
            "data_sources": q["data_sources"], "is_sample_data": any("SAMPLE" in s.upper() for s in q["data_sources"]),
            "loaded_at": STATE["loaded_at"]}


@app.get("/stations")
def stations(region: Optional[str] = None):
    ensure_loaded()
    st = STATE["stations"]
    if region: st = st[st["region"] == region]
    return {"count": int(len(st)), "stations": st.to_dict("records")}


@app.get("/regions")
def regions():
    ensure_loaded()
    return {"regions": sorted(STATE["stations"]["region"].unique().tolist())}


def _filter(df, station_id, region, start, end):
    if station_id: df = df[df["station_id"] == station_id]
    if region: df = df[df["region"] == region]
    try:
        if start: df = df[df["timestamp"] >= pd.Timestamp(start)]
        if end: df = df[df["timestamp"] <= pd.Timestamp(end)]
    except ValueError:
        raise HTTPException(422, "start/end must be YYYY-MM-DD")
    return df


@app.get("/observations")
def observations(station_id: Optional[str] = None, region: Optional[str] = None, start: Optional[str] = None,
                 end: Optional[str] = None, limit: int = Query(1000, ge=1, le=20000)):
    df = _filter(ensure_loaded(), station_id, region, start, end)
    sub = df.head(limit).copy()
    sub["timestamp"] = sub["timestamp"].dt.strftime("%Y-%m-%d")
    sub = sub.replace({np.nan: None})
    return {"total_matching": int(len(df)), "returned": int(len(sub)), "observations": sub.to_dict("records")}


@app.get("/observations/columnar")
def observations_columnar(start: Optional[str] = None, end: Optional[str] = None):
    """Compact bulk export used by the analytics service."""
    df = _filter(ensure_loaded(), None, None, start, end)
    return {"date": df["timestamp"].dt.strftime("%Y-%m-%d").tolist(), "station_id": df["station_id"].tolist(),
            "tmax_c": [None if pd.isna(v) else float(v) for v in df["tmax_c"]]}


# ----------------------------- simulated IoT AWS (Phase III) -----------------------------
class AwsReading(BaseModel):
    station_id: str
    date: str = Field(..., description="Observation day YYYY-MM-DD")
    tmax_c: float = Field(..., ge=-10, le=55)
    humidity_pct: Optional[float] = Field(None, ge=0, le=100)
    device_id: str = "AWS-SIM-001"
    simulated: bool = True


AWS: list = []


@app.post("/aws/readings", status_code=201)
def aws_ingest(r: AwsReading):
    df = ensure_loaded()
    if r.station_id not in set(df["station_id"]):
        raise HTTPException(404, f"Unknown station_id {r.station_id}")
    try:
        pd.Timestamp(r.date)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    rec = r.model_dump() | {"received_at": datetime.now(timezone.utc).isoformat(),
                            "label": "SIMULATED AWS - not a physical sensor" if r.simulated else "AWS"}
    AWS[:] = [a for a in AWS if not (a["station_id"] == r.station_id and a["date"] == r.date and a["device_id"] == r.device_id)]
    AWS.append(rec)
    return rec


@app.get("/aws/readings")
def aws_list(station_id: Optional[str] = None, limit: int = Query(200, ge=1, le=5000)):
    rows = [a for a in AWS if not station_id or a["station_id"] == station_id]
    rows = sorted(rows, key=lambda a: (a["date"], a["station_id"]))[-limit:]
    return {"count": len(rows), "readings": rows}


@app.post("/aws/simulate")
def aws_simulate(end_date: str, days: int = Query(7, ge=1, le=60), seed: int = 7):
    """Create SIMULATED AWS readings: record value + sensor bias/noise. Clearly labelled simulated."""
    df = ensure_loaded()
    ids = [s.strip() for s in os.getenv("AWS_SIM_STATIONS", "DEL,NGP,MAA,JAI,CCU,HYD").split(",")]
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(end_date)
    made = []
    for sid in ids:
        sub = df[(df["station_id"] == sid) & (df["timestamp"] <= end) & (df["timestamp"] > end - pd.Timedelta(days=days))]
        for _, row in sub.dropna(subset=["tmax_c"]).iterrows():
            val = round(float(row["tmax_c"] + 0.3 + rng.normal(0, 0.8)), 1)  # +0.3 sensor bias, 0.8 noise
            made.append(aws_ingest(AwsReading(station_id=sid, date=row["timestamp"].strftime("%Y-%m-%d"), tmax_c=val,
                                             humidity_pct=round(float(rng.uniform(15, 60)), 0), device_id=f"AWS-SIM-{sid}")))
    return {"simulated": True, "created": len(made), "stations": ids,
            "note": "Synthetic readings derived from the dataset; no physical AWS hardware is deployed."}


@app.delete("/aws/readings")
def aws_clear():
    AWS.clear()
    return {"cleared": True}
