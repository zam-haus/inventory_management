import math

from django.conf import settings
from django.contrib.gis.geos import Point
from django.test import SimpleTestCase

from .. import geo

# Somewhere in Erlangen
CENTER = Point(11.0046, 49.5973, srid=4326)


def local_point(east, north):
    """The WGS84 point `east` and `north` metres from CENTER."""
    c = geo.local(CENTER)
    return geo.wgs84(Point(c.x + east, c.y + north, srid=settings.MAPS_LOCAL_SRID))


class RectangleTests(SimpleTestCase):
    def sides(self, polygon):
        ring = geo.local(polygon).shell.coords
        return [round(math.dist(a, b), 4) for a, b in zip(ring, ring[1:])]

    def test_width_runs_east_west_and_depth_north_south(self):
        rectangle = geo.rectangle(CENTER, 1.2, 0.8)
        self.assertEqual(self.sides(rectangle), [1.2, 0.8, 1.2, 0.8])
        xs = [x for x, _y in geo.local(rectangle).shell.coords]
        self.assertAlmostEqual(max(xs) - min(xs), 1.2, places=4)
        self.assertAlmostEqual(geo.area_m2(rectangle), 0.96, places=4)

    def test_turned_a_quarter_the_width_runs_north_south(self):
        rectangle = geo.rectangle(CENTER, 1.2, 0.8, 90)
        xs, ys = zip(*geo.local(rectangle).shell.coords)
        self.assertAlmostEqual(max(xs) - min(xs), 0.8, places=4)
        self.assertAlmostEqual(max(ys) - min(ys), 1.2, places=4)
        self.assertLess(geo.distance_m(geo.anchor(rectangle), CENTER), 0.001)


class MovedTests(SimpleTestCase):
    def test_carried_along_with_a_turn(self):
        thing = local_point(1, 0)  # 1 m east of the pallet's centre
        target = local_point(10, 5)
        moved = geo.moved(thing, CENTER, target, turn=90)
        c, m = geo.local(target), geo.local(moved)
        self.assertAlmostEqual(m.x - c.x, 0, places=3)
        self.assertAlmostEqual(m.y - c.y, -1, places=3)  # clockwise: east becomes south


class FitTests(SimpleTestCase):
    def pairs(self, pixels, scale=0.02, turn=30, shift=(3.0, -7.0)):
        """Control points of an image drawn `scale` metres per pixel, turned `turn` degrees clockwise."""
        result = []
        for x, y in pixels:
            east, north = geo._rotate(x * scale, -y * scale, turn)
            result.append(((x, y), local_point(east + shift[0], north + shift[1])))
        return result

    def test_two_points_place_a_plan_drawn_to_scale(self):
        fit = geo.fit(self.pairs([(100, 200), (3000, 1800)]))
        self.assertAlmostEqual(fit.scale_m_per_px, 0.02, places=6)
        self.assertLess(fit.residual_m, 0.001)
        (_pixel, expected), = self.pairs([(2500, 400)])
        self.assertLess(geo.distance_m(fit.to_wgs84(2500, 400), expected), 0.001)

    def test_more_points_report_how_far_they_deviate(self):
        pairs = self.pairs([(100, 200), (3000, 1800), (500, 2500)])
        (pixel, point) = pairs[2]
        c = geo.local(point)
        pairs[2] = (pixel, geo.wgs84(Point(c.x + 0.3, c.y, srid=c.srid)))  # one point 30 cm off
        fit = geo.fit(pairs)
        self.assertGreater(fit.residual_m, 0.1)
        self.assertLess(fit.residual_m, 0.3)
        self.assertLess(geo.fit(pairs, affine=True).residual_m, 0.001)  # three points fit any affine map

    def test_too_few_or_coinciding_points(self):
        with self.assertRaises(ValueError):
            geo.fit(self.pairs([(100, 200)]))
        with self.assertRaises(ValueError):
            geo.fit(self.pairs([(100, 200), (300, 400)]), affine=True)
        with self.assertRaises(ValueError):
            geo.fit(self.pairs([(100, 200), (100, 200)]))

    def test_placement_corners_in_the_overlays_order(self):
        fit = geo.fit(self.pairs([(0, 0), (1000, 500)], turn=0))
        corners, outline = geo.placement(fit, 1000, 500)
        top_left, top_right, bottom_left = (geo.local(point) for point in corners)
        self.assertAlmostEqual(top_right.x - top_left.x, 20, places=3)  # 1000 px × 2 cm
        self.assertAlmostEqual(top_left.y - bottom_left.y, 10, places=3)
        self.assertAlmostEqual(geo.area_m2(outline), 200, places=1)
