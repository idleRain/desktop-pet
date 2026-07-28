"""桌面宠物的运动与朝向计算。

本模块只包含无副作用的纯函数，不依赖 PyQt5 与 Windows API，便于单元测试。
"""

import math

# 屏幕坐标系到导航角制的换算偏移量。
# 屏幕坐标系中 x 轴向右，y 轴向下，屏幕角 0 度指向正右方，对应导航角 90 度。
# 因此导航角等于屏幕角加上 90 度。
SCREEN_TO_HEADING_OFFSET_DEG = 90


def step_position(pos_x, pos_y, direction, speed):
    """按当前方向与速度计算下一帧坐标。"""
    return (
        pos_x + math.cos(direction) * speed,
        pos_y + math.sin(direction) * speed,
    )


def reflect_at_boundary(pos_x, pos_y, direction, bound_x, bound_y):
    """触及屏幕边界时修正坐标并反弹方向。

    bound_x 与 bound_y 为坐标分量的有效上限，即屏幕尺寸减去宠物尺寸。
    """
    new_x, new_y, new_dir = pos_x, pos_y, direction
    if pos_x < 0:
        new_x = 0
        new_dir = math.pi - direction
    elif pos_x > bound_x:
        new_x = bound_x
        new_dir = math.pi - direction
    if pos_y < 0:
        new_y = 0
        new_dir = -new_dir
    elif pos_y > bound_y:
        new_y = bound_y
        new_dir = -new_dir
    return new_x, new_y, new_dir


def compute_facing_deg(direction_rad, head_heading_deg):
    """将移动方向换算为图片旋转角，使头部对准爬行方向。

    移动方向采用屏幕角，先换算为导航角，再减去素材头部初始朝向，
    得到需要施加的顺时针旋转量。
    """
    move_heading_deg = math.degrees(direction_rad) + SCREEN_TO_HEADING_OFFSET_DEG
    return move_heading_deg - head_heading_deg
