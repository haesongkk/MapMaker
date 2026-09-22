"""Export GEN3C's clockwise/counterclockwise center-facing camera path.

Mirrors create_spiral_trajectory in GEN3C/camera_utils.py with center_depth=1.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np


def trajectory(direction: str, distance: float, frames: int = 121) -> np.ndarray:
    if direction not in ("clockwise", "counterclockwise"):
        raise ValueError(direction)
    sign = 1 if direction == "clockwise" else -1
    target = np.array([0.0, 0.0, 1.0])
    world_to_camera = []
    for i in range(frames):
        theta = 2 * math.pi * i / (frames - 1)
        camera = np.array([distance * (math.cos(theta) - 1) * sign,
                           distance * math.sin(theta), 0.0])
        forward = target - camera
        forward /= np.linalg.norm(forward)
        right = np.cross([0.0, 1.0, 0.0], forward)
        right /= np.linalg.norm(right)
        up = np.cross(forward, right)
        matrix = np.eye(4)
        matrix[:3, :3] = np.stack((right, up, forward))
        matrix[:3, 3] = -camera  # GEN3C look_at_matrix convention.
        world_to_camera.append(matrix)
    return np.stack(world_to_camera)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", required=True, choices=("clockwise", "counterclockwise"))
    parser.add_argument("--distance", type=float, required=True)
    parser.add_argument("--frames", type=int, default=121)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, trajectory(args.direction, args.distance, args.frames))


if __name__ == "__main__":
    main()
