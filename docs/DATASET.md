# Dataset documentation

## Provenance
| Item | Value |
|---|---|
| Shipped file | `data/sample_tmax.csv` (51,128 rows, 28 stations, 2021-01-01 … 2025-12-31) |
| Origin | **Synthetic**, produced by `scripts/generate_sample_data.py` (seed 42). `data_source = SAMPLE_SYNTHETIC` |
| What is real | City names and coordinates only |
| What is simulated | All Tmax values: smooth seasonal curve + regionally correlated AR(1) noise + random Apr–Jun heat episodes + small warming trend; ~0.4 % blank values and ~0.15 % `99.9` sentinels injected to test validation |
| Preferred real source | IMD Pune gridded data, https://imdpune.gov.in/lrfindex.php (manual download) |

It is **not** IMD data and must never be quoted as observations.

## Schema
| Column | Required | Description |
|---|---|---|
| `timestamp` | yes | Date `YYYY-MM-DD` (daily) |
| `station_id` | yes | Station or grid-cell id |
| `latitude`, `longitude` | yes | Decimal degrees (accepted: 6–38 N, 67–98.5 E) |
| `tmax_c` | yes | Daily maximum temperature °C (accepted −10…55) |
| `station_name` | no | Defaults to id |
| `region` | no | One of seven regions; else assigned by approximate lat/lon boxes |
| `terrain` | no | `plains` \| `coastal` \| `hill` (selects threshold); default `plains` |
| `data_source` | no | Provenance label shown in the UI |

## Validation rules (Data Service, reported at `/quality`)
Rows with unparseable timestamps or out-of-range coordinates are dropped; `99.9`, `-99.9`, `999`, `-999`, `99` are treated as missing-value codes; values outside −10…55 °C become missing; duplicate (station, date) rows are dropped; remaining gaps ≤ 3 days are linearly interpolated by the Analytics Service, longer gaps stay missing. On the sample: 73 sentinels + 193 blanks = 266 missing (0.52 %).

## Using real IMD data
Download GRD files manually, check the grid specification published with them, then run `scripts/imd_grd_to_csv.py` (defaults assume a 31×31, 1°, 7.5–37.5 N / 67.5–97.5 E float32 daily layout with 99.9 missing — recalled, **unverified**; the script was tested only on a fabricated file for format plumbing). Grid structure is preserved: each cell is one point at its centre. Review region assignment and thresholds afterwards; every grid cell defaults to `plains`.

## Regions and seasons
Seven regions are an assumption (see README). Seasons: Winter (Jan–Feb), Pre-monsoon (Mar–May), Monsoon (Jun–Sep), Post-monsoon (Oct–Dec).
