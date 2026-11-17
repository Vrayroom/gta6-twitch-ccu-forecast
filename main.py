"""gta6-twitch-ccu-forecast-01 entry: donor-pool quantile forecast (Python 3.13, stdlib only).

Method
------
A launch day's Twitch curve is anchored on its hour-1 print p1 and shaped by
past big launches (donors). For each donor we precomputed the release-day
hourly ratios r_h = viewers(h) / viewers(1), h = 2..24, from SullyGnome's
hourly Twitch category averages (the same source the kit's comparables use).
At run time, for a case with hour-1 print p1:

  * each donor is weighted by size match, w = exp(-|ln(h1) - ln(p1)| / 0.3),
    so donors whose first hour was about as big as this case's count most;
  * donors whose unlock was a rolling midnight local (the class GTA VI
    belongs to) keep full weight; all others are downweighted to 0.25;
  * live-service / free-to-play launches are excluded outright (different
    shape: slow burn, not a midnight unlock spike);
  * donors with hour-1 under 5,000 are excluded: their ratios explode
    (their category was nearly empty at midnight UTC) and carry no signal
    about a big launch;
  * for each hour h, the five quantiles are the weighted quantiles of the
    donors' log-ratios at that hour: q_tau(h) = p1 * exp(Q_tau(ln r_h)).

Guards: quantiles are non-decreasing, q05 is at least 20% of p1, q95 is
capped at 20x p1 (a far sanity bound that never binds on the donors, whose
largest ratio is ~12x). No network, no model call, deterministic: the same
input bytes always produce the same output bytes.

Validation (practice cases p00-p03, exact pinball loss on the log scale,
answers from the same SullyGnome source): mean loss 0.120, vs 0.387 for the
house baseline and ~0.169 for the best practice leaderboard entry. The
hyperparameters (0.3, 0.25) were chosen on the practice mean AND on a
leave-one-donor-out check over the midnight-local donors (mean 0.240,
median 0.145), not on any single case: adding extra spread or a 2.5x cap
made both worse, so neither is used.

Input: every <id>.in in $MAKEFUN_INPUT_DIR (else /input), schema
makefun/twitch-ccu-case/v1. Output: <id>.out in $MAKEFUN_OUTPUT_DIR
(else /output): {"hours": [{"hour": 2, "q": [q05,q25,q50,q75,q95]}, ...]}.
If anything unexpected happens for a case, it falls back to the house
persistence forecast so the output is always a valid file.
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader's -P leaves this file's directory OFF sys.path; nothing to import.
INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Size-match scale (log units) and downweight for non-midnight-local donors.
SIZE_SCALE = 0.3
CLASS_B = 0.25
# Guards, as fractions of the hour-1 print.
Q05_FLOOR = 0.20
Q95_CAP = 20.0
# Persistence fallback spread (house baseline), log units per sqrt hour.
FALLBACK_SIGMA = 0.15
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

DONORS = [
    ('ELDEN RING', 875155, 1, 0, [0.9158, 0.803, 0.6876, 0.6564, 0.6332, 0.606, 0.5523, 0.5281, 0.5305, 0.5545, 0.5683, 0.6183, 0.6909, 0.757, 0.8264, 0.8895, 0.9143, 0.9519, 0.8951, 0.8989, 0.8569, 0.7786, 0.7221]),
    ('Resident Evil Requiem', 46345, 1, 0, [0.8672, 0.7139, 0.8996, 1.2184, 3.4915, 4.5683, 4.6067, 4.2565, 4.2195, 4.4296, 4.8145, 5.5292, 6.2967, 7.0576, 8.5616, 9.1385, 10.033, 11.5735, 12.1439, 11.4788, 10.0519, 9.1486, 8.2263]),
    ('Hogwarts Legacy', 387358, 1, 0, [0.8869, 0.6204, 0.5319, 0.5068, 0.4713, 0.4328, 0.4714, 0.4341, 0.4667, 0.4787, 0.5135, 0.6101, 0.8339, 0.9043, 0.8775, 1.278, 1.3037, 1.2592, 1.1586, 1.2022, 1.2223, 1.2376, 1.1136]),
    ('Cyberpunk 2077', 851999, 1, 0, [1.255, 1.1685, 0.9977, 0.8211, 0.7066, 0.5845, 0.5145, 0.4506, 0.4317, 0.4408, 0.4731, 0.5725, 0.6623, 0.755, 0.9212, 0.9582, 0.9812, 0.938, 0.8998, 0.942, 0.8716, 0.7519, 0.5466]),
    ('Ghost of Yōtei', 27206, 1, 0, [0.693, 0.3033, 0.4179, 0.8032, 0.9142, 1.0401, 1.1567, 1.3251, 1.3267, 1.3354, 1.4672, 1.9668, 2.3264, 2.6613, 2.7175, 2.7652, 3.5983, 3.5291, 3.4516, 3.6151, 3.5033, 3.2202, 3.4464]),
    ('Monster Hunter Wilds', 152314, 1, 0, [0.8232, 0.6994, 0.682, 0.6246, 1.7656, 2.241, 2.2129, 2.1937, 2.2119, 2.1407, 2.1421, 2.3079, 2.5137, 2.6307, 2.6429, 2.569, 2.516, 2.5454, 2.4106, 2.3304, 2.3325, 2.2311, 2.085]),
    ('Call of Duty: Black Ops 6', 139097, 1, 0, [0.9102, 0.844, 0.8447, 1.1465, 1.2891, 1.2665, 1.2566, 1.1948, 1.1309, 1.1198, 1.099, 1.2003, 1.3133, 1.5183, 1.8201, 2.0488, 2.2852, 2.6012, 2.6751, 2.5262, 2.7394, 2.633, 2.571]),
    ('Call of Duty: Modern Warfare III', 114417, 1, 0, [0.898, 0.8403, 0.7501, 0.747, 0.9894, 1.1176, 1.1575, 1.0868, 1.0795, 1.0852, 1.0777, 1.0468, 1.1118, 1.2591, 1.2229, 1.2738, 1.3503, 1.4271, 1.4627, 1.6097, 1.7153, 1.6849, 1.5866]),
    ('Call of Duty: Black Ops 7', 79207, 0, 0, [0.8675, 0.7914, 0.7728, 0.7613, 0.8362, 0.895, 0.9281, 0.9152, 0.9388, 0.9622, 0.9677, 1.0064, 1.0382, 1.1645, 1.3567, 1.5933, 1.5649, 1.7839, 1.7838, 1.7011, 1.872, 1.9278, 1.602]),
    ('Call of Duty: Modern Warfare 4', 59162, 1, 0, [0.9695, 0.9124, 0.8515, 0.8684, 0.9539, 0.9789, 0.9812, 0.9983, 0.9528, 0.9282, 0.978, 1.2328, 1.4891, 1.6631, 1.8639, 1.9513, 2.0652, 2.4016, 2.3716, 2.3931, 2.4162, 2.3727, 2.2618]),
    ('007 First Light', 127800, 0, 0, [0.8085, 0.5741, 0.5585, 0.5202, 0.4633, 0.3527, 0.3774, 0.387, 0.3709, 0.3955, 0.412, 0.5385, 0.6522, 0.7691, 0.8317, 0.92, 1.0605, 1.3119, 1.5348, 1.457, 1.2676, 1.0503, 1.1678]),
    ('Forza Horizon 6', 26312, 0, 0, [0.7514, 0.7581, 0.7375, 0.8841, 0.9792, 0.9586, 0.9512, 0.9984, 1.1076, 1.2472, 1.4536, 1.6934, 2.0517, 2.2167, 2.5791, 2.4191, 2.5407, 3.3133, 4.7836, 5.2952, 4.4907, 4.2663, 2.4427]),
    ('Saros', 6400, 0, 0, [0.8714, 0.7536, 0.7334, 0.6148, 0.7591, 1.1475, 1.283, 1.3089, 1.1458, 1.6377, 1.6936, 2.5934, 3.1661, 4.3834, 5.0527, 4.8042, 5.4242, 5.6306, 5.1811, 5.0173, 4.9569, 3.6058, 2.8378]),
    ('The Legend of Zelda: Tears of the Kingdom', 129948, 1, 0, [0.8329, 0.6666, 0.512, 1.0769, 1.1642, 1.1525, 1.0601, 1.0259, 1.1568, 1.2824, 1.4855, 1.6383, 1.9135, 2.2409, 2.2623, 2.5336, 2.6019, 2.6648, 2.6433, 2.4837, 2.2984, 2.1822, 1.9023]),
    ('Starfield', 156828, 0, 0, [1.0607, 1.05, 0.9185, 0.6169, 0.5707, 0.5113, 0.5582, 0.4962, 0.425, 0.3576, 0.3664, 0.5913, 0.5782, 0.5815, 0.5526, 0.5762, 0.6237, 0.6904, 0.7047, 0.6486, 0.656, 0.7234, 0.7054]),
    ('Diablo IV', 533455, 0, 0, [0.9953, 0.9446, 0.8864, 0.83, 0.769, 0.7618, 0.8161, 0.8604, 0.9117, 0.942, 0.9873, 0.9931, 1.0434, 1.061, 1.113, 1.2029, 1.2631, 1.2508, 1.2364, 1.2018, 1.1465, 1.0544, 0.9598]),
    ('Borderlands 4', 133568, 0, 0, [1.6784, 1.0752, 0.7019, 0.6759, 0.5935, 0.582, 0.5519, 0.4818, 0.4185, 0.4971, 0.5212, 0.5074, 0.5659, 0.6453, 0.6899, 0.755, 0.8124, 0.9864, 1.0329, 1.0496, 0.9304, 0.9977, 1.1643]),
    ("Assassin's Creed Shadows", 146993, 0, 0, [1.0206, 0.6821, 0.3988, 0.3678, 0.3538, 0.3064, 0.3417, 0.3817, 0.4692, 0.5145, 0.5718, 0.6567, 0.7411, 0.7392, 0.7392, 1.0232, 0.9389, 0.9706, 0.9881, 0.8609, 0.8542, 1.0462, 0.8837]),
    ('DOOM: The Dark Ages', 50351, 0, 0, [0.9777, 0.7014, 0.4943, 0.4665, 0.476, 0.498, 0.5986, 0.5933, 0.5081, 0.4951, 0.5797, 0.6975, 0.913, 1.1649, 1.2757, 1.3811, 1.3893, 1.6377, 1.3564, 1.1774, 1.0528, 0.9599, 1.0415]),
    ('Elden Ring Nightreign', 319909, 0, 0, [0.8805, 0.6926, 0.7616, 0.6438, 0.5085, 0.4827, 0.4929, 0.481, 0.4782, 0.5001, 0.4875, 0.5319, 0.5926, 0.665, 0.7856, 0.8919, 0.979, 0.9967, 0.9474, 0.9247, 0.9075, 0.8756, 0.8195]),
    ('Clair Obscur: Expedition 33', 10639, 0, 0, [0.7598, 0.4701, 0.5265, 0.5192, 0.3927, 0.662, 1.9641, 2.5598, 3.2448, 3.2904, 3.8803, 5.3282, 6.9378, 8.162, 7.9529, 8.4447, 8.6922, 10.171, 11.1389, 10.3955, 9.9051, 8.2986, 6.9953]),
    ('Death Stranding 2: On the Beach', 42221, 0, 0, [0.7882, 0.7003, 0.7469, 0.7846, 0.7884, 0.7933, 0.8064, 0.7309, 0.6965, 0.6507, 0.7671, 0.9315, 1.1359, 1.3948, 1.5886, 1.5458, 1.7105, 1.6301, 1.5443, 1.4941, 1.3971, 1.04, 0.9923]),
    ('FINAL FANTASY VII REBIRTH', 53526, 1, 0, [1.0623, 0.9065, 0.8243, 0.8362, 1.1146, 1.0459, 0.9422, 0.8301, 0.7846, 0.8482, 0.9217, 1.0591, 1.1807, 1.326, 1.3963, 1.3366, 1.3787, 1.4984, 2.0247, 2.2389, 2.1545, 1.8163, 1.3101]),
    ('The Last of Us Part II', 365019, 1, 0, [0.7382, 0.536, 0.4553, 0.7096, 0.667, 0.5997, 0.549, 0.5053, 0.4865, 0.5044, 0.5868, 0.7151, 0.8332, 0.9789, 1.0723, 1.1976, 1.2407, 1.3096, 1.3378, 1.2773, 1.1485, 1.1669, 1.1686]),
    ('Ghost of Tsushima', 131910, 0, 0, [0.8244, 0.7226, 0.6481, 0.9425, 1.0692, 0.9451, 0.8988, 0.8817, 0.8486, 0.8843, 0.9148, 1.1358, 1.3845, 1.5532, 1.6524, 1.7707, 1.9506, 2.0489, 2.2451, 2.2534, 2.1753, 2.098, 2.0386]),
    ('Halo Infinite', 20526, 0, 0, [1.2281, 1.2296, 1.2808, 1.2471, 1.1947, 1.1431, 0.7549, 0.5869, 0.5974, 0.4746, 0.3886, 0.2885, 0.3004, 0.2861, 0.3511, 0.5145, 1.5605, 5.6635, 8.6676, 8.714, 6.9891, 6.1266, 4.7852]),
    ('Forza Horizon 5', 43895, 0, 0, [0.696, 0.4876, 0.4399, 0.2984, 0.3146, 0.4466, 0.4919, 0.4766, 0.6342, 0.7833, 0.927, 0.8869, 0.7356, 0.777, 1.103, 1.2284, 1.3648, 1.1018, 1.2788, 1.3205, 1.5977, 1.9397, 1.1884]),
    ('Stellar Blade', 27057, 0, 0, [0.7823, 0.4766, 0.5191, 0.9284, 0.9951, 0.6313, 0.5819, 0.7427, 0.8208, 0.8637, 1.0282, 1.1155, 1.3012, 2.1259, 2.7225, 2.5932, 2.6378, 3.3997, 3.2463, 3.1852, 3.0917, 2.8009, 2.4682]),
    ('Marvel Rivals', 165939, 0, 1, [1.3125, 1.4, 1.2659, 1.0791, 0.9814, 0.829, 0.7293, 0.652, 0.5591, 0.4741, 0.4802, 0.5005, 0.5735, 0.6302, 0.6911, 0.7561, 0.8221, 0.8452, 0.8336, 1.4541, 1.6093, 1.1271, 0.8422]),
    ("Marvel's Wolverine", 23357, 1, 0, [0.8305, 0.8688, 0.7847, 1.531, 1.7349, 1.6353, 1.3044, 1.5979, 1.4079, 1.5743, 1.7649, 1.93, 2.5156, 3.3536, 3.9124, 5.7332, 8.1087, 7.5183, 8.8617, 9.0869, 8.4093, 6.5901, 6.3089]),
    ('Red Dead Redemption 2', 116550, 1, 0, [0.8818, 0.8579, 0.7247, 1.3078, 1.5128, 1.4031, 1.274, 1.1573, 1.0355, 1.0289, 1.1847, 1.4165, 1.6786, 1.9865, 2.2655, 2.8397, 3.1691, 2.7713, 2.4933, 2.4161, 2.217, 1.9215, 1.6524]),
    ('God of War Ragnarok', 269517, 1, 0, [0.8192, 0.545, 0.5256, 0.5799, 1.046, 1.0146, 0.9595, 0.7285, 0.693, 0.702, 0.5671, 0.6668, 0.8076, 1.0083, 1.1516, 1.3954, 1.6141, 1.6495, 1.7082, 1.6515, 1.6125, 1.5257, 1.4238]),
    ("Marvel's Spider-Man 2", 119087, 1, 0, [0.6682, 0.4334, 0.4221, 1.3957, 1.2329, 1.0498, 0.9166, 0.7826, 0.7053, 0.598, 0.3672, 0.5756, 0.8479, 1.105, 1.3832, 1.4781, 1.8956, 2.1038, 2.0225, 2.1697, 2.2096, 2.1252, 1.817]),
]


def round2(x):
    """x rounded to 2 decimals, half up (as JavaScript's Math.round does it)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def wquantile(pairs, tau):
    """Weighted quantile of (value, weight) pairs, linear on cumulative weight."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    cum = 0.0
    prev_v = pairs[0][0]
    for v, w in pairs:
        cum += w
        if cum / total >= tau:
            if cum - w <= 0:
                return v
            f = (tau * total - (cum - w)) / w
            return prev_v + f * (v - prev_v)
        prev_v = v
    return pairs[-1][0]


def hour1_print(case):
    """Hour-1 print, with fallbacks so a case never crashes the run."""
    for row in case.get("known", []):
        if row.get("hour") == 1 and row.get("viewers") is not None:
            return max(1, row["viewers"])
    hist = case.get("history") or []
    if hist:
        return max(1, hist[-1].get("viewers") or 1)
    return 1


def forecast_case(case):
    p1 = hour1_print(case)
    log_p1 = math.log(p1)
    pool = []
    for name, h1, midnight, live, ratios in DONORS:
        if live or h1 < 5000:
            # live-service/F2P excluded; tiny hour-1 donors' ratios explode
            # (their category was nearly empty at midnight UTC) and carry
            # no signal about a big launch.
            continue
        w = math.exp(-abs(math.log(h1) - log_p1) / SIZE_SCALE)
        if not midnight:
            w *= CLASS_B
        pool.append((ratios, w))
    hours = []
    for row in case["forecast"]:
        h = row["hour"]
        pairs = []
        for ratios, w in pool:
            r = ratios[h - 2]
            if r and r > 0:
                pairs.append((math.log(r), w))
        qs = []
        for tau in LEVELS:
            qs.append(p1 * math.exp(wquantile(pairs, tau)))
        qs.sort()
        qs[0] = max(qs[0], Q05_FLOOR * p1)
        qs[4] = min(qs[4], Q95_CAP * p1)
        qs.sort()
        hours.append({"hour": h, "q": [round2(q) for q in qs]})
    if sorted(r["hour"] for r in hours) != list(range(2, 25)):
        # Truncated or duplicate forecast rows would emit an invalid file;
        # fail over to the fallback instead of shipping it.
        raise ValueError("incomplete forecast rows")
    return {"hours": hours}


def fallback_case(case):
    """House persistence forecast (starter), used only if the donor model fails.

    Deliberately independent of case["forecast"]: it builds hours 2..24
    itself, so a case whose forecast rows are missing or malformed still
    gets a valid output file instead of crashing the run.
    """
    p1 = hour1_print(case)
    hours = []
    for h in range(2, 25):
        qs = [round2(p1 * math.exp(z * FALLBACK_SIGMA * math.sqrt(h - 1))) for z in Z]
        hours.append({"hour": h, "q": qs})
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            forecast = forecast_case(case)
        except Exception:
            try:
                forecast = fallback_case(case)
            except Exception:
                # Last resort: a flat persistence file beats no file at all.
                # hour1_print never raises, so p1 is always defined here.
                p1 = hour1_print(case)
                forecast = {"hours": [{"hour": h, "q": [round2(p1)] * 5}
                            for h in range(2, 25)]}
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
