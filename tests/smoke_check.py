"""End-to-end smoke test of the running stack (all 5 services must be up).
Usage:  python tests/smoke_check.py [http://localhost:8000]
Exit code 0 = all checks passed.
"""
import json, sys, urllib.request, urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
results = []


def call(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


c, h = call("/api/health")
check("gateway health reports all services ok", c == 200 and h["overall"] == "ok", h)
c, m = call("/api/meta")
check("meta has stations, dates, suggested as-of", c == 200 and len(m["stations"]) > 0 and m["suggested_as_of"], m if c != 200 else "")
asof = m["suggested_as_of"]
c, o = call(f"/api/overview?as_of={asof}")
check("overview aggregates data+analytics+geo", c == 200 and "counts" in o and len(o["regional"]) == 7, o)
c, f = call(f"/api/forecast/DEL?as_of={asof}")
check("forecast returns 5 leads with intervals", c == 200 and len(f["forecast"]) == 5 and f["forecast"][0]["lower_90_c"] < f["forecast"][0]["upper_90_c"], f)
check("hold-out as-of is labelled out-of-sample", "out-of-sample" in f["validation_status"], f["validation_status"])
c, _ = call("/api/forecast/NOPE")
check("unknown station -> 404", c == 404)
c, _ = call("/api/forecast/DEL?as_of=1999-01-01")
check("as_of outside range -> 422", c == 422)
c, _ = call("/api/forecast/DEL?as_of=not-a-date")
check("bad date format -> 422", c == 422)
for src in ("observed", "predicted", "historical"):
    c, g = call(f"/api/geojson/{src}?as_of={asof}")
    ok = c == 200 and g["type"] == "FeatureCollection" and g["features"] and g["features"][0]["geometry"]["type"] == "Point"
    check(f"GeoJSON {src}", ok, g if not ok else "")
    c, r = call(f"/api/ranking/{src}?as_of={asof}&top=5")
    check(f"ranking {src} sorted descending", c == 200 and [x["score"] for x in r["ranking"]] == sorted([x["score"] for x in r["ranking"]], reverse=True))
    c, cl = call(f"/api/clusters/{src}?as_of={asof}")
    check(f"clusters {src}", c == 200 and "clusters" in cl)
c, _ = call("/api/geojson/bogus")
check("invalid geojson source -> 422", c == 422)
c, mt = call("/api/model/metrics")
r1 = mt["per_lead"][0]
check("model metrics: ridge MAE < persistence & climatology at +1d", r1["ridge"]["mae"] < r1["persistence"]["mae"] and r1["ridge"]["mae"] < r1["climatology"]["mae"], r1)
c, se = call("/api/seasonal")
check("seasonal stats cover 4 seasons", c == 200 and {r["season"] for r in se["rows"]} == {"Winter", "Pre-monsoon", "Monsoon", "Post-monsoon"})
for sh in ("citizen", "health", "farmer", "authority"):
    c, a = call("/api/advisory", "POST", {"station_id": "BKN", "stakeholder": sh, "as_of": asof})
    ok = c == 200 and "NOT an official" in a["advisory"]["disclaimer"] and a["advisory"]["review_status"].startswith("DRAFT")
    check(f"advisory ({sh}) is a labelled DRAFT with disclaimer", ok, a if not ok else "")
c, a = call("/api/advisory", "POST", {"station_id": "BKN", "stakeholder": "alien", "as_of": asof})
check("invalid stakeholder -> 422", c == 422)
c, a = call("/api/advisory", "POST", {"station_id": "BKN", "stakeholder": "citizen", "as_of": asof, "use_llm": True})
check("use_llm without key falls back to rule-based", c == 200 and a["advisory"]["text"])
c, rv = call(f"/api/advisory/{a['advisory']['id']}/review?approve=true", "POST")
check("human review step updates status", c == 200 and rv["review_status"].startswith("REVIEWED"))
call("/api/aws/readings", "DELETE")
c, s = call(f"/api/aws/simulate?end_date={asof}&days=5", "POST")
check("AWS simulation endpoint creates labelled readings", c == 200 and s["simulated"] and s["created"] > 0)
c, v = call("/api/validation/aws")
check("AWS validation returns MAE", c == 200 and v["n"] > 0 and v["all_simulated"] and v["mae_forecast_vs_aws_c"] is not None, v)
c, q = call("/api/data/quality")
check("data quality report present", c == 200 and q["rows_valid"] > 0)
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
