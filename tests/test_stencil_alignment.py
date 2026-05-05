import os
import subprocess
import sys
import tempfile
import unittest

import stencilframer


def write_temp(contents, suffix):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as fout:
        fout.write(contents)
    return path


KICAD_WITH_PADS = """
(kicad_pcb
  (footprint "J1"
    (at 10 10 90)
    (pad "1" smd rect (at 2 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
    (pad "2" smd rect (at 0 3) (size 1 1) (layers "B.Cu" "B.Paste" "B.Mask"))
  )
  (footprint "J2"
    (at 40 30)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
  )
)
"""


STENCIL_GERBER = """
%FSLAX33Y33*%
%MOMM*%
%ADD10R,1.000X1.000*%
D10*
X0Y0D02*
X100000Y0D01*
X100000Y-80000D01*
X0Y-80000D01*
X0Y0D01*
X10000Y-90000D02*
X20000Y-90000D01*
X20000Y-95000D01*
X10000Y-95000D01*
X10000Y-90000D01*
X20000Y-20000D03*
X80000Y-20000D03*
X50000Y-60000D03*
X20000Y-92000D03*
M02*
"""


ROUNDED_STENCIL_GERBER = """
%FSLAX33Y33*%
%MOMM*%
%ADD10R,1.000X1.000*%
D10*
X10000Y0D02*
X90000Y0D01*
G03X100000Y-10000I0J-10000D01*
X100000Y-70000D01*
G03X90000Y-80000I-10000J0D01*
X10000Y-80000D01*
G03X0Y-70000I0J10000D01*
X0Y-10000D01*
G03X10000Y0I10000J0D01*
X20000Y-20000D03*
X80000Y-20000D03*
X50000Y-60000D03*
M02*
"""


REGION_STENCIL_GERBER = """
%FSLAX33Y33*%
%MOMM*%
%ADD10C,0.100*%
D10*
X0Y0D02*
X100000Y0D01*
X100000Y-80000D01*
X0Y-80000D01*
X0Y0D01*
G36*
X19000Y-19000D02*
X21000Y-19000D01*
X21000Y-21000D01*
X19000Y-21000D01*
X19000Y-19000D01*
G37*
G36*
X79000Y-19000D02*
X81000Y-19000D01*
X81000Y-21000D01*
X79000Y-21000D01*
X79000Y-19000D01*
G37*
G36*
X49000Y-59000D02*
X51000Y-59000D01*
X51000Y-61000D01*
X49000Y-61000D01*
X49000Y-59000D01*
G37*
M02*
"""


OPEN_OUTLINE_REGION_STENCIL_GERBER = """
%FSLAX33Y33*%
%MOMM*%
%ADD10C,0.000*%
G54D10*
X-50000Y47000D02*
G75*
G02X-47000Y50000I3000J0D01*
G74*
G01*
X-250Y50000D01*
X250Y50000D02*
X47000Y50000D01*
G75*
G02X50000Y47000I0J-3000D01*
G74*
G01*
X50000Y250D01*
X50000Y-250D02*
X50000Y-47000D01*
G75*
G02X47000Y-50000I-3000J0D01*
G74*
G01*
X250Y-50000D01*
X-250Y-50000D02*
X-47000Y-50000D01*
G75*
G02X-50000Y-47000I0J3000D01*
G74*
G01*
X-50000Y-250D01*
X-50000Y250D02*
X-50000Y47000D01*
G36*
G01X19000Y-19000D02*
X21000Y-19000D01*
X21000Y-21000D01*
X19000Y-21000D01*
X19000Y-19000D01*
G37*
G36*
G01X29000Y-19000D02*
X31000Y-19000D01*
X31000Y-21000D01*
X29000Y-21000D01*
X29000Y-19000D01*
G37*
G36*
G01X39000Y-39000D02*
X41000Y-39000D01*
X41000Y-41000D01*
X39000Y-41000D01*
X39000Y-39000D01*
G37*
M02*
"""


CLI_KICAD = """
(kicad_pcb
  (gr_rect (start 0 0) (end 100 80) (layer "Edge.Cuts") (width 0.1))
  (footprint "A" (at 25 27) (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")))
  (footprint "B" (at 85 27) (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")))
  (footprint "C" (at 55 67) (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")))
)
"""


