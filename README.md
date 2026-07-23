# cat-apult

Telemetry capture, cleaning, and dataset tooling for **Liftoff: FPV Drone Racing**.

`cat-apult` streams live UDP telemetry from Liftoff, records your flights into clean CSV logs, splits them into continuous segments, visualizes them in 3D, and builds a windowed train/val/test dataset for trajectory-prediction models. Every stage runs on Liftoff's in-game physics clock, with coordinates normalized so each flight starts at the origin.

---

## Features

* **Real-time UDP Capture:** Listens to Liftoff's telemetry stream and records it directly to your machine.
* **Dual Output:** Each recording is saved twice - a complete log with every channel, and a truncated time + `x, y, z` log ready for downstream analysis or modeling.
* **In-Game Clock Throughout:** All derived quantities use Liftoff's physics timestamp, not packet-arrival time. See [Why in-game time](#why-in-game-time) - this one detail decides whether your velocities and accelerations are real or garbage.
* **Origin-Normalized Positions:** Every flight is translated to start at `(0, 0, 0)`, so trajectories are directly comparable no matter where on the map you launched. Since this is a pure translation, velocity and all motion dynamics are preserved.
* **Automatic Segmentation:** Detects drone resets, teleports, and dropped telemetry, then splits each flight into clean continuous segments, each re-zeroed into a standalone flight.
* **3D Trajectory Mapping:** Visualizes flight paths in a 3D environment with automatic translation from Unity's coordinate space (Y-up) to standard spatial graphs.
* **Speed Dynamics:** Dynamic path color-coding based on your drone's velocity.
* **Top-Down Analytics:** Includes a 2D top-down projection mapping out exact spatial coordinates.
* **Dataset Builder:** Resamples to a uniform timestep, derives ground-truth velocity, labels motion regimes, and slices sliding windows into `train` / `val` / `test` splits - partitioned by whole segment so no flight leaks across splits.

---

## One-Time Setup

Before running the scripts, you must configure Liftoff to stream its telemetry data over UDP.

1. Navigate to Liftoff's configuration folder. On Windows, this is typically located at:
```text
%USERPROFILE%\AppData\LocalLow\LuGus Studios\Liftoff\
```

2. Create a new file named **`TelemetryConfiguration.json`** inside that folder.
3. Paste the following configuration into the file:

```json
{
  "EndPoint": "127.0.0.1:9001",
  "StreamFormat": ["Timestamp", "Position", "Attitude", "Gyro", "Input"]
}
```

> **Note:** Liftoff reloads this configuration file whenever you reset your drone in-game, so you do not need to restart the entire game client after creating this file. Telemetry will only stream while you are actively flying (it does not stream during spectating or replays).

---

## Requirements

Ensure you have Python 3 installed along with the required dependencies:

```bash
pip install numpy matplotlib
```

> The capture script itself uses only the Python standard library - `numpy` and `matplotlib` are needed for the visualizer and the dataset tooling.

---

## Pipeline Overview

```text
Liftoff (UDP)
    |  liftoff_capture.py
    v
0 full recordings/          1 truncated recordings/
    |  check_recordings.py
    v
3 checked recordings/
    3 1 checked full/       3 2 checked trunc/
    |  build_dataset.py
    v
dataset/  train.npz  val.npz  test.npz  manifest.json
```

---

## How To Use

### 1. Capture Flight Data

Run the capture script in your terminal *before* or *during* your flight:

```bash
python liftoff_capture.py
```

* **`[Enter]`**: Press Enter to toggle recording **ON** or **OFF**.
* **`q [Enter]`**: Type `q` and press Enter to exit the script safely.

Each recording is saved as **two** CSV files (sharing the same timestamp) in two auto-generated folders:

* `0 full recordings/liftoff_full_YYYY-MM-DD_HH-MM-SS.csv` - every telemetry channel.
* `1 truncated recordings/liftoff_trunc_YYYY-MM-DD_HH-MM-SS.csv` - in-game time and position only (`t_sim, x, y, z`).

