from __future__ import annotations

import argparse
from pathlib import Path

from .models import analyze


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    analyze(args.image, args.output)


if __name__ == "__main__":
    main()
