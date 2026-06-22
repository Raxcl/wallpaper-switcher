#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
壁纸切换工具 - GUI 版
功能：预览、切换、下载、设置壁纸，自动切换，自定义设置
"""

import os
import io
import sys
import json
import time
import queue
import random
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import datetime

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from PIL import Image, ImageTk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

import ctypes

# ─────────────────────── 路径 ───────────────────────

if getattr(sys, 'frozen', False):
    # PyInstaller 打包后：可写文件放在 exe 同级目录
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_FILE = BASE_DIR / 'config.json'
HISTORY_FILE = BASE_DIR / 'history.json'
CACHE_DIR = BASE_DIR / 'cache'
LOG_FILE = BASE_DIR / 'wallpaper_gui.log'
MAX_WALLPAPER_CACHE = 50  # 壁纸列表最大缓存数量

# ─────────────────────── 日志 ───────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

# ─────────────────────── 配置 ───────────────────────

DEFAULT_CONFIG = {
    'token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE4MTMxMjEzMDYsInByaW1hcnlLZXkiOiJ3YWxscGFwZXJfdG9rZW5fMWVlZTNiZDYxOV8xMDEifQ.dUy299AQ0lI6UWqEhEIDnUQc2oUO5ZqzAhQqt57SFmU',
    'interval_minutes': 30,
    'api_url': 'https://api.soutushenqi.com/api/wallpaper/common/randomWallpaper',
    'page_size': 10,
    'max_retries': 3,
    'timeout': 15,
    'download_dir': str(BASE_DIR / 'downloads'),
    'auto_switch': False,
    'source': 'bing',
    'fetch_count': 10,
    'pexels_key': 'S8lTXaFWEPTTfXRPpfCG2fsNfudReoDDm234hkSf0DLjL6BPmdIDIvSz',
    'pixabay_key': '',
}


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                config.setdefault(k, v)
            return config
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-200:], f, indent=2, ensure_ascii=False)


# ─────────────────────── API ───────────────────────

KNOWN_DEAD = {'img.hb.aicdn.com', 'gd-hbimg.huaban.com'}


def _is_dead_url(url):
    """快速判断 URL 是否来自已知失效域名"""
    if not url:
        return True
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname in KNOWN_DEAD
    except Exception:
        return False


def fetch_wallpapers(config):
    headers = {
        'Content-Type': 'application/json',
        'token': config['token'],
        'timestamp': str(int(time.time() * 1000)),
    }
    payload = {
        'pageSize': config['page_size'],
        'horizontalScreen': 1,
        'isOperation': 1,
    }
    try:
        r = requests.post(config['api_url'], headers=headers, json=payload, timeout=config['timeout'], verify=False)
        r.raise_for_status()
        data = r.json()
        if data.get('code') == 200 and data.get('data'):
            return data['data']
    except Exception as e:
        logger.error(f"获取壁纸列表失败: {e}")
    return []


def _normalize_wp(d, large_url, thumb_url, source_tag):
    """将不同来源的数据统一为标准壁纸 dict"""
    wid = d.get('id') or d.get('startdate') or d.get('urlbase', '')
    return {
        'id': f"{source_tag}_{wid}",
        'title': d.get('title', '') or d.get('copyright', '') or '',
        'width': d.get('width', 0),
        'height': d.get('height', 0),
        'tagList': [],
        'largeUrl': large_url,
        'thumbUrl': thumb_url,
    }


def fetch_bing_wallpapers(config):
    """Bing 每日壁纸，无需 API Key，每天最多取 8 张"""
    try:
        url = 'https://cn.bing.com/HPImageArchive.aspx?format=js&idx=0&n=8&mkt=zh-CN'
        r = requests.get(url, timeout=config['timeout'], verify=False)
        r.raise_for_status()
        data = r.json()
        images = data.get('images', [])
        result = []
        for img in images:
            urlbase = img.get('urlbase', '')
            if not urlbase:
                continue
            large = f"https://www.bing.com{urlbase}_1920x1080.jpg"
            thumb = f"https://www.bing.com{urlbase}_1920x1080.jpg"
            img['width'] = 3840
            img['height'] = 2160
            result.append(_normalize_wp(img, large, thumb, 'bing'))
        return result
    except Exception as e:
        logger.error(f"Bing 壁纸获取失败: {e}")
        return []


def fetch_pexels_wallpapers(config, page=1):
    """Pexels 壁纸，需要 API Key"""
    key = config.get('pexels_key', '') or DEFAULT_CONFIG['pexels_key']
    if not key:
        return []
    try:
        headers = {'Authorization': key}
        queries = ['nature', 'landscape', 'mountain', 'ocean', 'city',
                   'forest', 'sky', 'architecture', 'abstract', 'space']
        q = random.choice(queries)
        params = {
            'query': q,
            'orientation': 'landscape',
            'size': 'large',
            'per_page': 15,
            'page': page,
        }
        r = requests.get('https://api.pexels.com/v1/search',
                         headers=headers, params=params, timeout=config['timeout'], verify=False)
        r.raise_for_status()
        data = r.json()
        result = []
        for photo in data.get('photos', []):
            src = photo.get('src', {})
            result.append(_normalize_wp(photo, src.get('large2x', ''),
                                        src.get('tiny', ''), 'pexels'))
        return result
    except Exception as e:
        logger.error(f"Pexels 壁纸获取失败: {e}")
        return []


def fetch_pixabay_wallpapers(config, page=1):
    """Pixabay 壁纸，需要 API Key"""
    key = config.get('pixabay_key', '')
    if not key:
        return []
    try:
        queries = ['nature', 'landscape', 'mountain', 'ocean', 'sunset',
                   'forest', 'city', 'flowers', 'aurora', 'stars']
        q = random.choice(queries)
        params = {
            'key': key,
            'q': q,
            'image_type': 'photo',
            'orientation': 'horizontal',
            'min_width': 1920,
            'min_height': 1080,
            'per_page': 20,
            'page': page,
        }
        r = requests.get('https://pixabay.com/api/',
                         params=params, timeout=config['timeout'], verify=False)
        r.raise_for_status()
        data = r.json()
        result = []
        for hit in data.get('hits', []):
            result.append(_normalize_wp(hit, hit.get('largeImageURL', ''),
                                        hit.get('webformatURL', ''), 'pixabay'))
        return result
    except Exception as e:
        logger.error(f"Pixabay 壁纸获取失败: {e}")
        return []


def download_image_bytes(url, config):
    """下载图片，返回 (bytes, PIL.Image) 或 None"""
    if not url or not url.startswith('http'):
        logger.debug(f"跳过无效 URL: {url}")
        return None
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname
        if hostname in KNOWN_DEAD:
            logger.debug(f"跳过已知失效域名: {hostname}")
            return None
    except Exception:
        pass
    try:
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://huaban.com/',
        }, timeout=config['timeout'], verify=False)
        if r.status_code != 200:
            logger.warning(f"下载失败 HTTP {r.status_code}: {url[:80]}")
            return None
        if len(r.content) < 1024:
            logger.warning(f"下载内容过小 ({len(r.content)} bytes): {url[:80]}")
            return None
        img = Image.open(io.BytesIO(r.content))
        img.load()  # 强制加载全部数据
        img = img.convert('RGB')
        logger.debug(f"下载成功 {img.size[0]}x{img.size[1]} ({len(r.content)//1024}KB): {url[:80]}")
        return r.content, img
    except Exception as e:
        logger.warning(f"下载异常 {type(e).__name__}: {url[:80]}")
        return None


def set_desktop_wallpaper(path):
    try:
        return bool(ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3))
    except Exception:
        return False


# ─────────────────────── Wallpaper ───────────────────────

class Wallpaper:
    __slots__ = ('id', 'title', 'width', 'height', 'tags', 'large_url', 'thumb_url')

    def __init__(self, d):
        self.id = d['id']
        self.title = d.get('title') or ''
        self.width = d.get('width', 0)
        self.height = d.get('height', 0)
        raw_tags = d.get('tagList', '[]')
        try:
            self.tags = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
        except Exception:
            self.tags = []
        self.large_url = d.get('largeUrl', '')
        self.thumb_url = d.get('thumbUrl', '')


# ═════════════════════════════════════════════════════════
#                      GUI 主类
# ═════════════════════════════════════════════════════════

class WallpaperApp:
    # 预览区域目标尺寸
    PREVIEW_W = 700
    PREVIEW_H = 400
    THUMB_SIZE = (120, 68)

    # 配色
    C_BG = '#f5f6fa'
    C_CARD = '#ffffff'
    C_ACCENT = '#5b6abf'      # 主色 靛蓝紫
    C_ACCENT_HOVER = '#4a59a8'
    C_SUCCESS = '#2ecc71'
    C_TEXT = '#2c3e50'
    C_TEXT_LIGHT = '#95a5a6'
    C_PREVIEW_BG = '#dfe6e9'
    C_THUMB_BG = '#ecf0f1'

    def __init__(self):
        self.config = load_config()
        self.history = load_history()
        self.wallpapers = []
        self.pil_images = {}
        self.large_pil_images = {}
        self.tk_images = {}
        self._loading_large_for = -1
        self.current_index = 0
        self.download_dir = Path(self.config.get('download_dir', str(BASE_DIR / 'downloads')))
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.auto_switch_on = self.config.get('auto_switch', False)
        self.auto_interval = self.config.get('interval_minutes', 30)
        self._auto_job = None
        self._fetching = False
        self._cancel_thumbs = False

        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # ── 窗口 ──
        self.root = ttk.Window(
            title="壁纸切换工具",
            themename="flatly",
            size=(1060, 800),
            minsize=(860, 640),
        )
        self.root.configure(bg=self.C_BG)
        self.root.place_window_center()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_styles()
        self._build_ui()

        self.root.after(200, self.do_fetch)

    # ──────────────── 自定义样式 ────────────────

    def _setup_styles(self):
        style = ttk.Style()

        # 全局字体
        default_font = ("Microsoft YaHei UI", 9)

        # 按钮样式
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"),
                         background=self.C_ACCENT, foreground="white")
        style.map("Accent.TButton",
                  background=[("active", self.C_ACCENT_HOVER), ("disabled", "#bdc3c7")])

        style.configure("Set.TButton", font=("Microsoft YaHei UI", 10, "bold"),
                         background=self.C_SUCCESS, foreground="white")
        style.map("Set.TButton",
                  background=[("active", "#27ae60"), ("disabled", "#bdc3c7")])

        style.configure("Nav.TButton", font=("Microsoft YaHei UI", 9))

        # 标签样式
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 14, "bold"),
                         background=self.C_BG, foreground=self.C_TEXT)
        style.configure("Info.TLabel", font=("Microsoft YaHei UI", 9),
                         background=self.C_BG, foreground=self.C_TEXT)
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 8),
                         background=self.C_BG, foreground=self.C_TEXT_LIGHT)
        style.configure("Counter.TLabel", font=("Microsoft YaHei UI", 10, "bold"),
                         background=self.C_BG, foreground=self.C_ACCENT)

    # ──────────────── UI 构建 ────────────────

    def _build_ui(self):
        # ── 顶部栏 ──
        top = ttk.Frame(self.root, style="TFrame", padding=(16, 10))
        top.pack(fill=X)
        ttk.Label(top, text="壁纸切换工具", style="Title.TLabel").pack(side=LEFT)

        self._btn_fetch = ttk.Button(top, text="  获取新壁纸  ", style="Accent.TButton",
                                     command=self.do_fetch)
        self._btn_fetch.pack(side=RIGHT)

        # ── 状态栏（先 pack 到底部，确保可见）──
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(self.root, textvariable=self.status_var,
                 font=("Microsoft YaHei UI", 8), fg=self.C_TEXT_LIGHT,
                 bg=self.C_BG, anchor=W, padx=16, pady=3).pack(fill=X, side=BOTTOM)

        # ── 底部面板（在预览之前 pack，确保不被挤压）──
        bottom = ttk.Frame(self.root, padding=(16, 4))
        bottom.pack(fill=X, side=BOTTOM)

        # 信息 + 操作按钮（一行）
        row1 = ttk.Frame(bottom)
        row1.pack(fill=X, pady=(0, 3))

        self.lbl_title = ttk.Label(row1, text="标题: -", style="Info.TLabel")
        self.lbl_title.pack(side=LEFT)

        self.lbl_counter = ttk.Label(row1, text="0 / 0", style="Counter.TLabel")
        self.lbl_counter.pack(side=RIGHT, padx=(10, 0))

        self.btn_next2 = ttk.Button(row1, text="  下一张  ", style="Nav.TButton",
                                    command=self._go_next)
        self.btn_next2.pack(side=RIGHT, padx=3)
        self.btn_prev2 = ttk.Button(row1, text="  上一张  ", style="Nav.TButton",
                                    command=self._go_prev)
        self.btn_prev2.pack(side=RIGHT, padx=3)

        self.btn_dl = ttk.Button(row1, text="  下载  ", bootstyle="info-outline",
                                 command=self._act_download)
        self.btn_dl.pack(side=RIGHT, padx=3)
        self.btn_set = ttk.Button(row1, text="  设为壁纸  ", style="Set.TButton",
                                  command=self._act_set)
        self.btn_set.pack(side=RIGHT, padx=(0, 6))

        # 分辨率/标签
        self.lbl_info = ttk.Label(bottom, text="", style="Sub.TLabel")
        self.lbl_info.pack(anchor=W, pady=(0, 3))

        # 缩略图条（白底卡片）
        thumb_card = tk.Frame(bottom, bg=self.C_CARD, highlightbackground='#dcdde1',
                              highlightthickness=1)
        thumb_card.pack(fill=X, pady=(0, 4))
        self.thumb_canvas = tk.Canvas(thumb_card, height=74, highlightthickness=0,
                                      bg=self.C_CARD)
        self.thumb_canvas.pack(fill=X, padx=4, pady=(3, 0))

        # 水平滚动条
        self.thumb_scrollbar = ttk.Scrollbar(thumb_card, orient=HORIZONTAL,
                                              command=self.thumb_canvas.xview,
                                              bootstyle="secondary")
        self.thumb_scrollbar.pack(fill=X, padx=4, pady=(0, 3))
        self.thumb_canvas.configure(xscrollcommand=self.thumb_scrollbar.set)

        # 鼠标滚轮绑定
        self.thumb_canvas.bind('<MouseWheel>', self._on_thumb_scroll)
        self.thumb_canvas.bind('<Enter>', lambda e: self.thumb_canvas.focus_set())

        # 设置行
        settings_row = tk.Frame(bottom, bg=self.C_BG)
        settings_row.pack(fill=X)

        self.auto_var = tk.BooleanVar(value=self.auto_switch_on)
        ttk.Checkbutton(settings_row, text="自动切换", variable=self.auto_var,
                        bootstyle="round-toggle", command=self._toggle_auto).pack(side=LEFT)
        ttk.Label(settings_row, text="间隔:", style="Info.TLabel").pack(side=LEFT, padx=(12, 3))
        self.ent_interval = ttk.Entry(settings_row, width=5, font=("Microsoft YaHei UI", 10))
        self.ent_interval.insert(0, str(self.auto_interval))
        self.ent_interval.pack(side=LEFT)
        ttk.Label(settings_row, text="分钟", style="Sub.TLabel").pack(side=LEFT, padx=(2, 6))
        ttk.Button(settings_row, text="应用", bootstyle="outline",
                   command=self._apply_interval, width=5).pack(side=LEFT)

        ttk.Separator(settings_row, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=10)

        # 壁纸源选择
        ttk.Label(settings_row, text="源:", style="Info.TLabel").pack(side=LEFT)
        source_options = ['Bing 每日', 'Pexels', 'Pixabay', '搜图神器']
        source_values = ['bing', 'pexels', 'pixabay', 'soutu']
        self._source_value_map = dict(zip(source_options, source_values))
        self._source_reverse_map = dict(zip(source_values, source_options))
        current_label = self._source_reverse_map.get(
            self.config.get('source', 'bing'), 'Bing 每日')

        self.source_var = tk.StringVar(value=current_label)
        self.source_combo = ttk.Combobox(
            settings_row, textvariable=self.source_var,
            values=source_options, state='readonly', width=10,
            font=("Microsoft YaHei UI", 9))
        self.source_combo.pack(side=LEFT, padx=4)
        self.source_combo.bind('<<ComboboxSelected>>', self._on_source_change)

        # 获取数量
        ttk.Label(settings_row, text="数量:", style="Sub.TLabel").pack(side=LEFT, padx=(6, 2))
        self.count_var = tk.StringVar(value=str(self.config.get('fetch_count', 10)))
        self.count_spin = tk.Spinbox(
            settings_row, textvariable=self.count_var,
            from_=1, to=100, width=4,
            font=("Microsoft YaHei UI", 9))
        self.count_spin.pack(side=LEFT, padx=2)
        self.count_spin.bind('<FocusOut>', self._on_count_change)
        self.count_spin.bind('<Return>', self._on_count_change)

        # API Key 输入（按源动态显示）
        self._key_label_pexels = ttk.Label(settings_row, text="Key:", style="Sub.TLabel")
        self._key_ent_pexels = ttk.Entry(settings_row, font=("Microsoft YaHei UI", 9), width=20)
        self._key_ent_pexels.insert(0, self.config.get('pexels_key', ''))

        self._key_label_pixabay = ttk.Label(settings_row, text="Key:", style="Sub.TLabel")
        self._key_ent_pixabay = ttk.Entry(settings_row, font=("Microsoft YaHei UI", 9), width=20)
        self._key_ent_pixabay.insert(0, self.config.get('pixabay_key', ''))

        self._btn_save_keys = ttk.Button(settings_row, text="保存", bootstyle="outline",
                                         command=self._save_keys, width=4)

        # 根据当前源显示对应的 Key 输入框
        self._update_key_visibility()

        ttk.Separator(settings_row, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=10)

        ttk.Label(settings_row, text="下载目录:", style="Sub.TLabel").pack(side=LEFT)
        self.ent_dir = ttk.Entry(settings_row, font=("Microsoft YaHei UI", 9))
        self.ent_dir.insert(0, str(self.download_dir))
        self.ent_dir.pack(side=LEFT, fill=X, expand=True, padx=4)
        ttk.Button(settings_row, text="浏览", bootstyle="outline",
                   command=self._browse_dir, width=5).pack(side=RIGHT)

        # ── 预览区域（最后 pack，填充剩余所有空间）──
        prev_outer = ttk.Frame(self.root, padding=(16, 0))
        prev_outer.pack(fill=BOTH, expand=True)

        # 预览卡片容器（白底 + 细边框）
        self.preview_frame = tk.Frame(prev_outer, bg=self.C_CARD, bd=0,
                                       highlightbackground='#dcdde1',
                                       highlightthickness=1)
        self.preview_frame.pack(fill=BOTH, expand=True)

        # 预览 Canvas
        self.preview_canvas = tk.Canvas(self.preview_frame, highlightthickness=0,
                                        bg=self.C_PREVIEW_BG)
        self.preview_canvas.pack(fill=BOTH, expand=True, padx=1, pady=1)
        self._canvas_img_id = None
        self.preview_canvas.bind('<Configure>', self._on_canvas_resize)

        # 高清加载提示（浮在预览区右下角）
        self._hd_loading_label = tk.Label(
            self.preview_canvas, text="加载高清中...",
            font=("Microsoft YaHei UI", 9), fg='white', bg='#333333',
            padx=8, pady=3)

    # ──────────────── 获取壁纸 ────────────────

    def do_fetch(self):
        if self._fetching:
            return
        self._fetching = True
        self._btn_fetch.configure(state=DISABLED, text="  获取中...  ")
        self._set_status("正在获取壁纸列表...")
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self):
        """多源获取壁纸，自动 fallback 到其他源"""
        source = self.config.get('source', 'bing')
        sources_order = {
            'bing':   ['bing', 'pexels', 'pixabay', 'soutu'],
            'pexels': ['pexels', 'pixabay', 'bing', 'soutu'],
            'pixabay':['pixabay', 'pexels', 'bing', 'soutu'],
            'soutu':  ['soutu', 'bing', 'pexels', 'pixabay'],
        }
        order = sources_order.get(source, sources_order['bing'])
        target_count = self.config.get('fetch_count', 10)
        seen_ids = set(w.id for w in self.wallpapers)
        valid_wps = []

        for src in order:
            if src == 'bing':
                raw_list = fetch_bing_wallpapers(self.config)
            elif src == 'pexels':
                page = random.randint(1, 5)
                raw_list = fetch_pexels_wallpapers(self.config, page=page)
            elif src == 'pixabay':
                page = random.randint(1, 5)
                raw_list = fetch_pixabay_wallpapers(self.config, page=page)
            else:
                # 搜图神器：请求数量与目标数量一致
                orig_size = self.config.get('page_size', 10)
                self.config['page_size'] = max(target_count, 10)
                raw_list = fetch_wallpapers(self.config)
                self.config['page_size'] = orig_size

            if not raw_list:
                continue

            source_name = {'bing': 'Bing', 'pexels': 'Pexels',
                           'pixabay': 'Pixabay', 'soutu': '搜图神器'}
            self.root.after(0, lambda n=source_name.get(src, src):
                            self._set_status(f"正在从 {n} 获取壁纸..."))

            for d in raw_list:
                if d.get('id') in seen_ids:
                    continue
                seen_ids.add(d.get('id'))

                large_url = d.get('largeUrl', '')
                thumb_url = d.get('thumbUrl', '')
                # 大图域名已死 → 不可能有高清预览，直接跳过
                if _is_dead_url(large_url):
                    continue

                valid_wps.append(d)
                if len(valid_wps) >= target_count:
                    self.root.after(0, lambda n=len(valid_wps): self._set_status(
                        f"已从 {source_name.get(src, src)} 获取 {n} 张壁纸"))
                    self.root.after(0, lambda v=valid_wps[:]: self._on_fetched(v))
                    return

        self.root.after(0, lambda v=valid_wps[:]: self._on_fetched(v))

    def _on_fetched(self, raw_list):
        self._fetching = False
        self._btn_fetch.configure(state=NORMAL, text="  获取新壁纸  ")

        # 取消正在运行的缩略图加载线程
        self._cancel_thumbs = True

        if not raw_list:
            self._set_status("未获取到有效壁纸，请检查网络或 token")
            return

        new_wallpapers = [Wallpaper(d) for d in raw_list]

        # 去重：排除已有壁纸
        existing_ids = set(w.id for w in self.wallpapers)
        truly_new = [w for w in new_wallpapers if w.id not in existing_ids]

        if not truly_new:
            self._cancel_thumbs = False
            self._set_status("没有新的壁纸")
            return

        # 追加到现有列表
        self.wallpapers.extend(truly_new)

        # 超过上限时裁剪最旧的，并标记需要全量重载缩略图
        need_full_reload = False
        if len(self.wallpapers) > MAX_WALLPAPER_CACHE:
            self.wallpapers = self.wallpapers[-MAX_WALLPAPER_CACHE:]
            self.pil_images.clear()
            self.large_pil_images.clear()
            self.tk_images.clear()
            need_full_reload = True

        # 导航到第一张新壁纸
        self.current_index = len(self.wallpapers) - len(truly_new)
        self._cancel_thumbs = False

        self._set_status(
            f"新增 {len(truly_new)} 张壁纸，共 {len(self.wallpapers)} 张，"
            f"正在加载缩略图...")

        # 裁剪后需要全量重载；否则只加载新壁纸的缩略图
        load_start = 0 if need_full_reload else self.current_index
        threading.Thread(target=self._load_thumbs_thread,
                         args=(load_start,), daemon=True).start()

    def _load_thumbs_thread(self, start_idx=0):
        # 快照当前壁纸列表，避免其他线程修改导致索引错乱
        wps = list(self.wallpapers)
        total = len(wps)
        count = total - start_idx

        for idx in range(start_idx, total):
            if self._cancel_thumbs:
                return
            wp = wps[idx]
            result = download_image_bytes(wp.thumb_url or wp.large_url, self.config)
            if result:
                _bytes, img = result
                thumb = img.copy()
                thumb.thumbnail(self.THUMB_SIZE, Image.LANCZOS)
                self.pil_images[idx] = thumb
                self.root.after(0, self._refresh_thumbs)
                # 第一张新缩略图加载完成时立即显示预览
                if idx == start_idx:
                    self.root.after(0, lambda i=idx: self._on_first_thumb(i))
            self.root.after(0, lambda i=idx, c=count: self._set_status(
                f"加载缩略图 {i - start_idx + 1}/{c}..."))

        self.root.after(0, self._on_thumbs_done)

    def _on_first_thumb(self, idx):
        """第一张缩略图加载完成，立即切换显示"""
        if self.current_index not in self.pil_images:
            self.current_index = idx
        self._update_preview()

    def _on_thumbs_done(self):
        self._refresh_thumbs()
        # 如果当前索引没有缩略图，自动跳到第一张已加载的
        if self.current_index not in self.pil_images and self.pil_images:
            self.current_index = min(self.pil_images.keys())
        self._update_preview()
        self._set_status(f"就绪 - 共 {len(self.wallpapers)} 张壁纸，{len(self.pil_images)} 张加载成功")
        # 后台预加载所有大图
        self._cancel_thumbs = False
        threading.Thread(target=self._preload_large_thread, daemon=True).start()

    def _preload_large_thread(self):
        """后台预加载所有壁纸的大图"""
        wps = list(self.wallpapers)
        total = len(wps)
        loaded = 0
        failed_indices = []
        logger.info(f"开始预加载大图，共 {total} 张")
        for idx in range(total):
            if self._cancel_thumbs:
                logger.info(f"预加载被取消，已加载 {loaded}/{total}")
                return
            if idx in self.large_pil_images:
                loaded += 1
                continue
            # 跳过正在被单独加载的当前选中项
            if idx == self._loading_large_for:
                continue
            wp = wps[idx]
            # 只尝试大图 URL，缩略图已经在 _load_thumbs_thread 里缓存好了
            result = download_image_bytes(wp.large_url, self.config) if wp.large_url else None
            if result:
                _bytes, img = result
                self.large_pil_images[idx] = img
                loaded += 1
                logger.debug(f"[{idx}] ID:{wp.id} 大图预加载成功 {img.size[0]}x{img.size[1]}")
                # 如果是当前选中项，立即更新预览
                if idx == self.current_index:
                    self.root.after(0, lambda i=idx: self._on_large_loaded(i))
            else:
                # 大图不可用，移除该壁纸（列表只保留高清图）
                failed_indices.append(idx)
                logger.warning(f"[{idx}] ID:{wp.id} 大图不可用，将被移除")
            self.root.after(0, lambda l=loaded, t=total: self._set_status(
                f"预加载高清图 {l}/{t}..."))

        # 移除没有高清图的壁纸
        if failed_indices:
            self.root.after(0, lambda: self._remove_failed_wallpapers(failed_indices))

        logger.info(f"预加载完成，成功 {loaded}/{total}，失败 {len(failed_indices)}")
        self.root.after(0, lambda: self._set_status(
            f"就绪 - 共 {len(self.wallpapers)} 张壁纸，{len(self.large_pil_images)} 张高清图已加载"))

    def _remove_failed_wallpapers(self, failed_indices):
        """移除没有高清图的壁纸，只保留能看高清的"""
        failed_set = set(failed_indices)
        count = len(failed_indices)
        self.wallpapers = [wp for i, wp in enumerate(self.wallpapers) if i not in failed_set]
        # 清空缓存，重新加载缩略图（因为索引已变）
        self.pil_images.clear()
        self.large_pil_images.clear()
        self.tk_images.clear()
        self.current_index = min(self.current_index, max(0, len(self.wallpapers) - 1))
        if self.wallpapers:
            self._cancel_thumbs = False
            threading.Thread(target=self._load_thumbs_thread, args=(0,), daemon=True).start()
        logger.info(f"已移除 {count} 张不可用壁纸，重新加载剩余 {len(self.wallpapers)} 张缩略图")

    # ──────────────── 缩略图栏 ────────────────

    def _on_thumb_scroll(self, event):
        """鼠标滚轮水平滚动缩略图栏"""
        self.thumb_canvas.xview_scroll(-1 * (event.delta // 120), "units")

    def _refresh_thumbs(self):
        c = self.thumb_canvas
        c.delete('all')

        # 使用 canvas 直接绘制缩略图卡片
        x_offset = 6
        for idx in sorted(self.pil_images.keys()):
            pil = self.pil_images[idx]
            tw, th = pil.size
            is_selected = (idx == self.current_index)

            # 卡片背景 + 边框
            border_color = self.C_ACCENT if is_selected else '#dcdde1'
            border_w = 2 if is_selected else 1
            pad = 3

            x1 = x_offset
            y1 = pad
            x2 = x1 + tw + pad * 2
            y2 = y1 + th + pad * 2

            # 画边框矩形
            c.create_rectangle(x1, y1, x2, y2,
                               outline=border_color, width=border_w, fill=self.C_CARD)

            # 贴图片
            tkimg = ImageTk.PhotoImage(pil)
            self.tk_images[('thumb', idx)] = tkimg
            c.create_image(x1 + pad, y1 + pad, image=tkimg, anchor=NW,
                           tags=f'thumb_{idx}')

            # 点击绑定
            c.tag_bind(f'thumb_{idx}', '<Button-1>', lambda e, i=idx: self._select(i))

            x_offset = x2 + 6

        # 更新滚动区域
        c.configure(scrollregion=(0, 0, x_offset, 74))

        # 自动滚动到当前选中项
        if self.current_index in self.pil_images and x_offset > 0:
            # 计算选中项的大致 x 位置并滚动到视野中
            sorted_keys = sorted(self.pil_images.keys())
            pos = sorted_keys.index(self.current_index)
            if len(sorted_keys) > 1:
                frac = pos / (len(sorted_keys) - 1) if len(sorted_keys) > 1 else 0
                # 让选中项居中显示
                canvas_width = c.winfo_width()
                if canvas_width <= 1:
                    canvas_width = 800
                view_frac = canvas_width / x_offset if x_offset > 0 else 1
                target = max(0, min(frac - view_frac / 2, 1 - view_frac))
                c.xview_moveto(target)

    # ──────────────── 预览 ────────────────

    def _update_preview(self):
        if not self.wallpapers:
            return
        idx = self.current_index
        wp = self.wallpapers[idx]

        # 先立即显示缩略图（放大版）作为快速预览
        if idx in self.pil_images:
            self._show_preview_pil(self.pil_images[idx])
        else:
            # 没有缩略图时清空 canvas，不显示任何占位符
            if self._canvas_img_id:
                self.preview_canvas.delete(self._canvas_img_id)
                self._canvas_img_id = None

        # 如果大图已缓存，直接显示大图
        if idx in self.large_pil_images:
            self._show_preview_pil(self.large_pil_images[idx])
            self._hd_loading_label.place_forget()
        else:
            # 后台加载大图，显示加载提示
            self._loading_large_for = idx
            self._hd_loading_label.place(relx=1.0, rely=1.0, anchor='se', x=-10, y=-10)
            threading.Thread(target=self._load_large_thread, args=(idx,), daemon=True).start()

        # 信息
        title = wp.title if wp.title else "无标题"
        self.lbl_title.configure(text=f"标题: {title}")
        tags = ", ".join(wp.tags) if wp.tags else "无"
        self.lbl_info.configure(text=f"{wp.width}x{wp.height}  |  ID: {wp.id}  |  标签: {tags}")
        self.lbl_counter.configure(text=f"{idx + 1} / {len(self.wallpapers)}")

        # 更新缩略图高亮
        self._refresh_thumbs()

    def _show_preview_pil(self, pil):
        """将 PIL 图片以 cover 模式填满预览区 Canvas（裁切多余部分，无灰边）"""
        cw = self.preview_canvas.winfo_width() or 800
        ch = self.preview_canvas.winfo_height() or 500
        if cw < 100 or ch < 100:
            cw, ch = 800, 500

        src_w, src_h = pil.size

        # cover 模式：用 max 比例缩放，确保图片完全覆盖 canvas
        ratio = max(cw / src_w, ch / src_h)
        new_w = int(src_w * ratio)
        new_h = int(src_h * ratio)
        scaled = pil.copy().resize((new_w, new_h), Image.LANCZOS)

        # 居中裁切到 canvas 精确尺寸
        left = (new_w - cw) // 2
        top = (new_h - ch) // 2
        display = scaled.crop((left, top, left + cw, top + ch))

        tkimg = ImageTk.PhotoImage(display)
        self.tk_images['preview'] = tkimg

        # 绘制到 canvas 左上角（已精确裁切，无需居中）
        if self._canvas_img_id:
            self.preview_canvas.delete(self._canvas_img_id)
        self._canvas_img_id = self.preview_canvas.create_image(0, 0, image=tkimg, anchor=NW)

    def _on_canvas_resize(self, event):
        """Canvas 大小变化时重新渲染预览图"""
        if not self.wallpapers:
            return
        idx = self.current_index
        if idx in self.large_pil_images:
            self._show_preview_pil(self.large_pil_images[idx])
        elif idx in self.pil_images:
            self._show_preview_pil(self.pil_images[idx])

    def _load_large_thread(self, idx):
        """后台下载大图，失败则回退到缩略图"""
        if idx >= len(self.wallpapers):
            self.root.after(0, self._hide_hd_loading)
            return
        wp = self.wallpapers[idx]
        # 先尝试大图
        result = None
        if wp.large_url:
            logger.debug(f"[{idx}] ID:{wp.id} 尝试 large_url: {wp.large_url[:60]}")
            result = download_image_bytes(wp.large_url, self.config)
        # 大图失败，回退到缩略图
        if not result and wp.thumb_url:
            logger.debug(f"[{idx}] ID:{wp.id} large 失败，回退 thumb_url: {wp.thumb_url[:60]}")
            result = download_image_bytes(wp.thumb_url, self.config)
        if result and idx == self._loading_large_for:
            _bytes, img = result
            self.large_pil_images[idx] = img
            logger.debug(f"[{idx}] ID:{wp.id} 大图加载成功 {img.size[0]}x{img.size[1]}")
        elif not result:
            logger.warning(f"[{idx}] ID:{wp.id} 大图和缩略图均失败")
        # 无论成功失败都回调，隐藏加载提示
        self.root.after(0, lambda: self._on_large_loaded(idx))

    def _hide_hd_loading(self):
        self._hd_loading_label.place_forget()

    def _on_large_loaded(self, idx):
        """大图加载完成，如果仍是当前选中项则替换预览"""
        self._hd_loading_label.place_forget()
        if idx == self.current_index and idx in self.large_pil_images:
            self._show_preview_pil(self.large_pil_images[idx])

    # ──────────────── 导航 ────────────────

    def _go_prev(self):
        if not self.wallpapers:
            return
        self.current_index = (self.current_index - 1) % len(self.wallpapers)
        self._update_preview()

    def _go_next(self):
        if not self.wallpapers:
            return
        self.current_index = (self.current_index + 1) % len(self.wallpapers)
        self._update_preview()

    def _select(self, idx):
        self.current_index = idx
        self._update_preview()

    # ──────────────── 设为壁纸 ────────────────

    def _act_set(self):
        if not self.wallpapers:
            return
        wp = self.wallpapers[self.current_index]
        self._set_status(f"正在下载并设置壁纸...")
        self.btn_set.configure(state=DISABLED)
        threading.Thread(target=self._set_thread, args=(wp,), daemon=True).start()

    def _set_thread(self, wp):
        result = download_image_bytes(wp.large_url, self.config) if wp.large_url else None
        if not result and wp.thumb_url:
            result = download_image_bytes(wp.thumb_url, self.config)
        if result:
            content, img = result
            path = CACHE_DIR / f"wallpaper_{wp.id}.jpg"
            img.save(str(path), 'JPEG', quality=95)
            ok = set_desktop_wallpaper(path)
            self.history.append({
                'id': wp.id, 'title': wp.title,
                'url': wp.large_url or wp.thumb_url,
                'time': datetime.now().isoformat(),
            })
            save_history(self.history)
            self.root.after(0, lambda: self._on_set_done(ok, wp.id))
        else:
            self.root.after(0, lambda: self._on_set_done(False, wp.id))

    def _on_set_done(self, ok, wid):
        self.btn_set.configure(state=NORMAL)
        if ok:
            self._set_status(f"壁纸设置成功 (ID: {wid})")
        else:
            self._set_status(f"设置壁纸失败，请查看日志")

    # ──────────────── 下载图片 ────────────────

    def _act_download(self):
        if not self.wallpapers:
            return
        wp = self.wallpapers[self.current_index]
        self._set_status("正在下载原图...")
        self.btn_dl.configure(state=DISABLED)
        threading.Thread(target=self._dl_thread, args=(wp,), daemon=True).start()

    def _dl_thread(self, wp):
        result = download_image_bytes(wp.large_url, self.config) if wp.large_url else None
        if not result and wp.thumb_url:
            result = download_image_bytes(wp.thumb_url, self.config)
        if result:
            content, img = result
            safe_title = "".join(c for c in (wp.title or str(wp.id)) if c.isalnum() or c in '._- ')[:40]
            filename = f"{safe_title}_{wp.id}.jpg"
            path = self.download_dir / filename
            img.save(str(path), 'JPEG', quality=95)
            self.root.after(0, lambda: self._on_dl_done(True, path))
        else:
            self.root.after(0, lambda: self._on_dl_done(False, None))

    def _on_dl_done(self, ok, path):
        self.btn_dl.configure(state=NORMAL)
        if ok:
            self._set_status(f"已保存: {path}")
        else:
            self._set_status("下载失败")

    # ──────────────── 设置面板 ────────────────

    def _on_source_change(self, event=None):
        label = self.source_var.get()
        value = self._source_value_map.get(label, 'bing')
        self.config['source'] = value
        save_config(self.config)
        name_map = {'bing': 'Bing 每日', 'pexels': 'Pexels',
                    'pixabay': 'Pixabay', 'soutu': '搜图神器'}
        self._set_status(f"壁纸源已切换为 {name_map.get(value, value)}")
        self._update_key_visibility()

    def _on_count_change(self, event=None):
        try:
            count = max(1, min(100, int(self.count_var.get())))
            self.count_var.set(str(count))
            self.config['fetch_count'] = count
            save_config(self.config)
            self._set_status(f"每次获取 {count} 张壁纸")
        except ValueError:
            self.count_var.set(str(self.config.get('fetch_count', 10)))

    def _update_key_visibility(self):
        """根据当前源显示/隐藏对应的 Key 输入框"""
        source = self.config.get('source', 'bing')

        # 先全部隐藏
        self._key_label_pexels.pack_forget()
        self._key_ent_pexels.pack_forget()
        self._key_label_pixabay.pack_forget()
        self._key_ent_pixabay.pack_forget()
        self._btn_save_keys.pack_forget()

        if source == 'pexels':
            self._key_label_pexels.configure(text="Pexels Key:")
            self._key_label_pexels.pack(side=LEFT, padx=(6, 2))
            self._key_ent_pexels.pack(side=LEFT, padx=2)
            self._btn_save_keys.pack(side=LEFT, padx=4)
        elif source == 'pixabay':
            self._key_label_pixabay.configure(text="Pixabay Key:")
            self._key_label_pixabay.pack(side=LEFT, padx=(6, 2))
            self._key_ent_pixabay.pack(side=LEFT, padx=2)
            self._btn_save_keys.pack(side=LEFT, padx=4)

    def _save_keys(self):
        self.config['pexels_key'] = self._key_ent_pexels.get().strip()
        self.config['pixabay_key'] = self._key_ent_pixabay.get().strip()
        save_config(self.config)
        self._set_status("API Key 已保存")

    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.download_dir))
        if d:
            self.ent_dir.delete(0, tk.END)
            self.ent_dir.insert(0, d)
            self.download_dir = Path(d)
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self.config['download_dir'] = str(d)
            save_config(self.config)

    def _apply_interval(self):
        try:
            mins = int(self.ent_interval.get())
            if mins < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "请输入一个正整数（分钟）")
            return
        self.auto_interval = mins
        self.config['interval_minutes'] = mins
        save_config(self.config)
        # 如果自动切换已开启，重启定时器
        if self.auto_switch_on:
            self._cancel_auto_job()
            self._schedule_auto()
        self._set_status(f"切换间隔已设为 {mins} 分钟")

    def _toggle_auto(self):
        self.auto_switch_on = self.auto_var.get()
        self.config['auto_switch'] = self.auto_switch_on
        save_config(self.config)
        if self.auto_switch_on:
            self._schedule_auto()
            self._set_status(f"自动切换已开启（每 {self.auto_interval} 分钟）")
        else:
            self._cancel_auto_job()
            self._set_status("自动切换已关闭")

    def _schedule_auto(self):
        self._auto_job = self.root.after(
            self.auto_interval * 60 * 1000, self._auto_switch_tick)

    def _cancel_auto_job(self):
        if self._auto_job:
            self.root.after_cancel(self._auto_job)
            self._auto_job = None

    def _auto_switch_tick(self):
        if not self.auto_switch_on or not self.wallpapers:
            return
        # 随机选一张
        idx = random.randint(0, len(self.wallpapers) - 1)
        self.current_index = idx
        self._update_preview()
        self._act_set()
        self._schedule_auto()

    # ──────────────── 辅助 ────────────────

    def _set_status(self, text):
        self.status_var.set(text)

    def _on_close(self):
        self.auto_switch_on = False
        self._cancel_auto_job()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ─────────────────────── 入口 ───────────────────────

MUTEX_NAME = r"Global\WallpaperSwitcher_Singleton_v2"


def _acquire_single_instance():
    """使用命名互斥锁确保只运行一个实例。返回 (mutex_handle, is_first)。"""
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return None, False
    return mutex, True


def _activate_existing_window():
    """尝试将已有窗口拉到前台。"""
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    found = []

    def _cb(hwnd, _lp):
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        if 'TkTopLevel' in cls_buf.value:
            title_buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buf, 256)
            if '壁纸' in title_buf.value or '切换' in title_buf.value:
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    if found:
        h = found[0]
        user32.ShowWindow(h, 9)       # SW_RESTORE
        user32.SetForegroundWindow(h)


if __name__ == '__main__':
    mutex, is_first = _acquire_single_instance()
    if not is_first:
        # 已有实例在运行，尝试激活它的窗口
        _activate_existing_window()
        print("[single-instance] Another instance is already running.")
        # 弹窗提示
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("壁纸切换工具", "程序已在运行中，请勿重复启动。")
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

    app = WallpaperApp()
    app.run()

    # 退出时释放互斥锁
    if mutex:
        ctypes.WinDLL('kernel32').CloseHandle(mutex)