class StencilAlignmentTest(unittest.TestCase):
    def test_extracts_kicad_paste_pads_with_rotation_and_side(self):
        path = write_temp(KICAD_WITH_PADS, ".kicad_pcb")
        try:
            top = stencilframer.extract_kicad_paste_pads(path, "F.Paste")
            bottom = stencilframer.extract_kicad_paste_pads(path, "B.Paste")
        finally:
            os.unlink(path)

        self.assertEqual(len(top), 2)
        self.assertEqual(len(bottom), 1)
        self.assertAlmostEqual(top[0]['center'][0], 10)
        self.assertAlmostEqual(top[0]['center'][1], 8)

    def test_parses_gerber_stencil_and_ignores_outside_features(self):
        path = write_temp(STENCIL_GERBER, ".gbr")
        try:
            stencil = stencilframer.parse_gerber_stencil(path)
        finally:
            os.unlink(path)

        self.assertEqual(stencil['outline'], [(0, -80), (0, 0), (100, 0), (100, -80)])
        self.assertEqual(len(stencil['pads']), 3)
        self.assertNotIn((20, -92), stencil['pads'])

    def test_parses_rounded_corner_stencil_outline(self):
        path = write_temp(ROUNDED_STENCIL_GERBER, ".gbr")
        try:
            stencil = stencilframer.parse_gerber_stencil(path)
        finally:
            os.unlink(path)

        self.assertEqual(stencil['outline'], [(0, -80), (0, 0), (100, 0), (100, -80)])
        self.assertEqual(len(stencil['pads']), 3)

    def test_parses_region_stencil_apertures(self):
        path = write_temp(REGION_STENCIL_GERBER, ".gbr")
        try:
            stencil = stencilframer.parse_gerber_stencil(path)
        finally:
            os.unlink(path)

        self.assertEqual(stencil['outline'], [(0, -80), (0, 0), (100, 0), (100, -80)])
        self.assertEqual(len(stencil['pads']), 3)
        self.assertIn((20, -20), stencil['pads'])
        self.assertIn((80, -20), stencil['pads'])
        self.assertIn((50, -60), stencil['pads'])

    def test_parses_open_rounded_outline_with_region_apertures(self):
        path = write_temp(OPEN_OUTLINE_REGION_STENCIL_GERBER, ".gbr")
        try:
            stencil = stencilframer.parse_gerber_stencil(path)
        finally:
            os.unlink(path)

        self.assertEqual(stencil['outline'], [(-50, -50), (-50, 50), (50, 50), (50, -50)])
        self.assertEqual(len(stencil['pads']), 3)

    def test_matches_translation_with_gerber_y_flip(self):
        stencil_points = [(20, -20), (80, -20), (50, -60)]
        pcb_points = [(25, 27), (85, 27), (55, 67)]

        match = stencilframer.match_stencil_to_pcb_pads(stencil_points, pcb_points)

        self.assertTrue(match['flip_y'])
        self.assertAlmostEqual(match['offset'][0], 5)
        self.assertAlmostEqual(match['offset'][1], 7)

    def test_detects_rotation_required(self):
        stencil_points = [(0, 0), (10, 0), (0, 10)]
        angle = 5.0/180.0*3.141592653589793
        pcb_points = [stencilframer.rotate_point_math(p, (0, 0), angle) for p in stencil_points]

        with self.assertRaises(ValueError):
            stencilframer.match_stencil_to_pcb_pads(stencil_points, pcb_points)

    def test_cli_stencil_file_generates_scad(self):
        pcb_path = write_temp(CLI_KICAD, ".kicad_pcb")
        stencil_path = write_temp(STENCIL_GERBER, ".gbr")
        fd, out_path = tempfile.mkstemp(suffix=".scad")
        os.close(fd)
        try:
            subprocess.check_call([
                sys.executable,
                "stencilframer.py",
                "--openscad",
                "/usr/bin/true",
                "-l",
                "999",
                "-r",
                "999",
                "-t",
                "999",
                "-b",
                "999",
                "--stencil-file",
                stencil_path,
                pcb_path,
                out_path,
            ])
            with open(out_path, "r") as fin:
                scad = fin.read()
        finally:
            os.unlink(pcb_path)
            os.unlink(stencil_path)
            os.unlink(out_path)

        self.assertIn("polygon(points=[[-45.0, -47.0], [-45.0, 33.0], [55.0, 33.0], [55.0, -47.0]])", scad)


if __name__ == '__main__':
    unittest.main()
