"""
check_recordings.py
==================
Scan every recording in "0 full recordings" and "1 truncated recordings", detect
discontinuities caused by drone resets / crash-respawns (position teleports and
telemetry pauses), and split each flight into clean continuous segments.

WHY NOT DETECT ON SPEED
-----------------------
t_wall is packet-arrival time and UDP packets arrive in bursts, so consecutive
timestamps can be ~0 apart even during normal motion. speed = distance / dt would
then blow up and cause false alarms. Instead we detect on quantities that are robust
to that jitter:
  * POSITION JUMP  - displacement between consecutive samples > --jump metres
                     (a drone can't physically move that far in one frame)
  * TIME GAP       - dt between consecutive samples > --gap seconds
                     (telemetry actually stopped: menu / reset / respawn)

OUTPUT
------
Clean segments are written (each re-zeroed to start at position (0,0,0) and time 0,
so every segment is a standalone flight) to:
    3 checked recordings/
        3 1 checked full/liftoff_full_<ts>_segNN.csv
        3 2 checked trunc/liftoff_trunc_<ts>_segNN.csv
Full + truncated versions of the same flight are split at identical boundaries.

RUN
---
    python check_recordings.py
    python check_recordings.py --gap 0.25 --jump 12 --min-samples 50
Add --report-only to inspect without writing anything.
"""

import argparse
import csv
import math
from pathlib import Path

FULL_DIR = Path("0 full recordings")
TRUNC_DIR = Path("1 truncated recordings")
OUT_DIR = Path("3 checked recordings")
OUT_FULL = OUT_DIR / "3 1 checked full"
OUT_TRUNC = OUT_DIR / "3 2 checked trunc"

FULL_PREFIX, TRUNC_PREFIX = "liftoff_full_", "liftoff_trunc_"


def load_csv(path):
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def positions(rows):
    t = [float(r["t_wall"]) for r in rows]
    x = [float(r["x"]) for r in rows]
    y = [float(r["y"]) for r in rows]
    z = [float(r["z"]) for r in rows]
    return t, x, y, z


def detect_breaks(t, x, y, z, gap_s, jump_m):
    """Return list of dicts describing each break (edge between i-1 and i)."""
    breaks = []
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        disp = math.dist((x[i], y[i], z[i]), (x[i - 1], y[i - 1], z[i - 1]))
        is_gap = dt > gap_s
        is_jump = disp > jump_m
        if is_gap or is_jump:
            breaks.append({
                "index": i, "t": t[i - 1], "dt": dt, "disp": disp,
                "gap": is_gap, "jump": is_jump,
                "implied_speed": disp / dt if dt > 1e-9 else float("inf"),
            })
    return breaks


def segment_bounds(n, breaks, min_samples):
    """Turn break indices into [start, end) slices, dropping short segments."""
    cuts = [0] + [b["index"] for b in breaks] + [n]
    segs, dropped = [], 0
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a >= min_samples:
            segs.append((a, b))
        else:
            dropped += (b - a)
    return segs, dropped


def write_segment(fieldnames, rows, sl, out_path, renorm):
    seg = [dict(r) for r in rows[sl[0]:sl[1]]]
    if renorm and seg:
        x0, y0, z0 = float(seg[0]["x"]), float(seg[0]["y"]), float(seg[0]["z"])
        t0 = float(seg[0]["t_wall"])
        for r in seg:
            r["x"] = f"{float(r['x']) - x0:.5f}"
            r["y"] = f"{float(r['y']) - y0:.5f}"
            r["z"] = f"{float(r['z']) - z0:.5f}"
            r["t_wall"] = f"{float(r['t_wall']) - t0:.4f}"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(seg)


def gather_flights():
    flights = {}
    if FULL_DIR.exists():
        for p in sorted(FULL_DIR.glob(f"{FULL_PREFIX}*.csv")):
            flights.setdefault(p.stem[len(FULL_PREFIX):], {})["full"] = p
    if TRUNC_DIR.exists():
        for p in sorted(TRUNC_DIR.glob(f"{TRUNC_PREFIX}*.csv")):
            flights.setdefault(p.stem[len(TRUNC_PREFIX):], {})["trunc"] = p
    return flights


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, default=0.25, help="time-gap threshold (s)")
    ap.add_argument("--jump", type=float, default=12.0, help="position-jump threshold (m)")
    ap.add_argument("--min-samples", type=int, default=50, help="drop segments shorter than this")
    ap.add_argument("--no-renorm", action="store_true", help="do NOT re-zero each segment")
    ap.add_argument("--report-only", action="store_true", help="detect only, write nothing")
    args = ap.parse_args()

    flights = gather_flights()
    if not flights:
        print("No recordings found in '0 full recordings' or '1 truncated recordings'.")
        return

    if not args.report_only:
        OUT_FULL.mkdir(parents=True, exist_ok=True)
        OUT_TRUNC.mkdir(parents=True, exist_ok=True)

    print(f"Scanning {len(flights)} flight(s)  "
          f"(gap>{args.gap}s or jump>{args.jump}m => break)\n")
    tot_segments = tot_breaks = tot_dropped = 0

    for ts in sorted(flights):
        srcs = flights[ts]
        have = "+".join(k for k in ("full", "trunc") if k in srcs)
        detect_src = srcs.get("trunc", srcs.get("full"))
        fields, rows = load_csv(detect_src)
        t, x, y, z = positions(rows)
        if len(rows) < 2:
            print(f"── {ts} ({have}): only {len(rows)} samples, skipped\n")
            continue

        breaks = detect_breaks(t, x, y, z, args.gap, args.jump)
        segs, dropped = segment_bounds(len(rows), breaks, args.min_samples)
        tot_breaks += len(breaks)
        tot_dropped += dropped
        tot_segments += len(segs)

        dur = t[-1] - t[0]
        print(f"── {ts}  ({have})")
        print(f"   {len(rows)} samples, {dur:.1f}s")
        if breaks:
            for b in breaks:
                kind = "gap+jump" if b["gap"] and b["jump"] else ("gap" if b["gap"] else "jump")
                print(f"   \u26a0 break @ t={b['t']:.2f}s : jump {b['disp']:.1f} m, "
                      f"dt {b['dt']*1000:.0f} ms (~{b['implied_speed']:.0f} m/s) [{kind}]")
        else:
            print("   no breaks - clean continuous flight")

        seg_desc = ", ".join(f"seg{k+1:02d}({b-a} pts)" for k, (a, b) in enumerate(segs))
        print(f"   \u2192 {len(segs)} segment(s): {seg_desc}"
              + (f"   [{dropped} pts dropped as too-short]" if dropped else ""))

        if not args.report_only:
            for k, sl in enumerate(segs, 1):
                if "full" in srcs:
                    ff, fr = load_csv(srcs["full"])
                    write_segment(ff, fr, sl,
                                  OUT_FULL / f"{FULL_PREFIX}{ts}_seg{k:02d}.csv",
                                  not args.no_renorm)
                if "trunc" in srcs:
                    tf, tr = load_csv(srcs["trunc"])
                    write_segment(tf, tr, sl,
                                  OUT_TRUNC / f"{TRUNC_PREFIX}{ts}_seg{k:02d}.csv",
                                  not args.no_renorm)
        print()

    print(f"Summary: {len(flights)} flight(s) -> {tot_segments} clean segment(s), "
          f"{tot_breaks} break(s) found, {tot_dropped} sample(s) dropped.")
    if not args.report_only:
        print(f"Written to '{OUT_DIR}/'.")


if __name__ == "__main__":
    main()