Position (`x, y, z`) is normalized in both files so every flight starts at `(0, 0, 0)`, and the truncated file's `t_sim` is re-zeroed so every flight starts at `t = 0`.

### 2. Visualize Trajectories

Once you have recorded a flight, you can generate 3D plots and top-down charts.

* **Visualize the latest recording** (newest file in `0 full recordings/`):
```bash
python visualize_liftoff.py
```

* **Visualize a specific recording file** (quote the path - the folder name contains spaces):
```bash
python visualize_liftoff.py "0 full recordings/liftoff_full_YOUR_TIMESTAMP.csv"
```

Running the visualizer will display an interactive window on your desktop and automatically save a corresponding `.png` plot next to your CSV file.

### 3. Check and Segment Recordings

A single recording is not always one continuous trajectory: you may have reset the drone, crashed and respawned, or lost packets. This step finds those points and splits each flight into clean, continuous segments.

```bash
python check_recordings.py --report-only          # inspect without writing anything
python check_recordings.py --min-samples 300      # write the segments
```

Three kinds of break are detected, all measured on the in-game clock so each means something physically real:

| Break | Trigger | Meaning |
| --- | --- | --- |
| `jump` | position moves more than `--jump` metres in one step | teleport: reset or crash-respawn |
| `gap` | `t_sim` advances more than `--gap` seconds | physics happened that we never received (dropped packets) |
| `reset` | `t_sim` goes backwards or stalls | Liftoff restarted its clock: drone reset |

A game freeze is deliberately **not** a break. If the simulation stalls, no physics advances, so `t_sim` stays continuous and the trajectory genuinely is continuous.

Useful flags: `--gap` (seconds), `--jump` (metres), `--min-samples` (drop segments shorter than this, which removes record-toggle slivers), `--no-renorm`.

Output lands in `3 checked recordings/`, with `3 1 checked full/` and `3 2 checked trunc/` split at identical boundaries. Each segment is re-zeroed in both position and time, so it stands alone as its own flight.

> Re-running regenerates this folder. Delete `3 checked recordings/` first so no stale segments from a previous run linger.

### 4. Build the Dataset

Turns the clean segments into windowed `.npz` splits for model training and evaluation.

```bash
python build_dataset.py
python build_dataset.py --dt 0.02 --window 50 --horizon 40 --stride 10
python build_dataset.py --accel-thresh 4 --turn-thresh 12
```

For each segment it resamples onto a uniform timestep (linear interpolation), derives ground-truth velocity by central differences, slides fixed-size windows of `W` input steps plus `H` future steps, and labels each window's dominant motion regime.

**Splitting happens at the segment level.** Whole segments are assigned to `train`, `val`, or `test` *before* being cut into windows, so no continuous flight is shared across splits and overlapping windows cannot leak future information into the test set.

With few segments, a random split can leave `val` or `test` covering only one regime. Hand-pick them instead:

```bash
python build_dataset.py --val-segments liftoff_trunc_..._seg01.csv \
                        --test-segments liftoff_trunc_..._seg02.csv liftoff_trunc_..._seg03.csv
```

Everything stored is **clean**. Measurement noise is added at runtime via `dataset_utils.add_noise`, which keeps noise-sweep evaluation trivial and doubles as training augmentation.

---

## Why In-Game Time

Two timestamps exist, and only one of them is usable for physics.

`t_wall` is when the UDP packet **arrived** at the capture script. Packets arrive in bursts: on a real flight, gaps between arrivals ranged from 0.10 ms to 277 ms around a median of 8.9 ms. Two positions genuinely 10 ms apart can be recorded 0.1 ms apart, so dividing a real 0.2 m step by a fake 0.0001 s yields 2000 m/s - and differentiating that for acceleration squares the error.

`t_sim` is Liftoff's own physics clock, which ticks at a fixed rate regardless of network behaviour.

