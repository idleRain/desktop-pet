"""DesktopPet 桌面宠物主程序。

无边框透明置顶窗口，宠物在桌面随机爬行，头部始终对准爬行方向，
叠加六足爬行的上下颠簸与左右倾斜动画。
"""

import sys
import os
import math
import random
import ctypes
import ctypes.wintypes
import logging
import tomllib
from dataclasses import dataclass, fields

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QPixmap, QPainter
from PyQt5.QtCore import Qt, QTimer

from motion import (
    step_position,
    reflect_at_boundary,
    compute_facing_deg,
)

logger = logging.getLogger("desktop_pet")

# 全局热键消息与标识常量。
WM_HOTKEY = 0x0312
HOTKEY_ID = 1

# TaskbarCreated 消息名，explorer 重启后广播，用于恢复宠物窗口的置顶状态。
TASKBAR_CREATED_MSG_NAME = "TaskbarCreated"

# 动画定时器间隔，单位为毫秒，约为每秒 60 帧。
ANIMATION_INTERVAL_MS = 16

# 倾斜动画相对颠簸的谐波倍频，倾斜频率为颠簸频率的两倍。
TILT_HARMONIC_MULTIPLIER = 2

# 初始位置距屏幕左上边缘的安全边距，单位为像素。
INITIAL_POSITION_MARGIN_PX = 100
# 初始位置距屏幕右下边缘的预留量，单位为像素。
INITIAL_POSITION_RESERVE_PX = 200

# 旋转包围盒相对图片对角线的额外留白，单位为像素，用于容纳颠簸偏移。
BOB_PADDING_PX = 4

# Win32 置顶管理常量与周期性刷新间隔，单位为毫秒。
HWND_TOPMOST = -1
TOPMOST_REFRESH_INTERVAL_MS = 2000

# SetWindowPos 标志：不改变 Z 序、尺寸、激活状态。
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


class ConfigError(Exception):
    """配置文件加载或校验失败时抛出。"""


@dataclass(frozen=True)
class PetConfig:
    """桌面宠物的可调参数，全部来自 config.toml。"""

    base_width: int
    speed_min: float
    speed_max: float
    speed_change_min: float
    speed_change_max: float
    direction_change_interval_min: int
    direction_change_interval_max: int
    sharp_turn_probability: float
    sharp_turn_range: float
    slight_turn_range: float
    bob_amplitude: float
    tilt_amplitude: float
    bob_freq_factor: float
    head_heading_deg: float
    hotkey_modifiers: int
    hotkey_key: int

    @classmethod
    def from_dict(cls, data: dict) -> "PetConfig":
        """从 toml 解析后的字典构造配置，缺失项给出明确提示。"""
        required = {field.name for field in fields(cls)}
        missing = required - set(data.keys())
        if missing:
            raise ConfigError(f"config.toml 缺少以下配置项: {sorted(missing)}")
        return cls(**{name: data[name] for name in required})


def _resource_path(*parts: str) -> str:
    """返回资源文件的绝对路径，兼容 PyInstaller 打包环境。

    打包后资源位于 _MEIPASS 根目录，开发运行时位于项目根目录。
    """
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def _load_config() -> PetConfig:
    """加载并校验 config.toml。"""
    config_path = _resource_path("config.toml")
    try:
        with open(config_path, "rb") as config_file:
            data = tomllib.load(config_file)
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件格式错误: {exc}") from exc
    return PetConfig.from_dict(data)


# 窗口扩展属性索引与标志常量。
# WS_EX_TOPMOST 仅在窗口创建时可靠，此处保留定义供注释引用，实际由 Qt.WindowStaysOnTopHint 设置。
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

# SetWindowPos: 使 SetWindowLongPtrW 的样式变更立即生效的标志。
SWP_FRAMECHANGED = 0x0020


