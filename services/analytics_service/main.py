"""Heatwave Analytics & Prediction Service (Phase II + Phase IV validation).

* pulls clean data from the Data Service over REST
* seasonal climatology ("normal") per station, anomaly = Tmax - normal
* transparent, configurable prototype risk index (risk_config.json)
* forecasting: pooled Ridge regression on anomalies, horizons 1-5 days,
  compared against persistence and climatology baselines on a time-based hold-out
* historical hotspot metrics, regional/seasonal stats, AWS-based forecast validation
"""
import json, logging, os, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sklearn.linear_model import Ridge

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [analytics] %(levelname)s %(message)s")
log = logging.getLogger("analytics")

DATA_URL = os.getenv("DATA_SERVICE_URL", "http://localhost:8001")
CFG_PATH = Path(os.getenv("RISK_CONFIG", Path(__file__).with_name("risk_config.json")))
CFG = json.loads(CFG_PATH.read_text())
HORIZONS = [1, 2, 3, 4, 5]
SEASONS = {"Winter": [1, 2], "Pre-monsoon": [3, 4, 5], "Monsoon": [6, 7, 8, 9], "Post-monsoon": [10, 11, 12]}
LEVELS = CFG["levels"]

app = FastAPI(title="Heatwave Analytics & Prediction Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


# ----------------------------------------------------------------- risk index
def classify(tmax, anom, terrain):
    """Vectorised prototype risk index -> 0 Low, 1 Moderate, 2 High, 3 Severe (NaN input -> -1)."""
    tmax, anom = np.asarray(tmax, float), np.asarray(anom, float)
    terrain = np.asarray(terrain)
    thr = np.array([CFG["abs_threshold_c"].get(t, CFG["abs_threshold_c"]["plains"]) for t in terrain.ravel()]).reshape(terrain.shape)
    plains = terrain == "plains"
    exceeds = tmax >= thr
    severe = (exceeds & (anom >= CFG["departure_severe_c"])) | (plains & (tmax >= CFG["plains_abs_severe_c"]))
    high = (exceeds & (anom >= CFG["departure_heatwave_c"])) | (plains & (tmax >= CFG["plains_abs_heatwave_c"]))
    mod = exceeds | ((anom >= CFG["departure_heatwave_c"]) & (tmax >= thr - CFG["moderate_margin_c"]))
    lvl = np.select([severe, high, mod], [3, 2, 1], 0)
    return np.where(np.isnan(tmax) | np.isnan(anom), -1, lvl)


def explain(tmax, anom, terrain, level):
    thr = CFG["abs_threshold_c"].get(terrain, 40.0)
    return (f"Tmax {tmax:.1f}C vs {terrain} threshold {thr:.0f}C; departure from station normal {anom:+.1f}C "
            f"(heatwave-like >= {CFG['departure_heatwave_c']}C, severe >= {CFG['departure_severe_c']}C) -> {LEVELS[level]}")


# ----------------------------------------------------------------- engine
class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self.ready = False
        self.error = None
        self.built_at = None

    def build(self):
        with httpx.Client(timeout=60) as c:
            st = c.get(f"{DATA_URL}/stations").json()["stations"]
            col = c.get(f"{DATA_URL}/observations/columnar").json()
            self.data_summary = c.get(f"{DATA_URL}/summary").json()
        long = pd.DataFrame(col)
        long["date"] = pd.to_datetime(long["date"])
        wide = long.pivot(index="date", columns="station_id", values="tmax_c").astype(float)
        wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq="D"))
        self.n_missing_raw = int(wide.isna().sum().sum())
        wide = wide.interpolate(limit=3, limit_area="inside")  # fill only short gaps
        self.stations = pd.DataFrame(st).set_index("station_id").loc[wide.columns]
        self.wide = wide
        self.ids = list(wide.columns)
        self.terrain = self.stations["terrain"].values
        last = wide.index.max()
        self.train_end = pd.Timestamp(os.getenv("TRAIN_END", (last - pd.Timedelta(days=365)).strftime("%Y-%m-%d")))
        self._climatology()
        self.anom = wide - self._clim_for(wide.index)
        self.level = pd.DataFrame(classify(wide.values, self.anom.values, np.tile(self.terrain, (len(wide), 1))),
                                  index=wide.index, columns=wide.columns)
        self._train_models()
        self._suggest()
        self._fc_cache = {}
        self.built_at = datetime.now(timezone.utc).isoformat()
        self.ready = True
        log.info("Engine ready: %s stations, %s..%s, train_end=%s", len(self.ids), wide.index.min().date(), last.date(), self.train_end.date())

    # climatology: mean by day-of-year over the TRAINING period, circularly smoothed
    def _climatology(self):
        tr = self.wide[self.wide.index <= self.train_end]
        doy = np.minimum(tr.index.dayofyear.values, 365)
        by = tr.groupby(doy).mean().reindex(range(1, 366)).interpolate(limit_direction="both")
        k = 15
        arr = by.values
        pad = np.vstack([arr[-k:], arr, arr[:k]])
        ker = np.ones(2 * k + 1) / (2 * k + 1)
        sm = np.apply_along_axis(lambda x: np.convolve(x, ker, mode="valid"), 0, pad)
        self.clim = pd.DataFrame(sm, index=range(1, 366), columns=by.columns)

    def _clim_for(self, dates):
        d = np.minimum(pd.DatetimeIndex(dates).dayofyear.values, 365)
        return self.clim.loc[d].values if len(d) else np.empty((0, len(self.ids)))

    def _feats(self):
        a = self.anom
        return [a, a.shift(1), a.shift(2), a.rolling(7, min_periods=5).mean(), a.rolling(30, min_periods=20).mean()]

    def _train_models(self):
        F = self._feats()
        self.models, self.metrics_rows = {}, []
        sigma, ev = {}, {}
        W = self.wide
        idx = W.index
        for h in HORIZONS:
            y = self.anom.shift(-h)
            tgt_dates = idx + pd.Timedelta(days=h)
            X = np.stack([f.values for f in F], axis=-1)           # (T, S, 5)
            Y = y.values
            valid = ~np.isnan(X).any(-1) & ~np.isnan(Y)
            tr_mask = valid & (tgt_dates <= self.train_end)[:, None]
            te_mask = valid & (tgt_dates > self.train_end)[:, None] & ~np.isnan(W.shift(-h).values)
            m = Ridge(alpha=1.0).fit(X[tr_mask], Y[tr_mask])
            self.models[h] = m
            # test predictions
            clim_t = pd.DataFrame(self._clim_for(tgt_dates), index=idx, columns=W.columns).values
            pred_anom = np.where(te_mask, m.predict(np.nan_to_num(X).reshape(-1, 5)).reshape(Y.shape), np.nan)
            pred = clim_t + pred_anom
            obs = W.shift(-h).values
            pers = W.values
            clim_pred = clim_t
            hot = np.isin(tgt_dates.month, [3, 4, 5, 6])[:, None] & te_mask
            def mae(p, mk): return float(np.nanmean(np.abs(p[mk] - obs[mk])))
            def rmse(p, mk): return float(np.sqrt(np.nanmean((p[mk] - obs[mk]) ** 2)))
            res = (obs - pred)[te_mask]
            sigma[h] = float(np.std(res))
            obs_anom = obs - clim_t
            terr = np.tile(self.terrain, (len(idx), 1))
            lo = classify(obs, obs_anom, terr) >= 2
            lp = classify(pred, pred - clim_t, terr) >= 2
            lpers = classify(pers, pers - clim_t, terr) >= 2
            def evalf(flag):
                hits = int((flag & lo & te_mask).sum()); miss = int((~flag & lo & te_mask).sum()); fa = int((flag & ~lo & te_mask).sum())
                return {"events": hits + miss, "hits": hits, "false_alarms": fa,
                        "pod": round(hits / (hits + miss), 3) if hits + miss else None,
                        "far": round(fa / (hits + fa), 3) if hits + fa else None}
            ev[h] = {"ridge": evalf(lp), "persistence": evalf(lpers)}
            self.metrics_rows.append({
                "lead_days": h, "n_test": int(te_mask.sum()),
                "ridge": {"mae": round(mae(pred, te_mask), 3), "rmse": round(rmse(pred, te_mask), 3)},
                "persistence": {"mae": round(mae(pers, te_mask), 3), "rmse": round(rmse(pers, te_mask), 3)},
                "climatology": {"mae": round(mae(clim_pred, te_mask), 3), "rmse": round(rmse(clim_pred, te_mask), 3)},
                "ridge_hot_season_mar_jun": {"n": int(hot.sum()), "mae": round(mae(pred, hot), 3) if hot.any() else None,
                                              "rmse": round(rmse(pred, hot), 3) if hot.any() else None},
                "residual_sigma_c": round(sigma[h], 3), "event_detection_high_or_above": ev[h],
                "coefficients": dict(zip(["anom_t", "anom_t-1", "anom_t-2", "mean_anom_7d", "mean_anom_30d"],
                                         [round(float(c), 4) for c in m.coef_])),
            })
        self.sigma = sigma
        self.n_train = int((self.wide.index <= self.train_end).sum())

    def _suggest(self):
        test_days = self.level.index[(self.level.index > self.train_end) & (self.level.index <= self.wide.index.max() - pd.Timedelta(days=5))]
        cnt = (self.level.loc[test_days] >= 2).sum(axis=1)
        self.suggested_as_of = (cnt.idxmax() if len(test_days) and cnt.max() > 0 else
                                (test_days[-1] if len(test_days) else self.wide.index.max())).strftime("%Y-%m-%d")

    # ------------------------------------------------------------ forecasting
    def forecast_matrix(self, as_of: pd.Timestamp):
        key = as_of.strftime("%Y-%m-%d")
        if key in self._fc_cache: return self._fc_cache[key]
        if as_of not in self.wide.index:
            raise HTTPException(422, f"as_of {key} outside data range {self.wide.index.min().date()}..{self.wide.index.max().date()}")
        i = self.wide.index.get_loc(as_of)
        if i < 30: raise HTTPException(422, "as_of needs >= 30 days of earlier history")
        feats = np.stack([f.iloc[i].values for f in self._feats()], axis=-1)   # (S,5)
        feats = np.where(np.isnan(feats), 0.0, feats)                          # unfilled gap -> assume normal
        out = {}
        for h in HORIZONS:
            d = as_of + pd.Timedelta(days=h)
            clim = self.clim.loc[min(d.dayofyear, 365)].values
            pa = self.models[h].predict(feats)
            s = self.sigma[h]
            fc = clim + pa
            obs = self.wide.loc[d].values if d in self.wide.index else np.full(len(self.ids), np.nan)
            out[h] = {"date": d.strftime("%Y-%m-%d"), "clim": clim, "fc": fc, "anom": pa, "lo": fc - 1.645 * s, "hi": fc + 1.645 * s,
                      "level": classify(fc, pa, self.terrain), "obs": obs,
                      "obs_level": classify(obs, obs - clim, self.terrain)}
        self._fc_cache[key] = out
        return out

    def validation_status(self, as_of):
        if as_of >= self.train_end:
            return "out-of-sample (forecast targets lie after the training period)"
        return "IN-SAMPLE (as_of lies inside the training period; accuracy here is optimistic)"


