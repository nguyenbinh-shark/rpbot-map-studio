"""Availability-aware scientific charts. Each exported figure has explicit provenance."""

import re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize


def generate(output, data, report, progress):
    output = Path(output)
    figdir = output / "figures"
    metricdir = output / "metrics"
    figdir.mkdir()
    metricdir.mkdir()
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "figure.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "savefig.dpi": 150,
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
        }
    )
    nd = data["nodes"]
    st = data["stats"]
    sensor = data["sensor"]
    ed = data["edges"]
    keys = data["keys"]
    xyz = nd[["x_m", "y_m", "z_m"]].to_numpy()
    t = nd.elapsed_s.to_numpy()
    full = report["settings"]["mode"] == "full"
    xlabel = "Elapsed time (s)" if data["time_valid"] else "Retained node index"
    pdf = PdfPages(output / "SLAM_report.pdf")
    figures = []
    metricfiles = []

    def sub(rows=1, cols=1, size=None):
        return plt.subplots(rows, cols, figsize=size or (12, 3.4 * rows), squeeze=False)

    def save(fig, slug, title, note="", svg=True, layout=True):
        progress(46 + min(29, len(figures) * 0.9), "Xuất hình: " + title)
        fig.suptitle(title, fontsize=14, fontweight="bold", y=0.985)
        if note:
            fig.text(0.014, 0.012, note, fontsize=7, color="#555")
        if layout:
            fig.tight_layout(rect=[0, 0.035, 1, 0.95])
        fig.savefig(figdir / (slug + ".png"))
        if svg and full:
            fig.savefig(figdir / (slug + ".svg"))
        pdf.savefig(fig)
        plt.close(fig)
        figures.append(
            {
                "title": title,
                "file": "figures/" + slug + ".png",
                "svg": "figures/" + slug + ".svg" if svg and full else None,
                "note": note,
            }
        )

    def series(ax, df, names, unit="Recorded value"):
        names = [k for k in names if k in df and df[k].notna().any()]
        for k in names:
            ax.plot(df.elapsed_s, df[k], lw=0.9, label=k)
        ax.set(xlabel="Elapsed time (s)", ylabel=unit)
        ax.grid(alpha=0.2)
        if names:
            ax.legend(fontsize=6)
        return names

    def group(slug, title, names, unit="Recorded value", note=""):
        names = [k for k in names if k in st and st[k].notna().any()]
        if not names:
            return
        fig, axes = sub()
        series(axes[0, 0], st, names, unit)
        save(fig, slug, title, note)

    def hist(ax, values, label):
        a = np.asarray(values, float)
        a = a[np.isfinite(a)]
        if len(a):
            ax.hist(a, bins=min(40, max(5, int(np.sqrt(len(a))))))
        ax.set(xlabel=label, ylabel="Samples")

    fig, axes = sub(size=(12, 8))
    ax = axes[0, 0]
    ax.axis("off")
    details = (
        f"RPBot Map Studio | OFFLINE SLAM ANALYSIS\n\nInput: {report['database_name']}\nFormat: {report.get('input_format', 'RTAB-Map')} | version: {report['database_version']}\n"
        f"{report['nodes_valid']} valid poses / {report['nodes_total']} Node rows\n{report['statistics_records']} statistics records | {report['metric_count']} recorded metrics\n"
        f"Pose source: {report['pose_source']}\nRetained-pose path: {report['path_m']:.2f} m\n"
        f"{report['links']} links | {report['non_neighbor_links']} non-neighbor links\n"
        f"{report['rgb_nodes']} RGB frames | {report['depth_nodes']} decoded depth frames\n"
        f"{report['pointcloud_vertices']:,} reconstructed color points\n\n"
        "Speed / acceleration use finite differences between retained poses.\nNode/statistics rates are not raw camera FPS.\n"
        "Stored covariance and internal consistency residuals are not ground-truth errors.\n"
        "No new loop-closure detection or SLAM optimization is performed.\n"
        "Constant-zero counters do not establish perfect matching or physical accuracy.\n\n"
        f"Source SHA-256:\n{report['source_sha256']}"
    )
    ax.text(0.025, 0.96, details, va="top", fontsize=11, linespacing=1.6)
    save(fig, "00_overview", "Input overview and interpretation", svg=False)

    fig, axes = sub(1, 2, (12, 7))
    ax = axes[0, 0]
    sc = ax.scatter(xyz[:, 0], xyz[:, 1], c=t, s=10, cmap="viridis")
    ax.plot(xyz[:, 0], xyz[:, 1], lw=0.6, c="gray", alpha=0.6)
    ax.scatter(xyz[0, 0], xyz[0, 1], c="green", label="Start")
    ax.scatter(xyz[-1, 0], xyz[-1, 1], c="red", marker="x", label="End")
    ax.legend()
    fig.colorbar(sc, ax=ax, label=xlabel)
    ax.set_aspect("equal")
    ax.set(xlabel="X (m)", ylabel="Y (m)")
    ax = axes[0, 1]
    ax.plot(xyz[:, 0], xyz[:, 1], lw=0.8)
    step = max(1, len(nd) // 20)
    for j in range(0, len(nd), step):
        ax.annotate(str(int(nd.node_id.iloc[j])), xyz[j, :2], fontsize=6)
    yy = np.deg2rad(nd.yaw_deg.to_numpy())
    ax.quiver(
        xyz[::step, 0],
        xyz[::step, 1],
        np.cos(yy[::step]),
        np.sin(yy[::step]),
        angles="xy",
        scale_units="xy",
        scale=1.5,
        width=0.004,
        color="orange",
    )
    ax.set_aspect("equal")
    ax.set(xlabel="X (m)", ylabel="Y (m)", title="Node IDs and headings")
    save(fig, "01_trajectory_xy", "Trajectory, node IDs and heading")
    fig = plt.figure(figsize=(12, 7))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot(*xyz.T)
    ax.scatter(*xyz[::step].T, c=t[::step], s=10)
    ax.set(xlabel="X (m)", ylabel="Y (m)", zlabel="Z (m)")
    ax.set_box_aspect(np.maximum(np.ptp(xyz, axis=0), 1))
    save(
        fig,
        "02_trajectory_3d",
        "3D trajectory",
        "Planar stored poses do not independently measure height.",
    )
    fig, axes = sub(3, 1)
    for ax, k in zip(axes.flat, ["x_m", "y_m", "z_m"]):
        ax.plot(t, nd[k])
        ax.set(xlabel=xlabel, ylabel=k)
        ax.grid(alpha=0.2)
    save(fig, "03_position", "Position versus time")
    fig, axes = sub(2, 2)
    for ax, k in zip(axes.flat, ["roll_deg", "pitch_deg", "yaw_deg", "yaw_unwrapped_deg"]):
        ax.plot(t, nd[k])
        ax.set(xlabel=xlabel, ylabel=k)
        ax.grid(alpha=0.2)
    save(fig, "04_orientation", "Roll, pitch, wrapped yaw and continuous yaw")
    if data["time_valid"] and len(nd) > 1:
        fig, axes = sub(2, 2)
        axes[0, 0].plot(t, nd.speed_mps)
        axes[0, 0].set(xlabel=xlabel, ylabel="Translation speed (m/s)")
        hist(axes[0, 1], nd.speed_mps, "Speed (m/s)")
        axes[1, 0].plot(t, nd.yaw_rate_degps)
        axes[1, 0].set(xlabel=xlabel, ylabel="Yaw rate (deg/s)")
        hist(axes[1, 1], nd.yaw_rate_degps, "Yaw rate (deg/s)")
        save(
            fig,
            "05_motion",
            "Finite-difference speed and yaw rate",
            "Derived between retained poses; not direct encoder or IMU measurements.",
        )
        dt = np.diff(nd.stamp_unix_s)
        v = np.divide(
            np.diff(xyz, axis=0),
            dt[:, None],
            out=np.full((len(dt), 3), np.nan),
            where=dt[:, None] > 0,
        )
        fig, axes = sub(2, 1)
        for j, k in enumerate(["x", "y", "z"]):
            axes[0, 0].plot(t[1:], v[:, j], label=k)
        axes[0, 0].legend()
        axes[0, 0].set(xlabel=xlabel, ylabel="Map-frame velocity (m/s)")
        if len(v) > 1:
            adt = np.diff((t[1:] + t[:-1]) / 2)
            acc = np.divide(
                np.diff(v, axis=0),
                adt[:, None],
                out=np.full((len(adt), 3), np.nan),
                where=adt[:, None] > 0,
            )
            for j, k in enumerate(["x", "y", "z"]):
                axes[1, 0].plot(t[2:], acc[:, j], label=k)
            axes[1, 0].legend()
        axes[1, 0].set(xlabel=xlabel, ylabel="Derived acceleration (m/s2)")
        save(
            fig,
            "06_derivatives",
            "Velocity components and derived acceleration",
            "Numerical derivatives amplify pose noise and do not replace raw accelerometer data.",
        )
    fig, axes = sub(2, 2)
    axes[0, 0].plot(t, nd.path_m, label="Retained poses")
    if "Memory/Distance_travelled/m" in st:
        axes[0, 0].plot(
            st.elapsed_s, st["Memory/Distance_travelled/m"], label="Recorded RTAB-Map counter"
        )
    axes[0, 0].legend(fontsize=7)
    axes[0, 0].set(xlabel=xlabel, ylabel="Cumulative distance (m)")
    axes[0, 1].plot(t, np.linalg.norm(xyz - xyz[0], axis=1))
    axes[0, 1].set(xlabel=xlabel, ylabel="Displacement from start (m)")
    axes[1, 0].plot(t, nd.step_m)
    axes[1, 0].set(xlabel=xlabel, ylabel="Translation per retained interval (m)")
    axes[1, 1].scatter(nd.step_m, np.r_[np.nan, np.abs(np.diff(nd.yaw_unwrapped_deg))], s=10)
    axes[1, 1].set(xlabel="Translation (m)", ylabel="Absolute yaw increment (deg)")
    save(
        fig,
        "07_distance",
        "Path, displacement and motion increments",
        "Endpoint separation is not a ground-truth loop-closure error.",
    )
    if data["time_valid"]:
        fig, axes = sub(2, 2)
        axes[0, 0].plot(t, nd.interval_s)
        axes[0, 0].set(xlabel=xlabel, ylabel="Retained-node interval (s)")
        hist(axes[0, 1], nd.interval_s, "Retained-node interval (s)")
        if len(st) > 1:
            sdt = np.diff(st.stamp_unix_s.astype(float))
            axes[1, 0].plot(st.elapsed_s.to_numpy()[1:], sdt)
            axes[1, 0].set(xlabel="Elapsed time (s)", ylabel="Statistics interval (s)")
            valid = sdt > 0
            axes[1, 1].plot(
                st.elapsed_s.to_numpy()[1:][valid], 1 / sdt[valid], label="Statistics records"
            )
        axes[1, 1].set(xlabel="Elapsed time (s)", ylabel="Reciprocal statistics interval (Hz)")
        save(
            fig,
            "08_intervals",
            "Retention and statistics intervals",
            "These rates do not measure raw camera FPS. Retained-ID/time gaps alone do not prove camera-frame loss.",
        )
    fig, axes = sub(1, 2, (12, 5))
    axes[0, 0].step(t, np.arange(1, len(t) + 1), where="post")
    axes[0, 0].set(xlabel=xlabel, ylabel="Cumulative retained poses")
    axes[0, 1].scatter(t, nd.node_id, s=8, label="Retained Nodes")
    if len(st):
        axes[0, 1].scatter(st.elapsed_s, st.record_id, s=3, label="Statistics records")
    axes[0, 1].legend()
    axes[0, 1].set(xlabel="Elapsed time / node index", ylabel="ID")
    save(fig, "09_retention", "Retained nodes and Statistics record coverage")
    if len(ed):
        fig, axes = sub(1, 2, (12, 7))
        for e in ed.itertuples():
            a, b = data["lookup"][e.from_id][:, 3], data["lookup"][e.to_id][:, 3]
            axes[0, 0].plot(
                [a[0], b[0]], [a[1], b[1]], lw=0.7, c="#3579b1" if e.type == 0 else "red"
            )
        axes[0, 0].set_aspect("equal")
        axes[0, 0].set(xlabel="X (m)", ylabel="Y (m)")
        counts = ed.type.value_counts().sort_index()
        axes[0, 1].bar(counts.index.astype(str), counts)
        axes[0, 1].set(xlabel="Stored link type (0 = neighbor)", ylabel="Link count")
        save(fig, "10_pose_graph", "Pose graph and stored link types")
        fig, axes = sub(2, 2)
        hist(axes[0, 0], ed.translation_m, "Link translation magnitude (m)")
        hist(axes[0, 1], ed.rotation_deg, "Link rotation magnitude (deg)")
        axes[1, 0].plot(ed.internal_translation_residual_m * 1000)
        axes[1, 0].set(xlabel="Link index", ylabel="Internal translation residual (mm)")
        axes[1, 1].plot(ed.internal_rotation_residual_deg)
        axes[1, 1].set(xlabel="Link index", ylabel="Internal rotation residual (deg)")
        save(
            fig,
            "11_internal_residuals",
            "Link motion and internal pose/link consistency",
            "Relative selected poses compared with stored link transforms; these are not ATE/RPE.",
        )
        if data["information"]:
            fig, axes = sub(1, 2, (12, 5))
            im = axes[0, 0].imshow(np.median(data["information"], axis=0))
            fig.colorbar(im, ax=axes[0, 0], label="Information value")
            axes[0, 0].set_xticks(range(6), ["x", "y", "z", "roll", "pitch", "yaw"])
            axes[0, 0].set_yticks(range(6), ["x", "y", "z", "roll", "pitch", "yaw"])
            for k in ["x", "y", "z", "roll", "pitch", "yaw"]:
                if "sigma_" + k in ed:
                    axes[0, 1].plot(ed["sigma_" + k], label=k)
            axes[0, 1].legend()
            axes[0, 1].set(xlabel="Link index", ylabel="Stored covariance-derived std")
            save(
                fig,
                "12_information",
                "Median stored information and covariance-derived deviations",
                "Translation std uses m; rotation uses rad. These settings are not measured physical accuracy.",
            )

    group(
        "13_ros_timing",
        "ROS wrapper processing, map update and publication timing",
        [k for k in keys if k.startswith("RtabmapROS/Time")],
        "Recorded duration (ms)",
        "Timing stages may overlap and are not summed.",
    )
    if "RtabmapROS/TimeTotal/ms" in st:
        values = st["RtabmapROS/TimeTotal/ms"].dropna().to_numpy()
        if len(values):
            fig, axes = sub(1, 2, (12, 5))
            hist(axes[0, 0], values, "ROS TimeTotal (ms)")
            a = np.sort(values)
            axes[0, 1].plot(a, np.arange(1, len(a) + 1) / len(a))
            axes[0, 1].set(xlabel="ROS TimeTotal (ms)", ylabel="Empirical cumulative probability")
            for q in [0.5, 0.95, 0.99]:
                v = np.quantile(a, q)
                axes[0, 1].axvline(v, ls="--", lw=0.8, label=f"p{q * 100:g}: {v:.1f} ms")
            axes[0, 1].legend()
            save(
                fig, "14_latency_distribution", "Processing latency histogram, ECDF and percentiles"
            )
    group(
        "15_core_timing",
        "Core RTAB-Map timing",
        [
            k
            for k in [
                "Timing/Total/ms",
                "Timing/Memory_update/ms",
                "Timing/Memory_cleanup/ms",
                "Timing/Map_optimization/ms",
            ]
        ],
        "Recorded duration (ms)",
        "Stages can be nested; these curves are not additive CPU times.",
    )
    group(
        "16_memory_timing",
        "Memory-stage timing",
        [k for k in keys if k.startswith("TimingMem/")],
        "Recorded duration (ms)",
    )
    group(
        "17_memory_growth",
        "Memory counters, graph growth and retention",
        [
            "Memory/Database_memory_used/MB",
            "Memory/Local_graph_size/",
            "Memory/Working_memory_size/",
            "Memory/Short_time_memory_size/",
        ],
        "Recorded units in legend",
        "Database_memory_used is an RTAB-Map counter, not measured operating-system RAM usage.",
    )
    group(
        "18_loop_features",
        "Loop-closure and visual-feature counters",
        [
            "Loop/Accepted_hypothesis_id/",
            "Loop/Visual_inliers/",
            "Loop/Visual_matches/",
            "Keypoint/Current_frame/words",
            "Keypoint/Dictionary_size/words",
        ],
        "Recorded count / ID",
        "Constant-zero counters do not establish perfect matching or zero physical error.",
    )
    group(
        "19_uncertainty",
        "Recorded map-to-base uncertainty",
        ["Loop/MapToBase_lin_std/m", "Loop/MapToBase_lin_var/m2"],
        "Recorded units in legend",
        "Estimator counters, not ground-truth error measurements.",
    )
    if len(sensor):
        if "brightness_mean" in sensor:
            fig, axes = sub(2, 2)
            sx = sensor.elapsed_s
            axes[0, 0].plot(sx, sensor.brightness_mean)
            axes[0, 0].fill_between(
                sx,
                sensor.brightness_mean - sensor.brightness_std,
                sensor.brightness_mean + sensor.brightness_std,
                alpha=0.2,
            )
            axes[0, 0].set(xlabel=xlabel, ylabel="Grayscale mean +/- std (0-255)")
            axes[0, 1].plot(sx, sensor.sharpness_proxy)
            axes[0, 1].set(xlabel=xlabel, ylabel="Laplacian variance")
            axes[1, 0].plot(sx, sensor.dark_pct, label="Gray <= 5")
            axes[1, 0].plot(sx, sensor.bright_pct, label="Gray >= 250")
            axes[1, 0].legend()
            axes[1, 0].set(xlabel=xlabel, ylabel="Pixels (%)")
            axes[1, 1].plot(np.arange(256), data["gray_hist"])
            axes[1, 1].set(xlabel="Grayscale value", ylabel="Decoded RGB pixel count")
            save(
                fig,
                "20_rgb_quality",
                "RGB brightness, contrast, clipping and sharpness proxies",
                "Laplacian variance depends on scene texture as well as blur; no universal good/bad threshold is applied.",
            )
        if "valid_depth_pct" in sensor:
            fig, axes = sub(2, 2)
            axes[0, 0].plot(sensor.elapsed_s, sensor.valid_depth_pct, label="Positive finite depth")
            axes[0, 0].plot(
                sensor.elapsed_s, sensor.in_range_depth_pct, label="Within reconstruction range"
            )
            axes[0, 0].legend(fontsize=7)
            axes[0, 0].set(xlabel=xlabel, ylabel="All image pixels (%)")
            axes[0, 1].plot(sensor.elapsed_s, sensor.depth_median_m)
            axes[0, 1].fill_between(
                sensor.elapsed_s, sensor.depth_p05_m, sensor.depth_p95_m, alpha=0.2
            )
            axes[0, 1].set(xlabel=xlabel, ylabel="Positive depth p05/median/p95 (m)")
            bins = data["depth_bins"]
            axes[1, 0].bar((bins[:-1] + bins[1:]) / 2, data["depth_hist"], width=0.048)
            axes[1, 0].set(xlabel="Positive depth (m), histogram clipped at 9 m", ylabel="Pixels")
            if "brightness_mean" in sensor:
                axes[1, 1].scatter(
                    sensor.brightness_mean, sensor.valid_depth_pct, c=sensor.elapsed_s, s=10
                )
                axes[1, 1].set(xlabel="Mean RGB grayscale", ylabel="Positive depth pixels (%)")
            save(
                fig,
                "21_depth_quality",
                "Depth coverage, quantiles, distribution and RGB association",
                "Positive uint16 depth values are converted from mm to m. An association does not establish causation.",
            )
        fig, axes = sub(2, 2)
        for k in ["rgb_bytes", "depth_bytes"]:
            axes[0, 0].plot(sensor.elapsed_s, sensor[k] / 1024, label=k)
        axes[0, 0].legend()
        axes[0, 0].set(xlabel=xlabel, ylabel="Compressed data (KiB)")
        if "depth_compression_ratio" in sensor:
            axes[0, 1].plot(sensor.elapsed_s, sensor.depth_compression_ratio)
            axes[0, 1].set(xlabel=xlabel, ylabel="Raw uint16 depth bytes / stored bytes")
        for k in ["ground_cells", "obstacle_cells", "empty_cells"]:
            axes[1, 0].plot(sensor.elapsed_s, sensor[k + "_bytes"] / 1024, label=k)
            axes[1, 1].plot(sensor.elapsed_s, sensor[k + "_samples"], label=k)
        axes[1, 0].legend(fontsize=7)
        axes[1, 0].set(xlabel=xlabel, ylabel="Compressed local grid (KiB)")
        axes[1, 1].legend(fontsize=7)
        axes[1, 1].set(xlabel=xlabel, ylabel="Stored local-grid samples")
        save(
            fig,
            "22_storage",
            "Data size, compression and per-node occupancy samples",
            "Local-grid samples overlap between nodes; counts do not measure unique global voxels.",
        )
    for which, label, index in [("rgb", "RGB", 0), ("depth", "Depth", 1)]:
        available = [(i, im[index]) for i, im in data["samples"].items() if im[index] is not None]
        if not available:
            continue
        rows = int(np.ceil(len(available) / 4))
        fig, axes = sub(rows, 4, (14, rows * 3))
        last = None
        for ax, (i, image) in zip(axes.flat, available):
            if index:
                last = ax.imshow(
                    np.ma.masked_where(~np.isfinite(image) | (image <= 0), image),
                    cmap="turbo",
                    vmin=report["settings"]["near_m"],
                    vmax=report["settings"]["far_m"],
                )
            else:
                ax.imshow(image)
            ax.set_title(f"Node {i}", fontsize=9)
            ax.axis("off")
        for ax in list(axes.flat)[len(available) :]:
            ax.axis("off")
        if index:
            fig.subplots_adjust(
                left=0.025, right=0.9, bottom=0.055, top=0.9, hspace=0.22, wspace=0.08
            )
            cax = fig.add_axes([0.925, 0.18, 0.014, 0.62])
            fig.colorbar(last, cax=cax, label="Depth (m); invalid values masked", extend="both")
        save(
            fig,
            "23_" + which + "_samples",
            label + " examples across the selected database",
            svg=False,
            layout=not bool(index),
        )
    if data["map"]:
        m = data["map"]
        g = m["pixels"]
        res = m["resolution"]
        o = m["origin"]
        fig, axes = sub(1, 2, (12, 8))
        axes[0, 0].imshow(
            g,
            cmap="gray",
            vmin=0,
            vmax=255,
            extent=[o[0], o[0] + g.shape[1] * res, o[1], o[1] + g.shape[0] * res],
        )
        axes[0, 0].plot(xyz[:, 0], xyz[:, 1], lw=0.7, c="dodgerblue")
        axes[0, 0].set(xlabel="X (m)", ylabel="Y (m)")
        areas = np.array([(g == 0).sum(), (g == 254).sum(), (g == 205).sum()]) * res**2
        axes[0, 1].bar(["Occupied", "Free", "Unknown"], areas, color=["#333", "#6a8", "#bbb"])
        axes[0, 1].set(ylabel="Grid area (m2)")
        save(fig, "24_occupancy_map", "Occupancy grid, trajectory and cell-class area", m["source"])
    fig, axes = sub(1, 2, (12, 8))
    h = axes[0, 0].hexbin(xyz[:, 0], xyz[:, 1], gridsize=45, cmap="magma", mincnt=1)
    fig.colorbar(h, ax=axes[0, 0], label="Retained node count")
    axes[0, 0].set_aspect("equal")
    axes[0, 0].set(xlabel="X (m)", ylabel="Y (m)")
    axes[0, 1].hist(nd.yaw_deg, bins=36)
    axes[0, 1].set(xlabel="Stored heading (deg)", ylabel="Retained poses")
    save(fig, "25_spatial_sampling", "Spatial node density and heading distribution")
    valid = nd.speed_mps.to_numpy()[1:]
    segments = np.stack((xyz[:-1, :2], xyz[1:, :2]), axis=1) if len(xyz) > 1 else None
    if segments is not None and np.isfinite(valid).any():
        fig, axes = sub(1, 2, (12, 8))
        for ax, values, label, cmap in zip(
            axes.flat,
            [valid, np.abs(nd.yaw_rate_degps.to_numpy()[1:])],
            ["Speed (m/s)", "Absolute yaw rate (deg/s)"],
            ["viridis", "plasma"],
        ):
            good = np.isfinite(values)
            a = values[good]
            lc = LineCollection(
                segments[good], cmap=cmap, norm=Normalize(a.min(), max(a.max(), a.min() + 1e-9))
            )
            lc.set_array(a)
            lc.set_linewidth(2)
            ax.add_collection(lc)
            ax.autoscale()
            ax.set_aspect("equal")
            ax.set(xlabel="X (m)", ylabel="Y (m)")
            fig.colorbar(lc, ax=ax, label=label)
        save(
            fig,
            "26_spatial_motion",
            "Trajectory colored by finite-difference motion",
            "Interpolation between retained nodes can hide intervening motion.",
        )
    cloud = data["cloud"]
    if cloud:
        P = cloud["points"]
        C = cloud["colors"] / 255
        ix = np.random.default_rng(42).choice(len(P), min(90000, len(P)), replace=False)
        fig = plt.figure(figsize=(12, 8))
        ax = fig.add_subplot(111, projection="3d")
        ax.scatter(*P[ix].T, c=C[ix], s=0.4, depthshade=False, rasterized=True)
        ax.set(xlabel="X (m)", ylabel="Y (m)", zlabel="Z (m)")
        ax.set_box_aspect(np.maximum(np.ptp(P, axis=0), 1))
        ax.view_init(elev=48, azim=-55)
        save(
            fig,
            "27_cloud_3d",
            f"Reconstructed color point cloud ({len(P):,} points)",
            "Rendering samples at most 90,000 points. Full PLY is retained.",
            svg=False,
        )
        fig, axes = sub(1, 3, (16, 5))
        for ax, (i, j) in zip(axes.flat, [(0, 1), (0, 2), (1, 2)]):
            ax.scatter(P[ix, i], P[ix, j], c=C[ix], s=0.3, rasterized=True)
            ax.set_aspect("equal")
            ax.set(xlabel="XYZ"[i] + " (m)", ylabel="XYZ"[j] + " (m)")
        save(fig, "28_cloud_projections", "Point-cloud top and side projections", svg=False)
        fig, axes = sub(1, 2, (12, 5))
        hist(axes[0, 0], P[:, 2], "Point Z in stored map frame (m)")
        h = axes[0, 1].hexbin(P[:, 0], P[:, 1], gridsize=80, bins="log", cmap="inferno")
        fig.colorbar(h, ax=axes[0, 1], label="log10(points/bin)")
        axes[0, 1].set_aspect("equal")
        axes[0, 1].set(xlabel="X (m)", ylabel="Y (m)")
        save(
            fig,
            "29_cloud_distribution",
            "Point height distribution and XY density",
            "The map origin is not a surveyed floor datum; Z is not floor-relative object height.",
        )
    chosen = [
        k
        for k in keys
        if (
            k.startswith("RtabmapROS/Time")
            or k.startswith("TimingMem/")
            or k in ["Memory/Local_graph_size/", "Memory/Database_memory_used/MB"]
        )
        and st[k].nunique() > 1
    ][:12]
    if len(chosen) > 1:
        corr = st[chosen].corr(method="spearman")
        corr.to_csv(output / "csv" / "timing_correlations.csv")
        fig, axes = sub(size=(12, 10))
        ax = axes[0, 0]
        im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
        labels = [k.split("/")[1] for k in chosen]
        ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
        ax.set_yticks(range(len(labels)), labels)
        fig.colorbar(im, ax=ax, label="Spearman rank correlation")
        save(
            fig,
            "30_correlations",
            "Timing and graph-growth associations",
            "Correlation can reflect nested definitions or common growth over time; it does not establish causation.",
        )
    if {"Loop/MapToBase_x/m", "Loop/MapToBase_y/m"}.issubset(st):
        fig, axes = sub(1, 2, (12, 7))
        axes[0, 0].plot(
            st["Loop/MapToBase_x/m"], st["Loop/MapToBase_y/m"], label="Statistics poses"
        )
        axes[0, 0].plot(xyz[:, 0], xyz[:, 1], ls="--", label="Selected retained poses")
        axes[0, 0].legend(fontsize=7)
        axes[0, 0].set_aspect("equal")
        axes[0, 0].set(xlabel="X (m)", ylabel="Y (m)")
        series(axes[0, 1], st, ["Loop/MapToBase_yaw/deg"], "Yaw (deg)")
        save(
            fig,
            "31_statistics_poses",
            "Statistics-record poses versus retained database nodes",
            "Statistics can include processing cycles whose signatures were not retained as Node rows; no cross-frame alignment is inferred.",
        )
    if full:
        for j, k in enumerate(keys):
            progress(77 + 15 * j / max(1, len(keys)), f"Xuất đồ thị chỉ số {j + 1}/{len(keys)}…")
            a = st[k]
            fig, ax = plt.subplots(figsize=(9, 3.4))
            ax.plot(st.elapsed_s, a, lw=1)
            ax.set(xlabel="Elapsed time (s)", ylabel=k.split("/")[-1] or "Recorded value", title=k)
            ax.grid(alpha=0.2)
            constant = a.nunique(dropna=True) == 1
            footer = f"{a.notna().sum()} samples | min={a.min():.6g} | median={a.median():.6g} | p95={a.quantile(0.95):.6g} | max={a.max():.6g}"
            if constant:
                footer += " | CONSTANT (as stored; not accuracy evidence)"
            fig.text(0.02, 0.02, footer, fontsize=7)
            fig.tight_layout(rect=[0, 0.06, 1, 1])
            slug = f"{j + 1:03d}_" + re.sub("[^a-zA-Z0-9]+", "_", k).strip("_")
            fig.savefig(metricdir / (slug + ".png"))
            fig.savefig(metricdir / (slug + ".svg"))
            plt.close(fig)
            metricfiles.append(
                {
                    "title": k,
                    "file": "metrics/" + slug + ".png",
                    "svg": "metrics/" + slug + ".svg",
                    "constant": constant,
                }
            )
        for start in range(0, len(keys), 6):
            progress(93, "Đóng các trang thống kê vào PDF…")
            fig, axes = sub(3, 2, (12, 10))
            for ax, k in zip(axes.flat, keys[start : start + 6]):
                ax.plot(st.elapsed_s, st[k], lw=0.8)
                ax.set_title(k, fontsize=8)
                ax.set_xlabel("Elapsed time (s)", fontsize=7)
                ax.set_ylabel(k.split("/")[-1] or "Recorded value", fontsize=7)
                ax.tick_params(labelsize=7)
                ax.grid(alpha=0.2)
                if st[k].nunique() == 1:
                    ax.text(
                        0.98,
                        0.92,
                        "CONSTANT",
                        transform=ax.transAxes,
                        ha="right",
                        va="top",
                        fontsize=7,
                        color="#a55",
                    )
            for ax in list(axes.flat)[len(keys[start : start + 6]) :]:
                ax.axis("off")
            fig.suptitle(
                f"All recorded metrics: {start + 1}-{min(start + 6, len(keys))} of {len(keys)}",
                fontsize=13,
            )
            fig.tight_layout(rect=[0, 0.03, 1, 0.95])
            fig.text(
                0.015,
                0.01,
                "Constant/zero counters are shown as recorded; their values do not establish measured accuracy or successful detection.",
                fontsize=7,
            )
            pdf.savefig(fig)
            plt.close(fig)
    pdf.close()
    report["figures"] = figures
    report["metrics"] = metricfiles
    report["figure_count"] = len(figures) + len(metricfiles)
    report["pdf_pages"] = len(figures) + (int(np.ceil(len(keys) / 6)) if full else 0)