Measured on the same real flight:

| Time base | Median tangential acceleration | Peak speed |
| --- | --- | --- |
| `t_wall` (arrival) | 59.8 m/s² (6 g sustained - impossible) | 3067 m/s |
| `t_sim` (in-game) | 1.78 m/s² | 40 m/s |

The distortion is also asymmetric: arrival jitter fabricates speeding up and slowing down, not turning, so every window looks like it is accelerating and genuine coordinated turns never get labeled. The full recordings keep `t_wall` for diagnosing capture-side issues, but nothing derived is ever computed from it.

### Migrating Older Recordings

Truncated files created before this change stored `t_wall`. Since the full recordings already contain `t_sim`, no re-flying is needed:

```bash
python rebuild_truncated.py --dry-run     # list what would be written
python rebuild_truncated.py
```

Empty `1 truncated recordings/` first, run the script once, then delete `3 checked recordings/` and re-run steps 3 and 4. New recordings already use the in-game clock, so this is a one-time migration.

---

## Telemetry Data Layout

The **full** log (in `0 full recordings/`) uses the column configuration below to align with the CATS data structure.

| Column Header | Description |
| --- | --- |
| `t_wall` | Packet-arrival time (seconds, relative). Diagnostics only - never use it for derived quantities |
| `t_sim` | Liftoff's in-game physics timestamp |
| `x`, `y`, `z` | Unity coordinate position (`y` acts as altitude), normalized so each recording starts at `(0, 0, 0)` |
| `qx`, `qy`, `qz`, `qw` | Flight attitude represented as a quaternion |
| `gx`, `gy`, `gz` | Gyroscope angular velocity metrics |
| `in1` to `in4` | Processed stick inputs (Throttle, Roll, Pitch, Yaw - verify the exact order by moving one stick at a time) |

The **truncated** log (in `1 truncated recordings/`) contains only `t_sim`, `x`, `y`, and `z`, with `t_sim` re-zeroed to start at `0`.

---

## Dataset Layout

Each split (`train.npz`, `val.npz`, `test.npz`) holds clean data plus a `manifest.json` recording the configuration, which segments landed in each split, and the regime distribution.

| Array | Shape | Description |
| --- | --- | --- |
| `input_pos` | `(N, W, 3)` | clean input positions - call `add_noise` on these to produce model input |
| `future_pos` | `(N, H, 3)` | clean future positions - the prediction targets |
| `state_gt` | `(N, W, 6)` | ground-truth `x, y, z, vx, vy, vz` over the input window |
| `regime` | `(N,)` | motion-regime label per window |
| `seg_id` | `(N,)` | source-segment index, for traceability |
| `dt` | scalar | uniform timestep in seconds |

Regime codes: `0 = CV` (constant velocity), `1 = CA` (accelerating or braking), `2 = CT` (coordinated turn), `3 = MIX` (accelerating through a turn, or a regime transition).

> Regime labels are a heuristic we impose, not ground truth - real human flight blends regimes continuously. They exist for the evaluation breakdown ("accuracy vs regime") and are never used for training, so mild fuzziness cannot affect the model. Tune `--accel-thresh` and `--turn-thresh` (both m/s²) by coloring a trajectory by its label and nudging until the labels match what the path visibly does.

---

## Scripts

| Script | Purpose |
| --- | --- |
| `liftoff_capture.py` | Record live telemetry into full and truncated CSVs |
| `visualize_liftoff.py` | 3D speed-colored path plus top-down view for one recording |
| `check_recordings.py` | Detect resets, teleports, and dropped telemetry; split into clean segments |
| `build_dataset.py` | Resample, derive velocity, window, and split into `train` / `val` / `test` |
| `dataset_utils.py` | Shared primitives (resampling, velocity, regime labeling, noise, loading) imported by every downstream consumer |
| `rebuild_truncated.py` | One-time migration of pre-`t_sim` truncated recordings |
