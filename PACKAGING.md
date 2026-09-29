# 打包桌面客户端

把 nnkBiliDown 打包成 **Windows / macOS / Linux 免安装客户端**：解压即用，内置 Python 运行时、
依赖库与 ffmpeg，用户不需要装 Python、Node.js、ffmpeg，也不需要联网下载依赖。

---

## 1. 为什么必须在目标系统上打包

PyInstaller **不能交叉编译**：Windows 上只能产出 Windows 可执行文件，macOS 的 `.app`
必须在 macOS 上生成，Linux 二进制必须在 Linux 上生成（且受 glibc 版本约束）。

所以本仓库提供两条路径：

| 方式 | 适用场景 | 产出 |
| --- | --- | --- |
| **GitHub Actions**（推荐） | 一次性拿到三平台产物 | 4 个安装包，见下方矩阵 |
| **本地打包** | 只想给自己的系统打包 / 调试 | `dist/nnkBiliDown-<系统>-<架构>.zip|tar.gz` |

---

## 2. 用 GitHub Actions 自动打包

工作流文件：`.github/workflows/build-clients.yml`

### 触发方式

```bash
# 方式一：推 tag，自动构建并创建 Release（产物直接挂到 Release 页面）
git tag v1.0.0
git push origin v1.0.0

# 方式二：手动触发，产物在 Actions 的 Artifacts 里下载
#   GitHub → Actions → Build Desktop Clients → Run workflow
```

推送到 `main` 且改动涉及 `backend/` `frontend/` `packaging/` 等目录时也会自动构建，
方便随时验证改动没有破坏打包。

### 构建矩阵

| Runner | 目标系统 | 产物 |
| --- | --- | --- |
| `windows-latest` | Windows 10/11 x64 | `nnkBiliDown-Windows-x64.zip` |
| `macos-13` | macOS Intel | `nnkBiliDown-macOS-x64.zip` |
| `macos-14` | macOS Apple Silicon (M 系列) | `nnkBiliDown-macOS-arm64.zip` |
| `ubuntu-22.04` | Linux x64（glibc ≥ 2.35） | `nnkBiliDown-Linux-x64.tar.gz` |

> Linux 选 `ubuntu-22.04` 而不是 `latest`，是为了用更低的 glibc 基线，
> 让产物能覆盖 Ubuntu 22.04+、Debian 12+、Fedora 36+ 等。

### 关于签名

- **Windows**：未做代码签名，SmartScreen 可能提示"未知发布者"，点"仍要运行"即可。
  要去掉提示需购买 EV/OV 证书并签名。
- **macOS**：未做代码签名与公证（需要 Apple Developer 账号，$99/年）。
  首次打开请**右键 → 打开**，或执行：
  ```bash
  xattr -dr com.apple.quarantine nnkBiliDown.app
  ```

---

## 3. 本地打包

### 依赖

- Python 3.10+（打包用的解释器，**不是**给最终用户装的）
- 前端产物 `frontend/dist`：仓库里已包含；只有改了前端才需要 Node.js 18+

### 一键打包

```bash
# Windows
python packaging\build.py

# macOS / Linux
python packaging/build.py
```

脚本会自动完成：生成图标 → 安装 PyInstaller/pywebview → 准备前端 → 下载内置 ffmpeg
→ PyInstaller 打包 → 校验产物 → 启动冒烟测试 → 归档。

### 常用参数

| 参数 | 说明 |
| --- | --- |
| `--ci` | CI 模式：强制内置 ffmpeg 并重新构建前端 |
| `--skip-ffmpeg` | 不内置 ffmpeg，客户端改用系统 PATH 里的 ffmpeg |
| `--build-frontend` | 强制用 npm 重新构建前端 |
| `--no-archive` | 只产出目录，不压缩成 zip/tar.gz |
| `--skip-smoke-test` | 跳过"启动产物 + 请求 /api/health"的冒烟测试 |
| `--icon-only` | 只重新生成图标 |

### 单独执行某一步

```bash
python packaging/make_icon.py        # 生成 assets/icon.png 与 icon.ico
python packaging/fetch_ffmpeg.py     # 下载本平台 ffmpeg 到 tools/ffmpeg
python packaging/fetch_ffmpeg.py --check   # 校验已有二进制能否运行
```

macOS 的 `icon.icns` 由 `build.py` 调用系统自带的 `sips` + `iconutil` 自动生成。

---

## 4. 产物结构

### Windows / Linux（onedir）

```text
nnkBiliDown/
├── nnkBiliDown.exe          # 双击启动（Linux 下是 nnkBiliDown）
├── _internal/               # PyInstaller 运行时与资源
│   ├── frontend/dist/       # 构建好的 React 前端
│   ├── backend/             # 后端源码副本（便于排障）
│   └── tools/ffmpeg/        # 内置 ffmpeg / ffprobe
└── ...
```

