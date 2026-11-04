#!/usr/bin/env python3
"""Draw the made-up sample scans in runner_scans/samples/input/ (needs Pillow, only when they change).

Every word on them is invented. The images are checked in, so packages and tests never need this script."""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "runner_scans" / "samples" / "input"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerifCondensed-Italic.ttf"
MARK = "MADE-UP SAMPLE, no real data"
PAGES = {
    "intake-form-sample-01": [("Intake form", "form"), ("Date: 2026-03-14", ""), ("Ref: SAMPLE-0101", ""),
                              ("Name: Sample Client One", ""), ("Needs: help with a housing form", ""),
                              ("Notes: prefers morning visits", ""), ("Pages: 1", "")],
    "intake-form-sample-02": [("Intake form", "form"), ("Date: 2026-03-1", "smudge"), ("Ref: SAMPLE-0102", ""),
                              ("Name: Sample Client Two", ""), ("Needs: a ride to the food bank", ""),
                              ("Notes: call after", "smudge"), ("Pages: 1", "")],
    "note-sample-03": [("Note", "form"), ("Ref: SAMPLE-0103", ""), ("Name: Sample Client Three", ""),
                       ("Notes: asked about the winter coat drive", ""), ("Initials: S.W.", "")],
    "intake-form-sample-04": [("Intake form", "form"), ("Date: 2026-04-02", ""), ("Ref: SAMPLE-0104", ""),
                              ("Name: Sample Client Four", ""), ("Pages: 2", "")],
}


def draw_page(name: str, lines: list[tuple[str, str]]) -> None:
    rng = random.Random(name)
    page = Image.new("L", (640, 420), 244)
    pen = ImageDraw.Draw(page)
    pen.text((24, 12), MARK, font=ImageFont.truetype(FONT, 15), fill=120)
    y = 44
    for text, mark in lines:
        x = 28 + rng.randint(-4, 6)
        for char in text:
            font = ImageFont.truetype(FONT, rng.randint(25, 28))
            pen.text((x, y + rng.randint(-2, 2)), char, font=font, fill=rng.randint(30, 70))
            x += pen.textlength(char, font=font) + rng.uniform(-0.4, 0.6)
        if mark == "smudge":
            for _ in range(70):
                sx, sy = x + rng.randint(0, 80), y + rng.randint(0, 28)
                pen.ellipse((sx, sy, sx + rng.randint(4, 14), sy + rng.randint(3, 9)), fill=rng.randint(70, 130))
        y += 50
    page.filter(ImageFilter.GaussianBlur(0.6)).quantize(16).save(OUT / f"{name}.png", optimize=True)


for page_name, page_lines in PAGES.items():
    draw_page(page_name, page_lines)
