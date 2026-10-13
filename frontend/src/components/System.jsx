import React, { useEffect, useState } from "react";
import { api, useApi } from "../api.js";
import { Async, Card, ErrorBox, Kind } from "../ui.jsx";

const PORTS = { gateway: 8000, data: 8001, analytics: 8002, geo: 8003, advisory: 8004 };
const COLOR = { ok: "#3d8f7a", starting: "#d9a21b", degraded: "#dd6b20", down: "#a4123f" };

export default function System() {
  const [h, setH] = useState({ loading: true });
  const [stamp, setStamp] = useState(null);
  useEffect(() => {
    let live = true;
    const load = () => api("/api/health").then((d) => { if (live) { setH({ data: d }); setStamp(new Date().toLocaleTimeString()); } })
      .catch((e) => live && setH({ error: e.message }));
    load(); const t = setInterval(load, 8000);
    return () => { live = false; clearInterval(t); };
  }, []);
  const q = useApi("/api/data/quality");
  const cfg = useApi("/api/config/risk");

  return (
    <div className="grid">
      <Card title="Microservice health" right={<span className="note">auto-refresh 8 s · last check {stamp || "…"}</span>}>
        {h.error && <ErrorBox error={h.error} />}
        {h.data && (
          <table><thead><tr><th>Service</th><th>Port</th><th>Status</th><th>Latency</th><th>Details</th></tr></thead>
            <tbody>{Object.entries(h.data.services).map(([k, v]) => (
              <tr key={k}><td><b>{k}</b></td><td className="mono">{PORTS[k]}</td>
                <td><span className="dot" style={{ background: COLOR[v.status] || "#999" }} />{v.status}</td><td>{v.latency_ms ? `${v.latency_ms} ms` : "—"}</td>
                <td className="note">{k === "data" && `dataset ${v.dataset}; source ${v.data_source?.join(", ")}; loaded ${v.loaded_at?.slice(0, 19)}Z`}
                  {k === "analytics" && `model ready: ${v.model_ready}; built ${v.built_at?.slice(0, 19) || "—"}Z`}
                  {k === "geo" && `upstream analytics: ${v.upstream_analytics}; cluster eps ${v.cluster_eps_km} km`}
                  {k === "advisory" && `mode: ${v.mode}`}
                  {v.error && <span style={{ color: "#8d1d1d" }}> {v.error}</span>}</td></tr>))}</tbody></table>
        )}
        {h.loading && <div className="state">Checking services…</div>}
      </Card>

      <div className="grid g2">
        <Card title="Data source &amp; quality report" right={<Kind k="sample" />}>
          <Async s={q} what="quality report">{(d) => (
            <table><tbody>{Object.entries(d).map(([k, v]) => <tr key={k}><td>{k.replaceAll("_", " ")}</td><td className="mono">{Array.isArray(v) ? v.join(", ") : String(v)}</td></tr>)}</tbody></table>)}
          </Async>
        </Card>
        <Card title="Risk-classification configuration (editable JSON)">
          <Async s={cfg} what="config">{(d) => (
            <>
              <p className="note"><b>{d.label}</b></p>
              <table><tbody>
                {Object.entries(d.abs_threshold_c).map(([k, v]) => <tr key={k}><td>Absolute threshold — {k}</td><td className="mono">{v} °C</td></tr>)}
                <tr><td>Departure for heatwave-like (High)</td><td className="mono">≥ {d.departure_heatwave_c} °C</td></tr>
                <tr><td>Departure for Severe</td><td className="mono">≥ {d.departure_severe_c} °C</td></tr>
                <tr><td>Plains absolute High / Severe</td><td className="mono">≥ {d.plains_abs_heatwave_c} / {d.plains_abs_severe_c} °C</td></tr>
              </tbody></table>
              <p className="note" style={{ color: "#8d1d1d" }}>{d.verification_note}</p>
            </>)}
          </Async>
        </Card>
      </div>
    </div>
  );
}
