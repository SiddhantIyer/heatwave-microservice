# Testing checklist

Automated: `pytest -q tests` (12 unit tests: risk levels per terrain, validator cleaning) · `python tests/smoke_check.py` (30 end-to-end checks through the gateway). Both passed on the final build.

## Manual UI flows
- [ ] Start services + frontend; header shows as-of date; yellow banner says *Synthetic sample data* and *not an official IMD declaration*
- [ ] Overview: totals, latest recorded Tmax with date, observed vs forecast regional charts, clusters table
- [ ] Map: switch Observed / Forecast / Historical; severity filter; colour by risk and by temperature; click a marker → popup → "Open advisory"; legend visible; region filter in header narrows markers
- [ ] Temperature: change station/window; forecast chart shows band, forecast, observed; seasonal bar chart
- [ ] Hotspots: three sources, factor columns, historical contribution bars, clusters
- [ ] Advisory: 4 stakeholder tabs, DRAFT status, disclaimer, "Mark reviewed" changes status; LLM checkbox disabled without key
- [ ] Validation: metrics table (honest note on low POD); simulate AWS → MAE and rows appear; Clear works
- [ ] System: all five services green; data quality report; risk configuration with unverified-threshold warning
- [ ] Jump with "Peak-heat demo date" and "Latest record"; the latest-record date shows a Low-risk winter picture
- [ ] Stop the Geo service: Map shows an error box, System shows geo *down*, Temperature and Advisory still work

## Key API checks (curl)
`/api/health` · `/api/forecast/DEL?as_of=2025-05-04` (200, 5 leads) · `/api/forecast/NOPE` (404) · `?as_of=1999-01-01` (422) · `/api/geojson/bogus` (422) · `POST /api/advisory` with stakeholder `alien` (422) · `POST /api/aws/simulate?end_date=2025-05-04` then `/api/validation/aws`.
