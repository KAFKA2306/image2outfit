#!/usr/bin/env python3
"""Public entry point for the read-only image2outfit review console."""

from __future__ import annotations

import sys
from typing import Any, Iterable

from tools import review_console as base


_original_render_html = base.render_html


def render_html(data: dict[str, Any]) -> str:
    """Render the console with unique landmarks and stable product-list targeting."""
    document = _original_render_html(data)
    document = document.replace(
        '<section class="product-list" id="products">',
        '<section class="product-list" id="product-list">',
        1,
    )
    return document


base.render_html = render_html
build = base.build


def main(argv: Iterable[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
