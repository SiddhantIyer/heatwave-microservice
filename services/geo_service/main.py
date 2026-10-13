"""Geospatial Hotspot & Risk Mapping Service.

Turns per-station analytics into map-ready GeoJSON, clusters high-risk stations
(DBSCAN on haversine distance) and produces ranked hotspot lists.
Spatial unit = the dataset's own point locations (stations or grid-cell centres);
nothing is interpolated or invented between points.
"""
import logging, os
from typing import Optional

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sklearn.cluster import DBSCAN

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [geo] %(levelname)s %(message)s")
log = logging.getLogger("geo")
ANALYTICS = os.getenv("ANALYTICS_SERVICE_URL", "http://localhost:8002")
EPS_KM = float(os.getenv("CLUSTER_EPS_KM", "450"))
HIST_FLAG_SCORE = float(os.getenv("HISTORICAL_HOTSPOT_MIN_SCORE", "40"))
LEVELS = ["Low", "Moderate", "High", "Severe"]
SOURCES = ("observed", "predicted", "historical")

app = FastAPI(title="Geospatial Hotspot & Risk Mapping Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


def fetch(path, params=None):
    try:
        r = httpx.get(f"{ANALYTICS}{path}", params={k: v for k, v in (params or {}).items() if v is not None}, timeout=60)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Analytics service unreachable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text)
    return r.json()


def records(source, as_of=None):
    """Normalise the three sources to one record shape: level, metric, score + provenance."""
    if source == "historical":
        d = fetch("/hotspots/historical")
        out = []
        for s in d["stations"]:
            out.append({**s, "kind": "historical", "level": 2 if s["score"] >= HIST_FLAG_SCORE else 0, "score": s["score"],
                        "temperature_c": s["p95_tmax_mar_jun_c"], "temperature_label": "P95 Tmax Mar-Jun",
                        "basis": f"Derived from historical observations {d['period'][0]} to {d['period'][1]}",
                        "factors": {"High+ days per year": s["high_or_above_days_per_year"], "P95 Tmax Mar-Jun (C)": s["p95_tmax_mar_jun_c"],
                                    "Longest High+ streak (days)": s["longest_high_streak_days"]},
                        "factor_contributions": s["factor_contributions"]})
        return out, {"period": d["period"], "method": d["method"], "validation_status": "historical observations"}
    d = fetch("/snapshot", {"as_of": as_of})
    meta = {"as_of": d["as_of"], "validation_status": d["validation_status"], "label": d["label"]}
    out = []
    for s in d["stations"]:
        base = {k: s[k] for k in ("station_id", "station_name", "region", "terrain", "latitude", "longitude")}
        if source == "observed":
            lvl = max(s["observed_risk_level"], 0)
            out.append({**base, "kind": "observed", "level": lvl, "score": lvl * 25 + min(max(s["observed_anomaly_c"] or 0, 0), 10) * 2.5,
                        "temperature_c": s["observed_tmax_c"], "temperature_label": "Observed Tmax", "anomaly_c": s["observed_anomaly_c"],
                        "basis": f"Observed value on {d['as_of']} (dataset record)",
                        "factors": {"Observed Tmax (C)": s["observed_tmax_c"], "Departure from normal (C)": s["observed_anomaly_c"]}})
        else:
            lvl = s["predicted_risk_level"]
            out.append({**base, "kind": "predicted", "level": lvl, "score": lvl * 25 + min(max(s["predicted_max_anomaly_c"] or 0, 0), 10) * 2.5,
                        "temperature_c": s["predicted_max_tmax_c"], "temperature_label": "Max forecast Tmax (next 5 days)",
                        "anomaly_c": s["predicted_max_anomaly_c"], "peak_date": s["predicted_peak_date"],
                        "basis": f"MODEL FORECAST issued as of {d['as_of']} for the next 5 days",
                        "factors": {"Max forecast Tmax (C)": s["predicted_max_tmax_c"], "Max forecast anomaly (C)": s["predicted_max_anomaly_c"],
                                    "Peak lead (days)": s["predicted_peak_lead_days"], "Upper 90% bound at peak (C)": s["predicted_peak_upper_90_c"]}})
    return out, meta


