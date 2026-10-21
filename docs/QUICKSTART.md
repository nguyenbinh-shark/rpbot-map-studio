# Quick start

[English overview](../README.md) · [Hướng dẫn tiếng Việt](README.vi.md)

## Windows

1. Download the Windows x86_64 ZIP from [Releases](https://github.com/nguyenbinh-shark/rpbot-map-studio/releases/latest).
2. Extract it to a writable folder. Open `RPBotMapStudio.exe`.
3. Click **Chọn file dữ liệu…** and select a supported input.
4. Select **Nhanh** (Quick) or **Đầy đủ** (Full), then **Phân tích dữ liệu**.
5. Browse **Tổng quan** (Overview), **Đồ thị** (Charts) and **Nhật ký** (Log).

No Python, ROS, WSL or compiler is required for the standalone download. Windows 10/11 x64 is the intended target; automated builds run on Windows Server 2022.

## Linux

Download the Linux x86_64 `.tar.gz`, then:

```bash
tar -xzf RPBotMapStudio-v2.0.0-linux-x86_64.tar.gz
chmod +x RPBotMapStudio
./RPBotMapStudio
```

Use a graphical desktop (X11 or an XWayland-enabled Wayland session). CI builds use Ubuntu 22.04 / glibc 2.35. Recent Debian/Ubuntu desktops with a compatible glibc are intended to work; every distribution is not individually validated. Headless analysis does not need a display:

```bash
./RPBotMapStudio --analyze examples/synthetic_trajectory.tum --output ./reports
```

Minimal desktop/server installations may need system libraries:

```bash
sudo apt-get install libx11-6 libxext6 libxrender1 libfontconfig1 libfreetype6 xdg-utils
```

The standalone package includes the Python, Tk and analysis libraries. Running directly from source additionally needs `python3-tk` and a compiled decoder; see [development](DEVELOPMENT.md).

## Try the demo

Download and extract `RPBotMapStudio-demo-data.zip` from the v2.0.0 release. Open `synthetic_rtabmap.db` for RGB-D analysis, `synthetic_trajectory.tum` for a trajectory, or `synthetic_room.ply` for a point cloud. All inputs are synthetic and redistributable.

![Completed analysis](media/windows-overview.png)

The left sidebar selects input, destination and settings. Four cards show available poses, recorded metrics, 3D vertices and exported figures. On the Charts tab, select a title to preview a figure; enter a metric name to filter the list.

![Chart browser](media/windows-charts.png)

## Output files

| File | Purpose |
|---|---|
| `index.html` | Offline gallery, warnings and links |
| `SLAM_report.pdf` | Multipage report |
| `manifest.json` | Available data, settings, counts and provenance |
| `source_manifest.json` | Input hashes and snapshot evidence |
| `csv/` | Extracted/derived tables |
| `figures/`, `metrics/` | PNG, and SVG in Full mode where applicable |
| `view_map_3d.html`, `map_3d_cloud.ply` | Interactive viewer/full point cloud when available |
| `map_2d.*` | Occupancy map when available in RTAB-Map data |
| `trajectory.tum`, `poses.kitti` | Portable trajectory exports when applicable |
| `RPBotMapStudio_report.zip` | Shareable report bundle; input snapshot excluded |
| `input_snapshot/` | Independent working copy of input; keep private |

Results default to `~/Downloads/RPBotMapStudio/` with a unique folder per run. Reports include input names, paths and extracted content; inspect a report before sharing it.

## Troubleshooting

- **Format not supported:** a SQLite container is not necessarily RTAB-Map. Native rosbag2, `.pbstream` and `.osa` require export first. Read [supported formats](FORMATS.md).
- **No 3D reconstruction:** a RTAB-Map input needs supported mono RGB-D calibration, valid depth and poses. Other available charts are still generated.
- **No speed plots:** timestamps are absent or unavailable. KITTI/g2o do not establish sample timing.
- **No map image:** trajectory and point-cloud files do not encode occupancy/free-space information.
- **Linux display error:** launch the GUI from a desktop session, or use `--analyze` on a server.
- **Permission denied:** place the Linux executable on a filesystem that permits execution, then `chmod +x` it.
- **Long analysis:** use Quick mode, standard density, or disable RTAB-Map RGB-D reconstruction. Cancel creates a partial result folder and preserves source data.

If a worker fails, inspect `progress.json`, `analysis.log` and `worker.log` in its output folder. Include the app version and a minimal reproducer in an issue.
