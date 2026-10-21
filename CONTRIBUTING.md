# Contributing

Open an issue describing the input format, available data and intended result before a large new reader. Small fixes can go straight to a pull request.

1. Create a virtual environment and follow [development setup](docs/DEVELOPMENT.md).
2. Add focused tests for the behavior being changed, particularly binary parsing, source preservation and coordinate/timestamp semantics.
3. Run `python -m unittest discover -s tests -v` and a representative GUI/CLI analysis.
4. Update the format matrix and limitations whenever support changes.

Keep changes independent of ROS and proprietary runtimes where possible. Use small synthetic fixtures; do not contribute private maps, personal camera frames, credentials, raw SQLite snapshots or large binaries. Explain provenance and redistribution permission for any external dataset.

Report validation precisely: distinguish source tests, packaged application tests, manual desktop checks and hardware validation. A chart alone does not prove SLAM accuracy.
