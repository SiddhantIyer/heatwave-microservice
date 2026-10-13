"""Generate a SYNTHETIC sample dataset (NOT IMD data) in the project's CSV schema.

Station names/coordinates are real Indian cities, but every temperature value is
simulated: a smooth seasonal climatology + regionally-correlated AR(1) noise +
random heat episodes in Apr-Jun. A few missing / sentinel (99.9) values are
injected on purpose to exercise the validation pipeline.

Usage:  python scripts/generate_sample_data.py
"""
import numpy as np, pandas as pd
from pathlib import Path

SEED = 42
START, END = "2021-01-01", "2025-12-31"
OUT = Path(__file__).resolve().parents[1] / "data" / "sample_tmax.csv"

R_WH, R_NW, R_CE, R_WC, R_EA, R_NE, R_SP = (
    "Western Himalaya & Hills", "Northwest Plains", "Central India", "West Coast & Gujarat",
    "East India", "Northeast India", "South Peninsula")

# id, name, lat, lon, region, terrain, (winter, premonsoon_peak, monsoon) typical Tmax, peak_doy
S = [
 ("SRN","Srinagar",34.08,74.80,R_WH,"hill",(6,28,31),170),
 ("SML","Shimla",31.10,77.17,R_WH,"hill",(11,26,22),150),
 ("DDN","Dehradun",30.32,78.03,R_WH,"plains",(22,38,33),145),
 ("DEL","Delhi",28.61,77.21,R_NW,"plains",(21,41,35),140),
 ("JAI","Jaipur",26.91,75.79,R_NW,"plains",(24,41,34),138),
 ("ASR","Amritsar",31.63,74.87,R_NW,"plains",(19,38,35),150),
 ("JDH","Jodhpur",26.30,73.02,R_NW,"plains",(25,42,35),138),
 ("BKN","Bikaner",28.02,73.31,R_NW,"plains",(23,43,36),142),
 ("LKO","Lucknow",26.85,80.95,R_NW,"plains",(23,41,34),140),
 ("NGP","Nagpur",21.15,79.09,R_CE,"plains",(28,43,31),135),
 ("BHO","Bhopal",23.26,77.41,R_CE,"plains",(26,40,30),135),
 ("RPR","Raipur",21.25,81.63,R_CE,"plains",(28,41,30),135),
 ("AMD","Ahmedabad",23.02,72.57,R_WC,"plains",(28,41,33),135),
 ("BOM","Mumbai",19.08,72.88,R_WC,"coastal",(31,34,30),125),
 ("STV","Surat",21.17,72.83,R_WC,"coastal",(31,36,31),130),
 ("GOI","Panaji",15.50,73.83,R_WC,"coastal",(33,34,29),115),
 ("PAT","Patna",25.59,85.14,R_EA,"plains",(24,39,34),140),
 ("IXR","Ranchi",23.34,85.31,R_EA,"plains",(25,37,30),138),
 ("BBI","Bhubaneswar",20.30,85.82,R_EA,"plains",(29,37,32),135),
 ("CCU","Kolkata",22.57,88.36,R_EA,"coastal",(27,36,32),135),
 ("GAU","Guwahati",26.14,91.74,R_NE,"plains",(24,31,32),200),
 ("IMF","Imphal",24.82,93.94,R_NE,"plains",(22,28,29),130),
 ("SHL","Shillong",25.57,91.88,R_NE,"hill",(17,22,23),170),
 ("HYD","Hyderabad",17.38,78.48,R_SP,"plains",(29,39,30),125),
 ("VGA","Vijayawada",16.51,80.65,R_SP,"plains",(31,41,32),135),
 ("MAA","Chennai",13.08,80.27,R_SP,"coastal",(29,38,34),150),
 ("BLR","Bengaluru",12.97,77.59,R_SP,"plains",(28,34,27),110),
 ("TRV","Thiruvananthapuram",8.52,76.94,R_SP,"coastal",(31,33,29),100),
]


def clim(doy, winter, peak, monsoon, peak_doy):
    """Periodic cosine-interpolated seasonal curve through 4 anchor points."""
    anchors = sorted([(15, winter), (peak_doy, peak), (215, monsoon), (300, (monsoon + winter) / 2 + 1.5)])
    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]
    xs = [xs[-1] - 365] + xs + [xs[0] + 365]
    ys = [ys[-1]] + ys + [ys[0]]
    out = np.empty(len(doy))
    for i, d in enumerate(doy):
        j = min(max(np.searchsorted(xs, d, side="right") - 1, 0), len(xs) - 2)
        t = (d - xs[j]) / (xs[j + 1] - xs[j])
        w = (1 - np.cos(np.pi * t)) / 2
        out[i] = ys[j] * (1 - w) + ys[j + 1] * w
    return out


def ar1(rng, n, phi, sigma):
    e = rng.normal(0, sigma * np.sqrt(1 - phi ** 2), n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def main():
    rng = np.random.default_rng(SEED)
    dates = pd.date_range(START, END, freq="D")
    n = len(dates)
    doy = np.minimum(dates.dayofyear.values, 365)
    regions = sorted({s[4] for s in S})
    reg_noise = {r: ar1(rng, n, 0.75, 1.5) for r in regions}
    reg_episode = {r: np.zeros(n) for r in regions}
    for r in regions:  # shared heat episodes per region/year (gives spatially coherent hotspots)
        for y in sorted(set(dates.year)):
            for _ in range(int(rng.integers(0, 3))):
                start_d = pd.Timestamp(f"{y}-04-05") + pd.Timedelta(days=int(rng.integers(0, 70)))
                L = int(rng.integers(3, 9))
                amp = rng.uniform(2.5, 6.0)
                shape = np.sin(np.linspace(0.2, np.pi - 0.2, L)) * amp
                idx = np.where(dates == start_d)[0]
                if len(idx):
                    seg = reg_episode[r][idx[0]: idx[0] + L]
                    seg += shape[: len(seg)]
    rows = []
    for sid, name, lat, lon, reg, terr, (w, p, m), pk in S:
        base = clim(doy, w, p, m, pk)
        trend = np.linspace(0, 0.5, n)  # tiny warming trend
        epi = reg_episode[reg] * (0.0 if terr == "hill" else rng.uniform(0.7, 1.1))
        t = np.round(base + trend + 0.6 * reg_noise[reg] + ar1(rng, n, 0.6, 1.1) + epi, 1)
        rows.append(pd.DataFrame({
            "timestamp": dates.strftime("%Y-%m-%d"), "station_id": sid, "station_name": name,
            "latitude": lat, "longitude": lon, "region": reg, "terrain": terr, "tmax_c": t,
            "data_source": "SAMPLE_SYNTHETIC"}))
    df = pd.concat(rows, ignore_index=True)
    miss = rng.random(len(df)) < 0.004   # injected quality problems
    sent = (rng.random(len(df)) < 0.0015) & ~miss
    df["tmax_c"] = df["tmax_c"].astype(object)
    df.loc[miss, "tmax_c"] = ""
    df.loc[sent, "tmax_c"] = 99.9        # IMD-style missing-value sentinel
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT} rows={len(df)} stations={len(S)} missing={miss.sum()} sentinel={sent.sum()}")


if __name__ == "__main__":
    main()
