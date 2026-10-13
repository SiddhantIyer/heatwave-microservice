import React from "react";

export const LEVELS = ["Low", "Moderate", "High", "Severe"];
export const RISK_COLORS = ["#3d8f7a", "#d9a21b", "#dd6b20", "#a4123f"];
export const REGION_ALL = "";

export const fmt = (x, d = 1) => (x === null || x === undefined || Number.isNaN(x) ? "—" : Number(x).toFixed(d));

export function tempColor(t) {
  if (t === null || t === undefined) return "#999";
  const stops = [[20, [64, 124, 168]], [30, [116, 169, 160]], [36, [226, 196, 96]], [41, [221, 107, 32]], [46, [164, 18, 63]]];
  if (t <= stops[0][0]) return `rgb(${stops[0][1]})`;
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1], [t1, c1] = stops[i], f = (t - t0) / (t1 - t0);
      return `rgb(${c0.map((v, k) => Math.round(v + (c1[k] - v) * f)).join(",")})`;
    }
  }
  return `rgb(${stops[stops.length - 1][1]})`;
}

export function RiskBadge({ level, label }) {
  if (level === null || level === undefined || level < 0) return <span className="badge" style={{ background: "#8a8f98" }}>No data</span>;
  return <span className="badge" style={{ background: RISK_COLORS[level] }}>{label || LEVELS[level]}</span>;
}

const KIND = {
  observed: ["Observed", "kind-observed"], forecast: ["Model forecast", "kind-forecast"],
  historical: ["Historical", "kind-historical"], simulated: ["Simulated", "kind-simulated"], sample: ["Sample data", "kind-simulated"],
};
export function Kind({ k }) {
  const [t, c] = KIND[k] || [k, ""];
  return <span className={`kind ${c}`}>{t}</span>;
}

export function Card({ title, right, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && <header className="card-h"><h3>{title}</h3><div>{right}</div></header>}
      {children}
    </section>
  );
}

export const Loading = ({ what = "data" }) => <div className="state"><span className="spinner" /> Loading {what}…</div>;
export const ErrorBox = ({ error }) => <div className="state error" role="alert">⚠ {error}</div>;

export function Async({ s, what, children }) {
  if (s.loading) return <Loading what={what} />;
  if (s.error) return <ErrorBox error={s.error} />;
  return s.data ? children(s.data) : null;
}

export function Stat({ label, value, sub, kind }) {
  return (
    <div className="stat">
      <div className="stat-l">{label} {kind && <Kind k={kind} />}</div>
      <div className="stat-v">{value}</div>
      {sub && <div className="stat-s">{sub}</div>}
    </div>
  );
}

export function Legend() {
  return (
    <div className="legend">
      {LEVELS.map((l, i) => <span key={l}><i style={{ background: RISK_COLORS[i] }} />{l}</span>)}
    </div>
  );
}
