import React, { useEffect, useState } from "react";
import { api, useApi } from "../api.js";
import { Card, ErrorBox, Kind, Loading, RiskBadge, Stat, fmt } from "../ui.jsx";

const STAKEHOLDERS = [["citizen", "Citizens"], ["health", "Public health"], ["farmer", "Farmers"], ["authority", "Local authorities"]];

export default function Advisory({ meta, asOf, region, station, setStation }) {
  const [stakeholder, setStakeholder] = useState("citizen");
  const [useLlm, setUseLlm] = useState(false);
  const [res, setRes] = useState({ loading: true });
  const health = useApi("/api/health");
  const llm = health.data?.services?.advisory?.llm_configured;
  const stations = meta.stations.filter((s) => !region || s.region === region);
  const sel = stations.find((s) => s.station_id === station) ? station : stations[0]?.station_id;

  useEffect(() => {
    let live = true;
    setRes({ loading: true });
    api("/api/advisory", { method: "POST", body: JSON.stringify({ station_id: sel, stakeholder, as_of: asOf, use_llm: useLlm }) })
      .then((d) => live && setRes({ data: d })).catch((e) => live && setRes({ error: e.message }));
    return () => { live = false; };
  }, [sel, stakeholder, asOf, useLlm]);

  const review = async (approve) => {
    try { const a = await api(`/api/advisory/${res.data.advisory.id}/review?approve=${approve}`, { method: "POST" }); setRes({ data: { ...res.data, advisory: a } }); }
    catch (e) { setRes({ ...res, error: e.message }); }
  };
  const a = res.data?.advisory, f = res.data?.forecast;

  return (
    <div className="grid">
      <Card>
        <div className="pill-row" style={{ alignItems: "center" }}>
          <label>Location&nbsp;
            <select value={sel} onChange={(e) => setStation(e.target.value)}>{stations.map((s) => <option key={s.station_id} value={s.station_id}>{s.station_name}</option>)}</select>
          </label>
          <div className="seg">{STAKEHOLDERS.map(([k, l]) => <button key={k} className={stakeholder === k ? "on" : ""} onClick={() => setStakeholder(k)}>{l}</button>)}</div>
          <label title={llm ? "" : "Set ANTHROPIC_API_KEY for the advisory service to enable"}>
            <input type="checkbox" disabled={!llm} checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> LLM-assisted wording {llm ? "" : "(not configured — rule-based mode)"}
          </label>
        </div>
      </Card>
      {res.error && <ErrorBox error={res.error} />}
      {res.loading && <Loading what="advisory" />}
      {f && a && (
        <div className="grid g2">
          <Card title={`Estimated risk — ${f.station_name}`} right={<Kind k="forecast" />}>
            <div className="grid g4" style={{ gridTemplateColumns: "1fr 1fr" }}>
              <Stat label="Peak forecast risk" value={<RiskBadge level={f.peak_forecast_risk.risk_level} />} sub={`day +${f.peak_forecast_risk.lead_days} (${f.peak_forecast_risk.date})`} />
              <Stat label="Observed on as-of date" value={`${fmt(f.observed_on_as_of.tmax_c)} °C`} sub={<><RiskBadge level={f.observed_on_as_of.risk_level} /> {f.as_of}</>} kind="observed" />
            </div>
            <table style={{ marginTop: 12 }}><thead><tr><th>Date</th><th>Forecast °C</th><th>90% range</th><th>Risk</th></tr></thead>
              <tbody>{f.forecast.map((l) => <tr key={l.date}><td>{l.date}</td><td>{fmt(l.forecast_tmax_c)}</td><td>{fmt(l.lower_90_c)}–{fmt(l.upper_90_c)}</td><td><RiskBadge level={l.risk_level} /></td></tr>)}</tbody></table>
            <p className="note"><b>Basis for the observed-day risk:</b> {f.observed_on_as_of.explanation}</p>
            <p className="note">{f.validation_status}. Forecast period: {f.forecast[0].date} → {f.forecast[4].date}.</p>
          </Card>
          <Card title={a.title} right={<><Kind k="sample" /> <span className="pill">{a.generated_by}</span></>}>
            <div className="adv">{a.text}</div>
            <div className="pill-row" style={{ marginTop: 12 }}>
              <span className="pill">Status: <b>{a.review_status}</b></span>
              <span className="pill">Issued from data as of {a.as_of}</span>
              <span className="pill">{a.data_basis}</span>
            </div>
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <button onClick={() => review(true)}>Mark reviewed (human-in-the-loop demo)</button>
              <button className="ghost" onClick={() => review(false)}>Reject</button>
            </div>
            <p className="note" style={{ marginTop: 10 }}><b>Limitations:</b> {a.limitations.join(" ")}</p>
            <div className="adv-disc">{a.disclaimer}</div>
          </Card>
        </div>
      )}
    </div>
  );
}
