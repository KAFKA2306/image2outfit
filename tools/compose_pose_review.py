#!/usr/bin/env python3
"""Compose six required pose renders into one WebP review sheet."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

POSES = (
    ("neutral", "NEUTRAL"),
    ("arms-up", "ARMS UP"),
    ("arm-cross", "ARM CROSS"),
    ("crouch", "CROUCH"),
    ("sit", "SIT"),
    ("prone", "PRONE"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tile-size", type=int, default=640)
    args = parser.parse_args()

    source_dir = args.input_dir.resolve()
    output = args.output.resolve()
    tile = args.tile_size
    margin = max(16, tile // 32)
    label_height = max(40, tile // 14)
    canvas = Image.new(
        "RGB",
        (margin * 4 + tile * 3, margin * 3 + (tile + label_height) * 2),
        (235, 235, 235),
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for index, (name, label) in enumerate(POSES):
        path = source_dir / f"{name}.png"
        if not path.is_file():
            raise FileNotFoundError(path)
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
            panel = Image.new("RGB", (tile, tile), (235, 235, 235))
            panel.paste(image, ((tile - image.width) // 2, (tile - image.height) // 2))
        column = index % 3
        row = index // 3
        x = margin + column * (tile + margin)
        y = margin + row * (tile + label_height + margin)
        canvas.paste(panel, (x, y))
        box = draw.textbbox((0, 0), label, font=font)
        draw.text(
            (x + (tile - (box[2] - box[0])) // 2, y + tile + margin // 2),
            label,
            fill=(35, 35, 35),
            font=font,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="WEBP", quality=94, method=6)
    if output.stat().st_size < 50_000:
        raise RuntimeError(f"Pose-review sheet is unexpectedly small: {output}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
