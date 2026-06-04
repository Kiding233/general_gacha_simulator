# gacha_simulator/paths.py
"""路径解析工具——同时支持开发环境和 PyInstaller 打包环境。

只读路径（捆绑资源）：
    get_config_dir()           → config/
    get_resource(filename)     → resources/

可写路径（用户数据）：
    get_user_data_dir(*subdirs) → 开发: 包内子目录 / 打包: %APPDATA%/GachaStat/
"""

import os
import sys


def get_base_dir() -> str:
    """返回应用根目录（只读——捆绑的资源文件）。

    开发环境：paths.py 所在目录（= gacha_simulator/ 包目录）
    打包环境：sys._MEIPASS（PyInstaller 的 _internal/ 目录）
    """
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_config_dir() -> str:
    """返回默认配置目录的绝对路径（只读——捆绑的默认配置）。"""
    return os.path.join(get_base_dir(), 'config')


def get_resource(filename: str) -> str:
    """返回 resources/ 目录下指定文件的绝对路径（只读——捆绑的资源）。"""
    return os.path.join(get_base_dir(), 'resources', filename)


def get_user_data_dir(*subdirs: str) -> str:
    """返回用户数据目录的绝对路径（可写——用户生成的数据）。

    开发环境：paths.py 所在目录下的对应子目录
    打包环境：%APPDATA%/GachaStat/ 下的对应子目录
    自动创建目录（exist_ok=True）。

    用法：
        get_user_data_dir()                    → %APPDATA%/GachaStat/
        get_user_data_dir('output')            → %APPDATA%/GachaStat/output/
        get_user_data_dir('output', 'analysis') → %APPDATA%/GachaStat/output/analysis/
    """
    if getattr(sys, 'frozen', False):
        base = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'GachaStat')
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(base, *subdirs)
    os.makedirs(target, exist_ok=True)
    return target
