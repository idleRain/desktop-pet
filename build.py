"""打包脚本：调用 PyInstaller 将桌面宠物打包为单文件 exe。

用法：
    python build.py
"""

import os
import sys

# 应用名，决定生成 exe 的文件名。
APP_NAME = "DesktopPet"
# 入口脚本相对路径。
ENTRY_SCRIPT = os.path.join("src", "desktop_pet.py")
# 需要打入 exe 的素材源路径与目标子目录。
ASSET_SOURCE = os.path.join("assets", "pet.png")
ASSET_DEST = "assets"
# 配置文件源路径与目标子目录，打入根目录以便程序按 _MEIPASS 直接读取。
CONFIG_SOURCE = "config.toml"
CONFIG_DEST = "."
# 图标参数取 NONE 表示不嵌入自定义图标，沿用系统默认。
ICON_NONE = "NONE"
# 打包产物所在目录。
DIST_DIR = "dist"


def build():
    """执行 PyInstaller 打包。"""
    try:
        import PyInstaller.__main__
    except ImportError:
        print("未检测到 PyInstaller，请先执行 pip install -r requirements.txt。")
        sys.exit(1)

    # --add-data 的源与目标以系统路径分隔符连接，兼容 Windows 与 Linux。
    add_data = ASSET_SOURCE + os.pathsep + ASSET_DEST
    config_data = CONFIG_SOURCE + os.pathsep + CONFIG_DEST

    args = [
        "--noconfirm",       # 自动覆盖旧产物，避免交互卡顿。
        "--clean",           # 清理 PyInstaller 缓存，强制重新分析依赖，避免新增依赖未被收集。
        "--onefile",         # 打包为单文件。
        "--windowed",        # 生成无控制台窗口的 exe。
        "--name", APP_NAME,
        "--add-data", add_data,
        "--add-data", config_data,
        "--icon", ICON_NONE,
        ENTRY_SCRIPT,
    ]

    print("开始执行打包。")
    code = 0
    try:
        PyInstaller.__main__.run(args)
    except SystemExit as exc:
        # PyInstaller 内部可能调用 sys.exit，此处捕获并转换为统一返回码。
        code = exc.code if isinstance(exc.code, int) else 1

    output_exe = os.path.join(DIST_DIR, APP_NAME + ".exe")
    if code != 0 or not os.path.exists(output_exe):
        print("打包失败，未生成 exe，请检查上方错误信息。")
        sys.exit(1)

    print("打包完成，exe 文件位于 dist 目录。")


if __name__ == "__main__":
    build()
