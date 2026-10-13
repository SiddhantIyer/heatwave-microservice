import React, { useMemo, useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from "react-leaflet";
import { useApi, qs } from "../api.js";
import { Async, Card, Kind, Legend, LEVELS, RISK_COLORS, RiskBadge, fmt, tempColor } from "../ui.jsx";

const SOURCES = [["observed", "Observed (as-of date)"], ["predicted", "Forecast (next 5 days)"], ["historical", "Historical hotspots"]];

export default function MapView({ asOf, region, setStation, goto }) {
  const [source, setSource] = useState("observed");
  const [minLevel, setMinLevel] = useState(0);
  const [colorBy, setColorBy] = useState("risk");
  const [clusters, setClusters] = useState(true);
  const g = useApi(`/api/geojson/${source}${qs({ as_of: asOf, region, min_level: source === "historical" ? 0 : minLevel })}`);
  const c = useApi(clusters ? `/api/clusters/${source}${qs({ as_of: asOf })}` : null);
  const feats = useMemo(() => (g.data?.features || []).filter((f) => source !== "historical" || f.properties.level >= minLevel), [g.data, source, minLevel]);

  return (
    <Card
      title="Interactive heatwave map"
      right={<Kind k={source === "observed" ? "observed" : source === "predicted" ? "forecast" : "historical"} />}
    >
      <div className="pill-row" style={{ marginBottom: 12, alignItems: "center" }}>
        <div className="seg">{SOURCES.map(([k, l]) => <button key={k} className={source === k ? "on" : ""} onClick={() => setSource(k)}>{l}</button>)}</div>
        <label>Min severity&nbsp;
          <select value={minLevel} onChange={(e) => setMinLevel(+e.target.value)}>
            {LEVELS.map((l, i) => <option key={l} value={i}>{l}+</option>)}
          </select>
        </label>
        <div className="seg">{[["risk", "Colour: risk"], ["temp", "Colour: temperature"]].map(([k, l]) => <button key={k} className={colorBy === k ? "on" : ""} onClick={() => setColorBy(k)}>{l}</button>)}</div>
        <label><input type="checkbox" checked={clusters} onChange={(e) => setClusters(e.target.checked)} /> Show hotspot clusters</label>
      </div>
      {g.error && <div className="state error">⚠ {g.error}</div>}
      <div className="map-wrap">
        <MapContainer center={[22.5, 80]} zoom={5} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
          <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {clusters && c.data?.clusters?.map((cl) => (
            <Circle key={cl.cluster_rank} center={[cl.centroid.latitude, cl.centroid.longitude]} radius={Math.max(cl.radius_km, 120) * 1000 + 60000}
              pathOptions={{ color: "#a4123f", weight: 1.5, dashArray: "6 5", fillOpacity: 0.05 }}>
              <Tooltip sticky>Cluster #{cl.cluster_rank}: {cl.stations.join(", ")}</Tooltip>
            </Circle>
          ))}
          {feats.map((f) => {
            const p = f.properties, [lon, lat] = f.geometry.coordinates;
            const col = colorBy === "risk" ? RISK_COLORS[p.level] : tempColor(p.temperature_c);
            return (
              <CircleMarker key={p.station_id} center={[lat, lon]} radius={7 + p.level * 3}
                pathOptions={{ color: "#1d2a2e", weight: 1, fillColor: col, fillOpacity: 0.88 }}>
                <Tooltip>{p.station_name}: {fmt(p.temperature_c)} °C · {p.risk_label}</Tooltip>
                <Popup>
                  <div style={{ minWidth: 220 }}>
                    <b>{p.station_name}</b> <RiskBadge level={p.level} /><br />
                    <span className="note">{p.region} · {p.terrain}</span>
                    <table style={{ marginTop: 6 }}><tbody>
                      {Object.entries(p.factors).map(([k, v]) => <tr key={k}><td>{k}</td><td><b>{fmt(v, v % 1 ? 1 : 0)}</b></td></tr>)}
                    </tbody></table>
                    <div className="note" style={{ marginTop: 6 }}>{p.basis}</div>
                    <button style={{ marginTop: 8 }} onClick={() => { setStation(p.station_id); goto("Advisory"); }}>Open advisory →</button>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
      <div style={{ display: "flex", gap: 24, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
        {colorBy === "risk" ? <Legend /> : <div><div className="tempbar" /><div className="note" style={{ display: "flex", justifyContent: "space-between", width: 180 }}><span>20°C</span><span>33</span><span>46°C</span></div></div>}
        <span className="note">Marker size grows with severity. Dashed rings = clusters of nearby High+ stations.</span>
      </div>
      <p className="note">
        {g.data?.metadata?.count ?? 0} stations shown. {g.data?.metadata?.spatial_note} {g.data?.metadata?.validation_status && `Status: ${g.data.metadata.validation_status}.`}
        &nbsp;Base map tiles need internet access.
      </p>
    </Card>
  );
}
