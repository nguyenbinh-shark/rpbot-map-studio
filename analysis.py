"""Offline RTAB-Map analysis. Only independent input snapshots are opened by SQLite."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import uuid
import zlib
import zipfile
import time
from contextlib import ExitStack, closing
import numpy as np
import pandas as pd
import cv2
from scipy.spatial.transform import Rotation
from codec import depth_image, matrix, calibration


class Cancelled(Exception):
    pass


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(min(0.015 * 2**attempt, 0.15))


class Progress:
    def __init__(self, output):
        self.output = Path(output)
        self.last = 0
        self.written = 0

    def check(self):
        if (self.output / "cancel.requested").exists():
            raise Cancelled("Đã hủy theo yêu cầu. File database gốc được giữ nguyên.")

    def __call__(self, percent, message, **extra):
        self.check()
        self.last = max(self.last, min(100, percent))
        now = time.monotonic()
        if now - self.written < 0.15:
            return
        self.written = now
        atomic_json(
            self.output / "progress.json",
            {"state": "running", "percent": self.last, "message": message, **extra},
        )


def inspect_file(path):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ValueError("Không tìm thấy file database đã chọn.")
    from importers import detect

    kind = detect(p)
    return {"path": str(p), "name": p.name, "bytes": p.stat().st_size, "format": kind}


def new_output(parent, source):
    p = Path(parent).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w .-]", "_", Path(source).stem)[:60].strip(" .") or "database"
    target = p / (
        stem + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    )
    target.mkdir(exist_ok=False)
    return target


def snapshot(source, output, progress):
    original = Path(source).resolve()
    inspect_file(original)
    companions = [
        p
        for suffix in ("", "-wal", "-shm", "-journal")
        if (p := Path(str(original) + suffix)).is_file()
    ]
    if shutil.disk_usage(output).free < sum(p.stat().st_size for p in companions) * 2 + 250_000_000:
        raise ValueError("Ổ chứa kết quả không đủ chỗ trống. Chọn thư mục trên ổ khác.")
    before = {
        p.name: {"bytes": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns, "sha256": digest(p)}
        for p in companions
    }
    folder = output / "input_snapshot"
    folder.mkdir()
    for p in companions:
        progress.check()
        target = folder / ("database.db" + p.name[len(original.name) :])
        shutil.copyfile(p, target)
        if digest(target) != before[p.name]["sha256"]:
            raise ValueError(
                "File nguồn thay đổi khi đang sao chép. Hãy tải lại bản database đã đóng sạch."
            )
    after = {
        p.name: {"bytes": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns, "sha256": digest(p)}
        for p in companions
    }
    if before != after:
        raise ValueError(
            "File nguồn đang được cập nhật. Hãy dùng bản database đã tải xong, rồi phân tích lại."
        )
    evidence = {
        "source_path": str(original),
        "files": before,
        "copied_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output / "source_manifest.json", evidence)
    return folder / "database.db", evidence


def columns(con, table):
    return {r[1] for r in con.execute('PRAGMA table_info("' + table + '")')}


def select_fields(available, names):
    return ",".join('"' + n + '"' if n in available else 'NULL AS "' + n + '"' for n in names)


def table_exists(con, name):
    return bool(
        con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    )


def bounded_string(blob):
    if not blob:
        return ""
    decoder = zlib.decompressobj()
    raw = decoder.decompress(blob, 8_000_001)
    if len(raw) > 8_000_000 or not decoder.eof:
        raise ValueError("Bản ghi Statistics nén quá lớn hoặc không đầy đủ.")
    return raw.decode("utf-8", errors="replace").strip("\x00")


def transform(points, pose):
    return points @ pose[:, :3].T + pose[:, 3]


def voxelize(points, colors, size):
    if not len(points):
        return points, colors
    keys = np.floor(points / size).astype(np.int32)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    count = np.bincount(inverse)
    P = np.column_stack(
        [np.bincount(inverse, weights=points[:, j]) / count for j in range(3)]
    ).astype(np.float32)
    C = (
        np.column_stack([np.bincount(inverse, weights=colors[:, j]) / count for j in range(3)])
        .clip(0, 255)
        .astype(np.uint8)
    )
    return P, C


def write_ply(path, points, colors):
    records = np.empty(
        len(points),
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
        ],
    )
    for j, k in enumerate(["x", "y", "z"]):
        records[k] = points[:, j]
    for j, k in enumerate(["red", "green", "blue"]):
        records[k] = colors[:, j]
    header = (
        "ply\nformat binary_little_endian 1.0\ncomment RPBot Map Studio; selected saved poses\nelement vertex "
        + str(len(points))
        + "\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    with Path(path).open("wb") as f:
        f.write(header.encode("ascii"))
        records.tofile(f)


def analyze(job):
    from importers import detect

    if detect(job["source"]) != "rtabmap":
        from portable_analysis import analyze as analyze_portable

        return analyze_portable(job)
    with ExitStack() as resources:
        return _analyze(job, resources)


def _analyze(job, resources):
    cv2.setNumThreads(4)
    output = Path(job["output"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    progress = Progress(output)
    warnings = []

    def warn(message):
        if message not in warnings:
            warnings.append(message)

    progress(1, "Kiểm tra file và tạo bản sao độc lập…")
    copied, evidence = snapshot(job["source"], output, progress)
    # Recovery of a hot SQLite journal can only affect the independent snapshot.
    con = resources.enter_context(closing(sqlite3.connect(copied, timeout=15)))
    con.row_factory = sqlite3.Row
    progress(3, "Kiểm tra tính toàn vẹn SQLite…")
    check = con.execute("PRAGMA integrity_check").fetchall()
    if [tuple(r) for r in check] != [("ok",)]:
        raise ValueError(
            "Database không đạt kiểm tra SQLite: " + str([tuple(r) for r in check[:4]])
        )
    con.execute("PRAGMA query_only=ON")
    if not table_exists(con, "Node") or not {"id", "pose"}.issubset(columns(con, "Node")):
        raise ValueError("SQLite hợp lệ nhưng không có cấu trúc Node/pose của RTAB-Map.")
    nc = columns(con, "Node")
    requested = ["id", "map_id", "weight", "stamp", "pose", "ground_truth_pose", "velocity", "gps"]
    raw = list(
        con.execute(
            "SELECT "
            + select_fields(nc, requested)
            + " FROM Node ORDER BY "
            + ("stamp,id" if "stamp" in nc else "id")
        )
    )
    if not raw:
        raise ValueError("Database chưa có node nào để phân tích.")
    nodes = []
    poses = []
    invalid = []
    for row in raw:
        b = row["pose"]
        if not b or len(b) != 48:
            invalid.append(row["id"])
            continue
        p = np.frombuffer(b, dtype="<f4").reshape(3, 4).astype(float)
        if not np.isfinite(p).all() or abs(np.linalg.det(p[:, :3]) - 1) > 0.05:
            invalid.append(row["id"])
            continue
        nodes.append(row)
        poses.append(p)
    if not nodes:
        raise ValueError("Không có pose hợp lệ. Database có thể chưa lưu được dữ liệu chuyển động.")
    if invalid:
        warn(f"{len(invalid)} node có pose rỗng/không hợp lệ, đã bỏ khỏi đồ thị chuyển động.")
    poses = np.stack(poses)
    ids = np.array([r["id"] for r in nodes])
    stamps = np.array([float(r["stamp"] or 0) for r in nodes])
    time_valid = bool(len(stamps) > 1 and np.isfinite(stamps).all() and np.ptp(stamps) > 0)
    t0 = float(stamps.min())
    t = stamps - t0 if time_valid else np.arange(len(nodes), dtype=float)
    if not time_valid:
        warn(
            "Thiếu timestamp hợp lệ; trục ngang chuyển động dùng số thứ tự node và không tính tốc độ theo giây."
        )
    admin = {}
    version = "unknown"
    pose_source = "Node poses (as stored)"
    if table_exists(con, "Admin"):
        row = con.execute("SELECT * FROM Admin LIMIT 1").fetchone()
        admin = dict(row) if row else {}
        version = str(admin.get("version", "unknown"))
        if admin.get("opt_ids") and admin.get("opt_poses"):
            try:
                optids = matrix(admin["opt_ids"]).ravel()
                opt = matrix(admin["opt_poses"]).reshape(-1, 3, 4)
                if len(optids) != len(opt):
                    raise ValueError("Số ID và số optimized pose không khớp.")
                mapping = {
                    int(i): p
                    for i, p in zip(optids, opt)
                    if np.isfinite(p).all() and abs(np.linalg.det(p[:, :3]) - 1) < 0.05
                }
                if all(int(i) in mapping for i in ids):
                    poses = np.stack([mapping[int(i)] for i in ids]).astype(float)
                    pose_source = "Saved optimized poses"
                else:
                    warn(
                        "Optimized poses không phủ hết node; dùng nhất quán toàn bộ Node pose để tránh trộn hệ tọa độ."
                    )
            except (ValueError, zlib.error, struct.error) as e:
                warn("Không đọc được optimized poses: " + str(e))
    xyz = poses[:, :, 3]
    angles = Rotation.from_matrix(poses[:, :, :3]).as_euler("xyz")
    yaw = np.unwrap(angles[:, 2])
    dt = np.diff(stamps)
    ds = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
    speed = np.divide(ds, dt, out=np.full(len(ds), np.nan), where=(dt > 0) & time_valid)
    yawrate = np.divide(np.diff(yaw), dt, out=np.full(len(ds), np.nan), where=(dt > 0) & time_valid)
    nd = pd.DataFrame(
        {
            "node_id": ids,
            "stamp_unix_s": stamps,
            "elapsed_s": t,
            "session_id": [r["map_id"] for r in nodes],
            "x_m": xyz[:, 0],
            "y_m": xyz[:, 1],
            "z_m": xyz[:, 2],
            "roll_deg": np.rad2deg(angles[:, 0]),
            "pitch_deg": np.rad2deg(angles[:, 1]),
            "yaw_deg": np.rad2deg(angles[:, 2]),
            "yaw_unwrapped_deg": np.rad2deg(yaw),
            "path_m": np.r_[0, np.cumsum(ds)],
            "interval_s": np.r_[np.nan, dt] if time_valid else np.full(len(t), np.nan),
            "step_m": np.r_[np.nan, ds],
            "speed_mps": np.r_[np.nan, speed],
            "yaw_rate_degps": np.r_[np.nan, np.rad2deg(yawrate)],
        }
    )
    csv = output / "csv"
    csv.mkdir()
    nd.to_csv(csv / "nodes_trajectory.csv", index=False)
    stats = []
    if table_exists(con, "Statistics") and {"id", "stamp", "data"}.issubset(
        columns(con, "Statistics")
    ):
        for r in con.execute("SELECT id,stamp,data FROM Statistics ORDER BY stamp,id"):
            progress.check()
            record = {
                "record_id": r["id"],
                "stamp_unix_s": r["stamp"],
                "elapsed_s": float(r["stamp"] or 0) - t0,
            }
            try:
                for item in bounded_string(r["data"]).split(";"):
                    if ":" not in item:
                        continue
                    k, v = item.rsplit(":", 1)
                    try:
                        value = float(v)
                        if np.isfinite(value):
                            record[k] = value
                    except ValueError:
                        pass
                stats.append(record)
            except (ValueError, zlib.error) as e:
                warn("Một số Statistics bị lỗi và được bỏ qua: " + str(e))
    st = pd.DataFrame(stats, columns=None if stats else ["record_id", "stamp_unix_s", "elapsed_s"])
    keys = sorted(set(st) - {"record_id", "stamp_unix_s", "elapsed_s"})
    st.to_csv(csv / "recorded_statistics.csv", index=False)
    if not keys:
        warn(
            "File không lưu chỉ số Statistics; vẫn phân tích được pose, map và dữ liệu ảnh còn có."
        )
    summary_stats = []
    for k in keys:
        a = st[k].dropna()
        summary_stats.append(
            {
                "metric": k,
                "samples": len(a),
                "min": a.min(),
                "mean": a.mean(),
                "median": a.median(),
                "p95": a.quantile(0.95),
                "max": a.max(),
                "constant": a.nunique() == 1,
            }
        )
    pd.DataFrame(
        summary_stats,
        columns=["metric", "samples", "min", "mean", "median", "p95", "max", "constant"],
    ).to_csv(csv / "statistics_summary.csv", index=False)
    parameters = {}
    if table_exists(con, "Info") and "parameters" in columns(con, "Info"):
        row = con.execute("SELECT parameters FROM Info LIMIT 1").fetchone()
        for item in (row[0] or "").split(";") if row else []:
            if ":" in item:
                k, v = item.split(":", 1)
                parameters[k] = v
    atomic_json(output / "parameters.json", parameters)

    def number(key, default):
        try:
            v = float(parameters.get(key, default))
            return v if np.isfinite(v) else default
        except (ValueError, TypeError):
            return default

    near = max(0, number("Grid/RangeMin", 0.3))
    far = number("Grid/RangeMax", 3.5)
    if far <= near:
        far = 4.0
    resolution = max(0.01, number("Grid/CellSize", 0.05))
    decimation = 2 if job.get("density") == "fine" else 4
    voxel = 0.025 if job.get("density") == "fine" else 0.04
    want_cloud = job.get("pointcloud", True)
    points = []
    colors = []
    point_count = 0
    cell_xy = {"free": [], "occupied": []}
    sensors = []
    samples = {}
    selected = set(ids[np.linspace(0, len(ids) - 1, min(12, len(ids)), dtype=int)])
    hist = np.zeros(180, dtype=np.int64)
    bins = np.linspace(0, 9, 181)
    grayhist = np.zeros(256, dtype=np.int64)
    data_cols = columns(con, "Data") if table_exists(con, "Data") else set()
    stored_map = None
    if admin.get("opt_map"):
        try:
            g = matrix(admin["opt_map"])
            res = float(admin.get("opt_map_resolution") or resolution)
            if g.ndim != 2 or res <= 0:
                raise ValueError("Thông số lưới bản đồ không hợp lệ.")
            pixels = np.full(g.shape, 205, np.uint8)
            pixels[(g >= 0) & (g < 50)] = 254
            pixels[g >= 50] = 0
            stored_map = {
                "pixels": np.flipud(pixels),
                "resolution": res,
                "origin": [
                    float(admin.get("opt_map_x_min") or 0),
                    float(admin.get("opt_map_y_min") or 0),
                ],
                "source": "Saved RTAB-Map occupancy grid",
            }
        except (ValueError, zlib.error, struct.error) as e:
            warn("Không đọc được occupancy map đã lưu: " + str(e))
    requested = [
        "image",
        "depth",
        "calibration",
        "ground_cells",
        "obstacle_cells",
        "empty_cells",
        "cell_size",
    ]
    if data_cols and "id" in data_cols:
        for j, (node, pose) in enumerate(zip(nodes, poses)):
            progress(6 + 34 * j / max(1, len(nodes)), f"Đọc ảnh và chiều sâu {j + 1}/{len(nodes)}…")
            r = con.execute(
                "SELECT " + select_fields(data_cols, requested) + " FROM Data WHERE id=?",
                (int(node["id"]),),
            ).fetchone()
            if r is None:
                continue
            rgb = None
            depth = None
            row = {
                "node_id": int(node["id"]),
                "elapsed_s": float(t[j]),
                "rgb_bytes": len(r["image"] or b""),
                "depth_bytes": len(r["depth"] or b""),
            }
            if r["image"]:
                try:
                    bgr = cv2.imdecode(np.frombuffer(r["image"], np.uint8), cv2.IMREAD_COLOR)
                    if bgr is None:
                        raise ValueError("không giải mã được JPEG/PNG")
                    if bgr.size > 48_000_000:
                        raise ValueError("ảnh quá lớn")
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                    row.update(
                        rgb_width=rgb.shape[1],
                        rgb_height=rgb.shape[0],
                        brightness_mean=float(gray.mean()),
                        brightness_std=float(gray.std()),
                        sharpness_proxy=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                        dark_pct=float((gray <= 5).mean() * 100),
                        bright_pct=float((gray >= 250).mean() * 100),
                    )
                    grayhist += np.bincount(gray.ravel(), minlength=256)
                except (ValueError, cv2.error) as e:
                    warn("Một số ảnh RGB không đọc được: " + str(e))
            if r["depth"]:
                try:
                    depth = depth_image(r["depth"])
                    valid = np.isfinite(depth) & (depth > 0)
                    d = depth[valid]
                    q = np.quantile(d, [0.05, 0.5, 0.95]) if len(d) else [np.nan] * 3
                    row.update(
                        valid_depth_pct=float(valid.mean() * 100),
                        in_range_depth_pct=float(
                            (valid & (depth >= near) & (depth <= far)).mean() * 100
                        ),
                        depth_p05_m=q[0],
                        depth_median_m=q[1],
                        depth_p95_m=q[2],
                        depth_max_m=float(d.max()) if len(d) else np.nan,
                        depth_width=depth.shape[1],
                        depth_height=depth.shape[0],
                        depth_compression_ratio=depth.size * 2 / len(r["depth"]),
                    )
                    hist += np.histogram(d, bins)[0]
                except (ValueError, cv2.error, struct.error) as e:
                    warn("Một số ảnh chiều sâu không đọc được: " + str(e))
            for col in ["ground_cells", "obstacle_cells", "empty_cells"]:
                b = r[col]
                row[col + "_bytes"] = len(b or b"")
                row[col + "_samples"] = 0
                if b:
                    try:
                        local = matrix(b)
                        row[col + "_samples"] = int(np.prod(local.shape[:2]))
                        if stored_map is None and local.ndim == 3 and local.shape[2] >= 3:
                            lp = local.reshape(-1, local.shape[2])[:, :3]
                            lp = lp[np.isfinite(lp).all(axis=1)]
                            xy = transform(lp, pose)[:, :2]
                            ix = np.unique(np.floor(xy / resolution).astype(np.int32), axis=0)
                            cell_xy["occupied" if col == "obstacle_cells" else "free"].append(ix)
                    except (ValueError, zlib.error, struct.error) as e:
                        warn("Một số local occupancy grid không đọc được: " + str(e))
            if int(node["id"]) in selected:
                samples[int(node["id"])] = (rgb, depth)
            if want_cloud and rgb is not None and depth is not None and r["calibration"]:
                try:
                    cam = calibration(r["calibration"])
                    h, w = depth.shape
                    sx = w / cam["width"]
                    sy = h / cam["height"]
                    if abs(sx - sy) > 1e-3:
                        raise ValueError("Tỷ lệ khung hình depth/calibration không khớp.")
                    if abs(rgb.shape[1] / rgb.shape[0] - w / h) > 0.01:
                        raise ValueError("Tỷ lệ khung hình RGB/depth không khớp.")
                    image = (
                        rgb
                        if rgb.shape[:2] == depth.shape
                        else cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA)
                    )
                    yy, xx = np.mgrid[0:h:decimation, 0:w:decimation]
                    zz = depth[::decimation, ::decimation]
                    valid = np.isfinite(zz) & (zz >= near) & (zz <= far) & (zz > 0)
                    if valid.any():
                        z = zz[valid]
                        local = np.column_stack(
                            (
                                (xx[valid] - cam["cx"] * sx) * z / (cam["fx"] * sx),
                                (yy[valid] - cam["cy"] * sy) * z / (cam["fy"] * sy),
                                z,
                            )
                        )
                        world = transform(transform(local, cam["local"]), pose).astype(np.float32)
                        color = image[::decimation, ::decimation][valid]
                        points.append(world)
                        colors.append(color)
                        point_count += len(world)
                        if point_count > 2_000_000:
                            pp, cc = voxelize(np.concatenate(points), np.concatenate(colors), voxel)
                            points = [pp]
                            colors = [cc]
                            point_count = len(pp)
                except (ValueError, cv2.error, struct.error) as e:
                    warn("Một số node không dựng được 3D: " + str(e))
            sensors.append(row)
    sensor = (
        pd.DataFrame(sensors)
        if sensors
        else pd.DataFrame(columns=["node_id", "elapsed_s", "rgb_bytes", "depth_bytes"])
    )
    sensor.to_csv(csv / "rgb_depth_and_storage.csv", index=False)
    pd.DataFrame({"bin_start_m": bins[:-1], "bin_end_m": bins[1:], "pixels": hist}).to_csv(
        csv / "depth_histogram.csv", index=False
    )
    pd.DataFrame({"gray_level": np.arange(256), "pixels": grayhist}).to_csv(
        csv / "brightness_histogram.csv", index=False
    )
    progress(41, "Dựng bản đồ và tổng hợp pose graph…")
    if stored_map is None and any(cell_xy.values()):
        arrays = {k: np.unique(np.concatenate(v), axis=0) for k, v in cell_xy.items() if v}
        all_xy = np.concatenate(list(arrays.values()))
        mn = all_xy.min(axis=0) - 2
        mx = all_xy.max(axis=0) + 2
        shape = mx - mn + 1
        if int(shape[0]) * int(shape[1]) <= 8_000_000:
            grid = np.full((int(shape[1]), int(shape[0])), 205, np.uint8)
            for k, val in [("free", 254), ("occupied", 0)]:
                if k in arrays:
                    a = arrays[k] - mn
                    grid[a[:, 1], a[:, 0]] = val
            stored_map = {
                "pixels": np.flipud(grid),
                "resolution": resolution,
                "origin": (mn * resolution).tolist(),
                "source": "Projection of stored local occupancy cells (not probabilistic RTAB-Map fusion)",
            }
            warn(
                "Map 2D được chiếu từ local grid đã lưu; chưa tái tạo thuật toán hợp nhất xác suất của RTAB-Map và chưa thử điều hướng thực tế."
            )
        else:
            warn("Lưới chiếu local grid vượt giới hạn 8 triệu ô; bỏ ảnh map 2D để bảo vệ bộ nhớ.")
    if stored_map:
        cv2.imencode(".pgm", stored_map["pixels"])[1].tofile(output / "map_2d.pgm")
        cv2.imencode(".png", stored_map["pixels"])[1].tofile(output / "map_2d.png")
        (output / "map_2d.yaml").write_text(
            f"image: map_2d.pgm\nmode: trinary\nresolution: {stored_map['resolution']}\norigin: [{stored_map['origin'][0]}, {stored_map['origin'][1]}, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n",
            encoding="utf-8",
        )
    cloud = None
    if points:
        progress(43, "Gộp và giảm mật độ đám mây điểm…")
        P, C = voxelize(np.concatenate(points), np.concatenate(colors), voxel)
        write_ply(output / "map_3d_cloud.ply", P, C)
        cloud = {
            "points": P,
            "colors": C,
            "vertices": len(P),
            "voxel_m": voxel,
            "decimation": decimation,
            "range_m": [near, far],
        }
        from viewer import write_viewer

        write_viewer(output, cloud)
    elif want_cloud:
        warn(
            "Không đủ RGB-D và calibration tương thích để dựng đám mây điểm màu; các đồ thị dữ liệu khác vẫn được xuất."
        )
    edges = []
    information = []
    lookup = {int(i): p for i, p in zip(ids, poses)}
    if table_exists(con, "Link"):
        lc = columns(con, "Link")
        if {"from_id", "to_id", "type", "transform"}.issubset(lc):
            for r in con.execute(
                "SELECT "
                + select_fields(lc, ["from_id", "to_id", "type", "transform", "information_matrix"])
                + " FROM Link"
            ):
                if (
                    r["from_id"] not in lookup
                    or r["to_id"] not in lookup
                    or not r["transform"]
                    or len(r["transform"]) != 48
                ):
                    continue
                tr = np.frombuffer(r["transform"], dtype="<f4").reshape(3, 4).astype(float)
                if not np.isfinite(tr).all() or abs(np.linalg.det(tr[:, :3]) - 1) > 0.05:
                    continue
                a, b = lookup[r["from_id"]], lookup[r["to_id"]]
                pr = a[:, :3].T @ b[:, :3]
                pt = a[:, :3].T @ (b[:, 3] - a[:, 3])
                e = {
                    "from_id": r["from_id"],
                    "to_id": r["to_id"],
                    "type": r["type"],
                    "translation_m": float(np.linalg.norm(tr[:, 3])),
                    "rotation_deg": float(np.rad2deg(Rotation.from_matrix(tr[:, :3]).magnitude())),
                    "internal_translation_residual_m": float(np.linalg.norm(pt - tr[:, 3])),
                    "internal_rotation_residual_deg": float(
                        np.rad2deg(Rotation.from_matrix(tr[:, :3].T @ pr).magnitude())
                    ),
                }
                if r["information_matrix"] and len(r["information_matrix"]) == 288:
                    inf = np.frombuffer(r["information_matrix"], dtype="<f8").reshape(6, 6)
                    if np.isfinite(inf).all():
                        information.append(inf)
                        if np.allclose(inf, inf.T) and np.linalg.eigvalsh(inf).min() > 0:
                            cov = np.linalg.inv(inf)
                            for k, v in zip(
                                ["x", "y", "z", "roll", "pitch", "yaw"],
                                np.sqrt(np.maximum(0, np.diag(cov))),
                            ):
                                e["sigma_" + k] = float(v)
                        else:
                            warn(
                                "Một số information matrix không xác định dương; không suy diễn thành covariance có độ chắc chắn bằng 0."
                            )
                edges.append(e)
    edge = (
        pd.DataFrame(edges)
        if edges
        else pd.DataFrame(
            columns=[
                "from_id",
                "to_id",
                "type",
                "translation_m",
                "rotation_deg",
                "internal_translation_residual_m",
                "internal_rotation_residual_deg",
            ]
        )
    )
    edge.to_csv(csv / "graph_links.csv", index=False)
    ground_truth = []
    for r in nodes:
        b = r["ground_truth_pose"]
        if b and len(b) == 48:
            a = np.frombuffer(b, dtype="<f4").reshape(3, 4)
            if np.isfinite(a).all() and abs(np.linalg.det(a[:, :3]) - 1) < 0.05:
                ground_truth.append(
                    {"node_id": r["id"], "x_m": a[0, 3], "y_m": a[1, 3], "z_m": a[2, 3]}
                )
    if ground_truth:
        pd.DataFrame(ground_truth).to_csv(csv / "ground_truth_as_stored.csv", index=False)
        warn(
            "Có ground truth trong file; xuất giá trị đã lưu. App chưa tự giả định hệ tọa độ/căn chỉnh để tính ATE/RPE."
        )
    else:
        warn("Không có ground truth hợp lệ; không xuất ATE/RPE hoặc RMSE vị trí so với thực tế.")
    report = {
        "app": "RPBot Map Studio",
        "format_version": 2,
        "input_format": "RTAB-Map",
        "database": str(Path(job["source"]).resolve()),
        "database_name": Path(job["source"]).name,
        "database_bytes": Path(job["source"]).stat().st_size,
        "database_version": version,
        "integrity": "ok",
        "source_sha256": evidence["files"][Path(job["source"]).name]["sha256"],
        "nodes_total": len(raw),
        "nodes_valid": len(nodes),
        "pose_source": pose_source,
        "statistics_records": len(st),
        "metric_count": len(keys),
        "links": len(edges),
        "non_neighbor_links": int((edge["type"] != 0).sum()) if len(edge) else 0,
        "path_m": float(ds.sum()),
        "duration_s": float(np.ptp(stamps)) if time_valid else None,
        "endpoint_gap_m": float(np.linalg.norm(xyz[-1] - xyz[0])),
        "rgb_nodes": int(sensor["brightness_mean"].notna().sum())
        if "brightness_mean" in sensor
        else 0,
        "depth_nodes": int(sensor["valid_depth_pct"].notna().sum())
        if "valid_depth_pct" in sensor
        else 0,
        "pointcloud_vertices": cloud["vertices"] if cloud else 0,
        "map_source": stored_map["source"] if stored_map else None,
        "ground_truth_nodes": len(ground_truth),
        "warnings": warnings,
        "figures": [],
        "metrics": [],
        "settings": {
            "mode": job.get("mode", "full"),
            "density": job.get("density", "standard"),
            "pointcloud": want_cloud,
            "near_m": near,
            "far_m": far,
            "zip": job.get("zip", True),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if "Memory/Distance_travelled/m" in st:
        a = st["Memory/Distance_travelled/m"].dropna()
        if len(a):
            report["reported_distance_m"] = float(a.iloc[-1])
            if abs(report["reported_distance_m"] - report["path_m"]) > max(
                0.5, report["path_m"] * 0.05
            ):
                warn(
                    "Quãng đường cộng từ pose khác bộ đếm Memory/Distance_travelled; xem cả hai, không coi bộ đếm là quãng đường thực đã được kiểm chứng."
                )
    con.close()
    data = {
        "nodes": nd,
        "poses": poses,
        "stats": st,
        "keys": keys,
        "sensor": sensor,
        "samples": samples,
        "edges": edge,
        "information": information,
        "cloud": cloud,
        "map": stored_map,
        "parameters": parameters,
        "depth_hist": hist,
        "depth_bins": bins,
        "gray_hist": grayhist,
        "time_valid": time_valid,
        "lookup": lookup,
    }
    from charts import generate

    generate(output, data, report, progress)
    progress(96, "Kiểm tra file nguồn và đóng gói báo cáo…")
    # A changed source is reported, never overwritten; the results refer to its snapshot.
    report["source_unchanged"] = all(
        p.is_file() and digest(p) == evidence["files"][p.name]["sha256"]
        for suffix in ("", "-wal", "-shm", "-journal")
        if (p := Path(str(Path(job["source"]).resolve()) + suffix)).name in evidence["files"]
    )
    if not report["source_unchanged"]:
        warn(
            "File nguồn thay đổi bởi ứng dụng khác trong lúc xử lý; báo cáo này dùng snapshot ở đầu phiên."
        )
    from report import write_report

    write_report(output, report)
    if job.get("zip", True):
        with zipfile.ZipFile(
            output / "RPBotMapStudio_report.zip",
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=4,
        ) as archive:
            for p in output.rglob("*"):
                progress.check()
                if (
                    p.is_file()
                    and not p.is_relative_to(output / "input_snapshot")
                    and p.name
                    not in (
                        "RPBotMapStudio_report.zip",
                        "cancel.requested",
                        "job.json",
                        "progress.json",
                        "worker.log",
                    )
                ):
                    archive.write(p, p.relative_to(output))
    atomic_json(
        output / "progress.json",
        {"state": "complete", "percent": 100, "message": "Phân tích hoàn tất.", "report": report},
    )
    return report
