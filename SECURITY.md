# Security and private data

For security issues, use the repository's private vulnerability reporting feature when available. If it is unavailable, open a minimal issue asking for a private reporting channel without exploit details or private datasets.

For ordinary parsing bugs, include app version, OS, supported format and a minimal synthetic reproducer. Avoid publishing raw robot databases, room layouts, location data or camera images without permission.

The app processes inputs locally and does not upload files. Source files are read as bytes and analyzed through independent snapshots. Report bundles contain extracted content, input names and local paths; review them before sharing. `input_snapshot/` is excluded from ZIP reports.

The v2 series is the currently maintained line. Standalone executables are not code signed; checksums identify the exact downloadable archives.
