"""Strict readers for portable SLAM exports. Coordinates are never aligned implicitly."""

from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

MAX_ROWS = 10_000_000


@dataclass
class Dataset:
    kind: str
    poses: np.ndarray | None = None
    stamps: np.ndarray | None = None
    ids: np.ndarray | None = None
    points: np.ndarray | None = None
    colors: np.ndarray | None = None
    edges: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def detect(path):
    p = Path(path)
    if not p.is_file():
        raise ValueError("Không tìm thấy file dữ liệu đã chọn.")
    if p.stat().st_size == 0:
        raise ValueError("File rỗng.")
    with p.open("rb") as stream:
        head = stream.read(4096)
    if head.startswith(b"SQLite format 3\0"):
        return "rtabmap"
    if head.startswith(b"ply\n") or head.startswith(b"ply\r\n"):
        return "ply"
    suffix = p.suffix.lower()
    if suffix == ".pcd":
        return "pcd"
    if suffix == ".g2o":
        return "g2o"
    if suffix == ".csv":
        return "csv"
    if suffix in (".tum", ".txt", ".kitti"):
        for line in head.decode("utf-8-sig", errors="replace").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split()
            if len(fields) == 8:
                return "tum"
            if len(fields) == 12:
                return "kitti"
            break
    raise ValueError(
        "Định dạng chưa hỗ trợ. Chọn RTAB-Map DB, TUM, KITTI, CSV, g2o, PLY hoặc PCD. Native .pbstream/.osa và rosbag chưa được hỗ trợ; hãy xuất quỹ đạo TUM/KITTI hoặc point cloud trước."
    )


def _numeric(path, width):
    a = np.loadtxt(path, comments="#", ndmin=2, encoding="utf-8-sig")
    if a.shape[1] != width or not 0 < len(a) <= MAX_ROWS or not np.isfinite(a).all():
        raise ValueError(
            f"Expected finite numeric rows with {width} columns (maximum {MAX_ROWS:,})."
        )
    return a


def _quaternions(q):
    norm = np.linalg.norm(q, axis=1)
    if np.any(norm < 1e-10) or np.any(np.abs(norm - 1) > 0.01):
        raise ValueError("Quaternion must be unit length, ordered qx qy qz qw.")
    return Rotation.from_quat(q).as_matrix()


def _poses(xyz, rotations):
    rotations = np.asarray(rotations).reshape(-1, 3, 3)
    if len(rotations) != len(xyz):
        raise ValueError("Rotation and position counts do not match.")
    if not np.isfinite(xyz).all() or not np.isfinite(rotations).all():
        raise ValueError("Pose contains non-finite coordinates.")
    if not np.allclose(
        rotations.transpose(0, 2, 1) @ rotations, np.eye(3), atol=1e-3
    ) or not np.allclose(np.linalg.det(rotations), 1, atol=1e-3):
        raise ValueError("Pose rotation must be a proper orthonormal rotation matrix.")
    return np.concatenate([rotations, xyz[:, :, None]], axis=2)


