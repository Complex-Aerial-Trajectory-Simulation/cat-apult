# cat-apult

Telemetry capture and 3D flight path visualization tools for **Liftoff: FPV Drone Racing**, built for the **Complex Aerial Trajectory Simulation (CATS)** organization.

`cat-apult` allows you to stream live UDP telemetry data from Liftoff, record your flights into clean CSV logs, and generate beautiful 3D and top-down spatial plots of your aerial trajectories.

---

## Features

* **Real-time UDP Capture:** Listens to Liftoff's telemetry stream and records it directly to your machine.
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

---

## How To Use

### 1. Capture Flight Data

Run the capture script in your terminal *before* or *during* your flight:

```bash
python liftoff_capture.py

```

* **`[Enter]`**: Press Enter to toggle recording **ON** or **OFF**.
* **`q [Enter]`**: Type `q` and press Enter to exit the script safely.

All flight logs will be saved automatically to a newly generated directory: `recordings/liftoff_YYYY-MM-DD_HH-MM-SS.csv`

### 2. Visualize Trajectories

Once you have recorded a flight, you can generate 3D plots and top-down charts.

* **Visualize the latest recording:**
```bash
python visualize_liftoff.py

```


* **Visualize a specific recording file:**
```bash
python visualize_liftoff.py recordings/liftoff_YOUR_TIMESTAMP.csv

```



Running the visualizer will display an interactive window on your desktop and automatically save a corresponding `.png` plot next to your CSV file.

---

## Telemetry Data Layout

The exported CSV files utilize the following column configuration to align with the CATS data structure:

| Column Header | Description |
| --- | --- |
| `t_wall` | Relative wall-clock execution time (seconds) |
| `t_sim` | In-game simulation time stamp |
| `x`, `y`, `z` | Unity coordinate position (`y` acts as altitude) |
| `qx`, `qy`, `qz`, `qw` | Flight attitude represented as a quaternion |
| `gx`, `gy`, `gz` | Gyroscope angular velocity metrics |
| `in1` to `in4` | Processed stick inputs (Throttle, Roll, Pitch, Yaw) |
