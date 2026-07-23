"""
liftoff_capture.py
==================
Capture Liftoff: FPV Drone Racing telemetry (UDP) into CSVs, one pair per recording.

For every recording, two files are written:
  * "0 full recordings/liftoff_full_YYYY-MM-DD_HH-MM-SS.csv"
        all channels: t_wall, t_sim, x, y, z, quaternion, gyro, 4 inputs
  * "1 truncated recordings/liftoff_trunc_YYYY-MM-DD_HH-MM-SS.csv"
        just: t_sim, x, y, z   (in-game clock + position)

The truncated file uses Liftoff's IN-GAME physics clock, re-zeroed to start at 0 - not
packet-arrival time. Arrival times jitter wildly (0.1 ms to 277 ms around a 8.9 ms
median), which would fabricate huge fake accelerations downstream. The full file keeps
both clocks so t_wall stays available for diagnosing capture-side issues.

x, y, z are NORMALIZED so each recording starts at (0, 0, 0): the first sample's
position is subtracted from every sample. This is a pure translation, so velocity and
all motion dynamics are unchanged; only absolute track position is dropped.

ONE-TIME SETUP
--------------
Create  TelemetryConfiguration.json  in Liftoff's config folder so the game streams to
this script. On Windows:

    %USERPROFILE%\\AppData\\LocalLow\\LuGus Studios\\Liftoff\\

with contents:

    { "EndPoint": "127.0.0.1:9001",
      "StreamFormat": ["Timestamp", "Position", "Attitude", "Gyro", "Input"] }

That StreamFormat produces a fixed 60-byte frame = 15 float32 values. Liftoff reloads
the config whenever you reset the drone, so no game restart is needed. Telemetry only
streams for a drone you are actively flying (not spectating/replay).

RUN
---
    python liftoff_capture.py

CONTROLS (type in this terminal window, then press Enter)
    [Enter]  ..... start a recording / stop it again (toggle)
    q [Enter] .... quit
"""

import socket
import struct
import csv
import threading
import time
from pathlib import Path
from datetime import datetime

HOST, PORT = "127.0.0.1", 9001
PACKET_FMT = "<15f" # 15 little-endian float32
PACKET_SIZE = struct.calcsize(PACKET_FMT)  # = 60 bytes

# Unpacked packet order (15 floats):
#   [0] t_sim, [1] x, [2] y, [3] z, [4..7] quat, [8..10] gyro, [11..14] inputs
# Liftoff uses Unity's coordinate system: Y is UP (altitude). Attitude is a quaternion.
FULL_COLUMNS = ["t_wall", "t_sim", "x", "y", "z",
                "qx", "qy", "qz", "qw",
                "gx", "gy", "gz",
                "in1", "in2", "in3", "in4"]
TRUNC_COLUMNS = ["t_sim", "x", "y", "z"]

FULL_DIR = Path("0 full recordings")
TRUNC_DIR = Path("1 truncated recordings")


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.recording = False
        self.full_file = self.trunc_file = None
        self.full_writer = self.trunc_writer = None
        self.full_name = self.trunc_name = None
        self.origin = None # (x0, y0, z0) of this recording, for normalization
        self.t_sim0 = None # first in-game timestamp, so trunc time starts at 0
        self.count = 0
        self.t0 = None

    def start(self):
        with self.lock:
            if self.recording:
                return
            FULL_DIR.mkdir(exist_ok=True)
            TRUNC_DIR.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.full_name = FULL_DIR / f"liftoff_full_{stamp}.csv"
            self.trunc_name = TRUNC_DIR / f"liftoff_trunc_{stamp}.csv"
            self.full_file = self.full_name.open("w", newline="")
            self.trunc_file = self.trunc_name.open("w", newline="")
            self.full_writer = csv.writer(self.full_file)
            self.trunc_writer = csv.writer(self.trunc_file)
            self.full_writer.writerow(FULL_COLUMNS)
            self.trunc_writer.writerow(TRUNC_COLUMNS)
            self.origin = None
            self.t_sim0 = None
            self.count = 0
            self.t0 = time.perf_counter()
            self.recording = True
        print(f"\n\u25cf REC  \u2192 {self.full_name}   (press Enter to stop)")

    def stop(self):
        with self.lock:
            if not self.recording:
                return
            self.recording = False
            for f in (self.full_file, self.trunc_file):
                f.flush()
                f.close()
            n, fn, tn = self.count, self.full_name, self.trunc_name
        print(f"\n\u25a0 saved {n} samples \u2192 {fn}\n{'':17}and \u2192 {tn}")

    def write(self, values):
        with self.lock:
            if not self.recording:
                return
            t_wall = time.perf_counter() - self.t0
            t_sim, px, py, pz = values[0], values[1], values[2], values[3]
            if self.origin is None:
                self.origin = (px, py, pz)
                self.t_sim0 = t_sim
            ox, oy, oz = self.origin
            xn, yn, zn = px - ox, py - oy, pz - oz
            rest = values[4:]  # quat + gyro + inputs


            self.full_writer.writerow(
                [f"{t_wall:.4f}", f"{t_sim:.5f}", f"{xn:.5f}", f"{yn:.5f}", f"{zn:.5f}"]
                + [f"{v:.5f}" for v in rest])
            self.trunc_writer.writerow(
                [f"{t_sim - self.t_sim0:.5f}", f"{xn:.5f}", f"{yn:.5f}", f"{zn:.5f}"])
            self.count += 1
            c = self.count
        if c % 250 == 0:
            print(f"\r   recording... {c} samples", end="", flush=True)


def receiver(sock, rec, stop_event):
    sock.settimeout(0.2)
    warned = False
    while not stop_event.is_set():
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        if len(data) != PACKET_SIZE:
            if not warned:
                print(f"\n[!] received a {len(data)}-byte packet, expected {PACKET_SIZE}. "
                      "Your StreamFormat probably differs from "
                      "[Timestamp, Position, Attitude, Gyro, Input].")
                warned = True
            continue
        rec.write(struct.unpack(PACKET_FMT, data))


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass
    sock.bind((HOST, PORT))

    rec = Recorder()
    stop_event = threading.Event()
    t = threading.Thread(target=receiver, args=(sock, rec, stop_event), daemon=True)
    t.start()

    print(f"Listening for Liftoff telemetry on {HOST}:{PORT}")
    print("Fly in Liftoff, then press [Enter] to start a recording, [Enter] again to "
          "stop it. Type q + Enter to quit.\n")
    try:
        while True:
            cmd = input()
            if cmd.strip().lower() == "q":
                break
            rec.stop() if rec.recording else rec.start()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        if rec.recording:
            rec.stop()
        stop_event.set()
        t.join(timeout=1.0)
        sock.close()
        print("Done.")


if __name__ == "__main__":
    main()