def trajectory(path, kind):
    warnings = []
    if kind == "tum":
        a = _numeric(path, 8)
        stamps, xyz, r = a[:, 0], a[:, 1:4], _quaternions(a[:, 4:8])
    elif kind == "kitti":
        a = _numeric(path, 12).reshape(-1, 3, 4)
        stamps, xyz, r = None, a[:, :, 3], a[:, :, :3]
        warnings.append(
            "KITTI pose file has no timestamps. Sample index is used; speed and duration are unavailable. Coordinates are preserved in the input frame."
        )
    elif kind == "csv":
        df = pd.read_csv(path)
        if not 0 < len(df) <= MAX_ROWS:
            raise ValueError("CSV is empty or too large.")
        position = ["x_m", "y_m", "z_m"] if {"x_m", "y_m", "z_m"}.issubset(df) else ["x", "y", "z"]
        if not set(position).issubset(df):
            raise ValueError("CSV requires x,y,z or x_m,y_m,z_m columns, in metres.")
        xyz = df[position].to_numpy(float)
        stampkey = next((k for k in ["timestamp", "stamp_unix_s", "time_s"] if k in df), None)
        stamps = df[stampkey].to_numpy(float) if stampkey and df[stampkey].notna().any() else None
        if {"qx", "qy", "qz", "qw"}.issubset(df):
            r = _quaternions(df[["qx", "qy", "qz", "qw"]].to_numpy(float))
        elif {"roll_deg", "pitch_deg", "yaw_deg"}.issubset(df):
            r = Rotation.from_euler(
                "xyz", df[["roll_deg", "pitch_deg", "yaw_deg"]].to_numpy(float), degrees=True
            ).as_matrix()
        else:
            raise ValueError(
                "CSV requires qx,qy,qz,qw or roll_deg,pitch_deg,yaw_deg. Missing orientation is not inferred."
            )
    else:
        raise ValueError("Unknown trajectory format: " + kind)
    poses = _poses(xyz, r)
    if stamps is not None and (not np.isfinite(stamps).all() or np.any(np.diff(stamps) <= 0)):
        raise ValueError(
            "Timestamps must be finite and strictly increasing, in seconds. Duplicate/reversed times are not silently sorted."
        )
    return Dataset(
        kind.upper(), poses=poses, stamps=stamps, ids=np.arange(len(poses)), warnings=warnings
    )


def pose_graph(path):
    vertices, edges, dimension = {}, [], None
    for number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        f = line.split()
        if not f or f[0].startswith("#"):
            continue
        tag = f[0]
        if tag in ("VERTEX_SE2", "VERTEX_SE3:QUAT"):
            dim = 2 if tag == "VERTEX_SE2" else 3
            if dimension and dim != dimension:
                raise ValueError("Mixed SE2/SE3 graphs are unsupported.")
            dimension = dim
            if len(f) != (5 if dim == 2 else 9):
                raise ValueError(f"Invalid vertex at line {number}.")
            key = int(f[1])
            a = np.array(f[2:], float)
            if key in vertices:
                raise ValueError(f"Duplicate graph vertex {key}.")
            if dim == 2:
                xyz = np.array([[a[0], a[1], 0.0]])
                r = Rotation.from_euler("z", [a[2]]).as_matrix()
            else:
                xyz, r = a[None, :3], _quaternions(a[None, 3:7])
            vertices[key] = _poses(xyz, r)[0]
        elif tag in ("EDGE_SE2", "EDGE_SE3:QUAT"):
            dim = 2 if tag == "EDGE_SE2" else 3
            if len(f) != (12 if dim == 2 else 31):
                raise ValueError(f"Invalid edge at line {number}.")
            values = np.array(f[3:], float)
            if not np.isfinite(values).all():
                raise ValueError("Graph edge has non-finite values.")
            if dim == 2:
                tr = _poses(
                    np.array([[values[0], values[1], 0.0]]),
                    Rotation.from_euler("z", [values[2]]).as_matrix(),
                )[0]
            else:
                tr = _poses(values[None, :3], _quaternions(values[None, 3:7]))[0]
            edges.append((int(f[1]), int(f[2]), tr, dim))
        elif tag != "FIX":
            raise ValueError(
                f"Unsupported g2o record {tag} at line {number}. Export SE2 or SE3:QUAT first."
            )
    if not vertices:
        raise ValueError("Graph has no supported pose vertices.")
    if any(a not in vertices or b not in vertices or dim != dimension for a, b, _, dim in edges):
        raise ValueError("Edge references missing vertices or a different pose dimension.")
    ids = np.array(sorted(vertices))
    return Dataset(
        "g2o SE" + str(dimension),
        poses=np.stack([vertices[i] for i in ids]),
        ids=ids,
        edges=edges,
        warnings=[
            "g2o vertex IDs are ordered numerically for visualization. Graph IDs do not establish temporal order; path length and motion derivatives are unavailable. No timestamps or ground truth are inferred."
        ],
    )


