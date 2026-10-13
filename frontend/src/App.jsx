import React, { useEffect, useState } from "react";
import { useApi } from "./api.js";
import { Async, Kind } from "./ui.jsx";
import Overview from "./components/Overview.jsx";
import MapView from "./components/MapView.jsx";
import Temperature from "./components/Temperature.jsx";
import Hotspots from "./components/Hotspots.jsx";
import Advisory from "./components/Advisory.jsx";
import Validation from "./components/Validation.jsx";
import System from "./components/System.jsx";

const TABS = ["Overview", "Map", "Temperature", "Hotspots", "Advisory", "Validation", "System"];

export default function App() {
  const meta = useApi("/api/meta");
  const [tab, setTab] = useState("Overview");
  const [asOf, setAsOf] = useState(null);
  const [region, setRegion] = useState("");
  const [station, setStation] = useState("DEL");

  useEffect(() => { if (meta.data && !asOf) setAsOf(meta.data.suggested_as_of); }, [meta.data, asOf]);

  const m = meta.data;
  const ctx = { meta: m, asOf, region, station, setStation, goto: setTab };
  const inTest = m && asOf && asOf > m.train_end;

  return (
    <>
      <header className="top">
        <div>
          <h1>Heatwave Intelligence &amp; Climate Risk Mapping</h1>
          <div className="sub">Use case KJS-CES-01 · Climate Intelligence for Heatwave Monitoring, Prediction and Early Warning</div>
        </div>
        {m && (
          <div className="controls">
            <label>As-of date
              <input type="date" value={asOf || ""} min={m.first_date} max={m.last_date} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
            </label>
            <button className="ghost" onClick={() => setAsOf(m.suggested_as_of)} title="Date in the hold-out year with the most High+ stations">Peak-heat demo date</button>
            <button className="ghost" onClick={() => setAsOf(m.last_date)}>Latest record</button>
            <label>Region
              <select value={region} onChange={(e) => setRegion(e.target.value)}>
                <option value="">All regions</option>
                {m.regions.map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
          </div>
        )}
      </header>
      <div className="banner">
        {m?.data_summary?.is_sample_data && <span><Kind k="sample" /> <b>Synthetic sample data</b> — not IMD observations.</span>}
        <span><b>Prototype risk index</b> — not an official IMD heatwave declaration or alert.</span>
        {m && asOf && (
          <span>Viewing <b>{asOf}</b>: observed values up to this date; forecasts cover the next 5 days
            {inTest ? " (hold-out period → out-of-sample hindcast; observed values shown for verification)." : " (inside training period → in-sample, optimistic)."}</span>
        )}
      </div>
      <nav className="tabs">
        {TABS.map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </nav>
      <main>
        <Async s={meta} what="dataset metadata">
          {() => asOf && (
            <>
              {tab === "Overview" && <Overview {...ctx} />}
              {tab === "Map" && <MapView {...ctx} />}
              {tab === "Temperature" && <Temperature {...ctx} />}
              {tab === "Hotspots" && <Hotspots {...ctx} />}
              {tab === "Advisory" && <Advisory {...ctx} />}
              {tab === "Validation" && <Validation {...ctx} />}
              {tab === "System" && <System {...ctx} />}
            </>
          )}
        </Async>
      </main>
    </>
  );
}
