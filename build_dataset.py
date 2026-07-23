"""
build_dataset.py
===============
Turn the clean, checked Liftoff segments into a windowed train/val/test dataset. It
produces the .npz files that the baseline, model, and evaluation all consume

Per segment:
    load truncated CSV (t_sim, x, y, z)
        -> resample onto a uniform dt grid (linear)
        -> derive velocity (central differences) => clean ground-truth state (pos + vel)
        -> slide fixed-size windows of W input steps + H future steps
        -> label each window's dominant motion regime (for the evaluation breakdown)

SPLITTING happens at the SEGMENT level: each whole segment is assigned to train, val,
or test, and only then is it cut into windows. No continuous flight is shared across
splits, so overlapping/adjacent windows can't leak future info into the test set

Everything stored is CLEAN. Measurement noise is added at runtime by
dataset_utils.add_noise - that keeps the "accuracy vs noise" sweep trivial and doubles
as training augmentation

Usage:
    python build_dataset.py
    python build_dataset.py --dt 0.02 --window 50 --horizon 40 --stride 20
    # hand-pick held-out flights so val/test contain a mix of regimes:
    python build_dataset.py --val-segments liftoff_trunc_..._seg_02.csv \\
                            --test-segments liftoff_trunc_..._seg_01.csv liftoff_trunc..._seg03.csv
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from dataset_utils import (
    resample_uniform, derive_velocity, label_regime, REGIME_NAMES
)

# Where the cleaned segments live (output of check_recordings.py)
TRUNC_DIR = Path("2 checked recordings") / "2 2 checked trunc"

def load_segment(path):
    """
    Read one truncated segment CSV -> (t (M,), pos (M, 3))

    :param path: str or Path, CSV to read
    :return: (t (M,), pos (M, 3))
    """
    t, x, y, z = [], [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t.append(float(row["t_sim"]))
            x.append(float(row["x"]))
            y.append(float(row["y"]))
            z.append(float(row["z"]))
    return np.asarray(t), np.column_stack([x, y, z])


def make_windows(pos_u, vel_u, dt, W, H, stride, seg_index, label_kwargs):
    """
    Slice one resampled segment into overlapping windows
    For each start index s, one window is:
    input_pos   = clean positions [s : s+W]             (model input, before noise)
    future_pos  = clean positions [s + W : s + W + H]   (prediction targets)
    state_gt    = [pos | vel]     [s : s + W] (W, 6)    (ground-truth state)
    regime      = label over tyhe whole (W+H) span      (dominant motion regime)

    :param pos_u: (L, 3) ndarray, uniform resampled positions (x, y, z).
    :param vel_u: (L, 3) ndarray, derived ground-truth velocities (vx, vy, vz).
    :param dt: float, uniform timestep interval (in seconds).
    :param W: int, number of historical/input timesteps (history window length).
    :param H: int, number of future timesteps to predict (forecast horizon length).
    :param stride: int, step size between consecutive window start indices.
    :param seg_index: int, numerical identifier for the source segment (for traceability).
    :param label_kwargs: dict, keyword arguments passed directly to `label_regime`
                         (e.g., threshold values, smoothing size).
    :return: tuple of lists `(ip, fp, sg, rg, sid)` containing input positions, future targets,
             full ground-truth states, regime codes, and segment IDs respectively.
    """
    L = len(pos_u)
    ip, fp, sg, rg, sid = [], [], [], [], []
    # last valid start leaves room for W input + H future steps
    last_start = L - (W + H)
    for s in range(0, last_start + 1, stride):
        ip.append(pos_u[s:s + W])
        fp.append(pos_u[s + W:s + W + H])
        sg.append(np.hstack([pos_u[s:s + W], vel_u[s:s + W]]))  # (W, 6)
        rg.append(label_regime(vel_u[s:s + W + H], dt, **label_kwargs))
        sid.append(seg_index)
    return ip, fp, sg, rg, sid


def assign_splits(names, val_frac, test_frac, seed, val_names, test_names):
    """
    Decide which split each segment goes to.
      * If explicit --val-segments / --test-segments are given, honor them and put
        everything else in train (recommended: hand-pick so val/test span regimes).
      * Otherwise do a seeded random split by fraction, guaranteeing >=1 segment each
        in val and test when possible.
    Returns {segment_name: "train"|"val"|"test"}.

    :param names: list of str, filenames or unique identifiers for all available segments.
    :param val_frac: float, fraction of segments to allocate to the validation set (e.g., 0.15).
    :param test_frac: float, fraction of segments to allocate to the test set (e.g., 0.15).
    :param seed: int, random seed for reproducible random partitioning.
    :param val_names: list or set of str, explicit list of segment names designated for validation.
    :param test_names: list or set of str, explicit list of segment names designated for testing.
    :return: dict, mapping of {segment_name: "train" | "val" | "test"}.
    """
    if val_names or test_names:
        val_set, test_set = set(val_names), set(test_names)
        return {n: ("val" if n in val_set else "test" if n in test_set else "train")
                for n in names}

    rng = np.random.default_rng(seed)
    order = rng.permutation(len(names))
    n = len(names)
    n_test = max(1, round(test_frac * n)) if n >= 3 else 0
    n_val = max(1, round(val_frac * n)) if n >= 3 else 0
    assign = {}
    for rank, i in enumerate(order):
        if rank < n_test:
            assign[names[i]] = "test"
        elif rank < n_test + n_val:
            assign[names[i]] = "val"
        else:
            assign[names[i]] = "train"
    return assign


def main():
    ap = argparse.ArgumentParser(description="Build the windowed dataset.")
    # windowing / timing
    ap.add_argument("--dt", type=float, default=0.02, help="uniform timestep (s); 0.02 = 50 Hz")
    ap.add_argument("--window", type=int, default=50, help="W: input length in steps")
    ap.add_argument("--horizon", type=int, default=40, help="H: future length to predict")
    ap.add_argument("--stride", type=int, default=10, help="step between window starts")
    # split control
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--test-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--val-segments", nargs="*", default=[], help="explicit val CSV names")
    ap.add_argument("--test-segments", nargs="*", default=[], help="explicit test CSV names")
    # regime labeling thresholds (m/s^2)
    ap.add_argument("--accel-thresh", type=float, default=6.0)
    ap.add_argument("--turn-thresh", type=float, default=6.0)
    ap.add_argument("--smooth", type=int, default=5)
    # io
    ap.add_argument("--trunc-dir", default=str(TRUNC_DIR))
    ap.add_argument("--out", default="3 dataset")
    args = ap.parse_args()

    W, H, dt = args.window, args.horizon, args.dt
    need = W + H
    label_kwargs = dict(accel_thresh=args.accel_thresh, turn_thresh=args.turn_thresh,
                        smooth=args.smooth)

    files = sorted(Path(args.trunc_dir).glob("liftoff_trunc_*.csv"))
    if not files:
        raise SystemExit(f"No segments found in '{args.trunc_dir}'. "
                         "Run check_recordings.py first.")

    # Load + resample every segment; keep only those long enough for a window
    segments = []
    for p in files:
        t, pos = load_segment(p)
        if len(t) < 2:
            print(f"  skip {p.name}: <2 samples")
            continue
        _, pos_u = resample_uniform(t, pos, dt)
        if len(pos_u) < need:
            print(f"  skip {p.name}: only {len(pos_u)} resampled steps (< W+H = {need})")
            continue
        vel_u = derive_velocity(pos_u, dt)
        segments.append({"name": p.name, "pos": pos_u, "vel": vel_u})

    if not segments:
        raise SystemExit("No segment was long enough to form a window. "
                         "Lower --window/--horizon or capture longer flights.")

    names = [s["name"] for s in segments]
    assign = assign_splits(names, args.val_frac, args.test_frac, args.seed,
                           args.val_segments, args.test_segments)

    # Build windows, grouped by split
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    buckets = {"train": [], "val": [], "test": []}
    for i, seg in enumerate(segments):
        split = assign[seg["name"]]
        buckets[split].append((i, seg))

    manifest = {"config": vars(args), "regime_names": REGIME_NAMES, "splits": {}}
    print(f"\n{len(segments)} segment(s), dt={dt}s, W={W}, H={H}, stride={args.stride}\n")

    for split, items in buckets.items():
        IP, FP, SG, RG, SID = [], [], [], [], []
        for seg_index, seg in items:
            ip, fp, sg, rg, sid = make_windows(seg["pos"], seg["vel"], dt, W, H,
                                               args.stride, seg_index, label_kwargs)
            IP += ip;
            FP += fp;
            SG += sg;
            RG += rg;
            SID += sid

        if not IP:
            print(f"[{split}] no windows (no segments assigned) - writing empty split")
            input_pos = np.empty((0, W, 3), np.float32)
            future_pos = np.empty((0, H, 3), np.float32)
            state_gt = np.empty((0, W, 6), np.float32)
            regime = np.empty((0,), np.int64)
            seg_id = np.empty((0,), np.int64)
        else:
            input_pos = np.stack(IP).astype(np.float32)
            future_pos = np.stack(FP).astype(np.float32)
            state_gt = np.stack(SG).astype(np.float32)
            regime = np.asarray(RG, np.int64)
            seg_id = np.asarray(SID, np.int64)

        np.savez_compressed(out_dir / f"{split}.npz",
                            input_pos=input_pos, future_pos=future_pos,
                            state_gt=state_gt, regime=regime, seg_id=seg_id,
                            dt=np.array(dt))

        # per-split report: regime distribution + which flights are in it
        dist = {REGIME_NAMES[c]: int((regime == c).sum()) for c in REGIME_NAMES}
        seg_names = [s["name"] for j, s in items] if items else []
        manifest["splits"][split] = {
            "segments": seg_names, "n_windows": int(len(regime)),
            "regime_counts": dist,
        }
        print(f"[{split}] {len(items)} segment(s) -> {len(regime)} windows | regimes {dist}")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {out_dir}/train.npz, val.npz, test.npz + manifest.json")
    # Friendly nudge: with few segments, check val/test actually contain varied regimes.
    for split in ("val", "test"):
        present = [k for k, v in manifest["splits"][split]["regime_counts"].items() if v]
        if manifest["splits"][split]["n_windows"] and len(present) < 2:
            print(f"  note: {split} covers only regime(s) {present}. "
                  "Consider hand-picking segments (--{split}-segments) for more variety.")


if __name__ == "__main__":
    main()
