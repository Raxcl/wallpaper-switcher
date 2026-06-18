#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 壁纸切换工具
来源：搜图神器 API
功能：系统托盘常驻，定时切换壁纸，自动跳过失效链接
"""

import os
import sys
import json
import time
import random
import logging
import threading
from pathlib import Path
from datetime import datetime
import requests
from PIL import Image
import pystray
from pystray import MenuItem as Item

# 基础路径
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / 'config.json'
HISTORY_FILE = BASE_DIR / 'history.json'
CACHE_DIR = BASE_DIR / 'cache'
LOG_FILE = BASE_DIR / 'wallpaper_switcher.log'

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    'token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE4MTMxMjEzMDYsInByaW1hcnlLZXkiOiJ3YWxscGFwZXJfdG9rZW5fMWVlZTNiZDYxOV8xMDEifQ.dUy299AQ0lI6UWqEhEIDnUQc2oUO5ZqzAhQqt57SFmU',
    'interval_minutes': 30,
    'api_url': 'https://api.soutushenqi.com/api/wallpaper/common/randomWallpaper',
    'page_size': 10,
    'max_retries': 3,
    'timeout': 10
}

def load_config():
    """加载配置文件"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

def save_config(config):
    """保存配置文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def load_history():
    """加载历史记录"""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_history(history):
    """保存历史记录"""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-100:], f, indent=2, ensure_ascii=False)  # 只保留最近100条

def fetch_wallpapers(config):
    """从 API 获取壁纸列表"""
    headers = {
        'Content-Type': 'application/json',
        'token': config['token'],
        'timestamp': str(int(time.time() * 1000))
    }
    
    payload = {
        'pageSize': config['page_size'],
        'horizontalScreen': 1,
        'isOperation': 1
    }
    
    try:
        response = requests.post(
            config['api_url'],
            headers=headers,
            json=payload,
            timeout=config['timeout']
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get('code') == 200 and data.get('data'):
            return data['data']
        else:
            logger.error(f"API 返回错误: {data}")
            return []
    except Exception as e:
        logger.error(f"获取壁纸列表失败: {e}")
        return []

def download_image(url, config):
    """下载图片并验证，失败返回 None"""
    if not url or not url.startswith('http'):
        return None
    
    # 已知失效的 CDN 域名，直接跳过节省时间
    KNOWN_DEAD_DOMAINS = ['img.hb.aicdn.com']
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ''
        if domain in KNOWN_DEAD_DOMAINS:
            logger.info(f"跳过已知失效域名: {domain}")
            return None
    except Exception:
        pass
    
    try:
        # 生成缓存文件名
        filename = f"{abs(hash(url))}_{int(time.time())}.jpg"
        filepath = CACHE_DIR / filename
        
        # 下载图片（不 stream，一次性读取方便验证）
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=config['timeout'])
        
        # HTTP 状态码非 200 直接跳过
        if response.status_code != 200:
            logger.warning(f"HTTP {response.status_code}: {url[:100]}")
            return None
        
        content = response.content
        
        # 检查响应体是否太小（CDN 可能返回错误 JSON 而非图片）
        if len(content) < 1024:
            logger.warning(f"响应太小({len(content)}B)，可能不是图片: {url[:100]}")
            return None
        
        # 尝试用 PIL 验证是否为有效图片
        import io
        try:
            img = Image.open(io.BytesIO(content))
            img.verify()
        except Exception:
            logger.warning(f"不是有效图片: {url[:100]}")
            return None
        
        # 验证通过，写入文件
        with open(filepath, 'wb') as f:
            f.write(content)
        
        logger.info(f"图片下载成功: {img.size[0]}x{img.size[1]}, {len(content)//1024}KB")
        return str(filepath.absolute())
            
    except requests.exceptions.Timeout:
        logger.warning(f"下载超时: {url[:100]}")
        return None
    except requests.exceptions.ConnectionError:
        logger.warning(f"连接失败: {url[:100]}")
        return None
    except Exception as e:
        logger.warning(f"下载异常: {url[:100]}, {e}")
        return None

def set_wallpaper(image_path):
    """设置 Windows 壁纸"""
    try:
        import ctypes
        
        # Windows API 常量
        SPI_SETDESKWALLPAPER = 20
        SPIF_UPDATEINIFILE = 0x01
        SPIF_SENDWININICHANGE = 0x02
        
        # 调用 Windows API 设置壁纸
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER,
            0,
            image_path,
            SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE
        )
        
        if result:
            logger.info(f"壁纸设置成功: {image_path}")
            return True
        else:
            logger.error(f"设置壁纸失败: {image_path}")
            return False
    except Exception as e:
        logger.error(f"设置壁纸异常: {e}")
        return False

def switch_wallpaper(config, history):
    """切换壁纸主逻辑，支持多批次重试"""
    logger.info("开始切换壁纸...")
    
    max_batches = config.get('max_retries', 3)
    
    for batch_num in range(1, max_batches + 1):
        logger.info(f"获取第 {batch_num} 批壁纸...")
        
        # 获取壁纸列表
        wallpapers = fetch_wallpapers(config)
        if not wallpapers:
            logger.warning(f"第 {batch_num} 批未获取到数据")
            continue
        
        # 过滤掉已经使用过的壁纸
        used_ids = [h['id'] for h in history[-20:]]  # 最近20张不重复
        available = [w for w in wallpapers if w['id'] not in used_ids]
        
        if not available:
            logger.info("所有壁纸都已使用过，使用全量列表")
            available = wallpapers
        
        # 随机打乱顺序
        random.shuffle(available)
        
        # 尝试下载并设置壁纸
        for wallpaper in available:
            wallpaper_id = wallpaper['id']
            large_url = wallpaper.get('largeUrl')
            thumb_url = wallpaper.get('thumbUrl')
            
            logger.info(f"尝试壁纸 ID: {wallpaper_id}, 标题: {wallpaper.get('title', '无标题')}")
            
            # 优先使用大图，失败则用缩略图
            image_path = None
            if large_url:
                image_path = download_image(large_url, config)
            
            if not image_path and thumb_url:
                logger.info(f"大图失败，尝试缩略图: {wallpaper_id}")
                image_path = download_image(thumb_url, config)
            
            if image_path:
                # 设置壁纸
                if set_wallpaper(image_path):
                    # 记录历史
                    history.append({
                        'id': wallpaper_id,
                        'title': wallpaper.get('title', ''),
                        'url': large_url or thumb_url,
                        'time': datetime.now().isoformat()
                    })
                    save_history(history)
                    
                    # 清理旧缓存（保留最近20张）
                    cleanup_cache()
                    
                    return True
        
        logger.warning(f"第 {batch_num} 批所有壁纸都无法下载")
    
    logger.error(f"已尝试 {max_batches} 批，全部失败，跳过本次切换")
    return False

def cleanup_cache():
    """清理旧缓存文件"""
    try:
        if not CACHE_DIR.exists():
            return
        
        files = sorted(CACHE_DIR.glob('*.jpg'), key=lambda p: p.stat().st_mtime)
        if len(files) > 20:
            for file in files[:-20]:
                file.unlink(missing_ok=True)
                logger.debug(f"清理缓存: {file}")
    except Exception as e:
        logger.warning(f"清理缓存失败: {e}")

class WallpaperTrayApp:
    """系统托盘应用"""
    
    def __init__(self):
        self.config = load_config()
        self.history = load_history()
        self.running = True
        self.stop_event = threading.Event()
        self.timer_thread = None
        self.icon = None
        
        # 确保缓存目录存在
        CACHE_DIR.mkdir(exist_ok=True)
    
    def create_icon(self):
        """创建托盘图标"""
        from PIL import Image, ImageDraw
        
        # 生成一个简单的图标（渐变色圆形）
        image = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # 画一个渐变色圆形
        for i in range(30, 0, -1):
            r = int(70 + (200 - 70) * (30 - i) / 30)
            g = int(130 + (220 - 130) * (30 - i) / 30)
            b = int(200 + (255 - 200) * (30 - i) / 30)
            draw.ellipse([32 - i, 32 - i, 32 + i, 32 + i], fill=(r, g, b, 255))
        
        return image
    
    def get_menu(self):
        """创建托盘菜单"""
        return pystray.Menu(
            Item('立即切换壁纸', self.on_switch_now, default=True),
            Item('修改切换间隔...', self.on_change_interval),
            pystray.Menu.SEPARATOR,
            Item('查看历史', self.on_view_history),
            Item('打开日志', self.on_open_log),
            Item('清理缓存', self.on_clear_cache),
            pystray.Menu.SEPARATOR,
            Item('退出', self.on_quit)
        )
    
    def on_switch_now(self, icon=None, item=None):
        """立即切换壁纸"""
        threading.Thread(target=self._do_switch, daemon=True).start()
    
    def _do_switch(self):
        """执行切换"""
        switch_wallpaper(self.config, self.history)
    
    def on_change_interval(self, icon=None, item=None):
        """修改切换间隔"""
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        
        new_interval = simpledialog.askinteger(
            "设置切换间隔",
            "请输入切换间隔（分钟）:",
            initialvalue=self.config['interval_minutes'],
            minvalue=1,
            maxvalue=1440,
            parent=root
        )
        
        if new_interval:
            self.config['interval_minutes'] = new_interval
            save_config(self.config)
            
            # 通知定时器线程重新等待
            self.stop_event.set()
            
            messagebox.showinfo("成功", f"切换间隔已设置为 {new_interval} 分钟", parent=root)
        
        root.destroy()
    
    def on_view_history(self, icon=None, item=None):
        """查看切换历史"""
        history_file = Path(HISTORY_FILE).absolute()
        if history_file.exists():
            os.startfile(str(history_file))
        else:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("提示", "暂无切换历史", parent=root)
            root.destroy()
    
    def on_open_log(self, icon=None, item=None):
        """打开日志文件"""
        if LOG_FILE.exists():
            os.startfile(str(LOG_FILE))
    
    def on_clear_cache(self, icon=None, item=None):
        """清理缓存"""
        try:
            count = 0
            if CACHE_DIR.exists():
                for file in CACHE_DIR.glob('*.*'):
                    file.unlink()
                    count += 1
                logger.info(f"缓存已清理，删除了 {count} 个文件")
        except Exception as e:
            logger.error(f"清理缓存失败: {e}")
    
    def on_quit(self, icon=None, item=None):
        """退出程序"""
        self.running = False
        self.stop_event.set()
        if self.icon:
            self.icon.stop()
    
    def timer_task(self):
        """定时任务 - 使用 Event 实现可中断等待"""
        while self.running:
            interval_seconds = self.config['interval_minutes'] * 60
            
            # 使用 Event.wait 替代 time.sleep，可被中断
            self.stop_event.wait(timeout=interval_seconds)
            
            if not self.running:
                break
            
            # 清除事件标志，继续下一轮等待
            self.stop_event.clear()
            
            # 执行切换
            logger.info(f"定时切换壁纸（间隔 {self.config['interval_minutes']} 分钟）")
            self._do_switch()
    
    def start_timer(self):
        """启动定时器"""
        self.stop_event.clear()
        self.timer_thread = threading.Thread(target=self.timer_task, daemon=True)
        self.timer_thread.start()
    
    def run(self):
        """运行应用"""
        logger.info("壁纸切换工具启动")
        
        # 启动时立即切换一次
        self._do_switch()
        
        # 启动定时器
        self.start_timer()
        
        # 创建托盘图标
        icon_image = self.create_icon()
        menu = self.get_menu()
        
        self.icon = pystray.Icon(
            'wallpaper_switcher',
            icon_image,
            f'壁纸切换工具（{self.config["interval_minutes"]}分钟）',
            menu
        )
        
        self.icon.run()

def main():
    """主函数"""
    try:
        app = WallpaperTrayApp()
        app.run()
    except KeyboardInterrupt:
        logger.info("程序被中断")
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)

if __name__ == '__main__':
    main()