def check_source(source):
    if source not in SOURCES: raise HTTPException(422, f"source must be one of {SOURCES}")


@app.get("/health")
def health():
    try:
        a = httpx.get(f"{ANALYTICS}/health", timeout=5).json().get("status")
    except httpx.HTTPError:
        a = "unreachable"
    return {"service": "geo_service", "status": "ok", "upstream_analytics": a, "cluster_eps_km": EPS_KM}


@app.get("/geojson/{source}")
def geojson(source: str, as_of: Optional[str] = None, region: Optional[str] = None, min_level: int = Query(0, ge=0, le=3)):
    check_source(source)
    recs, meta = records(source, as_of)
    feats = []
    for r in recs:
        if region and r["region"] != region: continue
        if r["level"] < min_level: continue
        props = {k: v for k, v in r.items() if k not in ("latitude", "longitude", "factor_contributions")}
        props["risk_label"] = LEVELS[r["level"]]
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]}, "properties": props})
    return {"type": "FeatureCollection", "features": feats, "metadata": {"source": source, "count": len(feats), **meta,
            "spatial_note": "Points are the dataset's station/grid-cell coordinates; no values are interpolated between them."}}


@app.get("/ranking/{source}")
def ranking(source: str, as_of: Optional[str] = None, region: Optional[str] = None, top: int = Query(10, ge=1, le=100)):
    check_source(source)
    recs, meta = records(source, as_of)
    recs = [r for r in recs if not region or r["region"] == region]
    recs.sort(key=lambda r: (r["score"], r["temperature_c"] or 0), reverse=True)
    for i, r in enumerate(recs): r["rank"] = i + 1; r["risk_label"] = LEVELS[r["level"]]
    return {"source": source, **meta, "ranking": recs[:top]}


def _hav(a, b):
    la1, lo1, la2, lo2 = map(np.radians, (a[0], a[1], b[0], b[1]))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(h))


@app.get("/clusters/{source}")
def clusters(source: str, as_of: Optional[str] = None, min_level: int = Query(2, ge=1, le=3)):
    """DBSCAN (haversine, eps=CLUSTER_EPS_KM, min_samples=2) over stations at/above min_level."""
    check_source(source)
    recs, meta = records(source, as_of)
    flagged = [r for r in recs if r["level"] >= (2 if source == "historical" else min_level)]
    if not flagged:
        return {"source": source, **meta, "eps_km": EPS_KM, "clusters": [], "isolated": [], "message": "No stations at or above the selected level."}
    X = np.radians([[r["latitude"], r["longitude"]] for r in flagged])
    lab = DBSCAN(eps=EPS_KM / 6371.0, min_samples=2, metric="haversine").fit_predict(X) if len(flagged) > 1 else np.array([-1])
    out = []
    for c in sorted(set(lab) - {-1}):
        mem = [r for r, l in zip(flagged, lab) if l == c]
        cen = (float(np.mean([m["latitude"] for m in mem])), float(np.mean([m["longitude"] for m in mem])))
        out.append({"centroid": {"latitude": round(cen[0], 3), "longitude": round(cen[1], 3)},
                    "radius_km": round(float(max(_hav(cen, (m["latitude"], m["longitude"])) for m in mem)), 0), "n_stations": len(mem),
                    "mean_score": round(float(np.mean([m["score"] for m in mem])), 1), "max_level": LEVELS[max(m["level"] for m in mem)],
                    "regions": sorted({m["region"] for m in mem}), "stations": [m["station_name"] for m in mem]})
    out.sort(key=lambda c: (c["mean_score"], c["n_stations"]), reverse=True)
    for i, c in enumerate(out): c["cluster_rank"] = i + 1
    iso = [r["station_name"] for r, l in zip(flagged, lab) if l == -1]
    return {"source": source, **meta, "eps_km": EPS_KM, "clusters": out, "isolated": iso,
            "method": "DBSCAN, haversine distance, min_samples=2; clusters of nearby flagged stations (not official hazard zones)"}
