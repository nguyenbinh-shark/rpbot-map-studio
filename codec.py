"""RTAB-Map compressed data readers; every buffer/dimension is validated."""

from pathlib import Path
import ctypes
import struct
import sys
import zlib
import numpy as np
import cv2

MAX_PIXELS = 16_000_000
_native = None


def asset(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / name


def native():
    global _native
    if _native is None:
        from platform_support import library_name

        p = asset(library_name())
        if not p.is_file():
            raise ValueError("Thiếu bộ giải mã chiều sâu. Hãy dùng bản app đầy đủ.")
        _native = ctypes.CDLL(str(p))
        _native.decode_rvl.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        _native.decode_rvl.restype = ctypes.c_int
    return _native


def depth_image(blob):
    """Return float32 depth in metres (RVL uint16 is stored in millimetres)."""
    if not blob:
        return None
    if blob[:8] == b"DEPTHINV":
        if len(blob) < 17:
            raise ValueError("Ảnh chiều sâu inverse bị thiếu dữ liệu.")
        a, b = struct.unpack_from("<ff", blob, 8)
        image = depth_image(blob[16:])
        if image is None:
            return None
        raw = np.rint(image * 1000)
        result = np.zeros_like(image)
        valid = (raw > 0) & (raw != b)
        result[valid] = a / (raw[valid] - b)
        result[~np.isfinite(result) | (result < 0)] = 0
        return result
    if blob[:8] == b"DEPTHRVL":
        if len(blob) < 20:
            raise ValueError("Ảnh chiều sâu RVL bị cắt ngắn.")
        w, h = struct.unpack_from("<II", blob, 8)
        if w == 0 or h == 0 or w * h > MAX_PIXELS:
            raise ValueError("Kích thước ảnh chiều sâu không hợp lệ.")
        result = np.empty((h, w), dtype=np.uint16)
        compressed = ctypes.create_string_buffer(blob[16:])
        code = native().decode_rvl(compressed, len(blob) - 16, result.ctypes.data, result.size)
        if code:
            raise ValueError(f"Không giải mã được chiều sâu RVL (mã {code}).")
        return result.astype(np.float32) * 0.001
    image = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("Định dạng ảnh chiều sâu chưa được hỗ trợ.")
    if image.size > MAX_PIXELS * 4:
        raise ValueError("Ảnh chiều sâu quá lớn.")
    if image.ndim == 2 and image.dtype == np.uint16:
        return image.astype(np.float32) * 0.001
    if image.ndim == 2 and image.dtype == np.float32:
        return image
    if image.ndim == 3 and image.shape[2] == 4 and image.dtype == np.uint8:
        return image.copy().view("<f4").reshape(image.shape[:2])
    raise ValueError(
        "Database có ảnh stereo/right hoặc kiểu depth không hỗ trợ; không suy đoán đơn vị."
    )


def matrix(blob, max_bytes=256_000_000):
    if not blob or len(blob) < 12:
        return None
    rows, cols, kind = struct.unpack("<iii", blob[-12:])
    channels = (kind >> 3) + 1
    depth = kind & 7
    types = {0: "u1", 1: "i1", 2: "<u2", 3: "<i2", 4: "<i4", 5: "<f4", 6: "<f8"}
    if rows < 1 or cols < 1 or channels < 1 or channels > 512 or depth not in types:
        raise ValueError("Metadata ma trận nén không hợp lệ.")
    dtype = np.dtype(types[depth])
    expected = rows * cols * channels * dtype.itemsize
    if expected > max_bytes:
        raise ValueError("Ma trận nén vượt giới hạn bộ nhớ.")
    obj = zlib.decompressobj()
    raw = obj.decompress(blob[:-12], expected + 1)
    if len(raw) != expected or not obj.eof or obj.unconsumed_tail:
        raise ValueError("Kích thước ma trận nén không khớp metadata.")
    shape = (rows, cols) if channels == 1 else (rows, cols, channels)
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def calibration(blob):
    """Decode mono CameraModel serialization introduced before RTAB-Map 0.23."""
    if not blob or len(blob) < 44:
        raise ValueError("Thiếu calibration camera.")
    head = struct.unpack_from("<11i", blob)
    if head[3] != 0:
        raise ValueError(
            "Dựng 3D hiện hỗ trợ mono RGB-D; calibration stereo/multi-camera sẽ được bỏ qua."
        )
    w, h = head[4:6]
    nk, nd, nr, np_, nl = head[6:11]
    if (
        w <= 0
        or h <= 0
        or w * h > MAX_PIXELS
        or nk not in (0, 9)
        or nd < 0
        or nd > 100
        or nr not in (0, 9)
        or np_ not in (0, 12)
        or nl not in (0, 12)
    ):
        raise ValueError("Calibration camera không hợp lệ.")
    size = 44 + 8 * (nk + nd + nr + np_) + 4 * nl
    if size != len(blob):
        raise ValueError("Calibration có nhiều camera hoặc dữ liệu không đúng kích thước hỗ trợ.")
    offset = 44
    K = np.frombuffer(blob, dtype="<f8", count=nk, offset=offset).reshape(3, 3) if nk else None
    offset += 8 * (nk + nd + nr)
    P = np.frombuffer(blob, dtype="<f8", count=np_, offset=offset).reshape(3, 4) if np_ else None
    offset += 8 * np_
    local = (
        np.frombuffer(blob, dtype="<f4", count=12, offset=offset).reshape(3, 4).astype(float)
        if nl
        else np.eye(4)[:3]
    )
    intr = P[:3, :3] if P is not None else K
    if intr is None or not np.isfinite(intr).all() or intr[0, 0] <= 0 or intr[1, 1] <= 0:
        raise ValueError("Thông số tiêu cự camera không hợp lệ.")
    if not np.isfinite(local).all() or abs(np.linalg.det(local[:, :3]) - 1) > 0.05:
        raise ValueError("Biến đổi camera không hợp lệ.")
    return {
        "width": w,
        "height": h,
        "fx": float(intr[0, 0]),
        "fy": float(intr[1, 1]),
        "cx": float(intr[0, 2]),
        "cy": float(intr[1, 2]),
        "local": local,
    }
