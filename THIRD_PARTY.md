# Format references and dependencies

RPBot Map Studio is an independent analysis tool, not an official RTAB-Map, TUM, KITTI, g2o, PCL or ROS distribution.

The native C RVL decoder is a bounded implementation of the format described in Andrew D. Wilson, *Fast Lossless Depth Image Compression* (SIGCHI 2017). RTAB-Map wrapper/calibration parsing is based on the documented/upstream formats:

- [RTAB-Map Compression.cpp](https://github.com/introlab/rtabmap/blob/master/corelib/src/Compression.cpp)
- [RTAB-Map CameraModel.cpp](https://github.com/introlab/rtabmap/blob/master/corelib/src/CameraModel.cpp)
- [RTAB-Map RVL codec](https://github.com/introlab/rtabmap/blob/master/corelib/src/rvl_codec.cpp)

Main runtime dependencies: Python (PSF), Tcl/Tk (Tcl/Tk license), NumPy/SciPy/pandas (BSD), Matplotlib (Matplotlib license), Pillow (HPND) and OpenCV (Apache 2.0 for current releases). PyInstaller is used to bundle binaries under its license and bootloader exception. Included distributions retain their own license files; the project's MIT license does not replace dependency licenses. Check the exact installed versions for complete notices. Portable PLY/PCD readers are implemented directly in this project.

FFmpeg is an optional maintainer tool used to record demo media and is not required by the application or bundled into its executable.
