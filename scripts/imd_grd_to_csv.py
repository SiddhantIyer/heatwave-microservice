"""Convert IMD gridded daily max-temperature GRD files into this project's CSV schema.

IMPORTANT - verify before use. The defaults below describe the IMD 1-degree x 1-degree daily Tmax
product as I recall it (31 x 31 grid, 7.5N-37.5N, 67.5E-97.5E, float32, one record of nlat x nlon values per day,
missing value 99.9). I could not download or inspect the real files while building this prototype, so CHECK the
specification on https://imdpune.gov.in/lrfindex.php and override any argument that differs
(--nlat --nlon --lat0 --lon0 --res --missing --byteorder).

Each grid cell becomes one "station": station_id = G<lat>_<lon>, coordinates = cell centre. The grid structure is
preserved (no interpolation). 'region' is left blank so the Data Service assigns an approximate region, or fill it with
the region list given by your faculty.

Example:
  python scripts/imd_grd_to_csv.py --inputs Maxtemp_MaxT_2022.GRD Maxtemp_MaxT_2023.GRD --years 2022 2023 \\
         --out data/imd_tmax.csv
  DATA_CSV=data/imd_tmax.csv python scripts/run_all.py
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def convert(path, year, nlat, nlon, lat0, lon0, res, missing, byteorder):
    raw = np.fromfile(path, dtype=np.dtype("float32").newbyteorder(byteorder))
    cell = nlat * nlon
    if raw.size % cell != 0:
        raise SystemExit(f"{path}: {raw.size} values is not a multiple of {nlat}x{nlon}={cell}. Wrong grid size or byte order?")
    days = raw.size // cell
    expected = 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
    if days != expected:
        print(f"  warning: {path} has {days} daily records, expected {expected} for {year}")
    cube = raw.reshape(days, nlat, nlon)
    cube = np.where(np.isclose(cube, missing) | (cube > 90), np.nan, cube)
    dates = pd.date_range(f"{year}-01-01", periods=days, freq="D")
    rows = []
    for i in range(nlat):
        for j in range(nlon):
            series = cube[:, i, j]
            if np.isnan(series).all():
                continue  # ocean / outside-India cell
            lat, lon = lat0 + i * res, lon0 + j * res
            rows.append(pd.DataFrame({"timestamp": dates.strftime("%Y-%m-%d"), "station_id": f"G{lat:.1f}_{lon:.1f}",
                                      "station_name": f"Grid {lat:.1f}N {lon:.1f}E", "latitude": lat, "longitude": lon,
                                      "terrain": "plains", "tmax_c": np.round(series, 2), "data_source": "IMD_GRD_1deg"}))
    return pd.concat(rows, ignore_index=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--years", nargs="+", type=int, required=True, help="year of each input file, same order")
    ap.add_argument("--out", default="data/imd_tmax.csv")
    ap.add_argument("--nlat", type=int, default=31); ap.add_argument("--nlon", type=int, default=31)
    ap.add_argument("--lat0", type=float, default=7.5); ap.add_argument("--lon0", type=float, default=67.5)
    ap.add_argument("--res", type=float, default=1.0); ap.add_argument("--missing", type=float, default=99.9)
    ap.add_argument("--byteorder", choices=["<", ">"], default="<")
    a = ap.parse_args()
    if len(a.inputs) != len(a.years):
        raise SystemExit("--inputs and --years must have the same length")
    frames = []
    for f, y in zip(a.inputs, a.years):
        print(f"reading {f} ({y})")
        frames.append(convert(f, y, a.nlat, a.nlon, a.lat0, a.lon0, a.res, a.missing, a.byteorder))
    df = pd.concat(frames, ignore_index=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"wrote {a.out}: {len(df)} rows, {df.station_id.nunique()} grid cells")


if __name__ == "__main__":
    main()
