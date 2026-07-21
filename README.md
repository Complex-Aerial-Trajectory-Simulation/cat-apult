# cat-apult

Telemetry capture and 3D flight path visualization tools for **Liftoff: FPV Drone Racing**.

`cat-apult` allows you to stream live UDP telemetry data from Liftoff, record your flights into clean CSV logs, and generate beautiful 3D and top-down spatial plots of your aerial trajectories. Every flight is saved as both a full telemetry log and a lightweight, modeling-ready position log, with coordinates normalized so each recording starts at the origin.

---

## Features

* **Real-time UDP Capture:** Listens to Liftoff's telemetry stream and records it directly to your machine.
* **Dual Output:** Each recording is saved twice - a complete log with every channel, and a truncated `x, y, z` + time log ready for downstream analysis or modeling.
* **Origin-Normalized Positions:** Every flight is translated to start at `(0, 0, 0)`, so trajectories are directly comparable no matter where on the map you launched. Since this is a pure translation, velocity and all motion dynamics are preserved.
* **Structured Data:** Exports clean, time-stamped CSV logs featuring wall time, simulation time, 3D positions, quaternions (attitude), gyro metrics, and stick inputs.
* **3D Trajectory Mapping:** Visualizes flight paths in a 3D environment with automatic translation from Unity's coordinate space (Y-up) to standard spatial graphs.
* **Speed Dynamics:** Dynamic path color-coding based on your drone's velocity.
* **Top-Down Analytics:** Includes a 2D top-down projection mapping out exact spatial coordinates.

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

Ensure you have Python 3 installed along with the required visualization dependencies:

```bash
pip install numpy matplotlib
```

> The capture script itself uses only the Python standard library - `numpy` and `matplotlib` are needed only for the visualizer.

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
* `1 truncated recordings/liftoff_trunc_YYYY-MM-DD_HH-MM-SS.csv` - real-world time and position only (`t_wall, x, y, z`).

Position (`x, y, z`) is normalized in both files so every flight starts at `(0, 0, 0)`.

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

---

## Telemetry Data Layout

Each recording produces two files. The **full** log (in `0 full recordings/`) uses the column configuration below to align with the CATS data structure. The **truncated** log (in `1 truncated recordings/`) contains only the `t_wall`, `x`, `y`, and `z` columns.

| Column Header | Description |
| --- | --- |
| `t_wall` | Relative wall-clock execution time (seconds) |
| `t_sim` | In-game simulation time stamp |
| `x`, `y`, `z` | Unity coordinate position (`y` acts as altitude), normalized so each recording starts at `(0, 0, 0)` |
| `qx`, `qy`, `qz`, `qw` | Flight attitude represented as a quaternion |
| `gx`, `gy`, `gz` | Gyroscope angular velocity metrics |
| `in1` to `in4` | Processed stick inputs (Throttle, Roll, Pitch, Yaw) |
