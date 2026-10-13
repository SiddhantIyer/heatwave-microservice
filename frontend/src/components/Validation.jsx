import React, { useState } from "react";
import { api, useApi } from "../api.js";
import { Async, Card, ErrorBox, Kind, Stat, fmt } from "../ui.jsx";

export default function Validation({ asOf }) {
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const m = useApi("/api/model/metrics");
  const v = useApi(`/api/validation/aws?t=${tick}`);

  const act = async (fn) => { setBusy(true); setErr(null); try { await fn(); setTick((t) => t + 1); } catch (e) { setErr(e.message); } setBusy(false); };

  return (
    <div className="grid">
      <Card title="Forecast model evaluation (time-based hold-out)" right={<Kind k="forecast" />}>
        <Async s={m} what="metrics">{(d) => (
          <>
            <p className="note"><b>Model:</b> {d.model}.<br /><b>Split:</b> train ≤ {d.split.train_end} ({d.split.n_train_days} days) · test {d.split.test_start} → {d.split.test_end}. {d.interval}.</p>
            <table>
              <thead><tr><th>Lead</th><th>Test n</th><th>Ridge MAE / RMSE</th><th>Persistence MAE / RMSE</th><th>Climatology MAE / RMSE</th><th>Ridge MAE Mar–Jun</th><th>Residual std (°C)</th><th>High+ event detection (ridge): POD / FAR</th></tr></thead>
              <tbody>{d.per_lead.map((r) => {
                const e = r.event_detection_high_or_above.ridge;
                return <tr key={r.lead_days}><td>+{r.lead_days}d</td><td>{r.n_test.toLocaleString()}</td>
                  <td><b>{r.ridge.mae} / {r.ridge.rmse}</b></td><td>{r.persistence.mae} / {r.persistence.rmse}</td><td>{r.climatology.mae} / {r.climatology.rmse}</td>
                  <td>{fmt(r.ridge_hot_season_mar_jun.mae, 2)}</td><td>{r.residual_sigma_c}</td>
                  <td>{e.pod ?? "n/a"} / {e.far ?? "n/a"} <span className="note">({e.hits}/{e.events} events)</span></td></tr>;
              })}</tbody>
            </table>
            <p className="note" style={{ color: "#8d1d1d" }}><b>Honest reading:</b> the regression improves average Tmax error over both baselines, but it regresses towards normal and therefore detects few High+ heat events (low POD). Extreme-event skill is weak; this is shown, not hidden. {d.caveat}</p>
          </>)}
        </Async>
      </Card>

      <Card title="IoT-AWS integration — SIMULATED" right={<Kind k="simulated" />}>
        <p className="note">No physical Automated Weather Station is deployed. The button below makes the Data Service create <b>simulated</b> AWS readings (dataset value + sensor bias/noise) for six stations, then the Analytics Service compares them with 1-day-ahead forecasts. This demonstrates Phases III–IV plumbing, not real sensor agreement.</p>
        <div className="pill-row">
          <button disabled={busy} onClick={() => act(() => api(`/api/aws/simulate?end_date=${asOf}&days=7`, { method: "POST" }))}>Simulate 7 days of AWS readings up to {asOf}</button>
          <button className="ghost" disabled={busy} onClick={() => act(() => api("/api/aws/readings", { method: "DELETE" }))}>Clear readings</button>
        </div>
        {err && <ErrorBox error={err} />}
        <Async s={v} what="AWS validation">{(d) => d.n === 0 ? <p className="note">{d.message}</p> : (
          <>
            <div className="grid g4" style={{ margin: "14px 0" }}>
              <Stat label="Readings compared" value={d.n} kind="simulated" />
              <Stat label="MAE forecast vs AWS" value={`${d.mae_forecast_vs_aws_c} °C`} sub={`RMSE ${d.rmse_forecast_vs_aws_c} · bias ${d.bias_forecast_minus_aws_c}`} />
              <Stat label="Risk-category agreement" value={`${d.risk_category_agreement_pct}%`} />
            </div>
            <table><thead><tr><th>Date</th><th>Station</th><th>AWS (sim) °C</th><th>Forecast +1d °C</th><th>Dataset record °C</th><th>Fcst − AWS</th><th>Fcst risk</th><th>AWS risk</th></tr></thead>
              <tbody>{d.rows.slice(-24).map((r, i) => <tr key={i}><td>{r.date}</td><td>{r.station_name}</td><td>{fmt(r.aws_tmax_c)}</td><td>{fmt(r.forecast_lead1_c)}</td><td>{fmt(r.record_tmax_c)}</td><td>{fmt(r.forecast_minus_aws_c, 2)}</td><td>{r.forecast_risk}</td><td>{r.aws_risk}</td></tr>)}</tbody></table>
            <p className="note">{d.note} Showing latest 24 rows of {d.n}.</p>
          </>)}
        </Async>
      </Card>
    </div>
  );
}
