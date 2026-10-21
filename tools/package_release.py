"""Create platform archive and checksums; input maps are never included."""

from pathlib import Path
import argparse
import hashlib
import shutil
import sys
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from main import VERSION

parser = argparse.ArgumentParser()
parser.add_argument("--platform", required=True)
args = parser.parse_args()
release = root / "release"
release.mkdir(exist_ok=True)
suffix = ".exe" if args.platform.startswith("windows") else ""
binary = root / "dist" / ("RPBotMapStudio" + suffix)
assert binary.is_file(), binary
stem = f"RPBotMapStudio-v{VERSION}-{args.platform}"
files = [
    (binary, binary.name),
    (root / "LICENSE", "LICENSE"),
    (root / "README.md", "README.md"),
    (root / "docs/QUICKSTART.md", "QUICKSTART.md"),
]
files.extend(
    [
        (root / "THIRD_PARTY.md", "THIRD_PARTY.md"),
        (root / "assets/THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_NOTICES.txt"),
    ]
)
if suffix:
    target = release / (stem + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for p, name in files:
            archive.write(p, name)
else:
    target = release / (stem + ".tar.gz")
    with tarfile.open(target, "w:gz") as archive:
        for p, name in files:
            archive.add(p, arcname=name)
with target.open("rb") as stream:
    sha = hashlib.file_digest(stream, "sha256").hexdigest()
(release / (target.name + ".sha256")).write_text(sha + "  " + target.name + "\n", encoding="ascii")
print(target)
