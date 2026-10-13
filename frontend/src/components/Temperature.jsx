import React, { useState } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi, qs } from "../api.js";
import { Async, Card, Kind, RiskBadge, fmt } from "../ui.jsx";

const addDays = (d, n) => { const t = new Date(d + "T00:00:00Z"); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); };
const SEASON_COLORS = { Winter: "#6b9ac4", "Pre-monsoon": "#dd6b20", Monsoon: "#3d8f7a", "Post-monsoon": "#b59a3a" };

export default function Temperature({ meta, asOf, region, station, setStation }) {
  const [win, setWin] = useState(120);
  const stations = meta.stations.filter((s) => !region || s.region === region);
  const sel = stations.find((s) => s.station_id === station) ? station : stations[0]?.station_id;
  const series = useApi(`/api/series/${sel}${qs({ start: addDays(asOf, -win), end: addDays(asOf, 5) })}`);
  const fc = useApi(`/api/forecast/${sel}${qs({ as_of: asOf })}`);
  const tr = useApi(`/api/trends${qs({ station_id: sel })}`);
  const se = useApi("/api/seasonal");

  return (
    <div className="grid">
      <Card>
        <div className="pill-row" style={{ alignItems: "center" }}>
          <label>Station&nbsp;
            <select value={sel} onChange={(e) => setStation(e.target.value)}>
              {stations.map((s) => <option key={s.station_id} value={s.station_id}>{s.station_name} ({s.region})</option>)}
            </select>
          </label>
          <label>Window&nbsp;
            <select value={win} onChange={(e) => setWin(+e.target.value)}>
              {[60, 120, 240, 365].map((w) => <option key={w} value={w}>{w} days before as-of</option>)}
            </select>
          </label>
        </div>
      </Card>

      <div className="grid g2">
        <Card title="Daily maximum temperature vs. station normal" right={<><Kind k="observed" /></>}>
          <Async s={series} what="series">{(d) => (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={d.series}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={(x) => x.slice(5)} minTickGap={30} />
                <YAxis domain={["auto", "auto"]} unit="°" />
                <Tooltip />
                <Legend />
                <Line dataKey="tmax_c" name="Observed Tmax (°C)" stroke="#a4123f" dot={false} strokeWidth={2} />
                <Line dataKey="normal_c" name="Normal (train-period climatology)" stroke="#1f5f6b" dot={false} strokeDasharray="5 4" />
                <ReferenceLine x={asOf} stroke="#1d2a2e" label={{ value: "as-of", fontSize: 11 }} />
              </LineChart>
            </ResponsiveContainer>)}
          </Async>
          <p className="note">Observations after the as-of line are shown only to verify the forecast (hindcast mode).</p>
        </Card>

        <Card title={`5-day forecast vs. observed (as of ${asOf})`} right={<Kind k="forecast" />}>
          <Async s={fc} what="forecast">{(d) => {
            const rows = d.forecast.map((l) => ({ ...l, band: [l.lower_90_c, l.upper_90_c] }));
            return (
              <>
                <ResponsiveContainer width="100%" height={230}>
                  <ComposedChart data={rows}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={(x) => x.slice(5)} />
                    <YAxis domain={["auto", "auto"]} unit="°" />
                    <Tooltip />
                    <Legend />
                    <Area dataKey="band" name="90% interval" fill="#d9a21b" stroke="none" fillOpacity={0.25} />
                    <Line dataKey="forecast_tmax_c" name="Forecast (°C)" stroke="#dd6b20" strokeWidth={2} />
                    <Line dataKey="observed_tmax_c" name="Observed (°C)" stroke="#1f5f6b" strokeWidth={2} strokeDasharray="4 3" />
                    <Line dataKey="normal_c" name="Normal" stroke="#999" dot={false} strokeDasharray="2 4" />
                  </ComposedChart>
                </ResponsiveContainer>
                <table><thead><tr><th>Lead</th><th>Date</th><th>Forecast</th><th>Observed</th><th>Error</th><th>Forecast risk</th></tr></thead>
                  <tbody>{d.forecast.map((l) => (
                    <tr key={l.lead_days}><td>+{l.lead_days}d</td><td>{l.date}</td><td>{fmt(l.forecast_tmax_c)}</td><td>{fmt(l.observed_tmax_c)}</td><td>{fmt(l.error_c, 2)}</td><td><RiskBadge level={l.risk_level} /></td></tr>))}</tbody></table>
                <p className="note">{d.validation_status}. {d.uncertainty_note}</p>
              </>);
          }}</Async>
        </Card>
      </div>

      <div className="grid g2">
        <Card title="Monthly mean &amp; maximum Tmax" right={<Kind k="observed" />}>
          <Async s={tr} what="trend">{(d) => (
            <>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={d.monthly}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" minTickGap={28} />
                  <YAxis domain={["auto", "auto"]} unit="°" />
                  <Tooltip /><Legend />
                  <Line dataKey="mean_tmax_c" name="Monthly mean" stroke="#1f5f6b" dot={false} strokeWidth={2} />
                  <Line dataKey="max_tmax_c" name="Monthly max" stroke="#a4123f" dot={false} />
                </LineChart>
              </ResponsiveContainer>
              <p className="note">Pre-monsoon (Mar–May) trend: {fmt(d.premonsoon_trend_c_per_decade, 2)} °C/decade. {d.trend_note}</p>
            </>)}
          </Async>
        </Card>

        <Card title="Regional &amp; seasonal comparison — mean Tmax (°C)" right={<Kind k="observed" />}>
          <Async s={se} what="seasonal stats">{(d) => {
            const regions = [...new Set(d.rows.map((r) => r.region))];
            const data = regions.map((rg) => ({ region: rg.replace(" & ", "/").replace(" India", ""), ...Object.fromEntries(d.rows.filter((r) => r.region === rg).map((r) => [r.season, r.mean_tmax_c])) }));
            return (
              <>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="region" interval={0} angle={-25} textAnchor="end" height={70} tick={{ fontSize: 11 }} />
                    <YAxis unit="°" /><Tooltip /><Legend />
                    {Object.keys(SEASON_COLORS).map((s) => <Bar key={s} dataKey={s} fill={SEASON_COLORS[s]} />)}
                  </BarChart>
                </ResponsiveContainer>
                <p className="note">{d.note}</p>
              </>);
          }}</Async>
        </Card>
      </div>
    </div>
  );
}
