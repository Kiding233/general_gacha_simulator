import os

_FONT_CONFIGURED = False

FONT_SEARCH_PATHS = [
    os.path.expanduser('~/.fonts'),
    '/usr/share/fonts/truetype',
    '/usr/local/share/fonts',
    '/usr/share/fonts/opentype',
]

CHINESE_FONT_PATTERNS = [
    'LXGWWenKai',
    'NotoSansCJK',
    'NotoSerifCJK',
    'SourceHanSans',
    'SourceHanSerif',
    'WenQuanYi',
    'SimHei',
    'SimSun',
    'Microsoft YaHei',
    'PingFang',
    'STHeiti',
    'STSong',
    'AR PL',
    'Droid Sans Fallback',
]


def _find_chinese_font():
    for search_dir in FONT_SEARCH_PATHS:
        if not os.path.isdir(search_dir):
            continue
        for root, dirs, files in os.walk(search_dir):
            for fname in files:
                if fname.endswith(('.ttf', '.otf', '.ttc')):
                    for pattern in CHINESE_FONT_PATTERNS:
                        if pattern.lower() in fname.lower():
                            return os.path.join(root, fname)
    return None


def configure_chinese_font():
    """配置 matplotlib 中文字体（惰性导入——仅调用时加载 matplotlib）。"""
    global _FONT_CONFIGURED
    if _FONT_CONFIGURED:
        return

    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    font_path = _find_chinese_font()

    font_name = None
    if font_path:
        try:
            fm.fontManager.addfont(font_path)
            prop = fm.FontProperties(fname=font_path)
            font_name = prop.get_name()
        except Exception:
            pass

    if font_name:
        plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
    else:
        for pattern in CHINESE_FONT_PATTERNS:
            plt.rcParams['font.sans-serif'] = [pattern] + plt.rcParams['font.sans-serif']

    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.unicode_minus'] = False

    _FONT_CONFIGURED = True
