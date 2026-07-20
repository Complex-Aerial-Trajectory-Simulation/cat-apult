"""
liftoff_capture.py
==================
Capture Liftoff: FPV Drone Racing telemetry (UDP) into one CSV per recording.

ONE-TIME SETUP
--------------
Create a file named  TelemetryConfiguration.json  in Liftoff's config folder so the
game streams telemetry to this script. On Windows that folder is:

    %USERPROFILE%\\AppData\\LocalLow\\LuGus Studios\\Liftoff\\

with contents:

    { "EndPoint": "127.0.0.1:9001",
      "StreamFormat": ["Timestamp", "Position", "Attitude", "Gyro", "Input"] }

That StreamFormat produces a fixed 60-byte frame = 15 float32 values, which is what
this script parses. Liftoff reloads the config whenever you reset the drone, so no
game restart is needed. Telemetry only streams for a drone you are actively flying
(not spectating/replay).

RUN
---
    python liftoff_capture.py

CONTROLS (type in this terminal window, then press Enter)
    [Enter]  ..... start a recording / stop it again (toggle)
    q [Enter] .... quit

Each recording -> recordings/liftoff_YYYY-MM-DD_HH-MM-SS.csv
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
PACKET_SIZE = struct.calcsize(PACKET_FMT) # = 60 bytes

# Column layout matches StreamFormat above.
# Liftoff uses Unity's coordinate system: Y is UP (altitude). Attitude is a quaternion.
# The 4 input channels are "processed" stick inputs; exact order can be confirmed by
# wiggling one stick and seeing which column moves (throttle/roll/pitch/yaw).
COLUMNS = ["t_wall", "t_sim", "x", "y", "z",
           "qx", "qy", "qz", "qw",
           "gx", "gy", "gz",
           "in1", "in2", "in3", "in4"]

OUTDIR = Path("recordings")


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.recording = False
        self.writer = None
        self.file = None
        self.count = 0
        self.t0 = None
        self.name = None

    def start(self):
        with self.lock:
            if self.recording:
                return
            OUTDIR.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.name = OUTDIR / f"liftoff_{stamp}.csv"
            self.file = self.name.open("w", newline="")
            self.writer = csv.writer(self.file)
            self.writer.writerow(COLUMNS)
            self.count = 0
            self.t0 = time.perf_counter()
            self.recording = True
        print(f"\n\u25cf REC  \u2192 {self.name}   (press Enter to stop)")

    def stop(self):
        with self.lock:
            if not self.recording:
                return
            self.recording = False
            self.file.flush()
            self.file.close()
            n, name = self.count, self.name
        print(f"\n\u25a0 saved {n} samples \u2192 {name}")

    def write(self, values):
        with self.lock:
            if not self.recording:
                return
            t_wall = time.perf_counter() - self.t0
            self.writer.writerow([f"{t_wall:.4f}"] + [f"{v:.5f}" for v in values])
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
