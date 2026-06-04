# -*- mode: python ; coding: utf-8 -*-
"""GachaStat PyInstaller 构建配置 —— 文件夹分发（onedir）模式"""

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

        # matplotlib 后端
        'matplotlib.backends.backend_qtagg',

        # scipy C 扩展（首版构建后根据 ImportError 补充）
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
        'test',
        'unittest',
        'pytest',
        'pdb',
        'distutils',
        'PyQt6.QtBluetooth',
        'PyQt6.QtDBus',
        'PyQt6.QtNfc',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.QtTest',
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)


pyz = PYZ(a.pure, a.zipped_data, cipher=None)


exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
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
