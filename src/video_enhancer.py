import sys
import os
import subprocess
import shutil
import re
import hashlib
import json
import time
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import cv2
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QLineEdit,
                             QPushButton, QComboBox, QCheckBox, QVBoxLayout, QWidget,
                             QProgressBar, QTextEdit, QHBoxLayout, QMessageBox, QListWidget)
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QPointF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QPolygonF

# 全局变量，用于跟踪当前运行的任务和取消状态
current_running_process = None
cancel_flag = False
cancelled_process_ids = set()

# 项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 任务状态持久化文件 - 用于断点续传
TASK_STATE_FILE = os.path.join(PROJECT_ROOT, 'temp', 'task_state.json')


def get_url_hash(url):
    """用 URL 生成唯一标识，用于状态文件索引"""
    return hashlib.md5(url.encode('utf-8')).hexdigest()


def load_task_state():
    """加载持久化任务状态"""
    if os.path.exists(TASK_STATE_FILE):
        try:
            with open(TASK_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_task_state(state):
    """保存持久化任务状态"""
    os.makedirs(os.path.dirname(TASK_STATE_FILE), exist_ok=True)
    with open(TASK_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_task_state_entry(url):
    """获取指定 URL 的任务状态"""
    state = load_task_state()
    url_hash = get_url_hash(url)
    return state.get(url_hash, {})


def update_url_state(url, **kwargs):
    """更新指定 URL 的状态字段，如 downloaded=True, converted=True 等"""
    state = load_task_state()
    url_hash = get_url_hash(url)
    if url_hash not in state:
        state[url_hash] = {"url": url}
    state[url_hash].update(kwargs)
    save_task_state(state)
    

def is_supported_video_url(url):
    """判断是否为当前工具支持的 B 站视频地址。"""
    parsed_url = urlparse(url)
    hostname = (parsed_url.hostname or "").lower()
    path = parsed_url.path.rstrip("/")
    
    if hostname == "b23.tv" or hostname.endswith(".b23.tv"):
        return True
    
    if hostname == "bilibili.com" or hostname.endswith(".bilibili.com"):
        return path.startswith("/video/") or path.startswith("/bangumi/play/")
    
    return False


def check_url_accessible(url, timeout=8):
    """检测输入地址是否可访问，避免无效地址直接进入下载流程。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Range": "bytes=0-0",
    }
    
    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=timeout) as response:
            status_code = response.getcode()
            return 200 <= status_code < 400, "", response.geturl()
    except HTTPError as e:
        # 401/403 说明地址可达但需要登录或权限，不应阻止后续 cookies 下载。
        if e.code in (401, 403):
            return True, "", e.url
        return False, f"HTTP {e.code}", e.url
    except URLError as e:
        return False, str(e.reason), ""
    except Exception as e:
        return False, str(e), ""


def create_app_icon():
    """创建应用程序图标 - 从 logo.png 文件加载"""
    # 获取资源目录路径
    logo_path = os.path.join(PROJECT_ROOT, 'resources', 'icons', 'logo.png')
    
    # 如果 logo.png 文件存在，从文件加载
    if os.path.exists(logo_path):
        return QIcon(logo_path)
    
    # 如果文件不存在，动态创建图标
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    # 绘制背景圆形（渐变蓝色）
    painter.setPen(Qt.NoPen)
    gradient_color = QColor(0, 122, 255)  # iOS 蓝色
    painter.setBrush(QBrush(gradient_color))
    painter.drawEllipse(10, 10, 108, 108)
    
    # 绘制视频播放图标（三角形）
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    triangle = [
        QPointF(50, 35),
        QPointF(50, 93),
        QPointF(95, 64)
    ]
    painter.drawPolygon(QPolygonF(triangle))
    
    # 绘制增强箭头（右上角）
    painter.setPen(QPen(QColor(76, 217, 100), 4))  # 绿色
    painter.drawLine(85, 25, 105, 25)
    painter.drawLine(95, 15, 105, 25)
    painter.drawLine(95, 35, 105, 25)
    
    painter.end()
    
    return QIcon(pixmap)

class DownloadSignals(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    set_enhance_checked = pyqtSignal(bool)  # 用于更新增强复选框状态
    step_changed = pyqtSignal(int, str)  # 步骤变化信号：步骤编号(0-2), 状态(pending/running/completed)


# 窗口类
class FrostedGlassWindow(QMainWindow):
    """主窗口"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)



def download_video_with_progress(url, output_dir, cookies_file, signals):
    try:
        # 使用系统Python 3.9运行you-get，避免miniforge3环境的SSL库问题
        cmd = ['/usr/bin/python3', '-m', 'you_get', '-o', output_dir]
        
        if cookies_file and os.path.exists(cookies_file):
            cmd.extend(['--cookies', cookies_file])
            signals.progress.emit(0, "已加载 cookies 文件")
        
        cmd.append(url)
        
        global current_running_process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        current_running_process = process
        
        signals.progress.emit(0, "开始下载...")
        
        last_percentage = 0
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if line:
                # 解析下载进度百分比
                if '%' in line:
                    try:
                        # 尝试提取百分比数字
                        parts = line.replace('%', ' ').split()
                        for part in reversed(parts):
                            try:
                                percentage = float(part)  # 转换为浮点数
                                if 0 <= percentage <= 100:
                                    percentage_int = int(percentage)
                                    if percentage_int > last_percentage:  # 只在进度增加时更新
                                        signals.progress.emit(percentage_int, f"正在下载 {percentage:.2f}%")
                                        last_percentage = percentage_int
                                    break
                            except:
                                continue
                        else:
                            # 如果没有找到百分比，显示原始信息
                            if any(keyword in line.lower() for keyword in ['download', 'site', 'title', 'stream']):
                                signals.progress.emit(0, line)
                    except:
                        pass
                else:
                    # 只显示关键信息，不显示下载过程中的详细信息
                    if any(keyword in line.lower() for keyword in ['error', 'failed', 'download error', 'site', 'title']):
                        signals.progress.emit(0, line)
        
        process.wait()
        
        if cancel_flag or process.pid in cancelled_process_ids:
            cancelled_process_ids.discard(process.pid)
            signals.progress.emit(0, "当前任务已取消")
            return False
        
        if process.returncode == 0:
            signals.progress.emit(0, "下载完成，开始处理视频...")
            return True
        else:
            signals.error.emit(f"下载失败，返回码: {process.returncode}")
            return False
            
    except Exception as e:
        signals.error.emit(str(e))
        return False

def process_video_task(url, output_dir, cookies_file, output_format, need_enhance, signals):
    global cancel_flag

    def collect_source_videos():
        video_extensions = ('.mp4', '.flv', '.mkv', '.webm')
        source_videos = []
        if not os.path.isdir(output_dir):
            return source_videos
        
        for filename in os.listdir(output_dir):
            name_lower = filename.lower()
            base_name = os.path.splitext(filename)[0].lower()
            if not name_lower.endswith(video_extensions):
                continue
            if base_name.startswith("temp_") or "_processed" in base_name or "_enhanced" in base_name:
                continue
            source_videos.append(filename)
        return source_videos
    
    # ===== 步骤0：下载视频（支持断点续传）=====
    signals.step_changed.emit(0, 'running')
    
    # 检查该 URL 是否已下载且文件仍存在
    state_entry = get_task_state_entry(url)
    if state_entry.get("downloaded") and state_entry.get("input_path"):
        cached_path = state_entry["input_path"]
        if os.path.exists(cached_path):
            input_path = cached_path
            input_filename = os.path.basename(input_path)
            signals.progress.emit(0, f"检测到已下载的视频 ({input_filename})，跳过下载步骤")
            signals.step_changed.emit(0, 'completed')
        else:
            signals.progress.emit(0, f"已下载的视频文件不存在 ({cached_path})，重新下载")
            before_download_files = set(collect_source_videos())
            if not download_video_with_progress(url, output_dir, cookies_file, signals):
                return
            signals.step_changed.emit(0, 'completed')
            after_download_files = collect_source_videos()
            downloaded_files = [f for f in after_download_files if f not in before_download_files]
            if not downloaded_files:
                downloaded_files = after_download_files
            downloaded_files = sorted(downloaded_files, key=lambda f: os.path.getmtime(os.path.join(output_dir, f)))
            if not downloaded_files:
                signals.error.emit("未找到下载的视频文件")
                return
            input_filename = downloaded_files[-1]
            input_path = os.path.join(output_dir, input_filename)
            update_url_state(url, downloaded=True, input_path=input_path, input_filename=input_filename)
    else:
        before_download_files = set(collect_source_videos())
        if not download_video_with_progress(url, output_dir, cookies_file, signals):
            return
        signals.step_changed.emit(0, 'completed')
        after_download_files = collect_source_videos()
        downloaded_files = [f for f in after_download_files if f not in before_download_files]
        if not downloaded_files:
            downloaded_files = after_download_files
        downloaded_files = sorted(downloaded_files, key=lambda f: os.path.getmtime(os.path.join(output_dir, f)))
        signals.progress.emit(0, f"找到的视频文件: {downloaded_files}")
        if not downloaded_files:
            signals.error.emit("未找到下载的视频文件")
            return
        input_filename = downloaded_files[-1]
        input_path = os.path.join(output_dir, input_filename)
        update_url_state(url, downloaded=True, input_path=input_path, input_filename=input_filename)
    
    # 检查是否已取消
    if cancel_flag:
        signals.progress.emit(0, "任务已取消")
        return
    
    # 生成输出文件名（基于原始文件名，添加标识）
    base_name = os.path.splitext(input_filename)[0]
    output_suffix = "_processed"
    
    # 检测原视频分辨率
    cap = cv2.VideoCapture(input_path)
    original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    signals.progress.emit(0, f"原视频分辨率: {original_width}x{original_height}")
    
    # 如果原视频已经是720p以上，跳过清晰度增强
    skip_enhance = False
    if original_height > 720:
        signals.progress.emit(0, "原视频已是高清(720p+)，自动跳过清晰度增强")
        signals.set_enhance_checked.emit(False)  # 取消勾选增强复选框
        skip_enhance = True
    else:
        signals.set_enhance_checked.emit(True)  # 勾选增强复选框

    # 步骤1：格式转换
    signals.step_changed.emit(1, 'running')
    output_path = os.path.join(output_dir, f"{base_name}{output_suffix}.{output_format}")
    
    # 检查是否已转换
    if os.path.exists(output_path):
        signals.progress.emit(0, f"检测到已转换的视频 ({os.path.basename(output_path)})，跳过格式转换步骤")
        signals.step_changed.emit(1, 'completed')
    else:
        signals.progress.emit(0, f"开始格式转换: {input_path}")
        cmd = ['ffmpeg', '-y', '-i', input_path, '-c:v', 'libx264', '-c:a', 'copy', output_path]
    
        global current_running_process
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1, universal_newlines=True)
        current_running_process = process
    
        duration_sec = None
        for line in iter(process.stdout.readline, ''):
            if line:
                # 解析进度
                if 'time=' in line and duration_sec is not None:
                    try:
                        time_str = line.split('time=')[1].split()[0]
                        parts = time_str.split(':')
                        if len(parts) == 3:
                            current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                            progress = min(int(current_sec / duration_sec * 100), 100)
                            signals.progress.emit(progress, f"格式转换: {progress}%")
                    except:
                        pass
                # 获取视频时长
                elif 'Duration:' in line:
                    try:
                        dur_str = line.split('Duration:')[1].split(',')[0].strip()
                        parts = dur_str.split(':')
                        if len(parts) == 3:
                            duration_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    except:
                        pass
    
        process.wait()
    
        if process.returncode == 0:
            signals.progress.emit(100, f"已转换为{output_format}格式")
            signals.step_changed.emit(1, 'completed')  # 步骤1完成
        else:
            signals.error.emit(f"格式转换失败")
            return
    
    # 更新状态：标记转换完成
    update_url_state(url, converted=True, converted_path=output_path)
    
    # 检查是否已取消
    if cancel_flag:
        signals.progress.emit(0, "任务已取消")
        return
    
    # 如果原视频已经是高清，跳过清晰度增强
    if skip_enhance:
        # 标记步骤2和步骤3为完成
        signals.step_changed.emit(3, 'completed')
        signals.step_changed.emit(3, 'completed')
        signals.progress.emit(0, f"处理完成！文件: {output_path}")
        signals.finished.emit("=== 所有处理完成 ===")
        return
    
    # 步骤2：清晰度增强
    signals.step_changed.emit(2, 'running')
    
    # 清晰度增强 - 使用 FFmpeg 高质量缩放 + 锐化
    if need_enhance:
        if os.path.exists(output_path):
            signals.progress.emit(0, "开始增强清晰度（Real-ESRGAN AI 超分辨率）...")
            enhanced_path = os.path.join(output_dir, f"{base_name}{output_suffix}_enhanced.{output_format}")
            
            # 使用预编译的 realesrgan-ncnn-vulkan 命令行工具
            # 工具存放在 tools 目录
            realesrgan_path = os.path.join(PROJECT_ROOT, 'tools', 'realesrgan-ncnn-vulkan')
            
            # 如果工具不存在，自动下载到 tools 目录
            if not os.path.exists(realesrgan_path):
                signals.progress.emit(0, "Real-ESRGAN 工具不存在，正在下载...")
                try:
                    import urllib.request
                    download_url = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip"
                    tools_dir = os.path.join(PROJECT_ROOT, 'tools')
                    os.makedirs(tools_dir, exist_ok=True)
                    zip_path = os.path.join(tools_dir, 'realesrgan-ncnn-vulkan-macos.zip')
                    
                    # 下载文件
                    urllib.request.urlretrieve(download_url, zip_path)
                    
                    # 解压文件
                    signals.progress.emit(0, "正在解压 Real-ESRGAN 工具...")
                    import zipfile
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(tools_dir)
                    
                    # 添加执行权限
                    os.chmod(realesrgan_path, 0o755)
                    
                    # 清理下载的zip文件
                    os.remove(zip_path)
                    
                    signals.progress.emit(0, "Real-ESRGAN 工具下载完成")
                except Exception as e:
                    signals.progress.emit(0, f"Real-ESRGAN 工具下载失败: {str(e)}")
                    raise Exception("Real-ESRGAN 工具下载失败")
            
            # 模型文件存放在 resources/models 目录
            model_dir = os.path.join(PROJECT_ROOT, 'resources', 'models')
            os.makedirs(model_dir, exist_ok=True)
            
            # ncnn 模型文件名（不含扩展名）
            model_name = 'realesrgan-x4plus'
            model_bin = os.path.join(model_dir, f'{model_name}.bin')
            model_param = os.path.join(model_dir, f'{model_name}.param')
            
            # 检查 Real-ESRGAN 工具和模型文件是否都存在
            if os.path.exists(realesrgan_path) and os.path.exists(model_bin) and os.path.exists(model_param):
                try:
                    # 先将视频拆分为帧
                    frames_dir = os.path.join(PROJECT_ROOT, 'temp', 'temp_frames')
                    enhanced_dir = os.path.join(PROJECT_ROOT, 'temp', 'enhanced_frames')
                    
                    # 获取视频总帧数
                    cap = cv2.VideoCapture(output_path)
                    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    cap.release()
                    
                    # 检查是否已有缓存的帧文件
                    frames_exist = os.path.exists(frames_dir)
                    enhanced_exist = os.path.exists(enhanced_dir)
                    
                    # 检查已提取的帧数是否匹配
                    if frames_exist:
                        existing_frames = len([f for f in os.listdir(frames_dir) if f.endswith('.png')])
                        frames_match = existing_frames == total_video_frames
                    else:
                        frames_match = False
                    
                    # 如果帧不匹配或不存在，清理并重新创建
                    import shutil
                    
                    # B站 URL 参数可能变化；同一转换后文件也视为同一视频缓存。
                    frames_from_same_url = state_entry.get("frames_url") == url if state_entry else False
                    frames_from_same_video = (
                        frames_from_same_url
                        or state_entry.get("frames_source_path") == output_path
                        or state_entry.get("converted_path") == output_path
                    ) if state_entry else False
                    
                    if not frames_match:
                        if os.path.exists(frames_dir):
                            shutil.rmtree(frames_dir)
                        os.makedirs(frames_dir, exist_ok=True)
                    elif frames_from_same_video:
                        signals.progress.emit(0, f"检测到已提取的帧 ({existing_frames}/{total_video_frames})，跳过提取步骤")
                    else:
                        # 帧文件来自不同的视频 URL，清理后重新提取
                        if os.path.exists(frames_dir):
                            shutil.rmtree(frames_dir)
                        os.makedirs(frames_dir, exist_ok=True)
                        frames_match = False
                    
                    if not enhanced_exist:
                        os.makedirs(enhanced_dir, exist_ok=True)
                    elif frames_from_same_video:
                        pass  # 同一视频复用已有增强帧，未完成的帧会在后续断点续传中继续处理
                    else:
                        # 增强帧来自不同的视频 URL，清理后重新处理
                        if os.path.exists(enhanced_dir):
                            shutil.rmtree(enhanced_dir)
                        os.makedirs(enhanced_dir, exist_ok=True)
                    
                    # 更新状态：记录当前视频的帧已提取
                    if frames_match and frames_from_same_video:
                        pass  # 已经记录过
                    elif frames_match:
                        update_url_state(url, frames_url=url, frames_source_path=output_path)
                    
                    # 原代码中额外处理
                    if not frames_match:
                        # 注：frames_match=False时，上面已经清理重建了frames_dir
                        pass
                    
                    # frames_match 后续引用，在原值基础上叠加 URL 检查
                    if not (frames_match and frames_from_same_video):
                        frames_match = False
                    
                    if frames_match and frames_from_same_video:
                        signals.progress.emit(0, f"检测到已提取的帧 ({total_video_frames} 帧)，跳过提取步骤")
                    else:
                        signals.progress.emit(0, "提取视频帧...")
                        
                        # 使用 Popen 实时读取提取进度
                        extract_cmd = ['ffmpeg', '-y', '-i', output_path, '-q:v', '1', f'{frames_dir}/frame_%08d.png']
                        extract_process = subprocess.Popen(extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                                          text=True, bufsize=1, universal_newlines=True)
                        current_running_process = extract_process
                        
                        last_extract_progress = 0
                        for line in iter(extract_process.stdout.readline, ''):
                            if line:
                                # 解析 FFmpeg 输出中的帧数
                                if 'frame=' in line:
                                    try:
                                        frame_part = line.split('frame=')[1].split()[0]
                                        current_frame = int(frame_part.strip())
                                        percent = round((current_frame / total_video_frames) * 100, 2) if total_video_frames > 0 else 0
                                        if percent > last_extract_progress:
                                            signals.progress.emit(int(percent), f"提取视频帧: {percent:.2f}% ({current_frame}/{total_video_frames})")
                                            last_extract_progress = percent
                                    except:
                                        pass
                    
                    if not frames_match:
                        extract_process.wait()
                    
                    # 保存帧提取状态，下次运行可直接复用
                    update_url_state(url, frames_url=url, frames_source_path=output_path)
                    
                    # 检查是否已取消
                    if cancel_flag:
                        signals.progress.emit(0, "任务已取消")
                        return
                    
                    # 仅遍历一次源帧目录，避免高帧数视频重复扫描导致卡顿。
                    all_source_frames = sorted(f for f in os.listdir(frames_dir) if f.endswith('.png'))
                    total_frames = len(all_source_frames)
                    
                    # ---- 帧级断点续传：检查已增强的帧，只处理未处理的帧 ----
                    already_enhanced = set()
                    if os.path.exists(enhanced_dir):
                        already_enhanced = set(f for f in os.listdir(enhanced_dir) if f.endswith('.png'))
                    
                    pending_frames = [f for f in all_source_frames if f not in already_enhanced]
                    
                    if not pending_frames:
                        signals.progress.emit(0, f"检测到已增强的帧 ({total_frames} 帧)，跳过 AI 超分辨率步骤")
                    else:
                        signals.progress.emit(
                            0,
                            f"检测到已增强 {len(already_enhanced)}/{total_frames} 帧，将继续处理剩余 {len(pending_frames)} 帧",
                        )
                        
                        # 将待处理帧复制到临时批次目录，避免重复处理已增强的帧
                        batch_dir = os.path.join(PROJECT_ROOT, 'temp', 'batch_enhance')
                        shutil.rmtree(batch_dir, ignore_errors=True)
                        os.makedirs(batch_dir, exist_ok=True)
                        for f in pending_frames:
                            shutil.copy2(os.path.join(frames_dir, f), os.path.join(batch_dir, f))
                        
                        enhance_cmd = [realesrgan_path, '-i', batch_dir, '-o', f'{enhanced_dir}/',
                                      '-n', model_name, '-m', model_dir, '-s', '4', '-j', '1:2:1', '-g', '0']
                        process = subprocess.Popen(enhance_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                 text=True, bufsize=1, universal_newlines=True)
                        current_running_process = process
                        
                        # 实时监控进度（基于已有增强帧数 + 新生成帧数）
                        base_enhanced_count = len(already_enhanced)
                        while process.poll() is None:
                            if cancel_flag:
                                process.terminate()
                                process.wait()
                                shutil.rmtree(batch_dir, ignore_errors=True)
                                signals.progress.emit(0, "任务已取消")
                                return
                            try:
                                current_enhanced = len([f for f in os.listdir(enhanced_dir) if f.endswith('.png')])
                                new_count = current_enhanced - base_enhanced_count
                                if new_count > 0:
                                    total_processed = base_enhanced_count + new_count
                                    percent = round((total_processed / total_frames) * 100, 2)
                                    signals.progress.emit(int(percent), f"AI 超分辨率: {percent:.2f}% ({total_processed}/{total_frames} 帧)")
                            except:
                                pass
                            # 每 3 秒轮询一次进度，避免频繁 listdir 导致卡顿
                            for _ in range(6):
                                if cancel_flag:
                                    break
                                time.sleep(0.5)
                        
                        shutil.rmtree(batch_dir, ignore_errors=True)
                        
                        if cancel_flag:
                            signals.progress.emit(0, "任务已取消")
                            return
                        
                        if process.returncode != 0:
                            signals.progress.emit(0, "Real-ESRGAN 执行失败，使用 FFmpeg 增强")
                            raise Exception("Real-ESRGAN 执行失败")
                        
                        current_enhanced = len([f for f in os.listdir(enhanced_dir) if f.endswith('.png')])
                        if current_enhanced <= len(already_enhanced):
                            signals.progress.emit(0, "Real-ESRGAN 未生成新输出，使用 FFmpeg 增强")
                            raise Exception("Real-ESRGAN 未生成输出")
                        
                        signals.progress.emit(0, f"AI 增强完成，共处理 {current_enhanced} 帧")
                    
                    enhanced_frame_count = len([f for f in os.listdir(enhanced_dir) if f.endswith('.png')])
                    if enhanced_frame_count == 0:
                        signals.progress.emit(0, "没有可用的增强帧，使用 FFmpeg 增强")
                        raise Exception("没有可用的增强帧")
                    
                    # 获取原始视频信息
                    cap = cv2.VideoCapture(output_path)
                    original_fps = cap.get(cv2.CAP_PROP_FPS)
                    original_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    original_duration = original_frame_count / original_fps
                    cap.release()
                    
                    # 获取增强后视频的帧率和帧数
                    cap2 = cv2.VideoCapture(f'{enhanced_dir}/frame_%08d.png')
                    enhanced_fps = cap2.get(cv2.CAP_PROP_FPS) if cap2.isOpened() else 30
                    cap2.release()
                    
                    # 统计增强后的帧数
                    enhanced_frame_count = len([f for f in os.listdir(enhanced_dir) if f.endswith('.png')])
                    
                    # 计算时间拉伸比例：原始时长 / 增强后帧数对应的时长
                    enhanced_duration = enhanced_frame_count / enhanced_fps if enhanced_fps > 0 else 30
                    pts_ratio = original_duration / enhanced_duration if enhanced_duration > 0 else 2.0
                    
                    signals.progress.emit(0, f"合成增强视频（音视频同步处理中...）...")
                    
                    # 先用原始帧率合成视频（带进度显示）
                    temp_enhanced = os.path.join(PROJECT_ROOT, 'temp', 'temp_enhanced_raw.mp4')
                    convert_cmd = ['ffmpeg', '-y', '-framerate', str(enhanced_fps), '-i', f'{enhanced_dir}/frame_%08d.png', 
                                  '-i', output_path, '-c:v', 'libx264', '-crf', '16', '-preset', 'slow', 
                                  '-pix_fmt', 'yuv420p', '-c:a', 'copy', temp_enhanced]
                    
                    process = subprocess.Popen(convert_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             text=True, bufsize=1, universal_newlines=True)
                    current_running_process = process
                    for line in iter(process.stdout.readline, ''):
                        # 检查是否已取消
                        if cancel_flag:
                            process.terminate()
                            signals.progress.emit(0, "任务已取消")
                            return
                        if line and 'frame=' in line:
                            try:
                                frame = int(line.split('frame=')[1].split()[0])
                                progress = min(int(frame / original_frame_count * 100), 99)
                                signals.progress.emit(progress, f"合成视频: {progress}%")
                            except:
                                pass
                    process.wait()
                    
                    # 检查是否已取消
                    if cancel_flag:
                        signals.progress.emit(0, "任务已取消")
                        return
                    
                    signals.progress.emit(99, "合成视频完成")
                    
                    # 步骤3：音视频同步处理
                    signals.step_changed.emit(3, 'running')
                    
                    # 音视频同步处理：调整时间戳以匹配原始视频时长（带进度显示）
                    signals.progress.emit(0, f"音视频同步处理（拉伸比例: {pts_ratio:.2f}）...")
                    sync_cmd = ['ffmpeg', '-y', '-i', temp_enhanced, '-i', output_path,
                               '-filter:v', f'setpts={pts_ratio}*PTS,fps={original_fps}', 
                               '-c:a', 'copy', '-shortest', enhanced_path]
                    
                    process = subprocess.Popen(sync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             text=True, bufsize=1, universal_newlines=True)
                    current_running_process = process
                    for line in iter(process.stdout.readline, ''):
                        # 检查是否已取消
                        if cancel_flag:
                            process.terminate()
                            signals.progress.emit(0, "任务已取消")
                            return
                        if line and 'time=' in line:
                            try:
                                time_str = line.split('time=')[1].split()[0]
                                parts = time_str.split(':')
                                if len(parts) == 3:
                                    current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                                    progress = min(int(current_sec / original_duration * 100), 99)
                                    signals.progress.emit(progress, f"音视频同步: {progress}%")
                            except:
                                pass
                    process.wait()
                    
                    # 检查是否已取消
                    if cancel_flag:
                        signals.progress.emit(0, "任务已取消")
                        return
                    
                    # 细节增强处理：改善人脸和纹理细节
                    signals.progress.emit(0, "细节增强处理...")
                    detail_enhanced = os.path.join(PROJECT_ROOT, 'temp', 'temp_detail_enhanced.mp4')
                    
                    # 组合滤镜链：
                    # 1. deband - 去色带/色块
                    # 2. unsharp - 边缘锐化
                    # 3. curves - 增强局部对比度
                    # 4. hqdn3d - 轻度降噪但保留细节
                    # 5. format - 统一像素格式
                    detail_cmd = ['ffmpeg', '-y', '-i', enhanced_path,
                                 '-vf', 'deband=1thr=0.003:2thr=0.003:3thr=0.003:range=16:blur=1,'
                                        'unsharp=5:5:0.5:3:3:0.3,'
                                        'curves=all=\'0/0 0.12/0.15 0.5/0.55 0.88/0.85 1/1\','
                                        'hqdn3d=2:1:2:1,'
                                        'format=pix_fmts=yuv420p',
                                 '-c:v', 'libx264', '-crf', '15', '-preset', 'medium',
                                 '-c:a', 'copy', detail_enhanced]
                    
                    process = subprocess.Popen(detail_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             text=True, bufsize=1, universal_newlines=True)
                    current_running_process = process
                    for line in iter(process.stdout.readline, ''):
                        # 检查是否已取消
                        if cancel_flag:
                            process.terminate()
                            signals.progress.emit(0, "任务已取消")
                            return
                        if line and 'time=' in line:
                            try:
                                time_str = line.split('time=')[1].split()[0]
                                parts = time_str.split(':')
                                if len(parts) == 3:
                                    current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                                    progress = min(int(current_sec / original_duration * 100), 99)
                                    signals.progress.emit(progress, f"细节增强: {progress}%")
                            except:
                                pass
                    process.wait()
                    
                    # 检查是否已取消
                    if cancel_flag:
                        signals.progress.emit(0, "任务已取消")
                        return
                    
                    # 替换原文件
                    if os.path.exists(detail_enhanced):
                        shutil.move(detail_enhanced, enhanced_path)
                    
                    # 清理临时文件
                    os.remove(temp_enhanced) if os.path.exists(temp_enhanced) else None
                    
                    signals.step_changed.emit(3, 'completed')  # 步骤3完成
                    signals.step_changed.emit(2, 'completed')  # 步骤2完成
                    signals.progress.emit(0, f"AI 增强完成！文件: {enhanced_path}")
                    
                except Exception as e:
                    # 提供详细的错误信息
                    error_details = []
                    if not os.path.exists(realesrgan_path):
                        error_details.append("Real-ESRGAN 工具不存在")
                    if not os.path.exists(model_bin):
                        error_details.append("模型文件 .bin 不存在")
                    if not os.path.exists(model_param):
                        error_details.append("模型文件 .param 不存在")
                    
                    if error_details:
                        error_msg = "Real-ESRGAN 不可用: " + ", ".join(error_details) + "，使用 FFmpeg 增强"
                    else:
                        error_msg = f"Real-ESRGAN 执行失败: {str(e)}，使用 FFmpeg 增强"
                    
                    signals.progress.emit(0, error_msg)
                    signals.progress.emit(0, "开始FFmpeg增强 + 细节处理...")
                    
                    # 获取原始视频信息用于同步
                    cap = cv2.VideoCapture(output_path)
                    original_fps = cap.get(cv2.CAP_PROP_FPS)
                    original_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    original_duration = original_frame_count / original_fps
                    cap.release()
                    
                    # FFmpeg增强 + 细节处理（一次性完成）
                    cmd = ['ffmpeg', '-y', '-i', output_path,
                          '-vf', 'scale=1920:1080:flags=lanczos,'
                                 'hqdn3d=4:3:6:4,'
                                 'unsharp=5:5:1.5:5:5:0.7,'
                                 'eq=contrast=1.2:brightness=0.05:saturation=1.15,'
                                 'deband=1thr=0.003:2thr=0.003:3thr=0.003:range=16:blur=1,'
                                 'format=pix_fmts=yuv420p',
                          '-c:v', 'libx264', '-crf', '16', '-preset', 'slow',
                          '-c:a', 'copy', enhanced_path]
                    
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             text=True, bufsize=1, universal_newlines=True)
                    current_running_process = process
                    for line in iter(process.stdout.readline, ''):
                        # FFmpeg 进度输出格式: time=00:00:09.86 或 time:00:00:09.86
                        if 'time=' in line or 'time:' in line:
                            try:
                                if 'time=' in line:
                                    time_str = line.split('time=')[1].split()[0]
                                else:
                                    time_str = line.split('time:')[1].split()[0]
                                parts = time_str.split(':')
                                if len(parts) == 3:
                                    current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                                    if original_duration > 0:
                                        progress = min(int(current_sec / original_duration * 100), 99)
                                        signals.progress.emit(progress, f"FFmpeg增强: {progress}%")
                            except:
                                pass
                    process.wait()
                    
                    # 检查是否已取消
                    if cancel_flag:
                        signals.progress.emit(0, "任务已取消")
                        return
                    
                    # 步骤3：音视频同步处理
                    signals.step_changed.emit(3, 'running')
                    signals.progress.emit(0, "音视频同步处理...")
                    temp_sync = os.path.join(PROJECT_ROOT, 'temp', 'temp_sync.mp4')
                    sync_cmd = ['ffmpeg', '-y', '-i', enhanced_path, '-i', output_path,
                               '-filter:v', f'setpts={original_duration / (original_duration - 0.1)}*PTS,fps={original_fps}',
                               '-c:a', 'copy', '-shortest', temp_sync]
                    
                    process = subprocess.Popen(sync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             text=True, bufsize=1, universal_newlines=True)
                    current_running_process = process
                    for line in iter(process.stdout.readline, ''):
                        # 检查是否已取消
                        if cancel_flag:
                            process.terminate()
                            signals.progress.emit(0, "任务已取消")
                            return
                        if 'time=' in line or 'time:' in line:
                            try:
                                if 'time=' in line:
                                    time_str = line.split('time=')[1].split()[0]
                                else:
                                    time_str = line.split('time:')[1].split()[0]
                                parts = time_str.split(':')
                                if len(parts) == 3:
                                    current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                                    if original_duration > 0:
                                        progress = min(int(current_sec / original_duration * 100), 99)
                                        signals.progress.emit(progress, f"音视频同步: {progress}%")
                            except:
                                pass
                    process.wait()
                    
                    # 检查是否已取消
                    if cancel_flag:
                        signals.progress.emit(0, "任务已取消")
                        return
                    
                    if os.path.exists(temp_sync):
                        shutil.move(temp_sync, enhanced_path)
                    
                    signals.step_changed.emit(3, 'completed')  # 步骤3完成
                    signals.step_changed.emit(2, 'completed')  # 步骤2完成
                    signals.progress.emit(0, f"清晰度增强完成！文件: {enhanced_path}")
            else:
                signals.progress.emit(0, "Real-ESRGAN 工具不可用，使用 FFmpeg 高级增强")
                signals.progress.emit(0, "开始FFmpeg增强 + 细节处理...")
                
                # 获取原始视频信息用于同步
                cap = cv2.VideoCapture(output_path)
                original_fps = cap.get(cv2.CAP_PROP_FPS)
                original_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                original_duration = original_frame_count / original_fps
                cap.release()
                
                # FFmpeg增强 + 细节处理（带进度显示）
                cmd = ['ffmpeg', '-y', '-i', output_path,
                      '-vf', 'scale=1920:1080:flags=lanczos,'
                             'hqdn3d=4:3:6:4,'
                             'unsharp=5:5:1.5:5:5:0.7,'
                             'eq=contrast=1.2:brightness=0.05:saturation=1.15,'
                             'deband=1thr=0.003:2thr=0.003:3thr=0.003:range=16:blur=1,'
                             'format=pix_fmts=yuv420p',
                      '-c:v', 'libx264', '-crf', '16', '-preset', 'medium',
                      '-c:a', 'copy', enhanced_path]
                
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, universal_newlines=True)
                current_running_process = process
                for line in iter(process.stdout.readline, ''):
                    # 检查是否已取消
                    if cancel_flag:
                        process.terminate()
                        signals.progress.emit(0, "任务已取消")
                        return
                    if line:
                        if 'time=' in line or 'time:' in line:
                            try:
                                if 'time=' in line:
                                    time_str = line.split('time=')[1].split()[0]
                                else:
                                    time_str = line.split('time:')[1].split()[0]
                                parts = time_str.split(':')
                                if len(parts) == 3:
                                    current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                                    if original_duration > 0:
                                        progress = min(int(current_sec / original_duration * 100), 99)
                                        signals.progress.emit(progress, f"FFmpeg增强: {progress}%")
                            except:
                                pass
                process.wait()
                
                # 检查是否已取消
                if cancel_flag:
                    signals.progress.emit(0, "任务已取消")
                    return
                
                # 步骤3：音视频同步处理
                signals.step_changed.emit(3, 'running')
                signals.progress.emit(0, "音视频同步处理...")
                temp_sync = os.path.join(PROJECT_ROOT, 'temp', 'temp_sync.mp4')
                sync_cmd = ['ffmpeg', '-y', '-i', enhanced_path, '-i', output_path,
                           '-filter:v', f'setpts={original_duration / (original_duration - 0.1)}*PTS,fps={original_fps}',
                           '-c:a', 'copy', '-shortest', temp_sync]
                
                process = subprocess.Popen(sync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, universal_newlines=True)
                current_running_process = process
                for line in iter(process.stdout.readline, ''):
                    # 检查是否已取消
                    if cancel_flag:
                        process.terminate()
                        signals.progress.emit(0, "任务已取消")
                        return
                    if 'time=' in line or 'time:' in line:
                        try:
                            if 'time=' in line:
                                time_str = line.split('time=')[1].split()[0]
                            else:
                                time_str = line.split('time:')[1].split()[0]
                            parts = time_str.split(':')
                            if len(parts) == 3:
                                current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                                if original_duration > 0:
                                    progress = min(int(current_sec / original_duration * 100), 99)
                                    signals.progress.emit(progress, f"音视频同步: {progress}%")
                        except:
                            pass
                process.wait()
                
                # 检查是否已取消
                if cancel_flag:
                    signals.progress.emit(0, "任务已取消")
                    return
                
                if os.path.exists(temp_sync):
                    shutil.move(temp_sync, enhanced_path)
                
                signals.step_changed.emit(3, 'completed')  # 步骤3完成
                signals.step_changed.emit(2, 'completed')  # 步骤2完成
                signals.progress.emit(0, f"清晰度增强完成！文件: {enhanced_path}")
        else:
            signals.error.emit(f"格式转换后的文件不存在: {output_path}")
            return
    
    # 用户取消了增强选项，标记步骤2和步骤3为完成
    if not need_enhance:
        signals.step_changed.emit(2, 'completed')
        signals.step_changed.emit(3, 'completed')
    
    signals.finished.emit("=== 所有处理完成 ===")

