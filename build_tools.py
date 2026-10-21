"""Generate product assets and compile the platform-native RVL decoder."""

from pathlib import Path
import shutil
import subprocess
import sys
from platform_support import library_name
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent
assets = root / "assets"
assets.mkdir(exist_ok=True)
from tools.collect_notices import collect

collect(assets / "THIRD_PARTY_NOTICES.txt")
gcc = shutil.which("gcc")
if not gcc:
    raise SystemExit("Build requires GCC. Released binaries need no compiler.")
flags = (
    ["-O3", "-shared", "-static-libgcc"] if sys.platform == "win32" else ["-O3", "-shared", "-fPIC"]
)
subprocess.run(
    [gcc, *flags, str(root / "native/depth_codec.c"), "-o", str(assets / library_name())],
    check=True,
)
im = Image.new("RGBA", (256, 256), "#14283e")
draw = ImageDraw.Draw(im)
draw.rounded_rectangle((24, 24, 232, 232), radius=35, outline="#396185", width=4)
route = [(55, 187), (100, 177), (99, 109), (162, 110), (188, 63)]
draw.line(route, fill="#57b4fa", width=10)
for x, y in route:
    draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill="#e8f4ff", outline="#246bdf", width=4)
draw.ellipse((177, 52, 199, 74), fill="#62dbad")
im.save(assets / "map_studio.png")
im.save(
    assets / "map_studio.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("Product icon and native depth codec generated: " + library_name())
