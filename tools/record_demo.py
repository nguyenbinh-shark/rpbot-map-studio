"""Record only this application's window while executing a real synthetic analysis."""

from argparse import Namespace
from pathlib import Path
import ctypes
import json
import shutil
import subprocess
import sys
import time
from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui import Application

root = Path(__file__).resolve().parents[1]
media = root / "docs/media"
media.mkdir(parents=True, exist_ok=True)
source = root / "examples/synthetic_rtabmap.db"
args = Namespace(
    output=str(root / "validation-private/demo"),
    mode="full",
    file=str(source),
    database=None,
    open_result=None,
    smoke=False,
    smoke_report=None,
    quit_on_complete=False,
)
app = Application(args)
app.root.geometry("1300x860")
app.root.update()
platform_name = "windows" if sys.platform == "win32" else "linux"
frames = 0
started = time.monotonic()
done_at = None
stages = set()
encoder = None
capture_retries = 0


def capture():
    global frames, encoder, done_at, capture_retries
    try:
        app.root.update_idletasks()
        if sys.platform == "win32":
            user = ctypes.windll.user32
            user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user.GetAncestor.restype = ctypes.c_void_p
            try:
                image = ImageGrab.grab(window=user.GetAncestor(app.root.winfo_id(), 2))
            except OSError:
                capture_retries += 1
                if capture_retries > 30:
                    raise
                app.root.after(500, capture)
                return
        else:
            x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
            image = ImageGrab.grab(
                bbox=(x, y, x + app.root.winfo_width(), y + app.root.winfo_height())
            )
        image = image.convert("RGB")
        # Codec requires even dimensions. Cropping removes at most one border pixel.
        w, h = image.size
        image = image.crop((0, 0, w - w % 2, h - h % 2))
        if encoder is None:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise RuntimeError("ffmpeg is required to record the demo.")
            encoder = subprocess.Popen(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    "rgb24",
                    "-video_size",
                    f"{image.width}x{image.height}",
                    "-framerate",
                    "5",
                    "-i",
                    "-",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "25",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(media / "demo.mp4"),
                ],
                stdin=subprocess.PIPE,
            )
        encoder.stdin.write(image.tobytes())
        frames += 1
        elapsed = time.monotonic() - started
        if elapsed > 1 and "start" not in stages:
            image.save(media / "choose-input.png")
            stages.add("start")
        if elapsed > 3 and "analyze" not in stages:
            app.start()
            stages.add("analyze")
        if app.result and done_at is None:
            done_at = time.monotonic()
            image.save(media / (platform_name + "-overview.png"))
        if done_at:
            after = time.monotonic() - done_at
            if after > 3 and "charts" not in stages:
                app.tabs.select(1)
                keys = list(app.chart_rows)
                key = next((k for k in keys if "Trajectory" in app.chart_rows[k]["title"]), keys[0])
                app.tree.selection_set(key)
                app.chart_selected()
                stages.add("charts")
            if after > 5 and "chartshot" not in stages:
                image.save(media / (platform_name + "-charts.png"))
                stages.add("chartshot")
            if after > 7 and "filter" not in stages:
                app.filter.set("Timing")
                app.populate_charts()
                keys = list(app.chart_rows)
                if keys:
                    app.tree.selection_set(keys[-1])
                    app.chart_selected()
                stages.add("filter")
            if after > 10 and "metricshot" not in stages:
                image.save(media / (platform_name + "-metrics.png"))
                stages.add("metricshot")
            if after > 12:
                encoder.stdin.close()
                encoder.wait(timeout=30)
                if encoder.returncode:
                    raise RuntimeError("ffmpeg encoding failed.")
                (root / "validation-private/demo-recording.json").write_text(
                    json.dumps(
                        dict(
                            frames=frames,
                            fps=5,
                            wall_seconds=elapsed,
                            output=str(app.output),
                            synthetic=True,
                            window_only=True,
                        ),
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                app.close()
                return
        if elapsed > 240:
            raise RuntimeError("Demo analysis timeout.")
        app.root.after(200, capture)
    except Exception:
        if encoder:
            encoder.stdin.close()
            encoder.wait(timeout=15)
        app.close()
        raise


app.root.after(500, capture)
app.run()
