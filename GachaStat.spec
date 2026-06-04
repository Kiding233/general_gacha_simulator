# -*- mode: python ; coding: utf-8 -*-
"""GachaStat PyInstaller 构建配置 —— 文件夹分发（onedir）模式"""

import os
import sys
from pathlib import Path

_SPEC_DIR = Path(SPECPATH)


a = Analysis(
    ['gacha_simulator/main.py'],

    pathex=[str(_SPEC_DIR)],

    binaries=[],

    datas=[
        ('gacha_simulator/config', 'config'),
        ('gacha_simulator/resources', 'resources'),
    ],

    hiddenimports=[
        # Qt WebEngine
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',

        # scipy C 扩展
        'scipy.special._ufuncs',
        'scipy.stats._stats',
        'scipy.stats._stats_mstats_common',
        'scipy.optimize._lbfgsb',
        'scipy.optimize._trlib',

        # 项目内部——动态/惰性导入模块
        'gacha_simulator.core.streaming',
        'gacha_simulator.core.comparison_analyzer',
        'gacha_simulator.core.result_store',
        'gacha_simulator.core.process_trace',
        'gacha_simulator.core.process_analysis',
        'gacha_simulator.core.bootstrap',
        'gacha_simulator.core.gdr_analysis',
        'gacha_simulator.core.forward_backward',
        'gacha_simulator.core.vulnerability',
        'gacha_simulator.core.worst_impact',
        'gacha_simulator.core.per_pool_analysis',
        'gacha_simulator.core.risk_analysis',

        # 图表渲染——analysis_panel 函数体内惰性导入
        'gacha_simulator.visualization.chart_spec',
        'gacha_simulator.visualization.plotly_charts',

        # 排期生成器
        'gacha_simulator.generator.schedule_generator',
        'gacha_simulator.generator.target_generator',
    ],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],

    excludes=[
        'tkinter',
        'sqlite3',
        'PyQt6.QtBluetooth',
        'PyQt6.QtDBus',
        'PyQt6.QtNfc',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.QtTest',
        # 未使用的传递依赖
        'pandas',
        'statsmodels',
        'lxml',
        'numba',
        'llvmlite',
        # font_config.py 惰性导入——无调用方，可安全排除
        'matplotlib',
        'PIL',
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)


# ── 过滤未使用的 Qt6 C++ DLL ──────────────────────────────────────────
# QtWebEngine 依赖链已包含所有必需 DLL，以下为确定不需要的模块。
_QT_DLL_EXCLUDE_PREFIXES = [
    'Qt6Pdf', 'Qt6PdfQuick',
    'Qt6Quick3D',             # 3D 渲染（含 RuntimeRender/Physics/Particles/Xr/Asset* 等）
    'Qt6Multimedia', 'Qt6MultimediaQuick',
    'Qt6SpatialAudio',
    'Qt6Sensors', 'Qt6SensorsQuick',
    'Qt6SerialPort',
    'Qt6Test', 'Qt6QuickTest',
    'Qt6TextToSpeech',
    'Qt6RemoteObjects',
    'Qt6StateMachine',
    'Qt6QuickTimeline',
    'Qt6QuickShapes',
    'Qt6QuickEffects',
    'Qt6QuickParticles',
    'Qt6QuickVectorImage',
    'Qt6Svg',
    # 额外 QML 皮肤（项目只使用默认 Fusion 风格）
    'Qt6QuickControls2Imagine',
    'Qt6QuickControls2Material',
    'Qt6QuickControls2Universal',
]

a.binaries = [
    (name, path, typ)
    for (name, path, typ) in a.binaries
    if not any(os.path.basename(name).startswith(prefix) for prefix in _QT_DLL_EXCLUDE_PREFIXES)
]

# ── 过滤 plotly 无用数据 + 未使用的 Qt QML 目录 ────────────────────
# widgetbundle.js: Jupyter Notebook 插件（桌面应用不需要）
# datasets/: 内置示例数据（gapminder.csv, election.csv 等）
_PLOTLY_EXCLUDE_PREFIXES = [
    'plotly/package_data/widgetbundle.js',
]
_PLOTLY_EXCLUDE_DIRS = [
    'plotly/package_data/datasets/',
]
_QT_QML_EXCLUDE_DIRS = [
    'PyQt6/Qt6/qml/QtMultimedia/',
    'PyQt6/Qt6/qml/QtQuick3D/',
    'PyQt6/Qt6/qml/QtSensors/',
    'PyQt6/Qt6/qml/QtTest/',
    'PyQt6/Qt6/qml/QtTextToSpeech/',
    'PyQt6/Qt6/qml/QtRemoteObjects/',
]

a.datas = [
    (name, path, typ)
    for (name, path, typ) in a.datas
    if name.replace('\\', '/') not in _PLOTLY_EXCLUDE_PREFIXES
    and not any(name.replace('\\', '/').startswith(d) for d in _PLOTLY_EXCLUDE_DIRS)
    and not any(name.replace('\\', '/').startswith(d) for d in _QT_QML_EXCLUDE_DIRS)
]


pyz = PYZ(a.pure, a.zipped_data, cipher=None)


exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GachaStat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_SPEC_DIR / 'gacha_simulator' / 'resources' / 'app_icon.png'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GachaStat',
)