class VideoDownloader(FrostedGlassWindow):
    def __init__(self):
        super().__init__()
        self.start_time = None  # 记录任务开始时间
        self.task_urls = []
        self.current_task_index = 0
        self.success_count = 0
        self.failed_count = 0
        self.batch_running = False
        self.batch_settings = {}
        self.process_thread = None
        self.ignore_cancel_error_count = 0
        self.init_ui()
        self.signals = DownloadSignals()
        self.signals.progress.connect(self.update_progress)
        self.signals.finished.connect(self.on_finished)
        self.signals.error.connect(self.on_error)
        self.signals.set_enhance_checked.connect(self.on_set_enhance_checked)
        self.signals.step_changed.connect(self.on_step_changed)

    def on_set_enhance_checked(self, checked):
        """更新增强复选框状态"""
        self.enhance_check.setChecked(checked)
        
    def on_step_changed(self, step_index, status):
        """更新步骤状态显示"""
        # step_index: 0=下载视频, 1=格式转换, 2=清晰度增强, 3=音视频同步
        # status: pending/running/completed
        steps = ["下载视频", "格式转换", "清晰度增强", "音视频同步"]
        
        for i in range(len(steps)):
            circle = self.step_circles[i]
            label = self.step_labels[i]
            
            if i < step_index or (i == step_index and status == 'completed'):
                # 已完成的步骤 - 绿色实心圆
                circle.setStyleSheet("""
                    QLabel {
                        background-color: #28a745;
                        color: white;
                        border: 2px solid #28a745;
                        border-radius: 15px;
                        font-size: 14px;
                        font-weight: bold;
                    }
                """)
                circle.setText("✓")
                label.setStyleSheet("color: #28a745; font-size: 12px; font-weight: bold;")
                
            elif i == step_index and status == 'running':
                # 当前步骤 - 蓝色高亮
                circle.setStyleSheet("""
                    QLabel {
                        background-color: #007AFF;
                        color: white;
                        border: 2px solid #007AFF;
                        border-radius: 15px;
                        font-size: 14px;
                        font-weight: bold;
                    }
                """)
                circle.setText(str(i + 1))
                label.setStyleSheet("color: #007AFF; font-size: 12px; font-weight: bold;")
                
            else:
                # 待进行的步骤 - 灰色空心圆
                circle.setStyleSheet("""
                    QLabel {
                        background-color: rgba(255, 255, 255, 150);
                        color: #999;
                        border: 2px solid rgba(150, 150, 150, 200);
                        border-radius: 15px;
                        font-size: 14px;
                        font-weight: bold;
                    }
                """)
                circle.setText(str(i + 1))
                label.setStyleSheet("color: #999; font-size: 12px;")
        
        # 更新连接线颜色
        for i, line in enumerate(self.step_lines):
            if i < step_index or (i == step_index and status == 'completed'):
                # 已完成的步骤之前的线 - 绿色
                line.setStyleSheet("background-color: #28a745;")
            else:
                # 未完成的步骤之间的线 - 灰色
                line.setStyleSheet("background-color: rgba(200, 200, 200, 200);")

    def init_ui(self):
        self.setWindowTitle("B站视频增强下载器")
        self.setWindowIcon(create_app_icon())  # 设置窗口图标
        self.setGeometry(300, 300, 1200, 900)

        # 主容器
        container = QWidget()
        container.setObjectName("glassContainer")
        container.setStyleSheet("""
            #glassContainer {
                background-color: #f5f5fa;
                border-radius: 10px;
            }
        """)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 内容区域
        content_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 15, 20, 20)
        
        # 统一样式
        input_style = """
            background-color: rgba(255, 255, 255, 200);
            border: 1px solid rgba(200, 200, 200, 150);
            border-radius: 5px;
            padding: 8px;
        """
        combo_style = """
            QComboBox {
                background-color: rgba(255, 255, 255, 200);
                border: 1px solid rgba(200, 200, 200, 150);
                border-radius: 6px;
                padding: 8px 30px 8px 10px;
                color: #333;
                font-size: 13px;
            }
            QComboBox:hover {
                border: 1px solid rgba(0, 122, 255, 180);
            }
            QComboBox:on {
                border: 1px solid rgba(0, 122, 255, 200);
            }
            QComboBox::drop-down {
                border: none;
                subcontrol-origin: padding;
                subcontrol-position: right center;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #888;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(255, 255, 255, 250);
                border: 1px solid rgba(200, 200, 200, 150);
                border-radius: 6px;
                selection-background-color: #007AFF;
                selection-color: white;
                color: #333;
                outline: none;
                padding: 8px 5px;
                margin-top: 2px;
            }
            QComboBox QAbstractItemView::item {
                min-height: 32px;
                padding-left: 12px;
                border-radius: 4px;
                margin: 2px 3px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: rgba(0, 122, 255, 30);
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #007AFF;
                color: white;
            }
        """

        layout.addWidget(QLabel("B站视频链接URL:"))
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入B站视频链接")
        self.url_input.setStyleSheet(input_style)
        url_layout.addWidget(self.url_input)
        
        self.add_task_btn = QPushButton("添加任务")
        self.add_task_btn.setMaximumWidth(100)
        self.add_task_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(52, 199, 89, 220);
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(52, 199, 89, 255);
            }
            QPushButton:pressed {
                background-color: rgba(40, 167, 69, 220);
            }
            QPushButton:disabled {
                background-color: rgba(180, 180, 180, 180);
                color: rgba(120, 120, 120, 180);
            }
        """)
        self.add_task_btn.clicked.connect(self.add_task_from_input)
        url_layout.addWidget(self.add_task_btn)
        layout.addLayout(url_layout)
        
        layout.addWidget(QLabel("任务列表（按添加顺序逐个下载和转换）:"))
        self.task_list = QListWidget()
        self.task_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(255, 255, 255, 180);
                border: 1px solid rgba(200, 200, 200, 150);
                border-radius: 5px;
                color: #333;
                padding: 5px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 122, 255, 180);
                color: white;
            }
        """)
        self.task_list.setMaximumHeight(110)
        layout.addWidget(self.task_list)
        
        task_btn_layout = QHBoxLayout()
        task_btn_layout.addStretch()
        self.remove_task_btn = QPushButton("删除选中")
        self.remove_task_btn.setMaximumWidth(100)
        self.remove_task_btn.setStyleSheet(self.add_task_btn.styleSheet())
        self.remove_task_btn.clicked.connect(self.remove_selected_task)
        task_btn_layout.addWidget(self.remove_task_btn)
        
        self.clear_task_btn = QPushButton("清空列表")
        self.clear_task_btn.setMaximumWidth(100)
        self.clear_task_btn.setStyleSheet(self.add_task_btn.styleSheet())
        self.clear_task_btn.clicked.connect(self.clear_task_list)
        task_btn_layout.addWidget(self.clear_task_btn)
        layout.addLayout(task_btn_layout)

        layout.addWidget(QLabel("Cookies文件路径（下载720p+高清视频需要）:"))
        self.cookies_input = QLineEdit()
        self.cookies_input.setPlaceholderText("cookies.txt 文件路径，留空则不使用")
        self.cookies_input.setStyleSheet(input_style)
        layout.addWidget(self.cookies_input)

        # 输出目录选择
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("输出目录:"))
        
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("选择视频输出目录")
        self.output_dir_input.setText(os.path.join(PROJECT_ROOT, 'output'))  # 默认项目 output 目录
        self.output_dir_input.setStyleSheet(input_style)
        self.output_dir_input.setReadOnly(True)  # 只读，只能通过浏览按钮修改
        output_layout.addWidget(self.output_dir_input)
        
        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.setMaximumWidth(80)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 122, 255, 220);
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 122, 255, 255);
            }
            QPushButton:pressed {
                background-color: rgba(0, 90, 180, 220);
            }
        """)
        self.browse_btn.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(self.browse_btn)
        
        layout.addLayout(output_layout)

        layout.addWidget(QLabel("输出格式:"))
        self.format_box = QComboBox()
        self.format_box.setStyleSheet(combo_style)
        self.format_box.addItem("MP4")
        self.format_box.addItem("MKV")
        layout.addWidget(self.format_box)

        self.enhance_check = QCheckBox("增强清晰度（1080p 高质量缩放 + 锐化）")
        self.enhance_check.setChecked(True)  # 默认勾选
        self.enhance_check.setStyleSheet("color: #333;")
        layout.addWidget(self.enhance_check)

        # 下载按钮和取消按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.download_btn = QPushButton("下载并转换")
        self.download_btn.setMaximumWidth(120)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 122, 255, 220);
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 122, 255, 255);
            }
            QPushButton:pressed {
                background-color: rgba(0, 90, 180, 220);
            }
            QPushButton:disabled {
                background-color: rgba(180, 180, 180, 180);
                color: rgba(120, 120, 120, 180);
            }
        """)
        self.download_btn.clicked.connect(self.process_video)
        btn_layout.addWidget(self.download_btn)
        
        self.cancel_btn = QPushButton("取消当前")
        self.cancel_btn.setMaximumWidth(90)
        self.cancel_btn.hide()  # 初始隐藏，任务进行时显示
        self.cancel_btn.setStyleSheet("""
            background-color: rgba(255, 59, 48, 220);
            color: white;
            border: none;
            border-radius: 5px;
            padding: 8px 15px;
            font-weight: bold;
        """)
        self.cancel_btn.clicked.connect(self.cancel_process)
        btn_layout.addWidget(self.cancel_btn)
        
        self.cancel_all_btn = QPushButton("取消全部")
        self.cancel_all_btn.setMaximumWidth(90)
        self.cancel_all_btn.hide()
        self.cancel_all_btn.setStyleSheet(self.cancel_btn.styleSheet())
        self.cancel_all_btn.clicked.connect(self.cancel_all_process)
        btn_layout.addWidget(self.cancel_all_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.task_status_label = QLabel("任务状态：未开始")
        self.task_status_label.setStyleSheet("""
            QLabel {
                color: #007AFF;
                font-size: 15px;
                font-weight: bold;
                padding: 4px 0;
            }
        """)
        layout.addWidget(self.task_status_label)

        self.progress_label = QLabel("当前任务流程:")
        self.progress_label.setStyleSheet("color: #333; font-weight: bold;")
        layout.addWidget(self.progress_label)
        
        # 步骤显示区域
        self.steps_widget = QWidget()
        steps_layout = QHBoxLayout()
        steps_layout.setContentsMargins(20, 10, 20, 10)
        steps_layout.setSpacing(0)
        
        self.step_circles = []  # 圆圈控件
        self.step_labels = []   # 步骤标签
        self.step_lines = []    # 连接线
        steps_info = ["下载视频", "格式转换", "清晰度增强", "音视频同步"]
        
        for i, step_name in enumerate(steps_info):
            # 步骤容器
            step_container = QWidget()
            step_v_layout = QVBoxLayout()
            step_v_layout.setContentsMargins(0, 0, 0, 0)
            step_v_layout.setSpacing(5)
            
            # 圆圈
            circle = QLabel()
            circle.setFixedSize(30, 30)
            circle.setAlignment(Qt.AlignCenter)
            circle.setText(str(i + 1))
            circle.setStyleSheet("""
                QLabel {
                    background-color: rgba(200, 200, 200, 200);
                    color: white;
                    border: 2px solid rgba(150, 150, 150, 200);
                    border-radius: 15px;
                    font-size: 14px;
                    font-weight: bold;
                }
            """)
            self.step_circles.append(circle)
            step_v_layout.addWidget(circle, alignment=Qt.AlignCenter)
            
            # 步骤名称
            step_label = QLabel(step_name)
            step_label.setStyleSheet("color: #999; font-size: 12px;")
            step_label.setAlignment(Qt.AlignCenter)
            self.step_labels.append(step_label)
            step_v_layout.addWidget(step_label, alignment=Qt.AlignCenter)
            
            step_container.setLayout(step_v_layout)
            steps_layout.addWidget(step_container)
            
            # 添加连接线（除了最后一个）
            if i < len(steps_info) - 1:
                line = QLabel()
                line.setFixedHeight(3)
                line.setMinimumWidth(40)
                line.setStyleSheet("background-color: rgba(200, 200, 200, 200);")
                self.step_lines.append(line)
                steps_layout.addWidget(line)
        
        self.steps_widget.setLayout(steps_layout)
        layout.addWidget(self.steps_widget)

        # 进度条容器（包含进度条和百分比标签）
        progress_container = QWidget()
        progress_container_layout = QHBoxLayout()
        progress_container_layout.setContentsMargins(0, 0, 0, 0)
        progress_container_layout.setSpacing(5)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 10000)  # 范围改为 0-10000，这样可以显示两位小数精度
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")  # 使用自定义格式显示百分比
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(220, 220, 220, 180);
                border: 1px solid rgba(180, 180, 180, 150);
                border-radius: 5px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #007AFF, stop:1 #5856D6);
                border-radius: 5px;
            }
        """)
        progress_container_layout.addWidget(self.progress_bar)
        
        # 添加百分比标签，显示精确的小数精度
        self.progress_percent_label = QLabel("0.00%")
        self.progress_percent_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.progress_percent_label.setStyleSheet("""
            QLabel {
                color: #007AFF;
                font-size: 14px;
                font-weight: bold;
                min-width: 70px;
                padding-right: 5px;
            }
        """)
        progress_container_layout.addWidget(self.progress_percent_label)
        
        progress_container.setLayout(progress_container_layout)
        layout.addWidget(progress_container)
        
        # 耗时显示标签
        self.time_label = QLabel("当前步骤 已耗时: --:-- | 预估剩余: --:--")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("""
            color: #007AFF;
            font-size: 12px;
            font-weight: bold;
            padding: 5px;
        """)
        layout.addWidget(self.time_label)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("""
            background-color: rgba(255, 255, 255, 180);
            border: 1px solid rgba(200, 200, 200, 150);
            border-radius: 5px;
            color: #333;
        """)
        self.status_text.setMaximumHeight(150)
        layout.addWidget(self.status_text)

        tips_label = QLabel("<font color='gray'>提示：下载720p及以上分辨率视频需要登录B站账号的cookies</font>")
        tips_label.setWordWrap(True)
        layout.addWidget(tips_label)
        
        content_widget.setLayout(layout)
        main_layout.addWidget(content_widget)
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def update_progress(self, percentage, message):
        import time as time_module
        
        # 如果是开始处理（百分比为0），记录开始时间
        if percentage == 0 and not self.start_time:
            self.start_time = time_module.time()
        
        # 从消息中提取精确的百分比数值
        percent_match = re.search(r'(\d+\.?\d*)%', message)
        percent_value = float(percent_match.group(1)) if percent_match else float(percentage)
        
        # 更新进度条，使用精确的小数精度显示文本
        self.progress_bar.setValue(int(percent_value * 100))  # 将百分比转换为 0-10000 范围
        self.progress_bar.setFormat(f"{percent_value:.2f}%")  # 显示两位小数
        
        # 更新百分比标签，显示精确的小数精度
        self.progress_percent_label.setText(f"{percent_value:.2f}%")
        
        # 更新耗时显示
        if self.start_time:
            elapsed_time = time_module.time() - self.start_time
            elapsed_str = self.format_time(elapsed_time)
            
            if percent_value > 0:
                # 计算预估剩余时间
                total_estimated_time = elapsed_time / (percent_value / 100)
                remaining_time = total_estimated_time - elapsed_time
                remaining_str = self.format_time(remaining_time)
                self.time_label.setText(f"已耗时: {elapsed_str} | 预估剩余: {remaining_str}")
            else:
                self.time_label.setText(f"已耗时: {elapsed_str} | 预估剩余: --:--")
        else:
            self.time_label.setText("已耗时: --:-- | 预估剩余: --:--")
        
        # 显示消息
        # 如果是进度消息（包含 "%"），每隔10%显示一次，或者显示帧数信息
        if re.search(r'\d+%', message):
            # 对于 AI 超分辨率，即使进度很低也要显示帧数信息
            if 'AI 超分辨率' in message or int(percent_value) % 10 == 0 or percent_value == 0:
                self.status_text.append(message)
                self.status_text.verticalScrollBar().setValue(self.status_text.verticalScrollBar().maximum())
        else:
            # 关键步骤消息，总是显示
            self.status_text.append(message)
            self.status_text.verticalScrollBar().setValue(self.status_text.verticalScrollBar().maximum())
    
    def format_time(self, seconds):
        """格式化时间显示"""
        if seconds < 0:
            return "--:--"
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    def on_finished(self, message):
        global current_running_process
        current_running_process = None
        self.status_text.append(message)
        self.progress_bar.setValue(10000)
        self.progress_bar.setFormat("100.00%")
        self.progress_percent_label.setText("100.00%")
        self.start_time = None  # 重置开始时间
        self.time_label.setText("已耗时: --:-- | 预估剩余: --:--")
        
        if cancel_flag:
            return
        
        if self.batch_running:
            self.success_count += 1
            self.status_text.append(f"任务 {self.current_task_index + 1}/{len(self.task_urls)} 处理完成")
            self.current_task_index += 1
            self.run_next_task()
            return
        
        self.set_task_controls_enabled(True)
        self.cancel_btn.hide()
        self.cancel_all_btn.hide()
        QMessageBox.information(self, "完成", "视频处理完成！", QMessageBox.Ok)

    def on_error(self, error_msg):
        global current_running_process
        current_running_process = None
        if self.ignore_cancel_error_count > 0:
            self.ignore_cancel_error_count -= 1
            return
        
        self.status_text.append(f"错误: {error_msg}")
        self.start_time = None  # 重置开始时间
        self.time_label.setText("已耗时: --:-- | 预估剩余: --:--")
        
        if cancel_flag:
            self.batch_running = False
            self.set_task_controls_enabled(True)
            self.cancel_btn.hide()
            self.cancel_all_btn.hide()
            self.update_task_status_label("cancelled")
            return
        
        if self.batch_running:
            self.failed_count += 1
            self.status_text.append(f"任务 {self.current_task_index + 1}/{len(self.task_urls)} 处理失败，继续下一个任务")
            self.current_task_index += 1
            self.run_next_task()
            return
        
        self.set_task_controls_enabled(True)
        self.cancel_btn.hide()
        self.cancel_all_btn.hide()
        critical_errors = ['下载失败', '格式转换失败', '未找到', '不存在']
        if any(keyword in error_msg for keyword in critical_errors):
            QMessageBox.critical(self, "错误", f"{error_msg}", QMessageBox.Ok)

    def cancel_process(self):
        """取消当前任务。批量模式下跳过当前任务并继续下一个任务。"""
        global current_running_process, cancel_flag, cancelled_process_ids
        was_batch_running = self.batch_running
        cancelled_task_number = self.current_task_index + 1
        should_ignore_cancel_error = False
        cancel_flag = True  # 设置取消标志
        if current_running_process:
            command_text = " ".join(current_running_process.args) if isinstance(current_running_process.args, list) else str(current_running_process.args)
            should_ignore_cancel_error = "you_get" not in command_text
            if current_running_process.pid:
                cancelled_process_ids.add(current_running_process.pid)
            current_running_process.terminate()
            current_running_process = None
        
        if was_batch_running:
            self.failed_count += 1
            if should_ignore_cancel_error:
                self.ignore_cancel_error_count += 1
            has_next_task = cancelled_task_number < len(self.task_urls)
            next_action = "继续下一个任务" if has_next_task else "已没有后续任务"
            self.status_text.append(f"任务 {cancelled_task_number}/{len(self.task_urls)} 已取消，{next_action}")
            self.current_task_index += 1
            cancel_flag = False
            self.start_time = None
            self.time_label.setText("已耗时: --:-- | 预估剩余: --:--")
            self.run_next_task()
            return
        
        self.status_text.append("操作已取消")
        self.progress_bar.setValue(0)
        self.batch_running = False
        self.set_task_controls_enabled(True)
        self.cancel_btn.hide()
        self.cancel_all_btn.hide()
        self.update_task_status_label("cancelled")
        self.start_time = None  # 重置开始时间
        self.time_label.setText("已耗时: --:-- | 预估剩余: --:--")
        # 重置步骤显示
        steps = ["下载视频", "格式转换", "清晰度增强", "音视频同步"]
        for i in range(len(steps)):
            circle = self.step_circles[i]
            label = self.step_labels[i]
            # 重置为灰色空心圆
            circle.setStyleSheet("""
                QLabel {
                    background-color: rgba(255, 255, 255, 150);
                    color: #999;
                    border: 2px solid rgba(150, 150, 150, 200);
                    border-radius: 15px;
                    font-size: 14px;
                    font-weight: bold;
                }
            """)
            circle.setText(str(i + 1))
            label.setStyleSheet("color: #999; font-size: 12px;")
        # 重置连接线
        for line in self.step_lines:
            line.setStyleSheet("background-color: rgba(200, 200, 200, 200);")

    def cancel_all_process(self):
        """取消全部任务，终止当前任务并停止后续队列。"""
        global current_running_process, cancel_flag, cancelled_process_ids
        was_batch_running = self.batch_running
        should_ignore_cancel_error = False
        cancel_flag = True
        
        if current_running_process:
            command_text = " ".join(current_running_process.args) if isinstance(current_running_process.args, list) else str(current_running_process.args)
            should_ignore_cancel_error = "you_get" not in command_text
            if current_running_process.pid:
                cancelled_process_ids.add(current_running_process.pid)
            current_running_process.terminate()
            current_running_process = None
        
        if was_batch_running and self.current_task_index < len(self.task_urls):
            self.failed_count += 1
            if should_ignore_cancel_error:
                self.ignore_cancel_error_count += 1
        
        self.batch_running = False
        self.status_text.append("全部任务已取消")
        self.progress_bar.setValue(0)
        self.set_task_controls_enabled(True)
        self.cancel_btn.hide()
        self.cancel_all_btn.hide()
        self.update_task_status_label("cancelled")
        self.start_time = None
        self.time_label.setText("已耗时: --:-- | 预估剩余: --:--")
        self.reset_step_display()
    
    def browse_output_dir(self):
        """浏览选择输出目录"""
        from PyQt5.QtWidgets import QFileDialog
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录", os.getcwd())
        if directory:
            self.output_dir_input.setText(directory)

    def validate_video_url(self, url):
        """校验 URL 格式、支持范围和可访问性。"""
        if not url:
            return False, "请输入视频URL"
        
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            return False, "地址非法，请输入 http 或 https 的网址"
        
        if not is_supported_video_url(url):
            return False, "地址非法，请输入 B 站视频地址"
        
        is_accessible, error_reason, final_url = check_url_accessible(url)
        if not is_accessible:
            message = "地址无效或无法访问，请检查后重新输入"
            if error_reason:
                message += f"\n原因：{error_reason}"
            return False, message
        
        if final_url and not is_supported_video_url(final_url):
            return False, "地址非法，请输入 B 站视频地址"
        
        return True, ""

    def add_task_from_input(self):
        """将输入框中的 URL 添加到任务列表。"""
        url = self.url_input.text().strip()
        is_valid, message = self.validate_video_url(url)
        if not is_valid:
            QMessageBox.warning(self, "提示", message, QMessageBox.Ok)
            return False
        
        existing_urls = self.get_task_urls()
        if url in existing_urls:
            QMessageBox.warning(self, "提示", "该 URL 已在任务列表中", QMessageBox.Ok)
            return False
        
        self.task_list.addItem(url)
        self.url_input.clear()
        self.update_task_status_label()
        return True

    def remove_selected_task(self):
        """删除当前选中的任务。"""
        if self.task_list.count() == 0:
            QMessageBox.information(self, "提示", "任务列表为空，请先添加任务", QMessageBox.Ok)
            return
        
        selected_row = self.task_list.currentRow()
        if selected_row >= 0:
            self.task_list.takeItem(selected_row)
            self.update_task_status_label()
        else:
            QMessageBox.information(self, "提示", "请先选择要删除的任务", QMessageBox.Ok)

    def clear_task_list(self):
        """清空任务列表。"""
        if self.task_list.count() == 0:
            QMessageBox.information(self, "提示", "任务列表为空，无需清空", QMessageBox.Ok)
            return
        
        self.task_list.clear()
        self.update_task_status_label()

    def get_task_urls(self):
        """获取任务列表中的 URL。"""
        return [self.task_list.item(i).text() for i in range(self.task_list.count())]

    def set_task_controls_enabled(self, enabled):
        """根据任务状态启用或禁用相关控件。"""
        self.download_btn.setEnabled(enabled)
        self.add_task_btn.setEnabled(enabled)
        self.remove_task_btn.setEnabled(enabled)
        self.clear_task_btn.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)
        self.url_input.setEnabled(enabled)
        self.cookies_input.setEnabled(enabled)
        self.output_dir_input.setEnabled(enabled)
        self.format_box.setEnabled(enabled)
        self.enhance_check.setEnabled(enabled)

    def update_task_status_label(self, status="idle"):
        """更新批量任务状态显示。"""
        total = len(self.task_urls) if self.task_urls else self.task_list.count()
        current = self.current_task_index + 1 if total else 0
        
        if status == "running" and total:
            self.task_status_label.setText(
                f"任务状态：共有 <span style='color:#2F6F9F; font-weight:800;'>{total}</span> 个任务，"
                f"当前第 <span style='color:#2F6F9F; font-weight:800;'>{current}</span> 个任务进行中"
            )
        elif status == "completed" and total:
            self.task_status_label.setText(
                f"任务状态：共有 <span style='color:#2F6F9F; font-weight:800;'>{total}</span> 个任务，"
                f"已全部处理完成，成功 <span style='color:#28a745; font-weight:800;'>{self.success_count}</span> 个，"
                f"失败 <span style='color:#FF3B30; font-weight:800;'>{self.failed_count}</span> 个"
            )
        elif status == "cancelled" and total:
            current = min(current, total)
            self.task_status_label.setText(
                f"任务状态：共有 <span style='color:#2F6F9F; font-weight:800;'>{total}</span> 个任务，"
                f"已在第 <span style='color:#2F6F9F; font-weight:800;'>{current}</span> 个任务取消"
            )
        elif total:
            self.task_status_label.setText(
                f"任务状态：共有 <span style='color:#2F6F9F; font-weight:800;'>{total}</span> 个任务，等待开始"
            )
        else:
            self.task_status_label.setText("任务状态：未开始")

    def reset_step_display(self):
        """重置步骤显示和进度信息。"""
        steps = ["下载视频", "格式转换", "清晰度增强", "音视频同步"]
        for i in range(len(steps)):
            circle = self.step_circles[i]
            label = self.step_labels[i]
            circle.setStyleSheet("""
                QLabel {
                    background-color: rgba(255, 255, 255, 150);
                    color: #999;
                    border: 2px solid rgba(150, 150, 150, 200);
                    border-radius: 15px;
                    font-size: 14px;
                    font-weight: bold;
                }
            """)
            circle.setText(str(i + 1))
            label.setText(steps[i])
            label.setStyleSheet("color: #999; font-size: 12px;")
        
        for line in self.step_lines:
            line.setStyleSheet("background-color: rgba(200, 200, 200, 200);")
        
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0.00%")
        self.progress_percent_label.setText("0.00%")

    def run_next_task(self):
        """按任务列表顺序执行下一个任务。"""
        if cancel_flag:
            return
        
        if self.current_task_index >= len(self.task_urls):
            self.batch_running = False
            self.set_task_controls_enabled(True)
            self.cancel_btn.hide()
            self.cancel_all_btn.hide()
            self.task_list.clearSelection()
            self.update_task_status_label("completed")
            summary = f"批量处理完成！成功 {self.success_count} 个，失败 {self.failed_count} 个。"
            self.status_text.append(summary)
            QMessageBox.information(self, "完成", summary, QMessageBox.Ok)
            return
        
        url = self.task_urls[self.current_task_index]
        total = len(self.task_urls)
        self.task_list.setCurrentRow(self.current_task_index)
        self.reset_step_display()
        self.update_task_status_label("running")
        self.start_time = None
        self.status_text.append(f"开始处理任务 {self.current_task_index + 1}/{total}: {url}")
        
        self.process_thread = Thread(
            target=process_video_task,
            args=(
                url,
                self.batch_settings["output_dir"],
                self.batch_settings["cookies_file"],
                self.batch_settings["output_format"],
                self.batch_settings["need_enhance"],
                self.signals
            )
        )
        self.process_thread.daemon = True
        self.process_thread.start()

    def process_video(self):
        global current_running_process, cancel_flag
        current_running_process = None
        cancel_flag = False  # 重置取消标志

        if self.url_input.text().strip() and not self.add_task_from_input():
            return
        
        task_urls = self.get_task_urls()
        if not task_urls:
            QMessageBox.warning(self, "提示", "请先添加至少一个 B 站视频任务", QMessageBox.Ok)
            return

        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            output_dir = os.getcwd()
        os.makedirs(output_dir, exist_ok=True)
        
        self.task_urls = task_urls
        self.current_task_index = 0
        self.success_count = 0
        self.failed_count = 0
        self.batch_running = True
        self.batch_settings = {
            "output_dir": output_dir,
            "cookies_file": self.cookies_input.text().strip(),
            "output_format": self.format_box.currentText(),
            "need_enhance": self.enhance_check.isChecked()
        }
        
        self.set_task_controls_enabled(False)
        self.cancel_btn.show()
        self.cancel_all_btn.show()
        self.status_text.clear()
        self.status_text.append(f"开始批量处理，共 {len(self.task_urls)} 个任务")
        self.update_task_status_label("running")
        self.run_next_task()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(create_app_icon())  # 设置应用程序图标
    
    app.setStyleSheet("""
        QMessageBox QPushButton {
            border: 1px solid #007AFF;
            padding: 6px 20px;
            border-radius: 6px;
            background-color: #007AFF;
            color: white;
            font-weight: bold;
            margin: 0;
            min-width: 80px;
        }
        QMessageBox QPushButton:hover {
            background-color: #0056CC;
            border-color: #0056CC;
        }
        QMessageBox QPushButton:pressed {
            background-color: #003D99;
            border-color: #003D99;
        }
        QMessageBox QPushButton:default {
            background-color: #007AFF;
            border-color: #007AFF;
        }
    """)
    window = VideoDownloader()
    window.show()
    sys.exit(app.exec_())
