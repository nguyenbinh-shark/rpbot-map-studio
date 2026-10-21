"""Validate a generated report without assumptions about the user's dataset."""

from pathlib import Path
from html.parser import HTMLParser
import argparse
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image
from pypdf import PdfReader


def verify(folder):
    folder = Path(folder)
    r = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert r["source_unchanged"]
    source = Path(r["database"])
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == r["source_sha256"]
    figures = r["figures"] + r["metrics"]
    assert len(figures) == r["figure_count"]
    for figure in figures:
        with Image.open(folder / figure["file"]) as image:
            image.verify()
        if figure.get("svg"):
            ET.parse(folder / figure["svg"])
    assert len(PdfReader(folder / "SLAM_report.pdf").pages) == r["pdf_pages"]

    class References(HTMLParser):
        count = 0

        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if (
                    key in ("src", "href")
                    and value
                    and not value.startswith(("#", "http:", "https:"))
                ):
                    assert (folder / value).exists(), value
                    self.count += 1

    refs = References()
    refs.feed((folder / "index.html").read_text(encoding="utf-8"))
    if (folder / "RPBotMapStudio_report.zip").exists():
        with zipfile.ZipFile(folder / "RPBotMapStudio_report.zip") as archive:
            assert archive.testzip() is None
            assert not any(p.startswith("input_snapshot/") for p in archive.namelist())
    return dict(
        input_format=r.get("input_format", "RTAB-Map"),
        poses=r["nodes_valid"],
        points=r["pointcloud_vertices"],
        figures=r["figure_count"],
        pdf_pages=r["pdf_pages"],
        local_links=refs.count,
        source_unchanged=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument(
        "--latest", action="store_true", help="Validate the newest run under a parent output folder"
    )
    args = parser.parse_args()
    folder = Path(args.folder)
    if args.latest:
        folder = max(folder.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime).parent
    print(json.dumps(verify(folder), indent=2))
