"""Collect installed runtime dependency notices for the current platform build."""

from importlib import metadata
from pathlib import Path
import sys


def collect(target):
    packages = [
        "numpy",
        "pandas",
        "scipy",
        "matplotlib",
        "Pillow",
        "opencv-python-headless",
        "opencv-python",
        "contourpy",
        "cycler",
        "fonttools",
        "kiwisolver",
        "pyparsing",
        "python-dateutil",
        "six",
        "packaging",
        "pytz",
        "tzdata",
    ]
    parts = [
        "RPBot Map Studio - bundled runtime dependency notices\nProject source: MIT. Dependency licenses remain applicable.\n"
    ]
    for name in packages:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        parts.append(f"\n{'=' * 72}\n{name} {dist.version}\n")
        found = False
        for file in dist.files or []:
            path = Path(str(file))
            if path.name.upper().startswith(
                ("LICENSE", "COPYING", "NOTICE")
            ) and path.suffix.lower() not in (".py", ".pyc"):
                actual = Path(dist.locate_file(file))
                if actual.is_file():
                    parts.append(
                        f"\n--- {path.as_posix()} ---\n"
                        + actual.read_text(encoding="utf-8", errors="replace")
                    )
                    found = True
        if not found:
            parts.append(
                str(
                    dist.metadata.get("License-Expression")
                    or dist.metadata.get("License")
                    or "See upstream project for license terms."
                )
            )
    for path in [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix)
        / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/LICENSE.txt",
    ]:
        if path.is_file():
            parts.append(
                "\nPython runtime license\n" + path.read_text(encoding="utf-8", errors="replace")
            )
            break
    Path(target).write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    collect(sys.argv[1])
