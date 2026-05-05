import unittest

import stencilframer


def line(start, end):
    return {'type': 'line', 'start': start, 'end': end}


def rect(xmin, ymin, xmax, ymax):
    points = [
        (xmin, ymin),
        (xmax, ymin),
        (xmax, ymax),
        (xmin, ymax),
    ]
    return [line(points[i], points[(i+1)%len(points)]) for i in range(len(points))]


class VoidFillingTest(unittest.TestCase):
    def test_polygon_area_uses_square_mm(self):
        self.assertEqual(abs(stencilframer.polygon_area([(0, 0), (5, 0), (5, 3), (0, 3)])), 15)

    def test_finds_only_large_voids_inside_selected_shape(self):
        shapes = [
            rect(0, 0, 20, 20),
            rect(2, 2, 4, 4),
            rect(5, 5, 10, 9),
            rect(30, 30, 40, 40),
        ]
        selected = stencilframer.paths_to_polygon(shapes[0])
        selected_center = stencilframer.polygon_center(selected)

        voids = stencilframer.find_void_polygons(
            shapes=shapes,
            selected_idx=0,
            selected_polygon=selected,
            selected_center=selected_center,
            min_area=15,
        )

        self.assertEqual(len(voids), 1)
        self.assertEqual(abs(stencilframer.polygon_area(voids[0])), 20)

    def test_can_transform_voids_for_kicad_and_mirror(self):
        shapes = [
            rect(0, 0, 20, 20),
            rect(5, 6, 10, 10),
        ]
        selected = stencilframer.paths_to_polygon(shapes[0])
        selected_center = stencilframer.polygon_center(selected)

        voids = stencilframer.find_void_polygons(
            shapes=shapes,
            selected_idx=0,
            selected_polygon=selected,
            selected_center=selected_center,
            min_area=15,
            mirror_y=True,
            mirror_x=True,
        )

        self.assertEqual(voids[0][0], (5, 4))


class LiftHolePositionTest(unittest.TestCase):
    def test_manual_lift_hole_positions_use_pcb_bounds(self):
        pol = [(-10, -5), (10, -5), (10, 5), (-10, 5)]

        self.assertEqual(stencilframer.positioned_lift_hole(pol, 'l')['x'], -10)
        self.assertEqual(stencilframer.positioned_lift_hole(pol, 'r')['x'], 10)
        self.assertEqual(stencilframer.positioned_lift_hole(pol, 't')['y'], -5)
        self.assertEqual(stencilframer.positioned_lift_hole(pol, 'b')['y'], 5)
        self.assertEqual((stencilframer.positioned_lift_hole(pol, 'tl')['x'], stencilframer.positioned_lift_hole(pol, 'tl')['y']), (-10, -5))
        self.assertEqual((stencilframer.positioned_lift_hole(pol, 'br')['x'], stencilframer.positioned_lift_hole(pol, 'br')['y']), (10, 5))

    def test_auto_lift_hole_keeps_existing_longest_edge_behavior(self):
        pol = [(-10, -5), (10, -5), (10, 5), (-10, 5)]

        hole = stencilframer.positioned_lift_hole(pol, 'auto')

        self.assertEqual(hole['x'], 0)
        self.assertEqual(hole['y'], -5)
        self.assertEqual(hole['r'], 5)


if __name__ == '__main__':
    unittest.main()
