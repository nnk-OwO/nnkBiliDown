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
    ├── MacOS/
    │   ├── nnkBiliDown              # 可执行文件
    │   ├── frontend -> …            # 交叉符号链接
    │   └── …
    ├── Frameworks/nnkBiliDown/      # COLLECT 目录被整体挪到这里
    │   └── _internal/               # 真正的资源所在
    │       ├── frontend/dist/
    │       ├── backend/
    │       └── tools/ffmpeg/
    └── Resources/                   # 非代码文件（与 MacOS 互相交叉链接）
        ├── frontend -> …
        ├── backend -> …
        └── tools -> …
```

> ⚠️ macOS 的资源位置和 Windows/Linux 完全不同：`.app` 会把 `COLLECT` 目录挪到
> `Contents/Frameworks/<NAME>/`，再通过 `Contents/Resources` 与 `Contents/MacOS`
> 互相做符号链接。所以 `sys._MEIPASS` 在 macOS 上指向
> `Contents/Frameworks/nnkBiliDown`。
>
> 因此**不要在脚本里硬编码某一层路径**。`build.py` 的产物校验用「以 `.app` 为根
> 遍历 + 按尾部路径匹配」的方式定位（见 `_app_layout()` / `_walk_files()`），
> 并且遍历时不跟随符号链接，避免 Resources ↔ MacOS 的环路。
>
> 想验证这套逻辑，可随时运行（任何平台都能跑，覆盖四种布局 + 负面用例）：
> ```bash
> python packaging/test_output_layout.py
> ```
> CI 里也会在打包前执行它。

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

### 构建"成功"但步骤红叉：`exit code 141`

如果你的 workflow 里出现这种怪现象——产物明明已经生成，某一步却失败——先看退出码：

- **141 = 128 + 13（SIGPIPE）**，典型来源是 `某个命令 | head -N`：
  `head` 读满 N 行就关闭管道，上游命令仍在写，收到 SIGPIPE 而死；
  GitHub Actions 的 bash **默认开启 `pipefail`**，于是整条管道被判为失败。

历史上「列出产物」步骤就踩了这个坑：

```bash
# ✗ 不要这样写
ls -lhR dist/ | head -60

# ✓ 结果落盘后再截断，或干脆不用管道
find dist -maxdepth 2 > /tmp/tree.txt 2>/dev/null || true
head -40 /tmp/tree.txt
```

另外 **`find -printf` 是 GNU 专有选项，macOS 的 BSD `find` 不支持**，
用它会导致 macOS 上静默无输出（诊断失效），也不要用。

本地验证 workflow 里的 shell 片段：

```bash
bash packaging/test_workflow_ls.sh
```

### 打包失败：`Process completed with exit code 1`，日志几乎是空的

Windows 上的经典坑：**控制台编码**。GitHub 的 Windows runner 默认是 cp1252 控制台，
脚本里的中文（`print("=== 检查环境")`）会直接抛 `UnicodeEncodeError` 并以退出码 1 结束，
看起来就像"什么都没干就失败了"。

已做三重防护，如果你改动脚本请保留：

1. workflow 顶层设 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`
2. 各脚本入口调用 `force_utf8_output()`，把标准流切到 UTF-8
3. `PYTHONIOENCODING` 缺失时仍能通过 `errors="replace"` 兜底

本地复现方式：

```powershell
$env:PYTHONIOENCODING = "cp1252"
$env:PYTHONUTF8 = "0"
python packaging/build.py --help
```

### 打包失败：`[失败] 产物缺少 …`

校验失败时会打印**产物实际内容清单**，直接照清单判断即可。常见原因：

- macOS：资源在 `Contents/Frameworks/<NAME>/_internal/`，不要在脚本里硬编码路径
- 前端未构建：`frontend/dist/index.html` 不存在
- ffmpeg 未内置：`--skip-ffmpeg` 或下载失败

先跑一次布局自测，快速排除定位逻辑问题：

```bash
python packaging/test_output_layout.py
```

### 打包失败：`无法清理 dist（WinError 32）`

上一次打包出来的客户端还在运行，`nnkBiliDown.exe` 锁住了产物目录。
结束该进程后重试即可；脚本内置了带重试的清理与明确提示。

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
