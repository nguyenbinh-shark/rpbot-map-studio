"""Shared report pipeline for portable trajectories, pose graphs and point clouds."""

from pathlib import Path
from datetime import datetime, timezone
import zipfile
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation
from analysis import Progress, snapshot, digest, atomic_json, write_ply
from importers import detect, read


def analyze(job):
    out = Path(job["output"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    progress = Progress(out)
    progress(1, "Nhận diện định dạng và sao chép file…")
    kind = detect(job["source"])
    copied, evidence = snapshot(job["source"], out, progress)
    dataset = read(copied, kind)
    progress(10, "Chuẩn hóa dữ liệu; giữ nguyên hệ tọa độ nguồn…")
    csv = out / "csv"
    csv.mkdir()
    source = Path(job["source"]).resolve()
    n = len(dataset.poses) if dataset.poses is not None else 0
    report = dict(
        app="RPBot Map Studio",
        format_version=2,
        input_format=dataset.kind,
        database=str(source),
        database_name=source.name,
        database_bytes=source.stat().st_size,
        database_version="n/a",
        integrity="parsed",
        source_sha256=evidence["files"][source.name]["sha256"],
        nodes_total=n,
        nodes_valid=n,
        pose_source="Input coordinates and orientations, without alignment",
        statistics_records=0,
        metric_count=0,
        links=len(dataset.edges),
        non_neighbor_links=0,
        path_m=None,
        duration_s=None,
        endpoint_gap_m=None,
        rgb_nodes=0,
        depth_nodes=0,
        pointcloud_vertices=len(dataset.points) if dataset.points is not None else 0,
        map_source=None,
        ground_truth_nodes=0,
        warnings=dataset.warnings,
        figures=[],
        metrics=[],
        settings=dict(
            mode=job.get("mode", "full"),
            density=job.get("density", "standard"),
            pointcloud=job.get("pointcloud", True),
            zip=job.get("zip", True),
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    if dataset.poses is not None:
        p = dataset.poses
        xyz = p[:, :, 3]
        angles = Rotation.from_matrix(p[:, :, :3]).as_euler("xyz")
        yaw = np.unwrap(angles[:, 2])
        timed = dataset.stamps is not None and len(p) > 1
        stamps = dataset.stamps if dataset.stamps is not None else np.zeros(n)
        t = stamps - stamps[0] if timed else np.arange(n, dtype=float)
        dt = np.diff(stamps)
        ds = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
        speed = np.divide(ds, dt, out=np.full(len(ds), np.nan), where=(dt > 0) & timed)
        yawrate = np.divide(np.diff(yaw), dt, out=np.full(len(ds), np.nan), where=(dt > 0) & timed)
        nd = pd.DataFrame(
            dict(
                node_id=dataset.ids,
                stamp_unix_s=stamps if dataset.stamps is not None else np.full(n, np.nan),
                elapsed_s=t,
                x_m=xyz[:, 0],
                y_m=xyz[:, 1],
                z_m=xyz[:, 2],
                roll_deg=np.rad2deg(angles[:, 0]),
                pitch_deg=np.rad2deg(angles[:, 1]),
                yaw_deg=np.rad2deg(angles[:, 2]),
                yaw_unwrapped_deg=np.rad2deg(yaw),
                path_m=np.r_[0, np.cumsum(ds)],
                interval_s=np.r_[np.nan, dt] if timed else np.full(n, np.nan),
                step_m=np.r_[np.nan, ds],
                speed_mps=np.r_[np.nan, speed],
                yaw_rate_degps=np.r_[np.nan, np.rad2deg(yawrate)],
            )
        )
        if dataset.edges or kind == "g2o":
            nd = nd.drop(columns=["path_m", "interval_s", "step_m", "speed_mps", "yaw_rate_degps"])
            _graph_figures(out, dataset, report, progress)
        else:
            report["path_m"] = float(ds.sum())
            report["endpoint_gap_m"] = float(np.linalg.norm(xyz[-1] - xyz[0]))
            report["duration_s"] = float(np.ptp(stamps)) if timed else None
            from charts import generate

            empty = pd.DataFrame(columns=["record_id", "stamp_unix_s", "elapsed_s"])
            generate(
                out,
                dict(
                    nodes=nd,
                    stats=empty,
                    sensor=pd.DataFrame(),
                    edges=pd.DataFrame(),
                    keys=[],
                    time_valid=timed,
                    samples={},
                    map=None,
                    cloud=None,
                    lookup={},
                    information=[],
                ),
                report,
                progress,
            )
        nd.to_csv(csv / "nodes_trajectory.csv", index=False)
        q = Rotation.from_matrix(p[:, :, :3]).as_quat()
        if dataset.stamps is not None:
            np.savetxt(
                out / "trajectory.tum",
                np.column_stack([stamps, xyz, q]),
                fmt="%.10f",
                header="timestamp tx ty tz qx qy qz qw",
            )
        else:
            report["warnings"].append(
                "No timestamped TUM export is created because source timestamps are unavailable."
            )
        np.savetxt(
            out / "poses.kitti",
            p.reshape(-1, 12),
            fmt="%.10f",
            header="Row-major 3x4 transforms; input coordinate frame preserved",
        )
    else:
        write_ply(out / "map_3d_cloud.ply", dataset.points, dataset.colors)
        from viewer import write_viewer

        cloud = dict(points=dataset.points, colors=dataset.colors, vertices=len(dataset.points))
        write_viewer(out, cloud)
        _cloud_figures(out, cloud, report, progress)
        pd.DataFrame(
            dict(
                axis=list("XYZ"),
                min_m=dataset.points.min(axis=0),
                max_m=dataset.points.max(axis=0),
                mean_m=dataset.points.mean(axis=0),
            )
        ).to_csv(csv / "pointcloud_bounds.csv", index=False)
    report["warnings"].append(
        "No ground-truth evaluation or SLAM optimization is performed. Only data present in the input are analyzed."
    )
    progress(97, "Kiểm tra checksum và tạo báo cáo offline…")
    report["source_unchanged"] = source.is_file() and digest(source) == report["source_sha256"]
    if not report["source_unchanged"]:
        report["warnings"].append(
            "Source changed externally while analyzing; this report uses the initial snapshot."
        )
    from report import write_report

    write_report(out, report)
    if job.get("zip", True):
        with zipfile.ZipFile(
            out / "RPBotMapStudio_report.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=4
        ) as archive:
            for p in out.rglob("*"):
                progress.check()
                if (
                    p.is_file()
                    and not p.is_relative_to(out / "input_snapshot")
                    and p.name
                    not in (
                        "RPBotMapStudio_report.zip",
                        "cancel.requested",
                        "job.json",
                        "progress.json",
                        "worker.log",
                        "analysis.log",
                    )
                ):
                    archive.write(p, p.relative_to(out))
    atomic_json(
        out / "progress.json",
        dict(state="complete", percent=100, message="Phân tích hoàn tất.", report=report),
    )
    return report


def _save_figures(out, report, items, progress):
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    folder = out / "figures"
    folder.mkdir()
    with PdfPages(out / "SLAM_report.pdf") as pdf:
        for j, (fig, title, note) in enumerate(items):
            progress(45 + 45 * j / len(items), "Xuất hình: " + title)
            fig.suptitle(title, fontweight="bold")
            fig.text(0.02, 0.015, note, fontsize=8)
            fig.tight_layout(rect=[0, 0.05, 1, 0.95])
            slug = f"{j:02d}_analysis"
            fig.savefig(folder / (slug + ".png"), dpi=150)
            svg = report["settings"]["mode"] == "full"
            if svg:
                fig.savefig(folder / (slug + ".svg"))
            pdf.savefig(fig)
            plt.close(fig)
            report["figures"].append(
                dict(
                    title=title,
                    file="figures/" + slug + ".png",
                    svg="figures/" + slug + ".svg" if svg else None,
                    note=note,
                )
            )
    report["figure_count"] = len(items)
    report["pdf_pages"] = len(items)


def _cloud_figures(out, cloud, report, progress):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = cloud["points"]
    c = cloud["colors"]
    ix = np.random.default_rng(42).choice(len(p), min(90000, len(p)), replace=False)
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(*p[ix].T, c=c[ix] / 255, s=0.6, rasterized=True)
    ax.set(xlabel="X (m)", ylabel="Y (m)", zlabel="Z (m)")
    ax.set_box_aspect(np.maximum(np.ptp(p, axis=0), 1))
    ax.view_init(elev=45, azim=-55)
    items = [
        (
            fig,
            f"Imported point cloud: {len(p):,} vertices",
            "Input coordinates preserved; up to 90,000 points displayed. Full PLY retained.",
        )
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, (a, b) in zip(axes, [(0, 1), (0, 2), (1, 2)]):
        ax.scatter(p[ix, a], p[ix, b], c=c[ix] / 255, s=0.5, rasterized=True)
        ax.set_aspect("equal")
        ax.set(xlabel="XYZ"[a] + " (m)", ylabel="XYZ"[b] + " (m)")
    items.append(
        (
            fig,
            "Point-cloud orthographic projections",
            "No free-space or occupancy interpretation is inferred.",
        )
    )
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for j, ax in enumerate(axes):
        ax.hist(p[:, j], bins=60, color="#246bdf")
        ax.set(xlabel="XYZ"[j] + " (m)", ylabel="Vertices")
    items.append(
        (
            fig,
            "Point coordinate distributions",
            "Coordinates are assumed to be metres; origin is not a surveyed datum.",
        )
    )
    _save_figures(out, report, items, progress)


def _graph_figures(out, dataset, report, progress):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = dataset.poses
    lookup = dict(zip(dataset.ids, p))
    xyz = p[:, :, 3]
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.scatter(xyz[:, 0], xyz[:, 1], s=12, c="#246bdf")
    rows = []
    for a, b, tr, _ in dataset.edges:
        pa, pb = lookup[a], lookup[b]
        ax.plot([pa[0, 3], pb[0, 3]], [pa[1, 3], pb[1, 3]], lw=0.6, c="#91abc4")
        pt = pa[:, :3].T @ (pb[:, 3] - pa[:, 3])
        pr = pa[:, :3].T @ pb[:, :3]
        rows.append(
            dict(
                from_id=a,
                to_id=b,
                translation_residual_m=float(np.linalg.norm(pt - tr[:, 3])),
                rotation_residual_deg=float(
                    np.rad2deg(Rotation.from_matrix(tr[:, :3].T @ pr).magnitude())
                ),
            )
        )
    ax.set_aspect("equal")
    ax.set(xlabel="X (m)", ylabel="Y (m)")
    items = [
        (
            fig,
            f"Stored pose graph: {len(p)} vertices, {len(rows)} edges",
            "All edges have the same display style. Loop-closure labels and chronological order are not inferred.",
        )
    ]
    table = pd.DataFrame(
        rows, columns=["from_id", "to_id", "translation_residual_m", "rotation_residual_deg"]
    )
    table.to_csv(out / "csv/graph_links.csv", index=False)
    if rows:
        fig, axes = plt.subplots(2, 1, figsize=(12, 7))
        axes[0].plot(table.translation_residual_m)
        axes[0].set(ylabel="Internal translation residual (m)")
        axes[1].plot(table.rotation_residual_deg)
        axes[1].set(xlabel="Stored edge index", ylabel="Internal rotation residual (deg)")
        items.append(
            (
                fig,
                "Internal graph consistency",
                "Relative stored poses versus edge transforms; these are not ground-truth ATE/RPE. Information matrices are not interpreted.",
            )
        )
    _save_figures(out, report, items, progress)
