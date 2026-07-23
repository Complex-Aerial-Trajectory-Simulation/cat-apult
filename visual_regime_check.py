"""
visual_regime_check.py
======================
Draw a segment with its trajectory colored by MOTION REGIME, so you can see whether
the labels match what the path visibly does - and tune the thresholds until they do.

Shows a 3D path, a top-down view, and a regime-vs-time strip, plus a printed
distribution. Colors: CV blue, CA green, CT orange, MIX red.

Usage:
    python visual_regime_check.py                     # newest checked segment
    python visual_regime_check.py "3 checked recordings/3 2 checked trunc/liftoff_trunc_X.csv"
    python visual_regime_check.py --accel-thresh 4 --turn-thresh 12
    python visual_regime_check.py --window 50 --horizon 40 --stride 10

Saves a PNG next to the CSV (suffixed _regimes) and opens an interactive window.
Note: Liftoff uses Unity axes (Y = up), so altitude is the 'y' column.

Tuning tip: raise --turn-thresh until only the visibly sharp corners come out orange;
raise --accel-thresh until only the obvious punch-outs and hard brakes come out green.
Long straights should be blue. These labels feed the evaluation breakdown only, never
training, so they need to be reasonable rather than perfect.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from dataset_utils import resample_uniform, derive_velocity, label_regime, REGIME_NAMES
from build_dataset import load_segment

# Where to look when no file is given: cleaned segments first, raw recordings second.
SEARCH_DIRS = [
    Path("2 checked recordings") / "2 2 checked trunc",
    Path("1 truncated recordings"),
]

REGIME_COLORS = {0: "#1f6feb", 1: "#2da44e", 2: "#e08c1a", 3: "#d1242f"}  # CV CA CT MIX


def pick_file():
    """Explicit path if given, else the newest truncated CSV we can find."""
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        return Path(sys.argv[1])
    for d in SEARCH_DIRS:
        files = sorted(d.glob("liftoff_trunc_*.csv"))
        if files:
            return files[-1]
    sys.exit("No segments found. Run check_recordings.py, or pass a CSV path explicitly.")


def per_sample_labels(vel_u, dt, W, H, stride, label_kwargs):
    """
    Label every sample of the segment, not just every window.

    Windows overlap (span W+H, step `stride`), so drawing each window's whole span
    would overdraw the trajectory several times. Instead each window's label is
    attached to its CENTER, and every sample takes the label of the nearest center.
    Consecutive centers sit exactly `stride` apart, so coverage is contiguous and
    each piece of the path is drawn once.

    :param vel_u: (L, 3) uniform-dt velocity
    :param dt: float, timestep in seconds
    :param W: int, input window length in steps
    :param H: int, future horizon length in steps
    :param stride: int, step between window starts
    :param label_kwargs: dict passed to label_regime
    :return: (labels (L,), window_labels (list[int])) - per-sample and per-window
    """
    L = len(vel_u)
    span = W + H
    if L < span:
        sys.exit(f"Segment has {L} resampled steps, fewer than W+H = {span}. "
                 "Use a longer segment or smaller --window/--horizon.")

    centers, win_labels = [], []
    for s in range(0, L - span + 1, stride):
        win_labels.append(label_regime(vel_u[s:s + span], dt, **label_kwargs))
        centers.append(s + span // 2)

    centers = np.asarray(centers)
    win_arr = np.asarray(win_labels)
    # nearest-center lookup for every sample index
    idx = np.searchsorted(centers, np.arange(L))
    idx = np.clip(idx, 0, len(centers) - 1)
    prev = np.clip(idx - 1, 0, len(centers) - 1)
    take_prev = np.abs(np.arange(L) - centers[prev]) <= np.abs(np.arange(L) - centers[idx])
    labels = np.where(take_prev, win_arr[prev], win_arr[idx])
    return labels, win_labels


def main():
    ap = argparse.ArgumentParser(description="Visualize motion-regime labels on a segment.")
    ap.add_argument("path", nargs="?", help="segment CSV (default: newest found)")
    ap.add_argument("--dt", type=float, default=0.02, help="resample timestep (s)")
    ap.add_argument("--window", type=int, default=50, help="W, matching build_dataset")
    ap.add_argument("--horizon", type=int, default=40, help="H, matching build_dataset")
    ap.add_argument("--stride", type=int, default=10, help="step between windows")
    ap.add_argument("--accel-thresh", type=float, default=4.0, help="m/s^2, CA trigger")
    ap.add_argument("--turn-thresh", type=float, default=12.0, help="m/s^2, CT trigger")
    ap.add_argument("--smooth", type=int, default=9, help="de-jitter window for labeling")
    args = ap.parse_args()

    path = Path(args.path) if args.path else pick_file()
    label_kwargs = dict(accel_thresh=args.accel_thresh, turn_thresh=args.turn_thresh,
                        smooth=args.smooth)

    t, pos = load_segment(path)
    if len(t) < 2:
        sys.exit("Segment too short to plot.")
    grid_t, pos_u = resample_uniform(t, pos, args.dt)
    vel_u = derive_velocity(pos_u, args.dt)
    labels, win_labels = per_sample_labels(vel_u, args.dt, args.window, args.horizon,
                                           args.stride, label_kwargs)

    speed = np.linalg.norm(vel_u, axis=1)
    x, y, z = pos_u[:, 0], pos_u[:, 1], pos_u[:, 2]

    # distribution over WINDOWS is what build_dataset will store, so report that
    counts = {c: int(np.sum(np.asarray(win_labels) == c)) for c in REGIME_NAMES}
    total = max(sum(counts.values()), 1)
    print(f"{path.name}: {len(pos_u)} steps, {grid_t[-1]-grid_t[0]:.1f}s, "
          f"peak speed {speed.max():.1f} m/s")
    print(f"thresholds: accel {args.accel_thresh} m/s^2, turn {args.turn_thresh} m/s^2, "
          f"smooth {args.smooth}")
    print("window regimes: " + "  ".join(
        f"{REGIME_NAMES[c]} {counts[c]} ({100*counts[c]/total:.1f}%)" for c in REGIME_NAMES))

    # Map Unity (x, y=up, z) -> plot (x, z, y) so the vertical axis is altitude.
    P = np.column_stack([x, z, y])
    seg_colors = [REGIME_COLORS[int(l)] for l in labels[:-1]]

    fig = plt.figure(figsize=(14, 7))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.35, 1], height_ratios=[3, 1])

    # --- 3D path, colored by regime ---
    ax = fig.add_subplot(gs[:, 0], projection="3d")
    segs3d = np.stack([P[:-1], P[1:]], axis=1)
    ax.add_collection3d(Line3DCollection(segs3d, colors=seg_colors, linewidths=1.8))
    ax.scatter(*P[0], c="lime", s=45, label="start")
    ax.scatter(*P[-1], c="black", s=45, marker="s", label="end")

    def _lim(vals):
        # A perfectly flat axis (e.g. constant altitude) would collapse the limits,
        # so pad it slightly.
        lo, hi = float(vals.min()), float(vals.max())
        if hi - lo < 1e-6:
            return lo - 1.0, hi + 1.0
        return lo, hi

    ax.set_xlim(*_lim(P[:, 0]))
    ax.set_ylim(*_lim(P[:, 1]))
    ax.set_zlim(*_lim(P[:, 2]))
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.set_zlabel("altitude y (m)")
    ax.set_title(f"{path.name}\naccel>{args.accel_thresh} = CA,  turn>{args.turn_thresh} = CT")

    # --- top-down ---
    ax2 = fig.add_subplot(gs[0, 1])
    for c, col in REGIME_COLORS.items():
        m = labels == c
        if m.any():
            ax2.scatter(x[m], z[m], c=col, s=6)
    ax2.plot(x, z, color="gray", lw=0.4, alpha=0.4, zorder=0)
    ax2.scatter(x[0], z[0], c="lime", s=45, zorder=3)
    ax2.scatter(x[-1], z[-1], c="black", s=45, marker="s", zorder=3)
    ax2.set_aspect("equal", "datalim")
    ax2.set_xlabel("x (m)")
    ax2.set_ylabel("z (m)")
    ax2.set_title("top-down (x-z)")

    # --- regime over time, with speed for context ---
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.plot(grid_t, speed, color="0.6", lw=0.8, zorder=1)
    for c, col in REGIME_COLORS.items():
        m = labels == c
        if m.any():
            ax3.scatter(grid_t[m], np.full(m.sum(), -0.06 * speed.max()),
                        c=col, s=8, marker="|", zorder=2)
    ax3.set_xlabel("t (s)")
    ax3.set_ylabel("speed (m/s)")
    ax3.set_title("regime over time")
    ax3.margins(x=0.01)

    handles = [Line2D([0], [0], color=REGIME_COLORS[c], lw=3,
                      label=f"{c}: {REGIME_NAMES[c]}  ({100*counts[c]/total:.0f}%)")
               for c in REGIME_NAMES]
    fig.legend(handles=handles, loc="lower left", ncol=4, frameon=False,
               bbox_to_anchor=(0.02, 0.005))

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    out = path.with_name(path.stem + "_regimes.png")
    fig.savefig(out, dpi=130)
    print("saved", out)
    plt.show()


if __name__ == "__main__":
    main()
