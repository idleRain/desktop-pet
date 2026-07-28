"""桌面宠物运动逻辑的单元测试，覆盖 motion 模块的纯函数。"""

import os
import sys
import math
import unittest

# 将 src 目录加入搜索路径，使测试可在不安装包的情况下直接运行。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from motion import (  # noqa: E402
    step_position,
    reflect_at_boundary,
    compute_facing_deg,
    SCREEN_TO_HEADING_OFFSET_DEG,
)


class StepPositionTests(unittest.TestCase):
    def test_zero_direction_moves_right(self):
        pos_x, pos_y = step_position(0, 0, 0, 5)
        self.assertAlmostEqual(pos_x, 5)
        self.assertAlmostEqual(pos_y, 0)

    def test_downward_direction(self):
        pos_x, pos_y = step_position(0, 0, math.pi / 2, 4)
        self.assertAlmostEqual(pos_x, 0)
        self.assertAlmostEqual(pos_y, 4)

    def test_speed_scales_displacement(self):
        pos_x, pos_y = step_position(0, 0, 0, 0)
        self.assertEqual((pos_x, pos_y), (0, 0))


class ReflectBoundaryTests(unittest.TestCase):
    def test_left_boundary_reverses_x(self):
        pos_x, pos_y, direction = reflect_at_boundary(-1, 10, 0.3, 100, 100)
        self.assertEqual(pos_x, 0)
        self.assertEqual(pos_y, 10)
        self.assertAlmostEqual(direction, math.pi - 0.3)

    def test_right_boundary_reverses_x(self):
        pos_x, pos_y, direction = reflect_at_boundary(101, 10, 0.3, 100, 100)
        self.assertEqual(pos_x, 100)
        self.assertAlmostEqual(direction, math.pi - 0.3)

    def test_top_boundary_reverses_y(self):
        pos_x, pos_y, direction = reflect_at_boundary(10, -1, 0.3, 100, 100)
        self.assertEqual(pos_y, 0)
        self.assertAlmostEqual(direction, -0.3)

    def test_bottom_boundary_reverses_y(self):
        pos_x, pos_y, direction = reflect_at_boundary(10, 101, 0.3, 100, 100)
        self.assertEqual(pos_y, 100)
        self.assertAlmostEqual(direction, -0.3)

    def test_inside_bounds_unchanged(self):
        pos_x, pos_y, direction = reflect_at_boundary(50, 50, 0.7, 100, 100)
        self.assertEqual((pos_x, pos_y, direction), (50, 50, 0.7))

    def test_corner_reflects_both_axes(self):
        pos_x, pos_y, direction = reflect_at_boundary(-1, -1, 0.4, 100, 100)
        self.assertEqual(pos_x, 0)
        self.assertEqual(pos_y, 0)
        # 同时触发左右与上下反弹，方向先做 x 反转再做 y 取反。
        self.assertAlmostEqual(direction, -(math.pi - 0.4))


class FacingDegreeTests(unittest.TestCase):
    def test_east_heading(self):
        deg = compute_facing_deg(0, 0)
        self.assertAlmostEqual(deg, SCREEN_TO_HEADING_OFFSET_DEG)

    def test_head_offset_subtracted(self):
        deg = compute_facing_deg(0, 45)
        self.assertAlmostEqual(deg, SCREEN_TO_HEADING_OFFSET_DEG - 45)


if __name__ == "__main__":
    unittest.main()