E = Engine()


def engine():
    with E.lock:
        if not E.ready:
            try:
                E.build(); E.error = None
            except Exception as ex:
                E.error = f"{type(ex).__name__}: {ex}"
                log.exception("Build failed")
    if not E.ready:
        raise HTTPException(503, f"Analytics not ready - data service unreachable or invalid? ({E.error})")
    return E


def _ts(s: Optional[str], default=None):
    if not s: return default
    try:
        return pd.Timestamp(s)
    except ValueError:
        raise HTTPException(422, f"Invalid date '{s}', use YYYY-MM-DD")


def _sidx(e, sid):
    if sid not in e.ids: raise HTTPException(404, f"Unknown station {sid}")
    return e.ids.index(sid)


def _num(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd) + 0.0


def _warmup():
    import time
    for _ in range(40):  # retry while the data service is still starting
        try:
            engine()
            return
        except HTTPException:
            time.sleep(3)


@app.on_event("startup")
def _startup():
    threading.Thread(target=_warmup, daemon=True).start()


@app.get("/health")
def health():
    return {"service": "analytics_service", "status": "ok" if E.ready else ("degraded" if E.error else "starting"), "model_ready": E.ready,
            "built_at": E.built_at, "error": E.error, "data_service": DATA_URL}


@app.get("/meta")
def meta():
    e = engine()
    return {"first_date": e.wide.index.min().strftime("%Y-%m-%d"), "last_date": e.wide.index.max().strftime("%Y-%m-%d"),
            "train_end": e.train_end.strftime("%Y-%m-%d"), "suggested_as_of": e.suggested_as_of, "horizons": HORIZONS,
            "risk_levels": LEVELS, "seasons": SEASONS, "data_summary": e.data_summary,
            "missing_values_before_gap_fill": e.n_missing_raw}


