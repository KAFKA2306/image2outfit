#!/usr/bin/env python3
"""Compose five square preview renders into one marketplace-ready WebP sheet."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


VIEWS = (
    ("front", "FRONT"),
    ("back", "BACK"),
    ("left", "LEFT"),
    ("right", "RIGHT"),
    ("three-quarter", "3/4"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tile-size", type=int, default=720)
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output = args.output.resolve()
    tile = args.tile_size
    margin = max(16, tile // 32)
    label_height = max(36, tile // 15)
    canvas = Image.new(
        "RGB",
        (margin + len(VIEWS) * (tile + margin), tile + label_height + margin * 2),
        (235, 235, 235),
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for index, (name, label) in enumerate(VIEWS):
        source_path = input_dir / f"{name}.png"
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        with Image.open(source_path) as source:
            source = source.convert("RGB")
            source.thumbnail((tile, tile), Image.Resampling.LANCZOS)
            panel = Image.new("RGB", (tile, tile), (235, 235, 235))
            panel.paste(
                source,
                ((tile - source.width) // 2, (tile - source.height) // 2),
            )
        x = margin + index * (tile + margin)
        y = margin
        canvas.paste(panel, (x, y))
        box = draw.textbbox((0, 0), label, font=font)
        text_width = box[2] - box[0]
        draw.text(
            (x + (tile - text_width) // 2, y + tile + margin // 2),
            label,
            fill=(35, 35, 35),
            font=font,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="WEBP", quality=94, method=6)
    if output.stat().st_size < 50_000:
        raise RuntimeError(f"Composed preview is unexpectedly small: {output}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
