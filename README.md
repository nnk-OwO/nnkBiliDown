# nnkBiliDown

<div align="center">

**一个本地运行、开箱即用的 Bilibili 视频下载器**

FastAPI · yt-dlp · ffmpeg · React · Vite · Tailwind CSS

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-ff0000)](https://github.com/yt-dlp/yt-dlp)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev/)
[![Platform](https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#)
[![License](https://img.shields.io/badge/License-MIT-2ea44f)](./LICENSE)

</div>

nnkBiliDown 在本地启动一个 Web 服务，通过浏览器即可解析并下载 B 站视频。支持 Cookie / 扫码登录、清晰度与编码选择、多分P和批量队列、实时进度、历史记录以及自动整理文件。

> ℹ️ **非官方声明**：本项目与哔哩哔哩（Bilibili）无任何关联，是非官方社区工具。项目名称中的 “Bili” 仅用于说明软件用途，不表示任何官方认证或授权。
>
> ⚠️ **免责声明**：本项目仅供个人学习、研究使用。请遵守相关法律法规与 Bilibili 服务条款，不要下载或传播未授权内容。

---

## ✨ 功能特性

### 账号登录

- 粘贴浏览器 Cookie（`SESSDATA` 等字段），测试后保存到本机
- 扫码登录：B 站 App 扫码确认后自动保存 Cookie（推荐）
- Cookie 只保存在本机数据目录，文件权限 `0600`，日志绝不输出完整 Cookie

### 视频解析

- 支持链接类型：
  - `https://www.bilibili.com/video/BV...` / `av...`
  - `https://b23.tv/...` 短链
  - 番剧 / 影视 `ep` / `ss` 链接
  - UP 主空间、收藏夹（批量列出所有视频）
- 展示封面、标题、UP 主、时长、简介、分P / 剧集列表
- 清晰度按钮组：`1080P 高码率`、`1080P 60帧`、`4K`、`8K`、`HDR`、`AVC / HEVC / AV1` 等
- 未登录时高画质灰锁，并标注 **需登录 / 大会员**

### 下载

- 单链接可选任意分P / 剧集；批量模式每行一个链接
- 1-3 并发任务队列；DASH 音视频由 yt-dlp 下载、ffmpeg 自动合并
- 可选输出格式 `MP4` / `MKV`
- 可选下载 CC 字幕、弹幕 XML、封面图
- 实时显示：百分比、下载速度、剩余时间、文件大小、合并状态
- 下载完成一键“打开文件夹”；失败任务可重试，`.part` 支持断点续传

### 其他

- 历史记录：标题、URL、清晰度、状态、时间、本地路径；支持重试与删除
- 设置：下载目录、文件名模板、默认清晰度/编码、并发数、代理
- 自动检测 ffmpeg，缺失时按操作系统给出安装提示
- 亮色 / 暗色主题，桌面与手机响应式布局
- 粘贴链接自动解析、页面聚焦自动读取剪贴板、浏览器书签小工具

---

## 🖥️ 界面速览

```text
┌────────────────────────────────────────────────────────────┐
│  nnkBiliDown          [账号状态]  [🌙/☀️]  [设置]           │
├────────────────────────────────────────────────────────────┤
│  🔗 粘贴 B 站链接                    [解析视频]              │
├────────────────────────────────────────────────────────────┤
│  ┌──────────┐  视频标题                                     │
│  │  封面     │  UP 主 · 时长 · 分P                           │
│  └──────────┘                                               │
│  清晰度: [4K(大会员)] [1080P高码率] [1080P] [720P] [480P]    │
│  编码:   [AVC] [HEVC] [AV1]    输出: [MP4|MKV]               │
│  分P:    ☑ P1 ...  ☑ P2 ...  ☐ P3 ...                       │
│                          [⬇ 开始下载（2）]                   │
├────────────────────────────────────────────────────────────┤
│  下载队列 / 历史记录                                         │
│  ██████████░░░░ 62.3%  3.2 MB/s  剩余 00:42                │
└────────────────────────────────────────────────────────────┘
```

---

## 📦 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.10+ | 启动器会自动创建虚拟环境 |
| ffmpeg | 较新版本即可 | DASH 音视频合并必需 |
| 浏览器 | Chrome / Edge / Firefox / Safari | 访问 Web UI |

> 生产模式**不需要 Node.js**：仓库已包含构建好的前端 `frontend/dist`。只有二次开发前端时才需要安装 Node。

### 安装 ffmpeg

**Windows**

```bat
winget install Gyan.FFmpeg
:: 或 choco install ffmpeg
```

**macOS**

```bash
brew install ffmpeg
```

**Ubuntu / Debian**

```bash
sudo apt update && sudo apt install ffmpeg
```

安装后请重启终端，并用 `ffmpeg -version` 验证。

---

## 🚀 快速开始

### Windows

双击或在终端运行：

```bat
scripts\start.bat
```

### macOS / Linux

```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

启动器会自动完成：

1. 检查 Python 版本并打印解释器路径
2. 创建 `.venv` 并安装依赖（首次运行约 1-2 分钟）
3. 检测 ffmpeg
4. 启动服务并等待端口就绪
5. 自动打开浏览器访问 **http://localhost:7860**

也可以直接使用 Python：

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python start.py --port 7860
```

常用启动参数：

```bash
python start.py --host 127.0.0.1 --port 7860 --no-browser
```

---

## 🔐 登录指南

游客通常只能下载 `360P / 480P`；登录后可解锁 `720P / 1080P`，大会员可解锁 `4K / 1080P 高码率` 等档位。

### 方式一：Cookie 登录

1. 浏览器登录 [bilibili.com](https://www.bilibili.com)
2. 按 `F12` 打开开发者工具 → **Network（网络）** → 刷新页面
3. 任选一个 `api.bilibili.com` 请求
4. 在 Request Headers 中复制完整的 `Cookie:` 值
5. 打开 nnkBiliDown → 右上角“登录账号” → 粘贴 → **测试并保存**

### 方式二：扫码登录

1. 打开“登录账号”弹窗
2. 点击 **显示二维码登录**
3. 使用 B 站手机 App 扫码并确认
4. 页面会自动保存 Cookie 并刷新登录状态

> Cookie 等同于账号凭证，请勿截图、分享或提交到代码仓库。

---

## 📥 使用流程

### 1. 解析

粘贴以下任一链接后点击“解析视频”（默认开启粘贴后自动解析）：

```text
https://www.bilibili.com/video/BV1GJ411x7h7
https://b23.tv/xxxx
https://www.bilibili.com/bangumi/play/ep277026
https://www.bilibili.com/bangumi/play/ss39431
https://space.bilibili.com/23248035/video
```

### 2. 选择

- 点击清晰度按钮选择画质；灰色档位代表当前账号不可用
- 选择编码：AVC 兼容性最好，HEVC/AV1 更省体积
- 勾选需要下载的分P / 剧集
- 选择 `MP4` / `MKV`，按需开启字幕、弹幕、封面

### 3. 下载

点击 **开始下载**。进度通过 WebSocket 实时推送；下载完成后点击 **打开文件夹**。

### 4. 批量下载

点击“批量 URL 输入”，每行粘贴一个链接。每个链接的所有分P / 剧集会加入队列；如需精确挑选分P，请使用单链接解析。

---

## 📂 数据与文件存储

### 应用数据目录

| 文件 | 路径 | 内容 |
| --- | --- | --- |
| 配置 | `~/.nnkbilidown/config.json` | 设置 + Cookie（`0600`） |
| 历史 | `~/.nnkbilidown/history.json` | 下载记录 |
| 临时 Cookie | `~/.nnkbilidown/cookies.txt` | 下载时给 yt-dlp 使用 |

旧版本数据目录 `~/.bili_downloader` 会在首次启动时自动迁移（保留旧目录作为备份）。

### 默认下载目录（跨平台智能识别）

nnkBiliDown 不会盲目使用 `C:\Users\...\Downloads`，而是先定位操作系统真正的“下载”文件夹：

| 系统 | 定位策略 |
| --- | --- |
| Windows | 优先读取注册表 Known Folder `{374DE290-...}`，能正确识别用户移动到 D 盘 / E 盘的“下载”文件夹 |
| macOS | `~/Downloads` |
| Linux | 优先读取 `~/.config/user-dirs.dirs` 中的 `XDG_DOWNLOAD_DIR`，回退到 `~/Downloads` |

应用默认把视频保存在：

```text
<系统下载文件夹>/nnkBiliDown/
```

#### 使用环境变量自定义

```bash
# 数据目录（兼容旧变量 BILIDL_HOME）
export NNKBILIDOWN_HOME=/path/to/data

# 下载根目录（兼容旧变量 BILIDL_DOWNLOAD_DIR）
export NNKBILIDOWN_DOWNLOAD_DIR=D:/Videos/bilibili
```

Windows PowerShell 示例：

```powershell
$env:NNKBILIDOWN_DOWNLOAD_DIR = "D:\Videos\bilibili"
scripts\start.bat
```

也可以在 Web UI 的“设置”中直接修改下载目录；该设置会保存在本地配置中。

---

## 🧩 技术架构

```text
Browser (React SPA)
   │  REST /api/*  +  WebSocket /api/ws
   ▼
FastAPI backend
   ├── bilibili.py     B 站 API 客户端、WBI 签名、链接解析
   ├── downloader.py   任务队列、yt-dlp 封装、进度钩子
   ├── qr_login.py     扫码登录
   ├── config.py       配置 / 历史 / 下载目录定位
   └── models.py       Pydantic 模型
   ▼
yt-dlp + ffmpeg  →  本地磁盘
```

### 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/cookie/test` | 测试并保存 Cookie |
| `DELETE` | `/api/cookie` | 清除 Cookie |
| `GET` | `/api/qr/generate` | 生成登录二维码 |
| `GET` | `/api/qr/status` | 轮询扫码状态 |
| `POST` | `/api/video/parse` | 解析视频 / 番剧 / 空间 / 收藏夹 |
| `POST` | `/api/tasks` | 创建下载任务 |
| `GET` | `/api/tasks` | 任务列表与历史 |
| `GET` | `/api/tasks/{id}/progress` | 查询进度（WebSocket 之外的兜底） |
| `POST` | `/api/tasks/{id}/retry` | 重试失败任务 |
| `POST` | `/api/tasks/{id}/cancel` | 取消任务 |
| `DELETE` | `/api/tasks/{id}` | 删除记录（`?delete_file=true` 同时删除文件） |
| `POST` | `/api/tasks/{id}/open-folder` | 打开任务所在文件夹 |
| `GET` / `PUT` | `/api/settings` | 读取 / 保存设置 |
| `GET` | `/api/health` | 健康检查、ffmpeg / yt-dlp 版本 |
| `WS` | `/api/ws` | 任务进度实时推送 |

---

## 🛠️ 项目结构

```text
nnkBiliDown/
├── backend/
│   ├── main.py            FastAPI 入口、API、WebSocket、静态托管
│   ├── bilibili.py        B 站 API 客户端、WBI 签名、视频解析
│   ├── downloader.py      下载队列、yt-dlp 封装、进度钩子
│   ├── config.py          配置/历史存储、跨平台下载目录定位
│   ├── qr_login.py        扫码登录
│   └── models.py          Pydantic 请求模型
├── frontend/
│   ├── src/               React + Tailwind 源码
│   └── dist/              已构建的生产前端（无需 Node）
├── scripts/
│   ├── start.bat          Windows 一键启动
│   ├── start.sh           macOS / Linux 一键启动
│   └── dev.sh             前后端开发模式
├── start.py               Python 跨平台启动器
├── requirements.txt
├── .gitignore
├── .gitattributes
├── LICENSE                MIT License
└── README.md
```

---

## 💻 前端二次开发

生产模式直接使用 `frontend/dist`。如需修改前端：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173，代理到 7860 后端
```

修改完成后：

```bash
npm run build      # 产物输出到 frontend/dist，重启后端生效
```

---

## ❓ 常见问题

### 1. 双击 start.bat 后只有一个光标在闪

这是正常现象：光标停留在窗口中表示本地服务正在运行。打开浏览器访问 **http://localhost:7860** 即可；按 `Ctrl+C` 停止服务。

如果完全没有任何输出，通常是 Windows 的“应用执行别名”把 `python` 指向了 Microsoft Store：

- 设置 → 应用 → 高级应用设置 → 应用执行别名 → 关闭 `python.exe` / `python3.exe`
- 或到 [python.org](https://www.python.org/downloads/) 安装 Python 3.10+，勾选 `Add python.exe to PATH`
- 然后在项目目录执行 `py -3 start.py` 或 `python start.py`

### 2. 解析或下载报 412 / 风控失败

- 稍等几分钟再试
- 先在浏览器中打开一次目标视频
- 登录账号后重新解析
- 在设置中配置代理，例如 `http://127.0.0.1:7890`

### 3. 未找到 ffmpeg

按上方说明安装，并确认 `ffmpeg -version` 能输出版本。安装后需要重启 nnkBiliDown。

### 4. Cookie 测试失败

- 请复制完整的 `Cookie:` 值，必须包含 `SESSDATA`
- Cookie 过期后需要重新复制
- 扫码登录如果提示失效，请重新生成二维码

### 5. 高画质按钮是灰色

灰色代表当前账号不可下载。登录（大会员解锁更多）后重新点击“解析视频”刷新档位。

### 6. 下载的视频没有声音 / 无法播放

- 优先选择 `MP4 + AVC`
- 确认 ffmpeg 可用：DASH 流必须合并后才能得到完整文件
- HEVC / AV1 需要较新的播放器

### 7. 下载文件夹不对

nnkBiliDown 默认使用操作系统真实的“下载”文件夹：

- Windows 读取注册表中的 Downloads Known Folder（即使你把它移动到了 D 盘 / E 盘）
- Linux 读取 `XDG_DOWNLOAD_DIR`
- macOS 使用 `~/Downloads`

也可以在设置中手动修改，或设置环境变量 `NNKBILIDOWN_DOWNLOAD_DIR`。

### 8. 端口被占用

```bash
python start.py --port 7861
```

---

## ⚖️ 使用与免责声明

### 非官方声明

本项目与哔哩哔哩（Bilibili）无任何关联，未获得哔哩哔哩的官方认证或授权。项目名称中的 “Bili” 仅用于说明软件用途。

### 法律与版权

- 本项目仅供个人学习、研究使用，请勿用于任何商业用途或侵犯他人权利的行为。
- 使用本工具下载的内容，其版权归原作者或权利方所有。请仅备份你本人有权访问的内容，并在下载后自行承担存储、使用与传播责任。
- 请遵守当地法律法规以及 Bilibili 服务条款；如果内容权利人要求删除已下载内容，请及时配合处理。
- 本项目不提供绕过付费、DRM、地区限制或访问控制的功能，也不提供任何预下载的视频文件。

### 账号安全

- Cookie 等同于账号凭证，请勿分享、截图或提交到代码仓库。
- 本项目只在本机保存登录信息，上传到 GitHub 前请确认不包含 `config.json`、`history.json`、`cookies.txt` 等个人数据。

### 免责声明

本软件按“现状”提供，作者不对因使用或无法使用本软件而造成的任何直接或间接损失承担责任。使用者应自行承担因使用本工具产生的全部责任。

---

## 📜 开源许可

本项目基于 [MIT License](./LICENSE) 开源。

```text
Copyright (c) 2026 nnk-OwO
```