@app.get("/config/risk")
def config_risk():
    return CFG


@app.get("/model/metrics")
def model_metrics():
    e = engine()
    return {"model": "Pooled Ridge regression on temperature anomalies (lags 0,1,2, 7-day and 30-day mean anomaly), one model per lead time",
            "baselines": ["persistence (Tmax(t+h)=Tmax(t))", "daily climatology of training years"],
            "split": {"type": "time-based", "train_end": e.train_end.strftime("%Y-%m-%d"), "test_start": (e.train_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                      "test_end": e.wide.index.max().strftime("%Y-%m-%d"), "n_train_days": e.n_train},
            "interval": "90% interval = forecast +/- 1.645 x hold-out residual std (empirical, assumes roughly normal, constant spread)",
            "per_lead": e.metrics_rows,
            "caveat": "Metrics describe skill on the loaded dataset only. With the synthetic sample dataset they demonstrate the pipeline, not real-world accuracy."}


@app.get("/series/{station_id}")
def series(station_id: str, start: Optional[str] = None, end: Optional[str] = None):
    e = engine(); j = _sidx(e, station_id)
    w = e.wide.iloc[:, j]
    s, en = _ts(start, w.index.min()), _ts(end, w.index.max())
    m = (w.index >= s) & (w.index <= en)
    idx = w.index[m]
    normal = e._clim_for(idx)[:, j]
    rows = [{"date": d.strftime("%Y-%m-%d"), "tmax_c": _num(v), "normal_c": _num(n), "anomaly_c": _num(v - n) if not np.isnan(v) else None,
             "risk_level": int(l) if l >= 0 else None} for d, v, n, l in zip(idx, w[m].values, normal, e.level.iloc[:, j][m].values)]
    return {"station_id": station_id, "station_name": e.stations.iloc[j]["station_name"], "train_end": e.train_end.strftime("%Y-%m-%d"), "series": rows}


@app.get("/trends")
def trends(station_id: Optional[str] = None, region: Optional[str] = None):
    e = engine()
    cols = [c for c in e.ids if (not station_id or c == station_id) and (not region or e.stations.loc[c, "region"] == region)]
    if not cols: raise HTTPException(404, "No matching stations")
    sub = e.wide[cols]
    mon = sub.mean(axis=1).groupby(sub.index.to_period("M")).agg(["mean", "max", "count"])
    mx = sub.max(axis=1).groupby(sub.index.to_period("M")).max()
    monthly = [{"month": str(p), "mean_tmax_c": _num(r["mean"]), "max_tmax_c": _num(mx[p])} for p, r in mon.iterrows()]
    pre = sub[sub.index.month.isin([3, 4, 5])].mean(axis=1).groupby(lambda d: d.year).mean()
    annual = [{"year": int(y), "premonsoon_mean_tmax_c": _num(v, 2)} for y, v in pre.items()]
    slope = float(np.polyfit(pre.index.values, pre.values, 1)[0] * 10) if len(pre) >= 3 else None
    return {"scope": station_id or region or "All stations", "n_stations": len(cols), "monthly": monthly, "premonsoon_annual": annual,
            "premonsoon_trend_c_per_decade": _num(slope, 2),
            "trend_note": f"Linear trend over only {len(pre)} years - indicative, not statistically robust."}


@app.get("/seasonal")
def seasonal():
    e = engine(); rows = []
    nyears = len(e.wide) / 365.25
    groups = {"All stations": e.ids} | {r: [c for c in e.ids if e.stations.loc[c, "region"] == r] for r in sorted(e.stations["region"].unique())}
    for g, cols in groups.items():
        for sname, months in SEASONS.items():
            msk = e.wide.index.month.isin(months)
            vals = e.wide.loc[msk, cols]
            lv = e.level.loc[msk, cols]
            rows.append({"region": g, "season": sname, "mean_tmax_c": _num(np.nanmean(vals.values)),
                         "p95_tmax_c": _num(np.nanpercentile(vals.values, 95)),
                         "high_or_above_station_days_per_year": _num(float((lv.values >= 2).sum()) / nyears / len(cols), 2)})
    return {"seasons": SEASONS, "rows": rows, "note": "Seasons follow the usual IMD split (Winter Jan-Feb, Pre-monsoon Mar-May, Monsoon Jun-Sep, Post-monsoon Oct-Dec)."}


def _asof(e, as_of):
    t = _ts(as_of, e.wide.index.max())
    if t > e.wide.index.max() or t < e.wide.index.min():
        raise HTTPException(422, f"as_of outside data range {e.wide.index.min().date()}..{e.wide.index.max().date()}")
    return t


@app.get("/forecast/{station_id}")
def forecast(station_id: str, as_of: Optional[str] = None):
    e = engine(); j = _sidx(e, station_id); t = _asof(e, as_of)
    fm = e.forecast_matrix(t)
    st = e.stations.iloc[j]
    obs0, an0, lv0 = e.wide.loc[t].iloc[j], e.anom.loc[t].iloc[j], e.level.loc[t].iloc[j]
    leads = []
    for h in HORIZONS:
        f = fm[h]
        o = f["obs"][j]
        leads.append({"lead_days": h, "date": f["date"], "forecast_tmax_c": _num(f["fc"][j]), "lower_90_c": _num(f["lo"][j]), "upper_90_c": _num(f["hi"][j]),
                      "normal_c": _num(f["clim"][j]), "forecast_anomaly_c": _num(f["anom"][j]), "risk_level": int(f["level"][j]), "risk_label": LEVELS[int(f["level"][j])],
                      "observed_tmax_c": _num(o), "observed_risk_level": int(f["obs_level"][j]) if not np.isnan(o) else None,
                      "error_c": _num(f["fc"][j] - o, 2) if not np.isnan(o) else None})
    mx = max(leads, key=lambda l: (l["risk_level"], l["forecast_tmax_c"]))
    return {"station_id": station_id, "station_name": st["station_name"], "region": st["region"], "terrain": st["terrain"],
            "latitude": float(st["latitude"]), "longitude": float(st["longitude"]), "as_of": t.strftime("%Y-%m-%d"),
            "observed_on_as_of": {"tmax_c": _num(obs0), "anomaly_c": _num(an0), "risk_level": int(lv0), "risk_label": LEVELS[int(lv0)] if lv0 >= 0 else None,
                                  "explanation": explain(obs0, an0, st["terrain"], int(lv0)) if lv0 >= 0 else "Observation missing"},
            "forecast": leads, "peak_forecast_risk": {"risk_level": mx["risk_level"], "risk_label": mx["risk_label"], "lead_days": mx["lead_days"], "date": mx["date"]},
            "validation_status": e.validation_status(t), "data_is_sample": e.data_summary.get("is_sample_data", True),
            "uncertainty_note": "90% interval from hold-out residuals; actual error can exceed it, especially for extremes.",
            "label": CFG["label"]}


@app.get("/snapshot")
def snapshot(as_of: Optional[str] = None):
    """All stations at once: observed state on as_of + 5-day forecast summary."""
    e = engine(); t = _asof(e, as_of); fm = e.forecast_matrix(t)
    rows = []
    for j, sid in enumerate(e.ids):
        st = e.stations.iloc[j]
        lv = int(e.level.loc[t].iloc[j]); lvl_f = [int(fm[h]["level"][j]) for h in HORIZONS]
        peak_h = int(np.argmax(lvl_f)) if max(lvl_f) > 0 else int(np.argmax([fm[h]["fc"][j] for h in HORIZONS]))
        peak_h = HORIZONS[peak_h]
        rows.append({"station_id": sid, "station_name": st["station_name"], "region": st["region"], "terrain": st["terrain"],
                     "latitude": float(st["latitude"]), "longitude": float(st["longitude"]),
                     "observed_tmax_c": _num(e.wide.loc[t].iloc[j]), "observed_anomaly_c": _num(e.anom.loc[t].iloc[j]),
                     "observed_risk_level": lv, "observed_risk_label": LEVELS[lv] if lv >= 0 else "No data",
                     "predicted_max_tmax_c": _num(max(fm[h]["fc"][j] for h in HORIZONS)),
                     "predicted_max_anomaly_c": _num(max(fm[h]["anom"][j] for h in HORIZONS)),
                     "predicted_risk_level": max(lvl_f), "predicted_risk_label": LEVELS[max(lvl_f)], "predicted_peak_lead_days": peak_h,
                     "predicted_peak_date": fm[peak_h]["date"], "predicted_peak_upper_90_c": _num(fm[peak_h]["hi"][j]),
                     "predicted_levels_by_lead": lvl_f})
    return {"as_of": t.strftime("%Y-%m-%d"), "validation_status": e.validation_status(t), "stations": rows,
            "data_is_sample": e.data_summary.get("is_sample_data", True), "label": CFG["label"]}


@app.get("/regional")
def regional(as_of: Optional[str] = None):
    snap = snapshot(as_of)
    df = pd.DataFrame(snap["stations"]); out = []
    for r, g in df.groupby("region"):
        out.append({"region": r, "n_stations": int(len(g)), "mean_observed_tmax_c": _num(g["observed_tmax_c"].mean()),
                    "observed_levels": {LEVELS[i]: int((g["observed_risk_level"] == i).sum()) for i in range(4)},
                    "predicted_levels": {LEVELS[i]: int((g["predicted_risk_level"] == i).sum()) for i in range(4)}})
    return {"as_of": snap["as_of"], "validation_status": snap["validation_status"], "regions": out}


@app.get("/hotspots/historical")
def hotspots_historical(start: Optional[str] = None, end: Optional[str] = None):
    e = engine()
    s, en = _ts(start, e.wide.index.min()), _ts(end, e.wide.index.max())
    m = (e.wide.index >= s) & (e.wide.index <= en)
    W, L = e.wide[m], e.level[m]
    nyears = max(m.sum() / 365.25, 1e-9)
    rows = []
    for j, sid in enumerate(e.ids):
        lv = L.iloc[:, j].values >= 2
        streak = best = 0
        for v in lv:
            streak = streak + 1 if v else 0; best = max(best, streak)
        pre = W.iloc[:, j][W.index.month.isin([3, 4, 5, 6])]
        st = e.stations.iloc[j]
        rows.append({"station_id": sid, "station_name": st["station_name"], "region": st["region"], "terrain": st["terrain"],
                     "latitude": float(st["latitude"]), "longitude": float(st["longitude"]),
                     "high_or_above_days_per_year": _num(lv.sum() / nyears, 2), "severe_days_per_year": _num((L.iloc[:, j].values == 3).sum() / nyears, 2),
                     "p95_tmax_mar_jun_c": _num(np.nanpercentile(pre.values, 95)), "longest_high_streak_days": int(best),
                     "max_tmax_c": _num(W.iloc[:, j].max())})
    df = pd.DataFrame(rows)
    def norm(c):
        v = df[c].astype(float); r = v.max() - v.min()
        return (v - v.min()) / r if r > 0 else v * 0
    wts = CFG["hotspot_weights"]
    contrib = {"hw_days": 100 * wts["hw_days"] * norm("high_or_above_days_per_year"), "p95": 100 * wts["p95"] * norm("p95_tmax_mar_jun_c"),
               "streak": 100 * wts["streak"] * norm("longest_high_streak_days")}
    df["score"] = (contrib["hw_days"] + contrib["p95"] + contrib["streak"]).round(1)
    df["factor_contributions"] = [{k: round(float(v.iloc[i]), 1) for k, v in contrib.items()} for i in range(len(df))]
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    return {"source": "historical", "period": [s.strftime("%Y-%m-%d"), en.strftime("%Y-%m-%d")], "weights": wts,
            "method": "score = 100 x (w1*norm(High+ days/yr) + w2*norm(P95 Tmax Mar-Jun) + w3*norm(longest High+ streak)); min-max across stations",
            "stations": df.to_dict("records")}


@app.get("/validation/aws")
def validation_aws():
    """Phase IV: compare 1-day-ahead forecasts with (simulated) AWS readings and with the dataset record."""
    e = engine()
    with httpx.Client(timeout=30) as c:
        try:
            readings = c.get(f"{DATA_URL}/aws/readings", params={"limit": 5000}).json()["readings"]
        except httpx.HTTPError as ex:
            raise HTTPException(503, f"Data service unreachable: {ex}")
    rows = []
    for r in readings:
        if r["station_id"] not in e.ids: continue
        d = pd.Timestamp(r["date"]); prev = d - pd.Timedelta(days=1)
        if prev not in e.wide.index or d not in e.wide.index or prev < e.wide.index[30]: continue
        j = e.ids.index(r["station_id"]); f = e.forecast_matrix(prev)[1]
        rec = e.wide.loc[d].iloc[j]
        rows.append({"station_id": r["station_id"], "station_name": e.stations.iloc[j]["station_name"], "date": r["date"], "aws_tmax_c": r["tmax_c"],
                     "forecast_lead1_c": _num(f["fc"][j]), "record_tmax_c": _num(rec), "forecast_minus_aws_c": _num(f["fc"][j] - r["tmax_c"], 2),
                     "aws_minus_record_c": _num(r["tmax_c"] - rec, 2), "simulated": bool(r.get("simulated", True)),
                     "forecast_risk": LEVELS[int(f["level"][j])], "aws_risk": LEVELS[int(classify(r["tmax_c"], r["tmax_c"] - f["clim"][j], e.terrain[j]))]})
    if not rows:
        return {"n": 0, "rows": [], "message": "No AWS readings yet. POST /aws/simulate on the data service (or use the System page button)."}
    df = pd.DataFrame(rows)
    return {"n": len(df), "mae_forecast_vs_aws_c": _num(df["forecast_minus_aws_c"].abs().mean(), 2),
            "rmse_forecast_vs_aws_c": _num(np.sqrt((df["forecast_minus_aws_c"] ** 2).mean()), 2),
            "bias_forecast_minus_aws_c": _num(df["forecast_minus_aws_c"].mean(), 2),
            "risk_category_agreement_pct": _num(100 * (df["forecast_risk"] == df["aws_risk"]).mean(), 1),
            "all_simulated": bool(df["simulated"].all()),
            "note": "AWS readings are SIMULATED (dataset value + bias/noise). This demonstrates the validation pipeline, not real sensor agreement.",
            "rows": df.sort_values(["date", "station_id"]).tail(300).to_dict("records")}
