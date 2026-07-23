import numpy as np
from dataset_utils import resample_uniform, derive_velocity, _moving_average
from build_dataset import load_segment

# Load test flight
t, pos = load_segment("1 truncated recordings\\liftoff_trunc_2026-07-22_11-25-37.csv")
dt = 0.02
_, pos_u = resample_uniform(t, pos, dt)
vel_u = derive_velocity(pos_u, dt)

# Decompose acceleration
accel = np.gradient(vel_u, dt, axis=0)
speed = np.linalg.norm(vel_u, axis=1)
tangent = vel_u / np.maximum(speed, 1e-6)[:, None]

a_tan = _moving_average(np.abs(np.sum(accel * tangent, axis=1)), k=11)
a_perp = accel - (np.sum(accel * tangent, axis=1))[:, None] * tangent
a_norm = _moving_average(np.linalg.norm(a_perp, axis=1), k=11)

print("Acceleration Distribution (m/s^2)")
print(f"Tangential (Linear) - Median: {np.median(a_tan):.2f} | 80th %ile: {np.percentile(a_tan, 80):.2f} | Max: {np.max(a_tan):.2f}")
print(f"Normal (Turning)    - Median: {np.median(a_norm):.2f} | 80th %ile: {np.percentile(a_norm, 80):.2f} | Max: {np.max(a_norm):.2f}")