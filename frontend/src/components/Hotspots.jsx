import React, { useState } from "react";
import { useApi, qs } from "../api.js";
import { Async, Card, Kind, LEVELS, RiskBadge, fmt } from "../ui.jsx";

const INFO = {
  predicted: ["forecast", "MODEL-GENERATED. Stations ranked by the highest risk level forecast within the next 5 days, then by the largest forecast departure from normal. Score = 25 × level + 2.5 × departure (capped at 10 °C)."],
  historical: ["historical", "DERIVED FROM HISTORICAL OBSERVATIONS. Score = 100 × (0.5·norm(High+ days/yr) + 0.25·norm(P95 Tmax Mar–Jun) + 0.25·norm(longest High+ streak)), min-max normalised across stations. No model involved."],
  observed: ["observed", "OBSERVED on the as-of date from the dataset record; ranked by risk level then departure from normal."],
};
const CC = { hw_days: "#a4123f", p95: "#dd6b20", streak: "#d9a21b" };

export default function Hotspots({ asOf, region, setStation, goto }) {
  const [source, setSource] = useState("predicted");
  const r = useApi(`/api/ranking/${source}${qs({ as_of: asOf, region, top: 12 })}`);
  const c = useApi(`/api/clusters/${source}${qs({ as_of: asOf })}`);
  return (
    <div className="grid">
      <Card title="Hotspot ranking" right={<div className="seg">{Object.keys(INFO).map((k) => <button key={k} className={source === k ? "on" : ""} onClick={() => setSource(k)}>{k}</button>)}</div>}>
        <div style={{ marginBottom: 10 }}><Kind k={INFO[source][0]} /> <span className="note">{INFO[source][1]}</span></div>
        <Async s={r} what="ranking">{(d) => (
          <table>
            <thead><tr><th>#</th><th>Station</th><th>Region</th><th>Risk</th><th>Score</th><th>Contributing factors</th></tr></thead>
            <tbody>{d.ranking.map((x) => (
              <tr key={x.station_id} className="click" onClick={() => { setStation(x.station_id); goto("Advisory"); }}>
                <td>{x.rank}</td><td><b>{x.station_name}</b></td><td>{x.region}</td><td><RiskBadge level={x.level} /></td>
                <td>{fmt(x.score)}
                  {x.factor_contributions && <div className="contrib" title="weights × normalised factors">{Object.entries(x.factor_contributions).map(([k, v]) => <span key={k} style={{ width: `${v}%`, background: CC[k] }} />)}</div>}</td>
                <td className="note">{Object.entries(x.factors).map(([k, v]) => <div key={k}>{k}: <b>{fmt(v, /days|streak/i.test(k) ? 0 : 1)}</b></div>)}</td>
              </tr>))}</tbody>
          </table>)}
        </Async>
        {source === "historical" && <p className="note"><span style={{ color: CC.hw_days }}>■</span> High+ days &nbsp;<span style={{ color: CC.p95 }}>■</span> P95 Tmax &nbsp;<span style={{ color: CC.streak }}>■</span> streak. Click a row to open its advisory.</p>}
      </Card>
      <Card title="Hotspot clusters" right={<Kind k={INFO[source][0]} />}>
        <Async s={c} what="clusters">{(d) => (d.clusters.length === 0 ? <div className="note">{d.message || "No clusters (fewer than 2 nearby flagged stations)."} {d.isolated?.length ? `Isolated: ${d.isolated.join(", ")}.` : ""}</div> : (
          <>
            <table><thead><tr><th>#</th><th>Stations</th><th>Regions</th><th>Max level</th><th>Mean score</th><th>Radius</th></tr></thead>
              <tbody>{d.clusters.map((x) => <tr key={x.cluster_rank}><td>{x.cluster_rank}</td><td>{x.stations.join(", ")}</td><td>{x.regions.join(", ")}</td><td><RiskBadge level={LEVELS.indexOf(x.max_level)} /></td><td>{x.mean_score}</td><td>{x.radius_km} km</td></tr>)}</tbody></table>
            <p className="note">{d.method}. Isolated flagged stations: {d.isolated.join(", ") || "none"}.</p>
          </>))}
        </Async>
      </Card>
    </div>
  );
}
