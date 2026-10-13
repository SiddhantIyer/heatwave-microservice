"""API Gateway / aggregation layer: the frontend's single entry point (port 8000).

Routes /api/* to the data, analytics, geo and advisory services, aggregates results
(overview, advisory generation) and converts upstream failures into clear 503 responses.
"""
import asyncio, logging, os, time
from typing import Optional

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [gateway] %(levelname)s %(message)s")
log = logging.getLogger("gateway")
SERVICES = {
    "data": os.getenv("DATA_SERVICE_URL", "http://localhost:8001"),
    "analytics": os.getenv("ANALYTICS_SERVICE_URL", "http://localhost:8002"),
    "geo": os.getenv("GEO_SERVICE_URL", "http://localhost:8003"),
    "advisory": os.getenv("ADVISORY_SERVICE_URL", "http://localhost:8004"),
}
app = FastAPI(title="Heatwave Intelligence API Gateway", version="1.0.0",
              description="Single entry point for the dashboard. Prefix: /api")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])
client = httpx.AsyncClient(timeout=90)


async def call(svc: str, path: str, method="GET", params=None, json=None):
    params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        r = await client.request(method, f"{SERVICES[svc]}{path}", params=params, json=json)
    except httpx.HTTPError as e:
        log.error("%s unreachable: %s", svc, e)
        raise HTTPException(503, f"The '{svc}' service is unavailable ({type(e).__name__}). Start it and retry.")
    if r.status_code >= 400:
        try: detail = r.json().get("detail", r.text)
        except Exception: detail = r.text
        raise HTTPException(r.status_code, f"[{svc}] {detail}")
    return r.json()


@app.get("/api/health")
async def health():
    async def one(name, url):
        t = time.perf_counter()
        try:
            r = await client.get(f"{url}/health", timeout=8)
            j = r.json(); j["latency_ms"] = round((time.perf_counter() - t) * 1000)
            return name, j
        except Exception as e:
            return name, {"status": "down", "error": f"{type(e).__name__}", "service": name}
    res = dict(await asyncio.gather(*[one(n, u) for n, u in SERVICES.items()]))
    res["gateway"] = {"status": "ok", "service": "gateway"}
    overall = "ok" if all(v.get("status") == "ok" for v in res.values()) else "degraded"
    return {"overall": overall, "services": res}


@app.get("/api/meta")
async def meta():
    m = await call("analytics", "/meta")
    st = await call("data", "/stations")
    return {**m, "stations": st["stations"], "regions": sorted({s["region"] for s in st["stations"]})}


@app.get("/api/overview")
async def overview(as_of: Optional[str] = None):
    summary, regional, hist, pred_clusters = await asyncio.gather(
        call("data", "/summary"), call("analytics", "/regional", params={"as_of": as_of}),
        call("geo", "/ranking/historical", params={"top": 100}), call("geo", "/clusters/predicted", params={"as_of": as_of}))
    snap = await call("analytics", "/snapshot", params={"as_of": as_of})
    st = snap["stations"]
    return {"as_of": snap["as_of"], "validation_status": snap["validation_status"], "dataset": summary,
            "counts": {"observed_high_or_above": sum(s["observed_risk_level"] >= 2 for s in st),
                       "predicted_high_or_above": sum(s["predicted_risk_level"] >= 2 for s in st),
                       "historical_hotspots": sum(r["level"] >= 2 for r in hist["ranking"])},
            "regional": regional["regions"], "predicted_clusters": pred_clusters["clusters"],
            "hottest_observed": sorted(st, key=lambda s: s["observed_tmax_c"] or -99, reverse=True)[:3]}


@app.get("/api/series/{sid}")
async def series(sid: str, start: Optional[str] = None, end: Optional[str] = None):
    return await call("analytics", f"/series/{sid}", params={"start": start, "end": end})


@app.get("/api/trends")
async def trends(station_id: Optional[str] = None, region: Optional[str] = None):
    return await call("analytics", "/trends", params={"station_id": station_id, "region": region})


@app.get("/api/seasonal")
async def seasonal():
    return await call("analytics", "/seasonal")


@app.get("/api/forecast/{sid}")
async def forecast(sid: str, as_of: Optional[str] = None):
    return await call("analytics", f"/forecast/{sid}", params={"as_of": as_of})


@app.get("/api/snapshot")
async def snapshot(as_of: Optional[str] = None):
    return await call("analytics", "/snapshot", params={"as_of": as_of})


@app.get("/api/model/metrics")
async def metrics():
    return await call("analytics", "/model/metrics")


@app.get("/api/config/risk")
async def risk_cfg():
    return await call("analytics", "/config/risk")


@app.get("/api/data/quality")
async def quality():
    return await call("data", "/quality")


@app.get("/api/geojson/{source}")
async def geojson(source: str, as_of: Optional[str] = None, region: Optional[str] = None, min_level: int = 0):
    return await call("geo", f"/geojson/{source}", params={"as_of": as_of, "region": region, "min_level": min_level})


@app.get("/api/ranking/{source}")
async def ranking(source: str, as_of: Optional[str] = None, region: Optional[str] = None, top: int = 10):
    return await call("geo", f"/ranking/{source}", params={"as_of": as_of, "region": region, "top": top})


@app.get("/api/clusters/{source}")
async def clusters(source: str, as_of: Optional[str] = None, min_level: int = 2):
    return await call("geo", f"/clusters/{source}", params={"as_of": as_of, "min_level": min_level})


@app.post("/api/advisory")
async def advisory(body: dict = Body(...)):
    """Aggregation: gateway fetches the forecast, then asks the advisory service to write for a stakeholder."""
    sid, stakeholder = body.get("station_id"), body.get("stakeholder", "citizen")
    if not sid: raise HTTPException(422, "station_id is required")
    f = await call("analytics", f"/forecast/{sid}", params={"as_of": body.get("as_of")})
    pk = max(f["forecast"], key=lambda l: (l["risk_level"], l["forecast_tmax_c"]))
    payload = {"stakeholder": stakeholder, "station_name": f["station_name"], "region": f["region"], "risk_level": pk["risk_level"],
               "peak_date": pk["date"], "peak_lead_days": pk["lead_days"], "forecast_tmax_c": pk["forecast_tmax_c"], "lower_90_c": pk["lower_90_c"],
               "upper_90_c": pk["upper_90_c"], "anomaly_c": pk["forecast_anomaly_c"], "observed_tmax_c": f["observed_on_as_of"]["tmax_c"],
               "as_of": f["as_of"], "validation_status": f["validation_status"], "is_sample_data": f["data_is_sample"],
               "use_llm": bool(body.get("use_llm", False))}
    adv = await call("advisory", "/advisory", method="POST", json=payload)
    return {"advisory": adv, "forecast": f}


@app.post("/api/advisory/{adv_id}/review")
async def review(adv_id: str, approve: bool = True):
    return await call("advisory", f"/advisory/{adv_id}/review", method="POST", params={"approve": str(approve).lower()})


@app.post("/api/aws/simulate")
async def aws_sim(end_date: str, days: int = 7):
    return await call("data", "/aws/simulate", method="POST", params={"end_date": end_date, "days": days})


@app.get("/api/aws/readings")
async def aws_readings(station_id: Optional[str] = None, limit: int = 100):
    return await call("data", "/aws/readings", params={"station_id": station_id, "limit": limit})


@app.delete("/api/aws/readings")
async def aws_clear():
    return await call("data", "/aws/readings", method="DELETE")


@app.get("/api/validation/aws")
async def aws_validation():
    return await call("analytics", "/validation/aws")
