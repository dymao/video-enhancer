# B站视频增强下载器

一款基于 Electron + Python Worker 的 B站视频下载与增强工具，支持 AI 超分辨率、FFmpeg 高清处理、音视频同步、批量任务队列和断点续处理。旧版 PyQt5 界面仍保留，可作为备用启动方式。

## ✨ 功能特点

- **B站视频下载**：支持输入 B站视频地址或 B站短链下载视频
- **批量任务队列**：支持动态添加多个 B站 URL，并按任务列表逐个下载和转换
- **地址校验**：下载前校验 URL 格式、地址可访问性，并拦截非 B站视频网页
- **视频清晰度选择**：自动获取视频可用清晰度列表，支持 4K/1080p/720p 等高清选项
- **AI 超分辨率**：集成 Real-ESRGAN 进行 4 倍放大，提升视频清晰度
- **FFmpeg 增强**：高质量缩放、锐化、降噪、对比度调整等多种滤镜
- **音视频同步**：自动修复音视频不同步问题
- **帧缓存机制**：跳过已处理帧，支持断点续处理
- **多步骤进度显示**：可视化展示下载、转换、增强、同步各步骤进度
- **实时耗时预估**：显示已耗时和预估剩余时间
- **Cookies 自动导入**：支持从浏览器自动导入 B站登录 cookies，获取高清视频权限
- **Electron 新界面**：现代桌面 UI，支持任务列表、输出设置、步骤进度和实时日志

## 📸 界面截图

![B站视频增强下载器界面截图](docs/images/screenshot.png)

## 📁 项目结构

```
video_enhancer/
├── electron/               # Electron 新界面
│   ├── main.js             # Electron 主进程，负责窗口、Worker 和系统对话框
│   ├── preload.js          # 安全 IPC 桥接
│   └── renderer/           # 前端界面
│       ├── index.html      # HTML 结构
│       ├── renderer.js     # 前端逻辑
│       └── styles.css      # 样式文件
├── src/                    # 源代码目录
│   └── video_enhancer.py   # Python 处理核心和 PyQt 旧界面
├── tools/                  # 工具脚本目录
│   ├── download_realesrgan.py   # Real-ESRGAN 工具下载脚本
│   └── download_models.py       # 模型文件下载脚本
├── resources/              # 资源目录
│   ├── icons/              # 图标文件
│   │   ├── logo.png
│   │   └── logo_*.png
│   └── models/             # Real-ESRGAN 模型文件
│       ├── realesrgan-x4plus.bin
│       ├── realesrgan-x4plus.param
│       └── ...
├── output/                 # 输出目录（存放处理后的视频）
├── temp/                   # 临时目录（存放视频帧等临时文件）
├── docs/                   # 文档目录
│   ├── images/             # 截图图片
│   └── usage.md            # 使用说明文档
├── README.md               # 项目说明
├── README_macos.md         # macOS 特定说明
├── package.json            # Electron 依赖和启动脚本
├── requirements.txt        # Python 依赖
└── LICENSE                 # 许可证
```

## 🛠️ 环境要求

- Python 3.9+
- Node.js / npm（Electron 新界面需要）
- macOS / Windows / Linux
- 依赖库：
  - PyQt5
  - OpenCV (`opencv-python`)
  - you-get (视频下载)
  - FFmpeg (视频处理)
  - Real-ESRGAN (可选，AI 超分辨率)

## 🚀 快速开始

### 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装 FFmpeg
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Windows
# 下载并安装：https://ffmpeg.org/download.html
```

### 下载 Real-ESRGAN 工具（可选）

```bash
python tools/download_realesrgan.py
```

### 运行程序

#### 方式一：Electron 新界面（推荐）

```bash
npm install
npm start
```

首次启动会自动创建 `.venv`、安装 Python 依赖，并执行 `npm install` 安装 Electron 依赖。

Electron 界面会调用 `src/video_enhancer.py --electron-worker` 执行实际处理，下载、转换、增强、断点续处理等核心能力仍复用原 Python 逻辑。

#### 方式二：PyQt 旧界面

```bash
python src/video_enhancer.py
```

#### 方式三：打包成可复制的 App

**macOS**

双击运行 `build_macos_app.command`，打包完成后复制 `dist/VideoEnhancer.app` 即可。

**Windows**

```bash
npm run dist:win
```

打包完成后生成以下文件：
- `release/win-ia32/Video Enhancer Setup.exe` - 安装版
- `release/win-ia32/Video Enhancer.exe` - 便携版（直接解压使用）

**macOS（Electron 打包）**

```bash
npm run dist:mac
```

打包完成后生成：
- `release/mac-arm64/Video Enhancer.app` - 可直接运行的 App
- `release/mac-arm64/Video Enhancer-2.0.0-arm64.dmg` - DMG 安装镜像

## 📖 使用说明

详细使用说明请查看 [docs/usage.md](docs/usage.md)

### 基本操作流程

1. **添加 B站视频任务**：输入 B站视频地址或 B站短链，点击"添加任务"加入列表
2. **动态管理任务**：可继续添加 URL，也可删除选中任务或清空列表
3. **选择输出目录**：默认输出到项目的 `output/` 目录
4. **设置输出格式**：支持 MP4、FLV、MKV 等格式
5. **选择清晰度**：输入 URL 后自动获取可用清晰度列表，选择目标清晰度
6. **配置 Cookies**（可选）：下载 720p+ 高清视频需要登录 cookies
7. **选择增强选项**：勾选"增强清晰度"启用 AI/FFmpeg 增强
8. **点击开始下载**：程序会按任务列表顺序逐个执行下载、转换、增强、同步等步骤
9. **查看任务状态**：流程区域会显示任务总数、当前第几个任务进行中，以及当前任务执行到哪一步
10. **取消任务**：批量处理时可选择"取消当前"跳过当前任务，或选择"取消全部"停止整个队列

### 高清视频下载（720p+）

下载 720p 及以上分辨率视频需要登录 B站账号的 cookies 文件：

1. **自动导入（推荐）**：点击"自动导入"按钮，从浏览器中提取已登录 B站的 cookies
2. **手动选择**：点击"选择..."按钮，选择之前导出的 cookies.txt 文件
3. 导入 cookies 后，程序会自动重新查询清晰度选项，显示 720p/1080p/4K 等高清选项

## 🎯 处理流程

```
步骤1: 下载视频
    ↓
