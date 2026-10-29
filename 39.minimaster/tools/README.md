# NewsMaster resource extraction

Requires Python 3 and Pillow (`python3 -m pip install Pillow`).

```sh
python3 tools/shp2png.py NEWS.SHP NEWS.SDX NEWS.SDR --output build/shapes
python3 tools/icn2png.py NEWS.ICN --output build/icons --correct-aspect
python3 tests/test_extractors.py --resources /path/to/original/files
```

The shape extractor writes 151 numbered PNGs, `catalog.csv` and `catalog.png` with names from SDR. It checks the little-endian SDX offsets and validates record boundaries and bitmap dimensions. SHP bit value **1=black**.

The icon extractor writes 59 numbered, **unscaled 40x20 PNGs**, plus `catalog.png` correcting the original non-square pixel aspect (2:1 vertical/horizontal). `--correct-aspect` also exports **40x40** copies under `corrected/`; never replace the original 40x20 resources with the corrected ones in MiniMaster. ICN bit value **0=black**.

This research tool does not bundle proprietary NewsMaster resources. Point it at files from your own installation.
