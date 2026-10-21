# Development and releases

## Local environment

Use Python 3.11/3.12 in a virtual environment. Install `requirements-dev.txt`, then run `python build_tools.py`. The build helper creates the neutral product icon and compiles `native/depth_codec.c` into the platform's DLL/shared object. GCC is a build dependency only.

```bash
python -m unittest discover -s tests -v
python tools/generate_demo.py
python main.py --analyze examples/synthetic_trajectory.tum --output test-results
python -m PyInstaller --noconfirm RPBotMapStudio.spec
```

GUI smoke example:

```bash
# Run on a desktop, or prefix with xvfb-run -a on Linux CI
dist/RPBotMapStudio --smoke --file examples/synthetic_rtabmap.db --output test-results/gui --smoke-report test-results/gui.json --quit-on-complete
python tools/check_smoke.py test-results/gui.json
```

`check_smoke.py` checks completion and mapped-window state, input SHA-256, image/SVG readability, PDF page counts, local report links and ZIP CRC. It does not establish robot/navigation performance or manual usability on every desktop.

## Layout

| Module | Responsibility |
|---|---|
| `main.py` | GUI/CLI entry point and isolated worker |
| `gui.py` | Tk desktop workflow and report browser |
| `platform_support.py` | Platform paths, external file opening, library names |
| `analysis.py` | Input snapshots and RTAB-Map analysis |
| `codec.py`, `native/` | Bounded compressed matrix/depth decoding |
| `importers.py` | Portable trajectory/graph/cloud readers |
| `portable_analysis.py` | Portable-data reports and exports |
| `charts.py`, `report.py`, `viewer.py` | Scientific figures, HTML/PDF manifest and WebGL |
| `tools/` | Fixtures, demo recording, packaging and validation |

## Reader contract

`importers.Dataset` carries available data: optional 3×4 poses, timestamps/IDs, graph edges, points/colors and warnings. Keep detection independent of analysis. Preserve units and coordinate frames. Reject invalid rotations, references and ambiguous encodings. Do not fill missing timing, orientation, depth or ground truth with plausible-looking values.

Native state readers should be added only with an official format reference and small redistributable fixtures. Prefer portable exports when a native format is unstable or depends on an external SLAM runtime. Keep parsing away from the original input; only the independent snapshot may be opened by SQLite or codecs.

## Packaging

Build on the target OS; PyInstaller does not cross-compile. The spec explicitly includes Matplotlib Agg, PDF and SVG backends plus the native depth decoder and product icons. Windows produces a one-file GUI EXE; Linux produces a one-file ELF. Both launch isolated analysis workers using the same executable.

```bash
python tools/package_release.py --platform linux-x86_64
# or --platform windows-x86_64
```

Release archives contain the executable, license, README and quick start. Adjacent `.sha256` files verify each archive. Input maps, SQLite sidecars, source snapshots, logs, settings and private validation runs must not be committed or uploaded.

## CI and tagged releases

The workflow tests Windows Server 2022 and Ubuntu 22.04 with Python 3.11, builds native codecs, runs regression tests, generates synthetic inputs, builds the standalone apps and validates GUI/CLI runs. Build artifacts are available on each Actions run.

For a versioned release, update `VERSION` and docs, create a GitHub release for the intended tag, then push the tag. Successful matrix jobs upload their platform archives/checksums to that release. Upload the reviewed synthetic demo-data ZIP and MP4 separately. Do not publish a platform artifact as validated until its packaged smoke passes.

## Reproduce screenshots and demo

```bash
python tools/generate_demo.py
python tools/record_demo.py
```

Recording needs FFmpeg and a desktop; on Linux use a dedicated Xvfb display to avoid unrelated windows. On Windows the recorder captures the application's HWND only. The script runs a real worker, switches tabs and filters metrics. Screenshots and recording use generated sample inputs. The video has no audio and is sampled at 5 fps. Failed capture must fail rather than fall back to a whole-desktop recording.

The GUI text is currently Vietnamese and report/chart labels are English. A complete language-switching system is a future enhancement.
