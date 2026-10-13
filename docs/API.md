# API documentation

All frontend calls go through the **gateway** (`http://localhost:8000`, prefix `/api`). Each service also exposes its own endpoints and live Swagger UI at `/docs`. Errors are JSON `{"detail": "..."}`: 404 unknown id, 422 invalid input, 503 upstream service unavailable (gateway text names the service).

## Gateway (8000)
| Method & path | Purpose |
|---|---|
| GET `/api/health` | Health of all services + latency |
| GET `/api/meta` | Date range, `train_end`, `suggested_as_of`, stations, regions |
| GET `/api/overview?as_of=` | Aggregates data summary, regional risk counts, clusters, hottest stations |
| GET `/api/series/{station}?start&end` | Daily Tmax, normal, anomaly, risk |
| GET `/api/trends?station_id=&region=` | Monthly mean/max, pre-monsoon annual trend |
| GET `/api/seasonal` | Region × season statistics |
| GET `/api/forecast/{station}?as_of=` | 5-day forecast with 90 % interval, observed values when available |
| GET `/api/snapshot?as_of=` | All stations: observed + forecast summary |
| GET `/api/model/metrics` | Hold-out MAE/RMSE, baselines, event detection |
| GET `/api/geojson/{observed\|predicted\|historical}?as_of&region&min_level` | Map-ready FeatureCollection |
| GET `/api/ranking/{source}?as_of&region&top` | Ranked hotspots with factors |
| GET `/api/clusters/{source}?as_of&min_level` | DBSCAN clusters of flagged stations |
| POST `/api/advisory` | Body `{station_id, stakeholder, as_of, use_llm}` → forecast + advisory (aggregation) |
| POST `/api/advisory/{id}/review?approve=` | Human-review status update |
| POST `/api/aws/simulate?end_date&days` · GET/DELETE `/api/aws/readings` | Simulated AWS data |
| GET `/api/validation/aws` | Forecast vs AWS comparison |
| GET `/api/config/risk` · `/api/data/quality` | Risk configuration · data quality report |

## Service contracts
**Data Service (8001):** `GET /health /quality /summary /stations?region= /regions /observations?station_id&region&start&end&limit /observations/columnar`; `POST /aws/readings` (body `{station_id,date,tmax_c,humidity_pct?,device_id?,simulated=true}`), `GET /aws/readings`, `POST /aws/simulate?end_date&days`, `DELETE /aws/readings`.
**Analytics Service (8002):** `GET /health /meta /config/risk /model/metrics /series/{id} /trends /seasonal /forecast/{id} /snapshot /regional /hotspots/historical /validation/aws`.
**Geo Service (8003):** `GET /health /geojson/{source} /ranking/{source} /clusters/{source}`; it calls the Analytics Service.
**Advisory Service (8004):** `GET /health /advisory`; `POST /advisory` (stakeholder ∈ citizen|health|farmer|authority, risk_level 0–3, forecast facts), `POST /advisory/{id}/review`.

Service-to-service calls: gateway → all four; analytics → data (`/stations`, `/observations/columnar`, `/summary`, `/aws/readings`); geo → analytics (`/snapshot`, `/hotspots/historical`).

## Example: forecast (real output, synthetic data)
`GET /api/forecast/NGP?as_of=2025-05-04` (lead list truncated to day +1)
```json
{
 "station_id": "NGP",
 "station_name": "Nagpur",
 "region": "Central India",
 "terrain": "plains",
 "latitude": 21.15,
 "longitude": 79.09,
 "as_of": "2025-05-04",
 "observed_on_as_of": {
  "tmax_c": 42.8,
  "anomaly_c": -0.1,
  "risk_level": 1,
  "risk_label": "Moderate",
  "explanation": "Tmax 42.8C vs plains threshold 40C; departure from station normal -0.1C (heatwave-like >= 4.5C, severe >= 6.5C) -> Moderate"
 },
 "forecast": [
  {
   "lead_days": 1,
   "date": "2025-05-05",
   "forecast_tmax_c": 42.8,
   "lower_90_c": 41.0,
   "upper_90_c": 44.6,
   "normal_c": 42.9,
   "forecast_anomaly_c": -0.1,
   "risk_level": 1,
   "risk_label": "Moderate",
   "observed_tmax_c": 41.3,
   "observed_risk_level": 1,
   "error_c": 1.49
  }
 ],
 "peak_forecast_risk": {
  "risk_level": 1,
  "risk_label": "Moderate",
  "lead_days": 1,
  "date": "2025-05-05"
 },
 "validation_status": "out-of-sample (forecast targets lie after the training period)",
 "data_is_sample": true,
 "uncertainty_note": "90% interval from hold-out residuals; actual error can exceed it, especially for extremes.",
 "label": "Prototype risk index (IMD-style criteria) - NOT an official IMD heatwave declaration"
}
```
## Example: observed hotspot clusters
`GET /api/clusters/observed?as_of=2025-05-04` (truncated)
```json
{
    "source": "observed",
    "as_of": "2025-05-04",
    "validation_status": "out-of-sample (forecast targets lie after the training period)",
    "label": "Prototype risk index (IMD-style criteria) - NOT an official IMD heatwave declaration",
    "eps_km": 450.0,
    "clusters": [
        {
            "centroid": {
                "latitude": 14.985,
                "longitude": 79.248
            },
            "radius_km": 287.0,
            "n_stations": 4,
            "mean_score": 79.2,
            "max_level": "Severe",
            "regions": [
                "South Peninsula"
            ],
            "stations": [
                "Bengaluru",
                "Hyderabad",
                "Chennai",
                "Vijayawada"
            ],
            "cluster_rank": 1
        }
    ],
    "isolated": [
        "Thiruvananthapuram"
    ]
}
```
## Example: GeoJSON feature (`/api/geojson/predicted?as_of=2025-05-04`)
```json
{"type":"Feature","geometry":{"type":"Point","coordinates":[72.57,23.02]},
 "properties":{"station_id":"AMD","station_name":"Ahmedabad","region":"West Coast & Gujarat","terrain":"plains",
  "kind":"predicted","level":1,"risk_label":"Moderate","score":25.0,"temperature_c":41.3,"temperature_label":"Max forecast Tmax (next 5 days)",
  "basis":"MODEL FORECAST issued as of 2025-05-04 for the next 5 days","factors":{"Max forecast Tmax (C)":41.3,"Peak lead (days)":1}}}
```
`metadata.spatial_note` states that points are dataset coordinates and nothing is interpolated.

## Example: advisory
`POST /api/advisory` body `{"station_id":"BKN","stakeholder":"farmer","as_of":"2025-05-04"}` → `advisory` contains
`title`, `text` (rule-based), `generated_by` ("rule-based"), `risk_label`, `review_status` ("DRAFT - pending human review"), `data_basis` ("SAMPLE/SYNTHETIC data - demonstration only"), `limitations[]`, `disclaimer` ("DEMONSTRATION ADVISORY ... NOT an official IMD warning or government alert ...").

## Example: simulated AWS ingest
```bash
curl -X POST localhost:8001/aws/readings -H 'content-type: application/json' \
  -d '{"station_id":"DEL","date":"2025-05-04","tmax_c":42.4,"humidity_pct":28,"device_id":"AWS-SIM-DEL","simulated":true}'
```
