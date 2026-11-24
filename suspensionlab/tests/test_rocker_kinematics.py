"""Независимые аналитические примеры геометрии, без двигателя CAD/Qt."""
from math import cos, dist, pi, sin, sqrt
from unittest import TestCase

from suspensionlab.core.rocker_kinematics import RockerError, RockerGeometry, solve_rocker


class TestRocker(TestCase):
    def geometry(self):
        return RockerGeometry((0., 0., 0.), (0., 0., 5.), (1., 0., 0.), (1., 1., 0.),
                              (0., 2., 0.), (0., 3., 0.))

    def assert_point(self, actual, expected):
        for a, b in zip(actual, expected, strict=True):
            self.assertAlmostEqual(a, b, places=9)

    def test_static_and_analytic_rotation(self):
        geometry = self.geometry()
        static = solve_rocker(geometry, geometry.rod_suspension)
        self.assertAlmostEqual(static.angle_rad, 0.)
        self.assert_point(static.rod_rocker, geometry.rod_rocker)
        self.assert_point(static.damper_rocker, geometry.damper_rocker)
        self.assertAlmostEqual(static.damper_length_mm, 1.)
        previous = 0.
        for index in range(1, 9):
            angle = index * pi / 48
            # The input pivot is independently rotated by the known angle.
            suspension = (cos(angle) - sin(angle), sin(angle) + cos(angle), 0.)
            pose = solve_rocker(geometry, suspension, previous_angle_rad=previous)
            self.assertAlmostEqual(pose.angle_rad, angle, places=9)
            self.assert_point(pose.rod_rocker, (cos(angle), sin(angle), 0.))
            self.assert_point(pose.damper_rocker, (-2 * sin(angle), 2 * cos(angle), 0.))
            self.assertAlmostEqual(pose.damper_length_mm, sqrt(13 - 12 * cos(angle)), places=9)
            self.assertAlmostEqual(dist(pose.rod_rocker, suspension), geometry.rod_length, places=9)
            previous = pose.angle_rad

    def test_spatial_axis_and_translated_origin(self):
        geometry = RockerGeometry((10., 20., 30.), (7., 0., 0.), (10., 21., 30.), (10., 21., 31.),
                                  (10., 20., 32.), (10., 20., 33.))
        angle = pi / 6
        target = (10., 20 + cos(angle) - sin(angle), 30 + sin(angle) + cos(angle))
        pose = solve_rocker(geometry, target)
        self.assertAlmostEqual(pose.angle_rad, angle, places=9)
        self.assert_point(pose.rod_rocker, (10., 20 + cos(angle), 30 + sin(angle)))
        self.assert_point(pose.damper_rocker, (10., 20 - 2 * sin(angle), 30 + 2 * cos(angle)))
        self.assertAlmostEqual(pose.damper_length_mm, sqrt(13 - 12 * cos(angle)), places=9)

    def test_branch_tracks_unwrapped_previous_angle(self):
        geometry = self.geometry()
        pose = solve_rocker(geometry, geometry.rod_suspension, previous_angle_rad=2 * pi)
        self.assertAlmostEqual(pose.angle_rad, 2 * pi, places=9)
        other = solve_rocker(geometry, geometry.rod_suspension, previous_angle_rad=pi / 2)
        self.assertAlmostEqual(other.angle_rad, pi / 2, places=9)
        with self.assertRaises(RockerError):
            solve_rocker(geometry, geometry.rod_suspension, previous_angle_rad=pi / 4)

    def test_out_of_reach_singular_and_invalid_inputs(self):
        geometry = self.geometry()
        for point in ((50., 0., 0.), (0., 0., 3.), (float('nan'), 1., 0.), (True, 0., 0.)):
            with self.subTest(point=point), self.assertRaises(RockerError):
                solve_rocker(geometry, point)
        # At the tangent the two mathematical branches merge: refuse ambiguity.
        with self.assertRaises(RockerError):
            solve_rocker(geometry, (2., 0., 0.))
        for invalid_angle in (None, True, float('inf'), 'zero'):
            with self.subTest(angle=invalid_angle), self.assertRaises(RockerError):
                solve_rocker(geometry, geometry.rod_suspension, previous_angle_rad=invalid_angle)
        for kwargs in ({'axis': (0., 0., 0.)}, {'rod_rocker': (0., 0., 2.)},
                       {'damper_rocker': (0., 0., 2.)}, {'rod_suspension': (1., 0., 0.)},
                       {'damper_body': (0., 2., 0.)}):
            values = {'pivot': (0., 0., 0.), 'axis': (0., 0., 1.), 'rod_rocker': (1., 0., 0.),
                      'rod_suspension': (1., 1., 0.), 'damper_rocker': (0., 2., 0.),
                      'damper_body': (0., 3., 0.)}
            values.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(RockerError):
                RockerGeometry(**values)