步骤2: 格式转换
    ↓
步骤3: 清晰度增强
    ├── Real-ESRGAN AI 超分辨率（优先）
    └── FFmpeg 高级增强（降级方案）
    ↓
步骤4: 音视频同步
    ↓
完成: 输出增强后的视频
```

## 🔁 断点续处理说明

- 已下载的视频会记录在 `temp/task_state.json`，再次处理同一视频时会跳过下载。
- 已转换的视频如果仍存在，会跳过格式转换步骤。
- 已提取的视频帧会保存在 `temp/temp_frames/`，帧数匹配且属于同一视频时会跳过提取；如果只连续提取了一部分，会从下一帧继续提取。
- 已完成 AI 超分辨率的帧会保存在 `temp/enhanced_frames/`，重新运行时只处理缺失帧，不会重复处理已增强帧。
- B站链接参数可能变化，程序会扫描 `task_state.json` 中所有历史记录，并根据 URL、转换后文件路径、帧来源路径判断是否属于同一视频，降低误判导致重新处理的概率。
- 提取帧数量可能因 OpenCV 与 FFmpeg 统计差异略有偏差；当连续帧数量已达到或超过视频总帧数时，会视为已完整提取并跳过提取步骤。
- 取消任务会终止当前处理进程组；重新开始任务前会清理当前项目遗留的孤儿 FFmpeg/Real-ESRGAN 进程，避免残留进程继续写入缓存。
- 不要手动删除 `temp/temp_frames/`、`temp/enhanced_frames/` 或 `temp/task_state.json`，否则断点续处理会失效。

## ⚠️ 注意事项

- AI 超分辨率处理速度较慢，建议在处理前评估视频时长
- 大尺寸视频可能需要较多磁盘空间（临时帧文件）
- 下载 720p+ 高清视频需要登录 B站 cookies
- Real-ESRGAN 需要 GPU 加速才能获得较好的处理速度
- 如果 AI 超分辨率中断，重新运行后会显示已增强帧数和剩余待处理帧数，并从缺失帧继续处理
- 如果提取帧中断，重新运行后会保留已连续提取的帧，并从下一帧继续补提取

## 📝 更新日志

### v2.0.0
- 全新 Electron 桌面界面，现代 UI 设计
- 支持视频清晰度自动获取和选择
- 新增 Cookies 自动导入功能，一键获取浏览器 B站登录态
- 导入 Cookies 后自动重新查询高清清晰度选项
- 支持批量任务队列管理
- 多步骤进度可视化显示
- 实时日志输出
- 支持 macOS 和 Windows 打包发布
- 修复清晰度列表重复问题

### v1.1
- 优化 Real-ESRGAN 断点续处理逻辑，避免未完成的增强帧目录被清空
- 优化视频帧提取断点续处理，连续已提取帧不再重复提取
- 增加跨历史记录的同一视频缓存识别，支持 URL 参数变化时复用已提取帧和已增强帧
- 优化高帧数视频的帧目录扫描，减少跳过阶段卡顿
- 调整 AI 超分辨率进度提示，明确显示已增强帧数和剩余待处理帧数
- 修复取消任务后 FFmpeg/Real-ESRGAN 可能继续运行的问题，并在启动新任务前清理当前项目残留处理进程
- 优化已提取帧完整性判断，兼容 OpenCV 与 FFmpeg 帧数统计存在少量差异的情况

### v1.0
- 初始版本发布
- 支持视频下载和格式转换
- 集成 Real-ESRGAN AI 超分辨率
- 实现 FFmpeg 降级增强方案
- 添加进度条和步骤显示
- 实现音视频同步功能

## 📄 许可证

MIT License
