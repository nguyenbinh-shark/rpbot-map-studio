# Input formats and conventions

Detection uses a SQLite/PLY signature or a recognized suffix and row shape. It does not identify a SLAM algorithm from an arbitrary filename. Coordinate frames remain exactly as stored; no ENU/NED, camera/body or world-frame conversion is silently applied. Positions are metres, rotations follow the explicit format, and timestamps are seconds.

## RTAB-Map

Required: SQLite `Node` table with `id` and 48-byte float32 3×4 `pose`. `stamp` is optional. `Data`, `Link`, `Statistics`, `Info` and `Admin` are used when available. Node poses must be finite and have a valid rotation. Saved optimized poses are used only when they cover every selected node; otherwise all selected Node poses are used consistently.

Supported depth: bounded `DEPTHRVL`, uint16 millimetre PNG, RTAB-Map float32 depth PNG and inverse-depth wrapper. Reconstruction supports the compatible mono CameraModel serialization. Stereo/multicamera files can still supply pose/statistics analysis; their calibration is not guessed.

Saved `Admin.opt_map` is extracted when present. Otherwise stored ground/empty/obstacle cells can be projected into a conservative 2D image. This is not RTAB-Map's probabilistic map fusion.

Native 0.23.13 RGB-D databases have been validated locally. Other schema/calibration versions require compatible fields and encodings; an arbitrary RTAB-Map version is not guaranteed. A rosbag2 `.db3` is also SQLite but does not have this schema.

## TUM

Eight whitespace-separated values per line, optional `#` comments:

```text
# timestamp tx ty tz qx qy qz qw
0.0 0.0 0.0 0.0 0.0 0.0 0.0 1.0
0.2 0.1 0.0 0.0 0.0 0.0 0.0 1.0
```

Timestamps must be finite and strictly increasing. Quaternions use **xyzw**, must be nonzero and within 1% of unit length; valid quaternions are normalized by the rotation library. Duplicate timestamps, reversed samples and non-finite values are rejected. A `.tum` or eight-column `.txt` is recognized.

Reference: [TUM RGB-D file formats](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/file_formats).

## KITTI

Twelve whitespace-separated values encode each row-major 3×4 transform:

```text
1 0 0 0   0 1 0 0   0 0 1 0
1 0 0 1   0 1 0 0   0 0 1 0
```

Recognized as `.kitti` or twelve-column `.txt`. Rotations must be proper orthonormal matrices. The coordinate frame is preserved, including camera-frame axes if that is what was exported. There are no timestamps in this format, so duration, speed and acceleration are omitted. The app does not assume the KITTI benchmark's nominal sampling interval for arbitrary exports.

Reference: [KITTI odometry benchmark and development kit](https://www.cvlibs.net/datasets/kitti/eval_odometry.php).

## CSV

Required position columns: `x,y,z` **or** `x_m,y_m,z_m`.

Required orientation: `qx,qy,qz,qw` **or** `roll_deg,pitch_deg,yaw_deg` (extrinsic rotations about x, y, z, as interpreted by SciPy's lowercase `xyz`; see note below).

Optional timestamp column, in priority order: `timestamp`, `stamp_unix_s`, `time_s`. A column of entirely empty values is treated as absent. Partially missing, non-finite or non-increasing timestamps are rejected. Additional columns are ignored; they are not promoted to SLAM Statistics automatically.

```csv
timestamp,x,y,z,qx,qy,qz,qw
0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.0
0.2,0.1,0.0,0.0,0.0,0.0,0.0,1.0
```

Euler convention: `Rotation.from_euler('xyz', ..., degrees=True)` from SciPy uses **extrinsic** rotations. Input columns should use this convention. Prefer explicit quaternions when exchanging trajectories between tools.

## g2o

Supported records: `VERTEX_SE2`, `EDGE_SE2`, `VERTEX_SE3:QUAT`, `EDGE_SE3:QUAT`, and ignored `FIX` annotations. A graph must use one pose dimension, unique vertex IDs and valid edge endpoints. Information entries are parsed for record validation but are not used for covariance inference or optimization. Other vertex/edge types are rejected explicitly.

IDs are sorted numerically to export vertices; IDs do not establish chronological order. No cumulative path length, velocity, inferred neighbor/loop classification or ground-truth error is produced. Internal residuals compare relative vertex transforms against stored edge transforms.

Reference: [g2o official implementation](https://github.com/RainerKuemmerle/g2o).

## PLY / PCD

PLY accepts ASCII/little-endian/big-endian binary vertex data with scalar `x,y,z`; optional `red,green,blue` must lie in 0–255. Vertex list properties and list-valued elements before the vertices are unsupported. Mesh faces after the vertices are ignored. PCD supports ASCII and little-endian uncompressed binary with unique scalar `COUNT 1` fields, `x,y,z`, and optional separate `r,g,b` or 32-bit packed `rgb`/`rgba`. `binary_compressed` PCD must be exported as ASCII/uncompressed binary first.

Non-finite points are omitted and counted. Missing color gets a clearly disclosed uniform display color. No camera calibration, time ordering, occupancy/free-space class or trajectory is inferred from point vertices. The input is limited to 10 million vertices; plotted views sample at most 90,000 and the WebGL display at most 500,000, while the exported PLY keeps all finite input points.

References: [PLY format](https://paulbourke.net/dataformats/ply/), [PCL PCD specification](https://pointclouds.org/documentation/tutorials/pcd_file_format.html).

## Unsupported native state

Cartographer `.pbstream`, ORB-SLAM `.osa`, ROS1 bags, rosbag2 `.db3`/`.mcap`, proprietary maps and other SQLite schemas are not direct inputs. Export a supported trajectory/cloud using the original tool. The exported file will not contain every internal metric or sensor frame from the native database.