class TestRockerSweep(TestCase):
    def setUp(self):
        self.geometry = RockerGeometry((0., 0., 0.), (0., 0., 5.), (1., 0., 0.), (1., 1., 0.),
                                       (0., 2., 0.), (0., 3., 0.))

    @staticmethod
    def point_at(travel):
        angle = travel * 0.01
        return cos(angle) - sin(angle), sin(angle) + cos(angle), 0.

    def test_tracks_independent_branches_and_finite_difference_ratio(self):
        from suspensionlab.core.rocker_kinematics import RockerInput, solve_rocker_sweep

        travels = (-4., -2., 0., 1., 3., 5.)
        samples = solve_rocker_sweep(self.geometry, [RockerInput(t, self.point_at(t)) for t in travels])
        self.assertEqual(len(samples), len(travels))
        for t, sample in zip(travels, samples, strict=True):
            self.assertAlmostEqual(sample.pose.angle_rad, t * 0.01, places=9)
            self.assertAlmostEqual(sample.pose.damper_length_mm, sqrt(13 - 12 * cos(t * 0.01)), places=9)
            self.assertAlmostEqual(dist(sample.pose.rod_rocker, self.point_at(t)), self.geometry.rod_length, places=9)
            self.assertIsNone(sample.error)
        self.assertIsNone(samples[0].motion_ratio)
        self.assertIsNone(samples[-1].motion_ratio)
        for sample in samples[1:-1]:
            angle = sample.travel_mm * 0.01
            expected = -0.06 * sin(angle) / sqrt(13 - 12 * cos(angle))
            self.assertAlmostEqual(sample.motion_ratio, expected, delta=1e-5)

    def test_stops_only_failed_branch_and_does_not_bridge_gaps(self):
        from suspensionlab.core.rocker_kinematics import RockerInput, solve_rocker_sweep

        travels = tuple(range(-6, 8, 2))
        values = [RockerInput(t, None if t == 2 else self.point_at(t)) for t in travels]
        samples = solve_rocker_sweep(self.geometry, values)
        by_t = {sample.travel_mm: sample for sample in samples}
        for t in (-6, -4, -2, 0):
            self.assertIsNotNone(by_t[t].pose)
        self.assertEqual(by_t[2].error, 'no suspension pose')
        self.assertEqual(by_t[4].error, 'not evaluated after branch failure')
        self.assertIsNone(by_t[6].pose)
        self.assertIsNone(by_t[0].motion_ratio)
        self.assertIsNone(by_t[2].motion_ratio)
        self.assertIsNotNone(by_t[-2].motion_ratio)

    def test_invalid_static_does_not_produce_fictitious_motion(self):
        from suspensionlab.core.rocker_kinematics import RockerInput, solve_rocker_sweep

        for point in (None, (1.1, 1., 0.), (float('nan'), 0., 0.)):
            samples = solve_rocker_sweep(self.geometry, [RockerInput(-1, self.point_at(-1)), RockerInput(0, point),
                                                         RockerInput(1, self.point_at(1))])
            self.assertTrue(all(s.pose is None and s.motion_ratio is None and s.error for s in samples))

    def test_rejects_unordered_sparse_or_invalid_grid(self):
        from suspensionlab.core.rocker_kinematics import RockerInput, solve_rocker_sweep

        def good(t):
            return RockerInput(t, self.point_at(t))
        for invalid in ([], [good(1)], [good(0), good(0)], [good(1), good(0)], [good(0), good(3)],
                        [good(0), RockerInput(float('nan'), (0., 0., 0.))],
                        [RockerInput(True, (0., 0., 0.)), good(0)]):
            with self.subTest(invalid=invalid), self.assertRaises(RockerError):
                solve_rocker_sweep(self.geometry, invalid)
        for step in (0, 2.1, float('nan'), True):
            with self.subTest(step=step), self.assertRaises(RockerError):
                solve_rocker_sweep(self.geometry, [good(0)], max_step_mm=step)

    def test_rejects_angle_jump_and_unreachable_pose(self):
        from suspensionlab.core.rocker_kinematics import RockerInput, solve_rocker_sweep

        inputs = [RockerInput(-2, self.point_at(-2)), RockerInput(0, self.point_at(0)),
                  RockerInput(2, self.point_at(60)), RockerInput(4, self.point_at(4))]
        result = solve_rocker_sweep(self.geometry, inputs, max_angle_step_rad=0.1)
        self.assertIsNotNone(result[0].pose)
        self.assertEqual(result[2].error, 'rocker angle step too large to track branch')
        self.assertIsNone(result[3].pose)
        inputs[2] = RockerInput(2, (100., 0., 0.))
        result = solve_rocker_sweep(self.geometry, inputs)
        self.assertIn('unreachable', result[2].error)
        self.assertIsNone(result[3].pose)