def point_cloud(path, kind):
    if kind == "ply":
        p, c = _ply(path)
    else:
        p, c = _pcd(path)
    if not 0 < len(p) <= MAX_ROWS:
        raise ValueError("Point cloud is empty or exceeds 10 million vertices.")
    good = np.isfinite(p).all(axis=1)
    warnings = []
    if not good.all():
        warnings.append(f"{int((~good).sum())} non-finite points omitted.")
    p = p[good]
    if not len(p):
        raise ValueError("Point cloud has no finite vertices.")
    if c is None:
        c = np.tile(np.array([75, 155, 220], np.uint8), (len(p), 1))
        warnings.append(
            "Source has no RGB fields. A uniform display color is used; it is not measured color."
        )
    else:
        c = np.asarray(c)[good]
        if not np.isfinite(c).all() or (c < 0).any() or (c > 255).any():
            raise ValueError("RGB properties must be finite values from 0 to 255.")
        c = c.astype(np.uint8)
    return Dataset(
        kind.upper(),
        points=p,
        colors=c,
        warnings=warnings
        + [
            "Point coordinates are assumed to be metres. No trajectory, camera calibration or occupancy/free-space semantics are inferred from the cloud."
        ],
    )


def _ply(path):
    types = dict(
        char="i1",
        uchar="u1",
        short="i2",
        ushort="u2",
        int="i4",
        uint="u4",
        float="f4",
        double="f8",
        int8="i1",
        uint8="u1",
        int16="i2",
        uint16="u2",
        int32="i4",
        uint32="u4",
        float32="f4",
        float64="f8",
    )
    with Path(path).open("rb") as stream:
        if stream.readline(16).strip() != b"ply":
            raise ValueError("Invalid PLY signature.")
        elements = []
        encoding = None
        for _ in range(10000):
            line = stream.readline(8192).decode("ascii").strip()
            f = line.split()
            if not f or f[0] in ("comment", "obj_info"):
                continue
            if f[0] == "format":
                if len(f) != 3 or f[2] != "1.0":
                    raise ValueError("Unsupported PLY version.")
                encoding = f[1]
            elif f[0] == "element":
                if len(f) != 3:
                    raise ValueError("Invalid PLY element.")
                count = int(f[2])
                if not 0 <= count <= MAX_ROWS:
                    raise ValueError("PLY element count exceeds the limit.")
                elements.append([f[1], count, []])
            elif f[0] == "property":
                if not elements:
                    raise ValueError("PLY property without element.")
                elements[-1][2].append(f[1:])
            elif f[0] == "end_header":
                break
            else:
                raise ValueError("Unsupported PLY header record.")
        else:
            raise ValueError("PLY header exceeds the limit.")
        if encoding not in ("ascii", "binary_little_endian", "binary_big_endian"):
            raise ValueError("Unsupported PLY encoding.")
        for name, count, properties in elements:
            if any(len(p) != 2 or p[0] not in types for p in properties):
                raise ValueError(
                    "List-valued fields before/in PLY vertices are unsupported. Export a vertex cloud first."
                )
            names = [p[1] for p in properties]
            if not properties or len(properties) > 128 or len(set(names)) != len(names):
                raise ValueError("Invalid PLY scalar properties.")
            endian = ">" if encoding == "binary_big_endian" else "<"
            dtype = np.dtype([(p[1], endian + types[p[0]]) for p in properties])
            if count * dtype.itemsize > 1_000_000_000:
                raise ValueError("PLY element exceeds the memory limit.")
            if name != "vertex":
                if encoding == "ascii":
                    for _ in range(count):
                        if not stream.readline(32768):
                            raise ValueError("Truncated PLY element.")
                else:
                    stream.seek(count * dtype.itemsize, 1)
                continue
            if not count or not {"x", "y", "z"}.issubset(names):
                raise ValueError("PLY requires nonempty x/y/z vertex properties.")
            if encoding == "ascii":
                rows = np.loadtxt(stream, ndmin=2, max_rows=count)
                if rows.shape != (count, len(names)):
                    raise ValueError("PLY ASCII vertices do not match header.")
                value = lambda key: rows[:, names.index(key)]
            else:
                raw = stream.read(count * dtype.itemsize)
                if len(raw) != count * dtype.itemsize:
                    raise ValueError("Truncated PLY binary vertices.")
                rows = np.frombuffer(raw, dtype=dtype)
                value = lambda key: rows[key]
            p = np.column_stack([value(k) for k in "xyz"]).astype(float)
            c = (
                np.column_stack([value(k) for k in ("red", "green", "blue")])
                if {"red", "green", "blue"}.issubset(names)
                else None
            )
            return p, c
        raise ValueError("PLY has no vertex element.")


