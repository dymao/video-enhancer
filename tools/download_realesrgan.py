#!/usr/bin/env python3
"""
Real-ESRGAN 工具下载脚本
用于下载和安装 Real-ESRGAN ncnn-vulkan 预编译版本
"""

import os
import urllib.request
import zipfile
import sys

# 项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def download_realesrgan():
    """下载并安装 Real-ESRGAN 工具"""
    
    print("=" * 60)
    print("Real-ESRGAN 工具下载脚本")
    print("=" * 60)
    
    # 下载URL
    download_url = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip"
    tool_name = "realesrgan-ncnn-vulkan"
    
    # 工具安装目录
    tools_dir = os.path.join(PROJECT_ROOT, 'tools')
    os.makedirs(tools_dir, exist_ok=True)
    tool_path = os.path.join(tools_dir, tool_name)
    zip_file = os.path.join(tools_dir, 'realesrgan-ncnn-vulkan-macos.zip')
    
    # 检查是否已存在
    if os.path.exists(tool_path):
        print(f"✓ {tool_name} 已存在，跳过下载")
        return True
    
    try:
        # 下载文件
        print(f"\n正在下载 Real-ESRGAN 工具...")
        print(f"下载地址: {download_url}")
        
        def show_progress(block_num, block_size, total_size):
            """显示下载进度"""
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(downloaded * 100 / total_size, 100)
                sys.stdout.write(f"\r下载进度: {percent:.1f}% ({downloaded / (1024*1024):.1f}MB / {total_size / (1024*1024):.1f}MB)")
                sys.stdout.flush()
        
        urllib.request.urlretrieve(download_url, zip_file, show_progress)
        print(f"\n✓ 下载完成")
        
        # 解压文件
        print(f"\n正在解压文件...")
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(tools_dir)
        print(f"✓ 解压完成")
        
        # 添加执行权限
        if os.path.exists(tool_path):
            os.chmod(tool_path, 0o755)
            print(f"✓ 已添加执行权限")
        else:
            print(f"✗ 解压后未找到 {tool_name}")
            return False
        
        # 清理下载的zip文件
        os.remove(zip_file)
        print(f"✓ 已清理临时文件")
        
        # 验证工具是否可用
        print(f"\n正在验证工具...")
        result = os.system(f"{tool_path} -h > /dev/null 2>&1")
        if result == 0:
            print(f"✓ {tool_name} 安装成功并可用")
            return True
        else:
            print(f"✗ {tool_name} 验证失败，但文件已存在")
            return True
            
    except Exception as e:
        print(f"\n✗ 下载失败: {str(e)}")
        return False

def check_models():
    """检查模型文件是否存在"""
    print(f"\n检查模型文件...")
    
    model_dir = os.path.join(PROJECT_ROOT, 'resources', 'models')
    required_models = [
        ("realesrgan-x4plus.bin", "67MB"),
        ("realesrgan-x4plus.param", "113KB")
    ]
    
    all_exist = True
    for model_file, expected_size in required_models:
        model_path = os.path.join(model_dir, model_file)
        if os.path.exists(model_path):
            size = os.path.getsize(model_path)
            print(f"✓ {model_file} 存在 ({size / (1024*1024):.1f}MB)")
        else:
            print(f"✗ {model_file} 不存在")
            all_exist = False
    
    return all_exist

if __name__ == "__main__":
    print()
    
    # 下载工具
    success = download_realesrgan()
    
    # 检查模型
    models_ok = check_models()
    
    print("\n" + "=" * 60)
    if success and models_ok:
        print("✓ Real-ESRGAN 工具和模型文件都已就绪")
        print("现在可以使用 AI 超分辨率功能了！")
    elif success:
        print("⚠ Real-ESRGAN 工具已安装，但模型文件不完整")
        print(f"请确保 {model_dir} 目录中有完整的模型文件")
    else:
        print("✗ Real-ESRGAN 工具安装失败")
        print("程序将自动使用 FFmpeg 增强作为替代方案")
    print("=" * 60)
    print()