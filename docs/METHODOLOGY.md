# AI methodology

## 1. Preprocessing
Validated daily Tmax → wide matrix (date × station) → gaps ≤ 3 days interpolated → **climatology** = mean by day-of-year over the training years, circularly smoothed (31-day window) → **anomaly** = Tmax − climatology.

## 2. Prototype risk index (transparent, configurable: `risk_config.json`)
Levels: Low / Moderate / High / Severe. Let `thr` = 40 °C plains, 37 °C coastal, 30 °C hill.
* **Severe**: Tmax ≥ thr and anomaly ≥ 6.5 °C, or plains Tmax ≥ 47 °C
* **High**: Tmax ≥ thr and anomaly ≥ 4.5 °C, or plains Tmax ≥ 45 °C
* **Moderate**: Tmax ≥ thr, or (anomaly ≥ 4.5 °C and Tmax ≥ thr − 3)
* **Low**: otherwise

These mirror the structure of published IMD heatwave criteria as I recall them, but the numbers were **not verified online** and the index uses a normal derived from five synthetic years, so it is *not* an IMD classification. "High+" in the UI means High or Severe.

## 3. Forecasting
* Target: Tmax anomaly at lead h = 1…5 days; one **Ridge regression** (α = 1) per lead, pooled over stations.
* Features: anomaly at t, t−1, t−2, 7-day mean anomaly, 30-day mean anomaly. Forecast = climatology(t+h) + predicted anomaly.
* **Time-aware split:** train on targets ≤ 2024-12-31, test on targets in 2025 (10,220 station-day cases per lead). Climatology also uses training years only → no future leakage.
* Baselines: persistence and climatology.
* Uncertainty: 90 % interval = forecast ± 1.645 × hold-out residual std (empirical; assumes near-normal, constant spread).
* As-of dates inside the training period are flagged **in-sample (optimistic)**; dates after 2024-12-31 are out-of-sample hindcasts.

## 4. Evaluation results (this run, synthetic data)
| Lead | Ridge MAE / RMSE | Persistence | Climatology | Residual σ |
|---|---|---|---|---|
| +1 d | 0.86 / 1.09 | 0.93 / 1.18 | 1.21 / 1.52 | 1.08 |
| +2 d | 1.05 / 1.32 | 1.21 / 1.53 | 1.21 / 1.52 | 1.31 |
| +3 d | 1.13 / 1.42 | 1.37 / 1.72 | 1.21 / 1.52 | 1.40 |
| +4 d | 1.16 / 1.46 | 1.47 / 1.85 | 1.21 / 1.52 | 1.44 |
| +5 d | 1.18 / 1.49 | 1.54 / 1.94 | 1.21 / 1.52 | 1.47 |

**Event detection (High+, 32 station-days in the test year):** at +1 d the model hit 3 of 32 (POD 0.09, FAR 0.50); at +2…+5 d it hit none. Persistence catches more events but with false-alarm ratios of 0.8–0.97. Conclusion: the model improves average temperature error but is **not a usable heatwave-event detector**; it regresses to normal. Because the data are synthetic, nothing here measures real-world accuracy. Reproduce with `GET /api/model/metrics`.

## 5. Hotspots
* **Historical:** per station over the full record: High+ days per year, 95th-percentile Tmax in Mar–Jun, longest High+ streak; min-max normalised, weighted 0.5/0.25/0.25 → score 0–100 (flagged hotspot if ≥ 40). Contribution bars show each factor's share.
* **Predicted:** highest forecast risk level in the next 5 days, then largest forecast anomaly; score = 25 × level + 2.5 × anomaly (capped at 10 °C).
* **Observed:** risk on the as-of date from the record.
* **Clusters:** DBSCAN (haversine, ε = 450 km, min 2 stations) on flagged stations; reported with centroid, radius, members. Analytical groupings only.

## 6. Advisory generation
Rule-based templates per stakeholder × level are the default. Optional LLM mode sends only the structured facts and the rule-based draft with an instruction to rephrase without adding numbers/places/actions; any failure falls back to rules. All advisories are DRAFT, carry limitations and a not-official disclaimer, and need a (demo) human review click.

## 7. Phase IV validation with AWS
Simulated AWS value = dataset record + 0.3 °C bias + N(0, 0.8). The comparison therefore tests the pipeline, not real sensors.
