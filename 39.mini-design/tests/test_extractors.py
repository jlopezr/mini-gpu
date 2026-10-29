#!/usr/bin/env python3
"""Test extractors with user's original NewsMaster resource files."""
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from shp2png import extract as shapes
from icn2png import extract as icons

class ExtractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = Path(sys.argv_resources)

    def test_shapes(self):
        items = shapes(*(self.resources / f'NEWS.{e}' for e in ('SHP', 'SDX', 'SDR')))
        self.assertEqual(len(items),151)
        self.assertEqual(items[0][0],'Masks')
        self.assertEqual(items[0][1].size,(88,52))

    def test_icons(self):
        items = icons(self.resources/'NEWS.ICN')
        self.assertEqual(len(items),59)
        self.assertTrue(all(im.size == (40,20) for im in items))

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--resources',type=Path,required=True)
    args = parser.parse_args()
    sys.argv_resources = args.resources
    unittest.main(argv=['test_extractors.py'])
