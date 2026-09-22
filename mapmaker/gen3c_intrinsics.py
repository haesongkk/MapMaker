"""Estimate GEN3C's image intrinsics with its MoGe-1 model and frame size."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
from moge.model.v1 import MoGeModel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=121)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.video))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if width <= 0 or height <= 0:
        raise RuntimeError(f'Cannot read video size: {args.video}')
    rgb = cv2.cvtColor(cv2.imread(str(args.image)), cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (1280, 720))
    tensor = torch.from_numpy(rgb.copy()).permute(2, 0, 1).float().cuda() / 255.0
    model = MoGeModel.from_pretrained('Ruicheng/moge-vitl').cuda().eval()
    with torch.inference_mode():
        intrinsics = model.infer(tensor)['intrinsics'].float().cpu().numpy()
    k = intrinsics.copy()
    k[0] *= width
    k[1] *= height
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, np.repeat(k[None], args.frames, axis=0))


if __name__ == '__main__':
    main()
