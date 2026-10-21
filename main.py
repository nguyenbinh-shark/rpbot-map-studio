"""RPBot Map Studio GUI and isolated analysis worker entry point."""

from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time
import traceback

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

VERSION = "2.0.0"
APP = "RPBot Map Studio"
from platform_support import state_directory

STATE = state_directory()


def main():
    parser = argparse.ArgumentParser(description=APP)
    parser.add_argument("database", nargs="?")
    parser.add_argument("--worker", metavar="JOB_JSON")
    parser.add_argument(
        "--analyze",
        metavar="FILE",
        help="Analyze a supported input without opening the desktop GUI",
    )
    parser.add_argument(
        "--no-cloud", action="store_true", help="Skip RGB-D reconstruction for RTAB-Map inputs"
    )
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--version", action="version", version=APP + " " + VERSION)
    parser.add_argument("--file")
    parser.add_argument("--output")
    parser.add_argument("--mode", choices=["full", "quick"], default="full")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--smoke-report")
    parser.add_argument("--quit-on-complete", action="store_true")
    parser.add_argument("--open-result")
    args = parser.parse_args()
    if args.analyze:
        from analysis import analyze, new_output, atomic_json

        output = new_output(
            args.output or Path.home() / "Downloads" / "RPBotMapStudio", args.analyze
        )
        job = dict(
            source=args.analyze,
            output=str(output),
            mode=args.mode,
            pointcloud=not args.no_cloud,
            zip=not args.no_zip,
        )
        atomic_json(output / "job.json", job)
        try:
            result = analyze(job)
            print(
                json.dumps(
                    dict(
                        output=str(output),
                        source_unchanged=result["source_unchanged"],
                        figures=result["figure_count"],
                    ),
                    ensure_ascii=False,
                )
            )
            return 0
        except Exception as exc:
            atomic_json(output / "progress.json", dict(state="failed", percent=0, message=str(exc)))
            print(str(exc), file=sys.stderr)
            return 1
    if args.worker:
        os.environ["MPLBACKEND"] = "Agg"
        os.environ["MPLCONFIGDIR"] = str(STATE / "matplotlib")
        STATE.mkdir(parents=True, exist_ok=True)
        job = json.loads(Path(args.worker).read_text(encoding="utf-8"))
        out = Path(job["output"])
        log = (out / "analysis.log").open("a", encoding="utf-8", buffering=1)
        previous_stdout, previous_stderr = sys.stdout, sys.stderr
        sys.stdout = log
        sys.stderr = log
        try:
            from analysis import analyze, Cancelled, atomic_json

            analyze(job)
            return 0
        except Exception as e:
            traceback.print_exc()
            cancelled = type(e).__name__ == "Cancelled"
            state = {
                "state": "cancelled" if cancelled else "failed",
                "percent": 0,
                "message": str(e) or type(e).__name__,
            }
            try:
                from analysis import atomic_json

                atomic_json(out / "progress.json", state)
            except Exception:
                (out / "progress.json").write_text(
                    json.dumps(state, ensure_ascii=False), encoding="utf-8"
                )
            return 2 if cancelled else 1
        finally:
            sys.stdout, sys.stderr = previous_stdout, previous_stderr
            log.close()
    from gui import Application

    return Application(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
