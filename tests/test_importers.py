import struct
import sys
from pathlib import Path
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importers import trajectory, pose_graph, point_cloud, detect
from analysis import analyze, digest


class ImportTests(unittest.TestCase):
    def test_big_endian_ply_with_rgb(self):
        p = self.root / "a.ply"
        p.write_bytes(
            b"ply\nformat binary_big_endian 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
            + struct.pack(">fffBBB", 1, 2, 3, 10, 20, 30)
        )
        data = point_cloud(p, "ply")
        np.testing.assert_array_equal(data.points, [[1, 2, 3]])
        np.testing.assert_array_equal(data.colors, [[10, 20, 30]])

    def test_truncated_ply_is_rejected(self):
        p = self.root / "a.ply"
        p.write_bytes(
            b"ply\nformat binary_little_endian 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
            + struct.pack("<fff", 1, 2, 3)
        )
        with self.assertRaisesRegex(ValueError, "Truncated"):
            point_cloud(p, "ply")

    def test_ply_rgb_range_is_not_silently_wrapped(self):
        p = self.write(
            "a.ply",
            "ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n1 2 3 300 0 0\n",
        )
        with self.assertRaisesRegex(ValueError, "0 to 255"):
            point_cloud(p, "ply")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_tum_quaternion_and_timing(self):
        p = self.write("a.tum", "# test\n0 0 0 0 0 0 0 1\n2 3 4 0 0 0 0 1\n")
        data = trajectory(p, "tum")
        self.assertEqual(detect(p), "tum")
        np.testing.assert_array_equal(data.poses[1, :, 3], [3, 4, 0])
        self.assertEqual(data.stamps[1], 2)

    def test_duplicate_timestamps_rejected(self):
        p = self.write("a.tum", "1 0 0 0 0 0 0 1\n1 1 0 0 0 0 0 1\n")
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            trajectory(p, "tum")

    def test_zero_quaternion_rejected(self):
        p = self.write("a.tum", "0 0 0 0 0 0 0 0\n")
        with self.assertRaisesRegex(ValueError, "Quaternion"):
            trajectory(p, "tum")

    def test_kitti_does_not_invent_timestamps(self):
        p = self.write("a.txt", "1 0 0 2 0 1 0 3 0 0 1 4\n")
        data = trajectory(p, "kitti")
        self.assertIsNone(data.stamps)
        np.testing.assert_array_equal(data.poses[0, :, 3], [2, 3, 4])

    def test_non_rotation_matrix_rejected(self):
        p = self.write("a.txt", "2 0 0 0 0 1 0 0 0 0 1 0\n")
        with self.assertRaisesRegex(ValueError, "rotation"):
            trajectory(p, "kitti")

    def test_csv_requires_explicit_orientation(self):
        p = self.write("a.csv", "timestamp,x,y,z\n0,1,2,3\n")
        with self.assertRaisesRegex(ValueError, "orientation"):
            trajectory(p, "csv")

    def test_se2_graph_missing_vertex_rejected(self):
        p = self.write("a.g2o", "VERTEX_SE2 0 0 0 0\nEDGE_SE2 0 2 1 0 0 1 0 0 1 0 1\n")
        with self.assertRaisesRegex(ValueError, "missing"):
            pose_graph(p)

    def test_se3_graph_read_and_residual(self):
        p = self.write(
            "a.g2o",
            "VERTEX_SE3:QUAT 1 0 0 0 0 0 0 1\nVERTEX_SE3:QUAT 8 1 0 0 0 0 0 1\nEDGE_SE3:QUAT 1 8 1 0 0 0 0 0 1 "
            + " ".join(["1"] * 21)
            + "\n",
        )
        d = pose_graph(p)
        self.assertEqual(len(d.edges), 1)
        self.assertIsNone(d.stamps)

    def test_binary_pcd_packed_color(self):
        p = self.root / "a.pcd"
        p.write_bytes(
            b"VERSION .7\nFIELDS x y z rgb\nSIZE 4 4 4 4\nTYPE F F F U\nCOUNT 1 1 1 1\nPOINTS 1\nDATA binary\n"
            + struct.pack("<fffI", 1, 2, 3, 0x123456)
        )
        d = point_cloud(p, "pcd")
        np.testing.assert_array_equal(d.colors[0], [18, 52, 86])

    def test_compressed_pcd_has_actionable_error(self):
        p = self.write(
            "a.pcd", "FIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nPOINTS 1\nDATA binary_compressed\n"
        )
        with self.assertRaisesRegex(ValueError, "Export ASCII"):
            point_cloud(p, "pcd")

    def test_ply_nan_points_omitted_without_fake_poses(self):
        p = self.write(
            "a.ply",
            "ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\nend_header\n1 2 3\nnan 0 0\n",
        )
        d = point_cloud(p, "ply")
        self.assertEqual(len(d.points), 1)
        self.assertIsNone(d.poses)
        self.assertTrue(d.warnings)

    def test_tum_pipeline_preserves_source_and_exports(self):
        p = self.write("quỹ đạo.tum", "0 0 0 0 0 0 0 1\n2 3 4 0 0 0 0 1\n")
        sha = digest(p)
        out = self.root / "out"
        out.mkdir()
        r = analyze(dict(source=str(p), output=str(out), mode="quick", zip=True))
        self.assertEqual(r["path_m"], 5)
        self.assertEqual(r["duration_s"], 2)
        self.assertTrue(r["source_unchanged"])
        self.assertEqual(digest(p), sha)
        self.assertTrue((out / "trajectory.tum").exists())
        self.assertTrue((out / "SLAM_report.pdf").exists())

    def test_cloud_pipeline_has_no_fabricated_path(self):
        p = self.write(
            "a.ply",
            "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n1 2 3\n2 3 4\n3 4 5\n",
        )
        out = self.root / "out"
        out.mkdir()
        r = analyze(dict(source=str(p), output=str(out), mode="quick", zip=False))
        self.assertEqual(r["nodes_valid"], 0)
        self.assertIsNone(r["path_m"])
        self.assertEqual(r["pointcloud_vertices"], 3)
        self.assertNotIn("SQLite: OK", (out / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