def _pcd(path):
    with Path(path).open("rb") as stream:
        header = {}
        for _ in range(100):
            line = stream.readline(8192).decode("ascii").strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            f = line.split()
            header[f[0].upper()] = f[1:]
            if f[0].upper() == "DATA":
                break
        else:
            raise ValueError("PCD header is missing DATA.")
        names = header.get("FIELDS", [])
        sizes = list(map(int, header.get("SIZE", [])))
        types = header.get("TYPE", [])
        counts = list(map(int, header.get("COUNT", ["1"] * len(names))))
        if (
            not names
            or len(set(names)) != len(names)
            or not len(names) == len(sizes) == len(types) == len(counts)
            or any(c != 1 for c in counts)
        ):
            raise ValueError("PCD requires unique scalar fields (COUNT 1).")
        count = int(header["POINTS"][0])
        if not 0 < count <= MAX_ROWS:
            raise ValueError("PCD vertex count exceeds the limit.")
        type_map = {
            ("F", 4): "<f4",
            ("F", 8): "<f8",
            ("U", 1): "u1",
            ("U", 2): "<u2",
            ("U", 4): "<u4",
            ("I", 1): "i1",
            ("I", 2): "<i2",
            ("I", 4): "<i4",
        }
        try:
            dtype = np.dtype([(n, type_map[t, s]) for n, t, s in zip(names, types, sizes)])
        except KeyError as exc:
            raise ValueError("Unsupported PCD field type.") from exc
        encoding = header["DATA"][0].lower()
        if encoding == "binary":
            raw = stream.read(count * dtype.itemsize + 1)
            if len(raw) != count * dtype.itemsize:
                raise ValueError("PCD binary payload size does not match POINTS.")
            arr = np.frombuffer(raw, dtype=dtype)
        elif encoding == "ascii":
            rows = np.loadtxt(stream, ndmin=2, max_rows=count + 1)
            if rows.shape != (count, len(names)):
                raise ValueError("PCD ASCII data does not match header.")
            arr = np.empty(count, dtype=dtype)
            for j, n in enumerate(names):
                arr[n] = rows[:, j]
        else:
            raise ValueError(
                "PCD binary_compressed is unsupported. Export ASCII or uncompressed binary PCD."
            )
        if not {"x", "y", "z"}.issubset(names):
            raise ValueError("PCD requires x/y/z fields.")
        p = np.column_stack([arr[k] for k in "xyz"]).astype(float)
        c = None
        if {"r", "g", "b"}.issubset(names):
            c = np.column_stack([arr[k] for k in ["r", "g", "b"]])
        elif "rgb" in names or "rgba" in names:
            packed = arr["rgb" if "rgb" in names else "rgba"].copy()
            if packed.dtype.itemsize != 4:
                raise ValueError("Packed RGB must be a 32-bit field.")
            bits = packed.view("<u4")
            c = np.column_stack([(bits >> 16) & 255, (bits >> 8) & 255, bits & 255])
        return p, c


def read(path, kind=None):
    kind = kind or detect(path)
    if kind in ("tum", "kitti", "csv"):
        return trajectory(path, kind)
    if kind == "g2o":
        return pose_graph(path)
    if kind in ("ply", "pcd"):
        return point_cloud(path, kind)
    raise ValueError("This input needs the RTAB-Map database reader.")
