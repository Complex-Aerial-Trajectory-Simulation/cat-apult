"""
rebuild_truncated.py
====================
ONE-TIME migration. Regenerate every truncated recording from its full counterpart so
the truncated files carry Liftoff's IN-GAME clock (`t_sim`, re-zeroed to start at 0)
instead of packet-arrival time.

Why: arrival time is when the UDP packet reached the capture script, not when the
sample was taken. It jitters from 0.1 ms to 277 ms around a 8.9 ms median, so using it
as a time axis fabricates enormous accelerations downstream (measured: a median
tangential acceleration of 59.8 m/s^2 - 6 g sustained - versus 1.78 m/s^2 on the
in-game clock). The full recordings already store `t_sim`, so no re-flying is needed.

Positions are copied across unchanged: the capture script already normalized them so
each recording starts at (0, 0, 0).

Run this ONCE, after emptying "1 truncated recordings". New recordings made with the
updated liftoff_capture.py already use the in-game clock, so you never need it again.

    python rebuild_truncated.py
    python rebuild_truncated.py --dry-run     # list what would be written
"""

import argparse
import csv
from pathlib import Path

FULL_DIR = Path("0 full recordings")
TRUNC_DIR = Path("1 truncated recordings")
FULL_PREFIX, TRUNC_PREFIX = "liftoff_full_", "liftoff_trunc_"
TRUNC_COLUMNS = ["t_sim", "x", "y", "z"]


def rebuild_one(full_path, out_path):
    """Read a full recording, write the truncated twin with re-zeroed t_sim."""
    with open(full_path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0
    if "t_sim" not in rows[0]:
        raise SystemExit(f"{full_path.name} has no t_sim column - it predates the "
                         "full-recording format and can't be migrated.")

    t0 = float(rows[0]["t_sim"])
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(TRUNC_COLUMNS)
        for r in rows:
            w.writerow([f"{float(r['t_sim']) - t0:.5f}",
                        r["x"], r["y"], r["z"]])
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full-dir", default=str(FULL_DIR))
    ap.add_argument("--trunc-dir", default=str(TRUNC_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    full_dir, trunc_dir = Path(args.full_dir), Path(args.trunc_dir)
    files = sorted(full_dir.glob(f"{FULL_PREFIX}*.csv"))
    if not files:
        raise SystemExit(f"No full recordings found in '{full_dir}'.")

    existing = list(trunc_dir.glob(f"{TRUNC_PREFIX}*.csv")) if trunc_dir.exists() else []
    if existing and not args.dry_run:
        print(f"! '{trunc_dir}' already holds {len(existing)} file(s); they will be "
              f"overwritten where names match.\n")

    if not args.dry_run:
        trunc_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for p in files:
        stem = p.stem[len(FULL_PREFIX):]
        out = trunc_dir / f"{TRUNC_PREFIX}{stem}.csv"
        if args.dry_run:
            print(f"  would write {out}")
            continue
        n = rebuild_one(p, out)
        total += n
        print(f"  {p.name} -> {out.name}  ({n} samples)")

    if args.dry_run:
        print(f"\n{len(files)} file(s) would be rebuilt.")
    else:
        print(f"\nRebuilt {len(files)} truncated recording(s), {total} samples total, "
              "now on the in-game clock.")
        print("Next: delete '3 checked recordings', then re-run check_recordings.py "
              "and build_dataset.py.")


if __name__ == "__main__":
    main()
