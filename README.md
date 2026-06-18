## 壁纸切换工具

Windows 桌面壁纸自动切换工具，通过搜图神器 API 获取随机壁纸，支持 GUI 预览和系统托盘两种模式。

### 文件说明

| 文件 | 说明 |
|------|------|
| `wallpaper_gui.py` | GUI 版本，带预览、缩略图栏、自动切换 |
| `wallpaper_switcher.py` | 托盘版本，后台定时切换 |
| `start.bat` | 启动 GUI 版本 |
| `start_silent.bat` | 启动托盘版本 |

### 壁纸图片域名状态

API 返回的壁纸图片来源域名分为三类：**有效域名**（可正常下载）、**不稳定域名**（域名可达但部分图片失效，需逐张验证）和**失效域名**（CDN 已下线，请求必定失败）。代码中通过 `KNOWN_DEAD` 集合预过滤失效域名，避免无意义的请求；不稳定域名走正常下载验证流程。

#### 失效域名（KNOWN_DEAD）

| 域名 | 说明 |
|------|------|
| `img.hb.aicdn.com` | 花瓣/堆糖旧 CDN，已下线，API 返回中占比约 50% |

#### 不稳定域名

| 域名 | 说明 |
|------|------|
| `gd-hbimg.huaban.com` | 花瓣 CDN，域名可达但大量图片返回 HTTP 567，少部分仍可用，不做一刀切过滤 |

#### 有效域名

| 域名 | 来源 |
|------|------|
| `gimg2.baidu.com` | 百度图片 |
| `img0.baidu.com` / `img1.baidu.com` / `img2.baidu.com` | 百度图片（缩略图） |
| `image-assets.soutushenqi.com` | 搜图神器官方上传 |
| `c-ssl.duitang.com` | 堆糖 CDN |
| `i0.hdslb.com` / `i2.hdslb.com` | B站图床 |
| `hbimg.huaban.com` | 花瓣 CDN（注意无 `gd-` 前缀，仍有效） |
| `wx2.sinaimg.cn` | 微博图床 |
| `pic1.zhimg.com` / `pic3.zhimg.com` / `pic4.zhimg.com` | 知乎图床 |
| `i01piccdn.sogoucdn.com` / `i02piccdn.sogoucdn.com` / `i03piccdn.sogoucdn.com` | 搜狗图片 CDN |
| `img.mm4000.com` | 美图图库 |
| `pic1.win4000.com` | 壁纸图库 |

> 以上域名列表基于 2026-06-18 实际 API 返回数据统计，后续如有变动请更新代码中的 `KNOWN_DEAD` 集合及本文档。
