import sys
from pathlib import Path
import sqlite3
import tempfile
import unittest
import struct
import zlib
from contextlib import closing
import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codec import depth_image, matrix, calibration
from analysis import inspect_file, snapshot, Progress, Cancelled, analyze, digest


def pose(x=0):
    a = np.eye(4, dtype="<f4")[:3]
    a[0, 3] = x
    return a.tobytes()


class CodecTests(unittest.TestCase):
    def test_valid_native_rvl_runs_and_signed_deltas(self):
        nibbles = []
        for value in [0, 2, 2000, 2, 2, 1, 3]:
            while True:
                rest = value >> 3
                nibbles.append((value & 7) | (8 if rest else 0))
                value = rest
                if not value:
                    break
        nibbles += [0] * ((-len(nibbles)) % 8)
        payload = b"".join(
            struct.pack("<I", sum(v << (28 - 4 * i) for i, v in enumerate(nibbles[j : j + 8])))
            for j in range(0, len(nibbles), 8)
        )
        actual = depth_image(b"DEPTHRVL" + struct.pack("<II", 5, 1) + payload)
        np.testing.assert_allclose(actual, [[1, 1.001, 0, 0, 0.999]], atol=1e-6)

    def test_png_depth_units(self):
        a = np.array([[0, 300, 3500], [1000, 2500, 65535]], np.uint16)
        np.testing.assert_allclose(
            depth_image(cv2.imencode(".png", a)[1].tobytes()), a.astype(float) / 1000, rtol=1e-6
        )

    def test_truncated_rvl_rejected_without_native_overread(self):
        with self.assertRaises(ValueError):
            depth_image(b"DEPTHRVL" + struct.pack("<II", 640, 480) + b"\0" * 4)

    def test_rvl_unbounded_dimension_rejected(self):
        with self.assertRaises(ValueError):
            depth_image(b"DEPTHRVL" + struct.pack("<II", 0xFFFFFFFF, 480) + b"\0" * 4)

    def test_bounded_matrix_metadata(self):
        a = np.array([[0, -1, 100]], dtype=np.int8)
        blob = zlib.compress(a.tobytes()) + struct.pack("<iii", 1, 3, 1)
        np.testing.assert_array_equal(matrix(blob), a)
        with self.assertRaises(ValueError):
            matrix(zlib.compress(b"x") + struct.pack("<iii", 1, 500_000_000, 5))

    def test_wrong_matrix_length_rejected(self):
        with self.assertRaises(ValueError):
            matrix(zlib.compress(b"bad") + struct.pack("<iii", 2, 3, 5))

    def test_stereo_calibration_not_guessed(self):
        with self.assertRaises(ValueError):
            calibration(struct.pack("<11i", 0, 23, 13, 1, 640, 480, 9, 5, 9, 12, 12))


class SnapshotTests(unittest.TestCase):
    def test_wrong_file_has_clear_error(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "not_a_database.db"
            p.write_bytes(b"This is not SQLite" * 20)
            with self.assertRaisesRegex(ValueError, "chưa hỗ trợ"):
                inspect_file(p)

    def test_quiescent_wal_snapshot_preserves_original_and_committed_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bản đồ có khoảng trắng.db"
            c = sqlite3.connect(source)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE saved(n)")
            c.execute("INSERT INTO saved VALUES(42)")
            c.commit()
            original = digest(source)
            out = root / "output"
            out.mkdir()
            copied, evidence = snapshot(source, out, Progress(out))
            with closing(sqlite3.connect(copied)) as backup:
                self.assertEqual(backup.execute("SELECT n FROM saved").fetchone()[0], 42)
            self.assertEqual(digest(source), original)
            self.assertIn(source.name + "-wal", evidence["files"])
            c.close()

    def test_cancel_before_reading_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cancel.requested").touch()
            with self.assertRaises(Cancelled):
                Progress(root)(1, "start")


class AnalysisTests(unittest.TestCase):
    def test_pose_only_file_produces_report_without_fabricating_sensor_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "pose_only.db"
            out = root / "out"
            out.mkdir()
            with closing(sqlite3.connect(source)) as c:
                c.execute("CREATE TABLE Node(id INTEGER PRIMARY KEY,stamp REAL,pose BLOB)")
                c.executemany(
                    "INSERT INTO Node VALUES(?,?,?)",
                    [(1, 1, pose()), (2, 2, pose(1)), (3, 3, pose(2))],
                )
                c.commit()
            original = digest(source)
            result = analyze(
                {
                    "source": str(source),
                    "output": str(out),
                    "mode": "quick",
                    "pointcloud": True,
                    "zip": False,
                }
            )
            self.assertEqual(result["nodes_valid"], 3)
            self.assertEqual(result["metric_count"], 0)
            self.assertEqual(result["pointcloud_vertices"], 0)
            self.assertEqual(result["path_m"], 2)
            self.assertEqual(digest(source), original)
            self.assertTrue((out / "index.html").exists())
            self.assertTrue((out / "SLAM_report.pdf").exists())
            self.assertNotIn("view_map_3d.html", (out / "index.html").read_text(encoding="utf-8"))

    def test_empty_database_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "empty.db"
            out = root / "out"
            out.mkdir()
            with closing(sqlite3.connect(source)) as c:
                c.execute("CREATE TABLE Node(id INTEGER,pose BLOB)")
                c.commit()
            with self.assertRaisesRegex(ValueError, "chưa có node"):
                analyze({"source": str(source), "output": str(out)})


if __name__ == "__main__":
    unittest.main()
