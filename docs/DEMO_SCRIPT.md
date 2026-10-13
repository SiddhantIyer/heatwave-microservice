# Demonstration script (≈ 8 minutes)

**Setup before the session:** services + frontend running, browser on http://localhost:5173 with internet for map tiles, Swagger tab on http://localhost:8000/docs.

1. **Context (45 s).** "KJS-CES-01: heatwave monitoring and early warning with IMD data. Our prototype implements the five phases as microservices. Data here is a labelled synthetic sample because IMD GRD files need manual download; the schema and a converter are ready for the real data."
2. **Architecture (60 s).** Show `docs/architecture.svg`: gateway + four services; analytics pulls from data, geo pulls from analytics; advisory optionally uses an LLM with rule fallback.
3. **System tab (45 s).** Five green services, ports, data-quality report (sentinels, missing values) → Phase I.
4. **Overview (60 s).** As-of 4 May 2025 (hold-out year, out-of-sample). Point at Observed vs Model-forecast badges; South Peninsula shows Severe observed while the forecast shows less.
5. **Map (90 s).** Toggle Observed → Forecast → Historical; filter High+; show dashed cluster ring; click Hyderabad → popup → open advisory. Mention points are station locations, nothing interpolated.
6. **Temperature + Hotspots (60 s).** Forecast vs observed with 90 % band; historical ranking with factor bars (Bikaner, Nagpur) explaining why they rank.
7. **Advisory (60 s).** Switch citizen → farmer → authority; show DRAFT status, limitations, disclaimer; click "Mark reviewed" (human-in-the-loop).
8. **Validation (75 s).** Metrics vs baselines: better MAE, but low event detection — "we report this honestly". Click *Simulate AWS readings*: MAE vs AWS; emphasise **simulated, no hardware**.
9. **Resilience (30 s, optional).** Stop geo service → map errors, others still work.
10. **Limitations/future (30 s).** Real IMD data, humidity/heat index, better models, verified IMD thresholds, persistent DB, real AWS over MQTT, official-approval workflow.

**Likely viva questions:** Why Ridge on anomalies? (simple, transparent, leakage-safe, beats baselines on MAE.) Why is POD low? (shrinks to normal; extremes rare; need richer features/models.) Is this official? (No — prototype index.) How would real AWS data enter? (POST `/aws/readings`.)
