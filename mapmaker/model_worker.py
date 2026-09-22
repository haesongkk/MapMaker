"""Isolated model process for mutually incompatible model dependencies."""
from __future__ import annotations

import argparse
from pathlib import Path

from .common import read_json, write_json
from .models import hunyuan_mesh, ram_tags, sam_video


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="model", required=True)
    ram = sub.add_parser("ram")
    ram.add_argument("--images", type=Path, required=True)
    ram.add_argument("--checkpoint", type=Path, required=True)
    ram.add_argument("--output", type=Path, required=True)
    sam = sub.add_parser("sam")
    sam.add_argument("--video", type=Path, required=True)
    sam.add_argument("--labels", type=Path, required=True)
    sam.add_argument("--output", type=Path, required=True)
    sam.add_argument("--summary", type=Path, required=True)
    mesh = sub.add_parser("hunyuan")
    mesh.add_argument("--views", type=Path, required=True)
    mesh.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.model == "ram":
        write_json(args.output, ram_tags([Path(x) for x in read_json(args.images)], args.checkpoint))
    elif args.model == "sam":
        write_json(args.summary, sam_video(args.video, read_json(args.labels), args.output))
    elif args.model == "hunyuan":
        hunyuan_mesh({key: Path(path) for key, path in read_json(args.views).items()}, args.output)


if __name__ == "__main__":
    main()