# 配置 user32 相关函数的参数与返回类型。
# 显式声明类型可在 64 位环境下正确传递窗口句柄等指针参数。
if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _user32.RegisterHotKey.argtypes = [
        ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
    ]
    _user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
    _user32.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
    _user32.RegisterWindowMessageW.restype = ctypes.wintypes.UINT

    # SetWindowPos: 运行时 Z 序管理 API。WS_EX_TOPMOST 通过 Qt.WindowStaysOnTopHint
    # 在窗口创建时设置，此处仅用于在运行时通过 HWND_TOPMOST 参数维持 Z 序。
    _user32.SetWindowPos.argtypes = [
        ctypes.wintypes.HWND, ctypes.wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint,
    ]
    _user32.SetWindowPos.restype = ctypes.wintypes.BOOL

    # GetWindowLongPtrW / SetWindowLongPtrW: 读取与修改窗口扩展样式。
    _user32.GetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongPtrW.restype = ctypes.c_size_t
    _user32.SetWindowLongPtrW.argtypes = [
        ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_size_t,
    ]
    _user32.SetWindowLongPtrW.restype = ctypes.c_size_t
else:
    _user32 = None


class DesktopPet(QWidget):
    """桌面宠物窗口，负责动画驱动与置顶维持。"""

    def __init__(self):
        super().__init__()
        self._user_hidden = False
        self.drag_pos = None
        self.bob_offset = 0.0
        self.final_angle = 0.0

        self.config = _load_config()
        self._init_window()
        self._load_pixmap()
        self._init_bounds()
        self._init_motion()
        self._init_timers()
        self._register_hotkey()

    def _init_window(self):
        """配置无边框透明窗口。

        通过 Qt.WindowStaysOnTopHint 在窗口创建时设置 WS_EX_TOPMOST 扩展样式，
        这是 Win32 文档中唯一可靠的方式。WS_EX_NOACTIVATE 与 WS_EX_TOOLWINDOW
        在 showEvent 中通过 SetWindowLongPtrW 补充设置。
        """
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Window |
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        # 显示窗口时不激活前台，避免抢占其他应用焦点。
        self.setAttribute(Qt.WA_ShowWithoutActivating)

    def _load_pixmap(self):
        """加载并缩放素材，计算旋转包围盒尺寸。"""
        img_path = _resource_path("assets", "pet.png")
        pixmap = QPixmap(img_path)
        if pixmap.isNull():
            raise ConfigError(f"无法加载素材图片: {img_path}")
        self.base_width = self.config.base_width
        scale = self.base_width / pixmap.width()
        self.base_height = int(pixmap.height() * scale)
        self.scaled_pixmap = pixmap.scaled(
            self.base_width, self.base_height,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        # 旋转后的最大包围盒为以图片对角线为边长的正方形，留出颠簸余量。
        diagonal = math.hypot(self.base_width, self.base_height)
        self.window_size = int(math.ceil(diagonal)) + BOB_PADDING_PX * 2
        self.resize(self.window_size, self.window_size)

    def _init_bounds(self):
        """计算屏幕边界与初始随机位置。"""
        screen = QApplication.primaryScreen().geometry()
        self.screen_width = screen.width()
        self.screen_height = screen.height()
        self.bound_x = self.screen_width - self.base_width
        self.bound_y = self.screen_height - self.base_height
        max_x = max(
            INITIAL_POSITION_MARGIN_PX + 1,
            self.bound_x - INITIAL_POSITION_RESERVE_PX,
        )
        max_y = max(
            INITIAL_POSITION_MARGIN_PX + 1,
            self.bound_y - INITIAL_POSITION_RESERVE_PX,
        )
        self.pos_x = float(random.randint(INITIAL_POSITION_MARGIN_PX, max_x))
        self.pos_y = float(random.randint(INITIAL_POSITION_MARGIN_PX, max_y))

    def _init_motion(self):
        """初始化移动与动画参数。"""
        self.speed = random.uniform(self.config.speed_min, self.config.speed_max)
        self.direction = random.uniform(0, 2 * math.pi)
        self.direction_change_timer = 0
        self.direction_change_interval = random.randint(
            self.config.direction_change_interval_min,
            self.config.direction_change_interval_max,
        )
        self.anim_frame = 0
        self.bob_amplitude = self.config.bob_amplitude
        self.tilt_amplitude = self.config.tilt_amplitude
        self.bob_freq_factor = self.config.bob_freq_factor
        self.head_heading_deg = self.config.head_heading_deg

    def _init_timers(self):
        """启动动画定时器、置顶维持定时器，并注册 explorer 重启消息。"""
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_animation)
        self.animation_timer.start(ANIMATION_INTERVAL_MS)

        # 周期性重新断言 HWND_TOPMOST，防止系统操作导致置顶状态丢失。
        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        self._topmost_timer.start(TOPMOST_REFRESH_INTERVAL_MS)

        self._taskbar_created_msg = _user32.RegisterWindowMessageW(
            TASKBAR_CREATED_MSG_NAME
        )

    def _register_hotkey(self):
        """注册全局热键，失败时记录日志但不中断启动。"""
        try:
            hwnd = int(self.winId())
            ok = _user32.RegisterHotKey(
                hwnd, HOTKEY_ID,
                self.config.hotkey_modifiers, self.config.hotkey_key,
            )
        except OSError as exc:
            logger.warning("注册全局热键异常: %s", exc)
            return False
        if not ok:
            logger.warning("全局热键注册失败，组合键可能已被其他程序占用。")
        return bool(ok)

    def nativeEvent(self, event_type, message):
        """处理 Windows 原生消息：热键与 explorer 重启恢复。"""
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.toggle_visibility()
                return True, 0
            if msg.message == self._taskbar_created_msg:
                if not self._user_hidden:
                    self.show()
                return True, 0
        except (OSError, ValueError) as exc:
            logger.debug("原生消息处理异常: %s", exc)
        return super().nativeEvent(event_type, message)

    def toggle_visibility(self):
        """切换宠物的显示与隐藏状态。"""
        self._user_hidden = not self._user_hidden
        if self._user_hidden:
            self.hide()
        else:
            self.show()

    def showEvent(self, event):
        """窗口显示时通过 Win32 原生 API 应用扩展样式并断言 HWND_TOPMOST Z 序。"""
        super().showEvent(event)
        self._apply_native_styles()

    def _apply_native_styles(self):
        """设置窗口扩展样式并通过单次 SetWindowPos 原子地建立 HWND_TOPMOST Z 序。

        WS_EX_TOPMOST 已由 Qt.WindowStaysOnTopHint 在窗口创建时设置，此处不再
        通过 SetWindowLongPtrW 修改该标志，因为创建后修改 WS_EX_TOPMOST 无法
        保证与实际 Z 序同步。仅补充设置 WS_EX_NOACTIVATE 与 WS_EX_TOOLWINDOW，
        然后用单次 SetWindowPos 同时完成样式刷新与 Z 序断言，避免两步操作造成
        的 Z 序瞬间错位。
        """
        hwnd = int(self.winId())
        ex_style = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ex_style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        _user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex_style)
        # 单次调用同时应用样式变更与 HWND_TOPMOST Z 序，避免中间状态。
        _user32.SetWindowPos(
            ctypes.wintypes.HWND(hwnd),
            ctypes.wintypes.HWND(HWND_TOPMOST),
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

    def _reassert_topmost(self):
        """周期性重新断言窗口的 HWND_TOPMOST Z 序。

        Windows 11 存在已知的 Z 序丢失问题，某些系统操作（如打开 Paint、Win+D
        快速切换）可能导致 WS_EX_TOPMOST 窗口被非置顶窗口暂时覆盖。此方法通过
        定期调用 SetWindowPos(HWND_TOPMOST) 恢复正确的 Z 序。
        """
        if not self.isVisible():
            return
        hwnd = ctypes.wintypes.HWND(int(self.winId()))
        _user32.SetWindowPos(
            hwnd,
            ctypes.wintypes.HWND(HWND_TOPMOST),
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )

    def _set_window_position(self, x, y):
        """移动窗口，通过 SWP_NOZORDER 确保不改变 Z 序。

        置顶状态由 Qt.WindowStaysOnTopHint 在创建时设置的 WS_EX_TOPMOST 样式
        以及周期性 SetWindowPos(HWND_TOPMOST) 调用共同维持，移动操作本身不触碰 Z 序。
        """
        hwnd = ctypes.wintypes.HWND(int(self.winId()))
        _user32.SetWindowPos(
            hwnd, 0,
            x, y, 0, 0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )

    def paintEvent(self, event):
        """实时旋转绘制宠物图片，避免每帧生成新的 pixmap。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        center = self.window_size / 2
        painter.translate(center, center)
        painter.rotate(self.final_angle)
        painter.drawPixmap(
            int(-self.base_width / 2),
            int(-self.base_height / 2),
            self.scaled_pixmap,
        )

    def update_animation(self):
        """单帧动画编排：变向变速、位移、边界反弹、视觉计算、移动窗口。"""
        self.anim_frame += 1
        self._step_heading()
        self._step_position()
        self._update_visuals()
        self._move_window()

    def _step_heading(self):
        """按间隔随机改变方向与速度。"""
        self.direction_change_timer += 1
        if self.direction_change_timer < self.direction_change_interval:
            return
        self.direction_change_timer = 0
        self.direction_change_interval = random.randint(
            self.config.direction_change_interval_min,
            self.config.direction_change_interval_max,
        )
        self.direction = self._next_direction()
        self.speed = random.uniform(
            self.config.speed_change_min, self.config.speed_change_max,
        )

    def _next_direction(self):
        """按概率选择大转向或微调，返回新方向。"""
        if random.random() < self.config.sharp_turn_probability:
            delta = random.uniform(
                -math.pi * self.config.sharp_turn_range,
                math.pi * self.config.sharp_turn_range,
            )
        else:
            delta = random.uniform(
                -self.config.slight_turn_range,
                self.config.slight_turn_range,
            )
        return self.direction + delta

    def _step_position(self):
        """计算位移并在触及边界时反弹。"""
        self.pos_x, self.pos_y = step_position(
            self.pos_x, self.pos_y, self.direction, self.speed,
        )
        self.pos_x, self.pos_y, self.direction = reflect_at_boundary(
            self.pos_x, self.pos_y, self.direction,
            self.bound_x, self.bound_y,
        )

    def _update_visuals(self):
        """计算颠簸偏移、倾斜偏移与朝向角度。"""
        bob_freq = self.speed * self.bob_freq_factor
        self.bob_offset = (
            math.sin(self.anim_frame * bob_freq) * self.bob_amplitude
        )
        tilt_offset = (
            math.sin(self.anim_frame * bob_freq * TILT_HARMONIC_MULTIPLIER)
            * self.tilt_amplitude
        )
        facing_deg = compute_facing_deg(self.direction, self.head_heading_deg)
        self.final_angle = facing_deg + tilt_offset

    def _move_window(self):
        """移动窗口到当前帧的坐标，Z 序由独立的定时器维持。"""
        horizontal_offset = (self.window_size - self.base_width) / 2
        vertical_offset = (self.window_size - self.base_height) / 2
        new_x = int(self.pos_x - horizontal_offset)
        new_y = int(self.pos_y - vertical_offset + self.bob_offset)
        self._set_window_position(new_x, new_y)
        self.update()

    def mousePressEvent(self, event):
        """记录拖拽起点偏移。"""
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """左键拖动窗口，使用原生 SetWindowPos 避免破坏 HWND_TOPMOST 状态。"""
        if event.buttons() & Qt.LeftButton and self.drag_pos is not None:
            top_left = event.globalPos() - self.drag_pos
            self.pos_x = top_left.x() + (self.window_size - self.base_width) / 2
            self.pos_y = top_left.y() + (self.window_size - self.base_height) / 2
            self._set_window_position(top_left.x(), top_left.y())
            event.accept()

    def closeEvent(self, event):
        """关闭时注销热键、停止动画与置顶定时器。"""
        try:
            self.animation_timer.stop()
            self._topmost_timer.stop()
            _user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID)
        except OSError as exc:
            logger.debug("关闭时清理资源异常: %s", exc)
        event.accept()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    if sys.platform != "win32":
        logger.error("DesktopPet 仅支持 Windows。")
        sys.exit(1)
    app = QApplication(sys.argv)
    try:
        pet = DesktopPet()
    except ConfigError as exc:
        logger.error("初始化失败: %s", exc)
        sys.exit(1)
    pet.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