### macOS

```text
nnkBiliDown.app/
└── Contents/
    ├── MacOS/nnkBiliDown        # 可执行文件
    └── Resources/
        ├── frontend/dist/
        └── tools/ffmpeg/
```

---

## 5. 客户端运行行为

打包后的程序由 `desktop.py` 驱动，与源码模式的区别：

| 行为 | 说明 |
| --- | --- |
| 应用窗口 | 默认用 Chromium 内核浏览器的 `--app` 模式开独立窗口（无地址栏/标签页） |
| 后端选择 | Windows: Edge → Chrome；macOS: Chrome → Edge → Chromium；Linux: chromium → google-chrome → edge |
| 兜底顺序 | 应用窗口 → pywebview(GTK/Cocoa) 原生窗口 → 系统浏览器 |
| 端口 | 优先 7860；被占用时自动改用随机空闲端口 |
| 数据目录 | 与源码模式一致：`~/.nnkbilidown`（遵循 `NNKBILIDOWN_HOME`） |
| 日志 | 数据目录下的 `nnkbilidown.log`，出问题先看它 |
| 退出 | 关闭窗口后服务仍在后台运行（避免打断下载）；在任务管理器结束 `nnkBiliDown.exe` |

### 命令行参数

```bash
nnkBiliDown.exe                          # 应用窗口（默认）
nnkBiliDown.exe --port 7861              # 指定端口
nnkBiliDown.exe --no-window              # 只起服务 + 打开系统浏览器
nnkBiliDown.exe --no-window --no-browser # 纯后台，不打开任何界面
nnkBiliDown.exe --window-mode chrome     # 指定窗口后端（edge/chrome/chromium/pywebview/browser/none）
nnkBiliDown.exe --quit-with-window       # 关闭窗口时一并退出
nnkBiliDown.exe --console                # 保留控制台日志
```

### 环境变量

沿用源码模式的全部变量：

```bash
NNKBILIDOWN_HOME           # 数据目录
NNKBILIDOWN_DOWNLOAD_DIR   # 下载根目录
NNKBILIDOWN_FFMPEG         # 手动指定 ffmpeg（可指向文件或目录）
NNKBILIDOWN_NO_BROWSER=1   # 不自动打开浏览器
PYWEBVIEW_GUI=gtk          # Linux 下强制 pywebview 后端
```

---

## 6. 内置 ffmpeg 的说明与许可

- 来源：Windows / Linux 用 [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) 的
  `*-gpl` 静态构建；macOS 依次尝试 zgrep、evermeet.cx。
- 这些构建启用了 `--enable-gpl`，因此**随包分发时需要保留许可证声明**：
  打包脚本会自动把 `tools/ffmpeg/LICENSE.txt` 与 `README.txt` 放进产物。
- ffmpeg 是独立可执行程序，通过命令行被调用，不与本项目链接。
- 体积影响：`ffmpeg` + `ffprobe` 约 320 MB（未压缩），压缩后安装包约 160 MB。
  若想显著减小体积，用 `--skip-ffmpeg` 打包，用户自行安装 ffmpeg 即可。

---

## 7. 排障

### 打包失败：`Permission denied` / `WinError 5`

PyInstaller 需要创建命名管道做模块收集，并对临时目录有读写权限。
若在受限沙箱、只读目录或权限收紧的环境里运行会失败：

- 换到普通用户终端（非受限容器）执行
- 确认 `%TEMP%` / `/tmp` 可写
- Windows 上不要用"以管理员身份运行"以外的特殊策略限制子进程

### 打包失败：`未找到前端产物 frontend/dist`

仓库里包含构建好的 `frontend/dist`。若被删除：

```bash
cd frontend && npm install && npm run build
# 或
python packaging/build.py --build-frontend
```

### 产物启动后立刻退出

`build.py` 的冒烟测试会打印产物的真实输出。也可手动运行：

```bash
dist/nnkBiliDown/nnkBiliDown.exe --console --no-window --no-browser
```

### 客户端里 ffmpeg 显示 `source: system`

说明没有内置成功，回退到了系统 PATH。检查 `/api/health` 的 `ffmpeg.source` 字段：

- `bundled` 内置
- `env` 由 `NNKBILIDOWN_FFMPEG` 指定
- `system` 系统安装

### macOS 提示"已损坏，无法打开"

未签名应用的正常现象：

```bash
xattr -dr com.apple.quarantine /path/to/nnkBiliDown.app
```

### Linux 上一启动就提示找不到浏览器

客户端本身可用，只是没有 Chromium 内核浏览器开窗口：

```bash
sudo apt install chromium          # Debian/Ubuntu
sudo dnf install chromium          # Fedora
```

或者用 `--no-window` 走系统浏览器。
