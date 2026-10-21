"""Desktop integration without a ROS or platform-specific Python dependency."""

from pathlib import Path
import os
import subprocess
import sys


def state_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RPBotMapStudio"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "rpbot-map-studio"


def open_path(path):
    path = Path(path).resolve()
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(
            ["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def library_name():
    return (
        "depth_codec.dll"
        if sys.platform == "win32"
        else ("libdepth_codec.dylib" if sys.platform == "darwin" else "libdepth_codec.so")
    )
