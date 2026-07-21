"""
visualize_liftoff.py
===================
Draw a Liftoff recording in 3D (path colored by speed) plus a top-down view.

Usage:
    python visualize_liftoff.py # the newest recording
    python visualize_liftoff.py "0 full recordings/liftoff_full_x.csv" # a specific file

Saves a PNG next to the CSV and opens an interactive window.
Note: Liftoff uses Unity axes (Y = up), so altitude is the 'y' column.
"""

import sys
import csv
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection


def pick_file():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    files = sorted(Path("0 full recordings").glob("liftoff_full_*.csv"))
    if not files:
        sys.exit("No recordings found in '0 full recordings/'. Pass a CSV path explicitly.")
    return files[-1]


def load(path):
    t, x, y, z = [], [], [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            t.append(float(row["t_sim"]))
            x.append(float(row["x"]))
            y.append(float(row["y"]))
            z.append(float(row["z"]))
    return (np.asarray(a) for a in (t, x, y, z))


def maybe_downsample(step_arrays, target=8000):
    n = len(step_arrays[0])
    if n <= target:
        return step_arrays
    idx = np.linspace(0, n - 1, target).astype(int)
    return [a[idx] for a in step_arrays]


def main():
    path = pick_file()
    t, x, y, z = load(path)
    if len(t) < 2:
        sys.exit("Recording too short to plot.")

    # speed straight from position (works because telemetry position is clean (as opposed to if we introduced the noise))
    dt = np.gradient(t)
    dt[dt == 0] = 1e-6
    speed = np.sqrt(np.gradient(x) ** 2 + np.gradient(y) ** 2 + np.gradient(z) ** 2) / dt

    t, x, y, z, speed = maybe_downsample([t, x, y, z, speed])

    # Map Unity (x, y=up, z) -> plot (x, z, y) so the vertical axis is altitude.
    P = np.column_stack([x, z, y])
    segs = np.stack([P[:-1], P[1:]], axis=1)
    smax = speed.max() + 1e-9

    fig = plt.figure(figsize=(13, 6))

    ax = fig.add_subplot(1, 2, 1, projection="3d")
    lc = Line3DCollection(segs, cmap="viridis", array=speed[:-1], linewidths=1.6)
    ax.add_collection3d(lc)
    ax.scatter(*P[0], c="lime", s=45, label="start")
    ax.scatter(*P[-1], c="red", s=45, label="end")
    ax.set_xlim(P[:, 0].min(), P[:, 0].max())
    ax.set_ylim(P[:, 1].min(), P[:, 1].max())
    ax.set_zlim(P[:, 2].min(), P[:, 2].max())
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.set_zlabel("altitude y (m)")
    ax.set_title(f"{path.name}\n{len(t)} pts | {t[-1] - t[0]:.1f}s | peak {speed.max():.1f} m/s")
    ax.legend(loc="upper left")

    ax2 = fig.add_subplot(1, 2, 2)
    sc = ax2.scatter(x, z, c=speed, cmap="viridis", s=7)
    ax2.plot(x, z, color="gray", lw=0.4, alpha=0.5)
    ax2.scatter(x[0], z[0], c="lime", s=45)
    ax2.scatter(x[-1], z[-1], c="red", s=45)
    ax2.set_aspect("equal", "datalim")
    ax2.set_xlabel("x (m)")
    ax2.set_ylabel("z (m)")
    ax2.set_title("top-down (x-z)")
    fig.colorbar(sc, ax=ax2, label="speed (m/s)")

    fig.tight_layout()
    out = path.with_suffix(".png")
    fig.savefig(out, dpi=130)
    print("saved", out)
    plt.show()


if __name__ == "__main__":
    main()
