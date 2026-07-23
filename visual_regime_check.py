import matplotlib.pyplot as plt
import numpy as np
from dataset_utils import derive_velocity, label_regime, resample_uniform
from build_dataset import load_segment

# Load and resample your short, regime-dense flight
t, pos = load_segment("1 truncated recordings\\liftoff_trunc_2026-07-22_11-25-37.csv")
dt = 0.02
_, pos_u = resample_uniform(t, pos, dt)
vel_u = derive_velocity(pos_u, dt)

# Slide through in windows (matching your build_dataset settings)
W, H, stride = 50, 40, 10
colors = {0: "blue", 1: "green", 2: "orange", 3: "red"}  # CV, CA, CT, MIX

fig = plt.figure(figsize=(10, 8))
ax = fig.add_subplot(111, projection="3d")

label_kwargs = dict(accel_thresh=4.0, turn_thresh=12.0, smooth=5)

for s in range(0, len(pos_u) - (W + H) + 1, stride):
    # Get regime for this span
    regime = label_regime(vel_u[s : s + W + H], dt, **label_kwargs)

    # Plot the window positions in 3D
    span = pos_u[s : s + W + H]
    ax.plot(
        span[:, 0],
        span[:, 1],
        span[:, 2],
        color=colors[regime],
        alpha=0.6,
        linewidth=2,
    )

# Legend
for code, name in {0: "CV", 1: "CA", 2: "CT", 3: "MIX"}.items():
    ax.plot([], [], [], color=colors[code], label=f"{code}: {name}")

ax.set_title("Regime Verification")
ax.legend()
plt.show()