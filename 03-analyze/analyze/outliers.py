"""O-robust-z: robust z-score outliers (median / MAD). Spec: analyze/METHOD.md."""
import math
import statistics

Z_THRESHOLD = 3.5        # |z| at or above this is an outlier (Iglewicz-Hoaglin)
MIN_SAMPLE = 8           # fewer values in a group: report candidates with flagged=false
MAD_SCALE = 1.4826       # MAD -> sigma for normal data
MEANAD_SCALE = 1.253314  # mean absolute deviation -> sigma, used when MAD == 0
MIN_REL_SPREAD = 0.5     # O-spread-floor: scale >= this * |median| for metrics with "spread_floor" (flag beyond ~2.75x median)


def robust_z(values, rel_floor=0.0):
    """O-robust-z: returns (median, scale, [z]) ; scale 0 -> all z = 0 (no spread, no outlier).
    rel_floor (O-spread-floor): scale is at least rel_floor * |median|."""
    med = statistics.median(values)
    dev = [abs(v - med) for v in values]
    mad = statistics.median(dev)
    scale = MAD_SCALE * mad if mad > 0 else MEANAD_SCALE * (sum(dev) / len(dev))
    scale = max(scale, rel_floor * abs(med))
    return med, scale, [(v - med) / scale if scale > 0 else 0.0 for v in values]


def find(metric, group, items, log=False, floor=False):
    """items: [(session_id, value)] for one metric and group. Returns outlier dicts, |score| desc.
    log=True (O-log-scale): z on log10(value), values <= 0 left out, baseline back in value units.
    floor=True (O-spread-floor, linear only): scale >= MIN_REL_SPREAD * |median|."""
    if log:
        items = [(sid, v) for sid, v in items if v > 0]
    if not items:
        return []
    items = sorted(items, key=lambda x: x[0])
    med, scale, zs = robust_z([math.log10(v) if log else v for _, v in items],
                           MIN_REL_SPREAD if floor and not log else 0.0)
    med = 10 ** med if log else med
    n, out = len(items), []
    for (sid, v), z in zip(items, zs):
        if abs(z) >= Z_THRESHOLD:
            out.append({"metric": metric, "group": group, "session_id": sid, "value": v, "baseline": med,
                        "score": round(z, 4), "method": "robust_z", "n": n, "session_ids": [sid],
                        "flagged": n >= MIN_SAMPLE})
    return sorted(out, key=lambda o: (-abs(o["score"]), o["session_id"]))
