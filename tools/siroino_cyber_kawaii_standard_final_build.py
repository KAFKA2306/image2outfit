#!/usr/bin/env python3
"""Final standard-body Cyber Kawaii build with corrected evidence labels."""
from __future__ import annotations

import siroino_cyber_kawaii_standard_build as standard

ORIGINAL_CONTACT_SHEET = standard.legacy.g.contact_sheet


def contact_sheet(images, output, *, order, title):
    if title == "CYBER KAWAII LAYERED SET / SIROINO _LARGE":
        title = "CYBER KAWAII LAYERED SET / SIROINO"
    return ORIGINAL_CONTACT_SHEET(images, output, order=order, title=title)


def main() -> int:
    standard.legacy.g.contact_sheet = contact_sheet
    return standard.main()


if __name__ == "__main__":
    raise SystemExit(main())
