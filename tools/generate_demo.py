"""Deterministic, redistributable synthetic inputs. No user maps are included."""

from pathlib import Path
import json
import sqlite3
import struct
import sys
import zlib
import numpy as np
import cv2
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import write_ply


def generate(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0, 48, 241)
    phase = t / 48 * 2 * np.pi
    xyz = np.column_stack(
        [4 * np.sin(phase), 3 * np.sin(phase) * np.cos(phase), 0.15 * np.sin(2 * phase)]
    )
    yaw = np.arctan2(np.gradient(xyz[:, 1]), np.gradient(xyz[:, 0]))
    rot = Rotation.from_euler("z", yaw[:, None])
    p = np.concatenate([rot.as_matrix(), xyz[:, :, None]], axis=2)
    np.savetxt(
        folder / "synthetic_trajectory.tum",
        np.column_stack([t, xyz, rot.as_quat()]),
        fmt="%.9f",
        header="SYNTHETIC DEMO - timestamp tx ty tz qx qy qz qw; seconds/metres",
    )
    np.savetxt(
        folder / "synthetic_poses.kitti",
        p.reshape(-1, 12),
        fmt="%.9f",
        header="SYNTHETIC DEMO - row-major 3x4 transforms; no timestamps",
    )
    np.savetxt(
        folder / "synthetic_trajectory.csv",
        np.column_stack([t, xyz, rot.as_quat()]),
        fmt="%.9f",
        delimiter=",",
        header="timestamp,x,y,z,qx,qy,qz,qw",
        comments="",
    )
    graph = ["# SYNTHETIC DEMO - SE2 graph, not a hardware experiment"]
    selected = np.arange(0, len(p), 8)
    for i in selected:
        graph.append(f"VERTEX_SE2 {i} {xyz[i, 0]:.9f} {xyz[i, 1]:.9f} {yaw[i]:.9f}")
    for a, b in zip(selected[:-1], selected[1:]):
        delta = rot[a].as_matrix().T @ (xyz[b] - xyz[a])
        dy = (yaw[b] - yaw[a] + np.pi) % (2 * np.pi) - np.pi
        graph.append(f"EDGE_SE2 {a} {b} {delta[0]:.9f} {delta[1]:.9f} {dy:.9f} 100 0 0 100 0 100")
    (folder / "synthetic_graph.g2o").write_text("\n".join(graph) + "\n", encoding="utf-8")
    rng = np.random.default_rng(42)
    points = []
    colors = []
    for axis, value, color in [
        (0, -7, [75, 150, 230]),
        (0, 7, [235, 150, 70]),
        (1, -6, [100, 190, 150]),
        (1, 6, [180, 130, 210]),
        (2, 0, [160, 175, 190]),
    ]:
        a = rng.uniform([-7, -6, 0], [7, 6, 3], size=(6000, 3))
        a[:, axis] = value
        points.append(a)
        colors.append(np.tile(color, (len(a), 1)))
    points = np.concatenate(points)
    colors = np.concatenate(colors).astype(np.uint8)
    write_ply(folder / "synthetic_room.ply", points, colors)
    with (folder / "synthetic_room.pcd").open("w", encoding="ascii") as stream:
        stream.write(
            "# SYNTHETIC DEMO\nVERSION .7\nFIELDS x y z r g b\nSIZE 4 4 4 1 1 1\nTYPE F F F U U U\nCOUNT 1 1 1 1 1 1\nWIDTH 30000\nHEIGHT 1\nPOINTS 30000\nDATA ascii\n"
        )
        np.savetxt(stream, np.column_stack([points, colors]), fmt=["%.5f"] * 3 + ["%d"] * 3)
    db = folder / "synthetic_rtabmap.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    try:
        con.executescript(
            "CREATE TABLE Node(id INTEGER PRIMARY KEY,map_id INTEGER,stamp REAL,pose BLOB); CREATE TABLE Data(id INTEGER PRIMARY KEY,image BLOB,depth BLOB,calibration BLOB); CREATE TABLE Statistics(id INTEGER PRIMARY KEY,stamp REAL,data BLOB); CREATE TABLE Admin(version TEXT);"
        )
        con.execute("INSERT INTO Admin VALUES(?)", ("synthetic compatible schema",))
        w, h = 160, 120
        fx = fy = 125.0
        cx = (w - 1) / 2
        cy = (h - 1) / 2
        k = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], "<f8")
        local = np.array([[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 0.8]], "<f4")
        calib = (
            struct.pack("<11i", 0, 23, 13, 0, w, h, 9, 0, 0, 0, 12) + k.tobytes() + local.tobytes()
        )
        u, v = np.meshgrid(np.arange(w), np.arange(h))
        rays = np.stack([(u - cx) / fx, (v - cy) / fy, np.ones_like(u)], axis=-1)
        for j, i in enumerate(range(0, len(t), 4), 1):
            pose = p[i].copy()
            pose[2, 3] = 0
            worldrays = rays @ local[:, :3].T @ pose[:, :3].T
            origin = pose[:, 3] + pose[:, :3] @ local[:, 3]
            depths = []
            for a, low, high in [(0, -7, 7), (1, -6, 6), (2, 0, 3)]:
                direction = worldrays[:, :, a]
                distance = np.divide(
                    np.where(direction > 0, high, low) - origin[a],
                    direction,
                    out=np.full_like(direction, np.inf),
                    where=np.abs(direction) > 1e-9,
                )
                distance[distance <= 0] = np.inf
                depths.append(distance)
            depth = np.minimum.reduce(depths)
            valid = np.isfinite(depth) & (depth < 20)
            rgb = np.zeros((h, w, 3), np.uint8)
            rgb[:, :, 0] = (45 + u * 1.1).clip(0, 255)
            rgb[:, :, 1] = (60 + v * 1.2).clip(0, 255)
            rgb[:, :, 2] = (120 + 50 * np.sin(u / 15 + j / 8)).clip(0, 255)
            con.execute(
                "INSERT INTO Node VALUES(?,?,?,?)",
                (j, 0, float(t[i]), pose.astype("<f4").tobytes()),
            )
            image = cv2.imencode(".jpg", rgb)[1].tobytes()
            d = cv2.imencode(
                ".png", np.where(valid, depth * 1000, 0).clip(0, 65535).astype(np.uint16)
            )[1].tobytes()
            con.execute("INSERT INTO Data VALUES(?,?,?,?)", (j, image, d, calib))
            stats = {
                "Timing/Total/ms": 24 + 8 * np.sin(j / 7),
                "Memory/Local_graph_size/": j,
                "Memory/Database_memory_used/MB": j * 0.1,
                "Loop/Visual_matches/": 120 + int(30 * np.cos(j / 9)),
                "Loop/Visual_inliers/": 90 + int(20 * np.cos(j / 9)),
                "RtabmapROS/TimeTotal/ms": 35 + 10 * np.sin(j / 8),
            }
            con.execute(
                "INSERT INTO Statistics VALUES(?,?,?)",
                (
                    j,
                    float(t[i]),
                    zlib.compress(";".join(f"{a}:{b}" for a, b in stats.items()).encode()),
                ),
            )
        con.commit()
    finally:
        con.close()
    (folder / "README.md").write_text(
        "# Synthetic demo inputs\n\nGenerated by `python tools/generate_demo.py`. These files describe an artificial room and trajectory, not a measured run. Coordinates are metres and timestamps are seconds. Safe to redistribute under the project MIT license.\n\nThe RTAB-Map database is a minimal compatible schema fixture, not a database produced by RTAB-Map. Use it to try the UI. Native RTAB-Map 0.23.13 RGB-D databases are tested separately and are not published.\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "folder": str(folder),
                "trajectory_poses": len(t),
                "pointcloud_vertices": len(points),
                "rtabmap_nodes": 61,
            }
        )
    )


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "examples")
