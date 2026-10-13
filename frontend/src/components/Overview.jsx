import React from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi, qs } from "../api.js";
import { Async, Card, Kind, LEVELS, RISK_COLORS, RiskBadge, Stat, fmt } from "../ui.jsx";

function RegionChart({ rows, field, title, kind }) {
  const data = rows.map((r) => ({ region: r.region.replace(" & ", "/"), ...r[field] }));
  return (
    <Card title={title} right={<Kind k={kind} />}>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} layout="vertical" margin={{ left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" allowDecimals={false} />
          <YAxis type="category" dataKey="region" width={150} tick={{ fontSize: 12 }} />
          <Tooltip />
          <Legend />
          {LEVELS.map((l, i) => <Bar key={l} dataKey={l} stackId="a" fill={RISK_COLORS[i]} />)}
        </BarChart>
      </ResponsiveContainer>
    </Card>
  );
}

export default function Overview({ asOf, region, goto, setStation }) {
  const s = useApi(`/api/overview${qs({ as_of: asOf })}`);
  return (
    <Async s={s} what="overview">
      {(d) => {
        const regional = d.regional.filter((r) => !region || r.region === region);
        const ds = d.dataset;
        return (
          <div className="grid">
            <div className="grid g4">
              <Card><Stat label="Stations / observations" value={`${ds.n_stations} / ${ds.n_observations.toLocaleString()}`} sub={`${ds.date_min} → ${ds.date_max}`} kind={ds.is_sample_data ? "sample" : "historical"} /></Card>
              <Card><Stat label="Latest recorded Tmax in dataset" value={`${fmt(ds.latest_max_tmax_c)} °C`} sub={`${ds.latest_max_station} · ${ds.latest_timestamp} (hottest station that day; mean ${fmt(ds.latest_mean_tmax_c)} °C)`} kind="observed" /></Card>
              <Card><Stat label={`High+ stations observed on ${d.as_of}`} value={d.counts.observed_high_or_above} sub={`of ${ds.n_stations} stations`} kind="observed" /></Card>
              <Card><Stat label="High+ stations in 5-day forecast" value={d.counts.predicted_high_or_above} sub={`Historical hotspots (score ≥ 40): ${d.counts.historical_hotspots}`} kind="forecast" /></Card>
            </div>
            <div className="grid g2">
              <RegionChart rows={regional} field="observed_levels" title={`Regional risk distribution — observed on ${d.as_of}`} kind="observed" />
              <RegionChart rows={regional} field="predicted_levels" title="Regional risk distribution — peak risk in next 5-day forecast" kind="forecast" />
            </div>
            <div className="grid g2">
              <Card title={`Hottest observed stations on ${d.as_of}`} right={<Kind k="observed" />}>
                <table><thead><tr><th>Station</th><th>Region</th><th>Tmax °C</th><th>Departure</th><th>Risk</th></tr></thead>
                  <tbody>{d.hottest_observed.map((x) => (
                    <tr key={x.station_id} className="click" onClick={() => { setStation(x.station_id); goto("Advisory"); }}>
                      <td>{x.station_name}</td><td>{x.region}</td><td>{fmt(x.observed_tmax_c)}</td>
                      <td>{x.observed_anomaly_c > 0 ? "+" : ""}{fmt(x.observed_anomaly_c)} °C</td><td><RiskBadge level={x.observed_risk_level} /></td>
                    </tr>))}</tbody></table>
              </Card>
              <Card title="Predicted hotspot clusters (High+)" right={<Kind k="forecast" />}>
                {d.predicted_clusters.length === 0 ? <div className="note">No clusters of High+ stations are forecast for this date.</div> : (
                  <table><thead><tr><th>#</th><th>Stations</th><th>Max level</th><th>Radius</th></tr></thead>
                    <tbody>{d.predicted_clusters.map((c) => (
                      <tr key={c.cluster_rank}><td>{c.cluster_rank}</td><td>{c.stations.join(", ")}</td><td><RiskBadge level={LEVELS.indexOf(c.max_level)} /></td><td>{c.radius_km} km</td></tr>))}</tbody></table>
                )}
                <p className="note">Clusters group nearby flagged stations (DBSCAN); they are analytical groupings, not official hazard zones.</p>
              </Card>
            </div>
            <p className="note">Dataset provenance: {ds.data_sources.join(", ")}. Forecast status: {d.validation_status}.</p>
          </div>
        );
      }}
    </Async>
  );
}
