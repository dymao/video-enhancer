#!/usr/bin/env python3
import urllib.request
import os
import zipfile

# 模型文件目录
model_dir = '/Users/mervin/PycharmProjects/realesrgan_models'
os.makedirs(model_dir, exist_ok=True)

# 下载 Real-ESRGAN ncnn macOS 包（包含模型文件）
url = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip'
zip_path = os.path.join(model_dir, 'realesrgan-ncnn-vulkan-macos.zip')

print(f'正在下载 Real-ESRGAN ncnn macOS 包...')
print(f'URL: {url}')

try:
    urllib.request.urlretrieve(url, zip_path)
    file_size = os.path.getsize(zip_path)
    print(f'下载完成！文件大小: {file_size / (1024*1024):.2f} MB')
    
    # 解压并提取模型文件
    print('正在解压并提取模型文件...')
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # 列出所有文件
        all_files = zip_ref.namelist()
        print(f'压缩包内文件: {all_files}')
        
        # 提取 models 目录下的文件
        for file in all_files:
            if 'models/' in file and (file.endswith('.bin') or file.endswith('.param')):
                zip_ref.extract(file, model_dir)
                print(f'已提取: {file}')
    
    # 移动模型文件到正确位置
    extracted_models_dir = os.path.join(model_dir, 'models')
    if os.path.exists(extracted_models_dir):
        for f in os.listdir(extracted_models_dir):
            src = os.path.join(extracted_models_dir, f)
            dst = os.path.join(model_dir, f)
            os.rename(src, dst)
            print(f'移动: {f}')
        os.rmdir(extracted_models_dir)
    
    # 删除 zip 文件
    os.remove(zip_path)
    print('清理完成！')
    
    # 列出最终模型文件
    print('\n最终模型文件:')
    for f in os.listdir(model_dir):
        fpath = os.path.join(model_dir, f)
        fsize = os.path.getsize(fpath)
        print(f'  {f} ({fsize / 1024:.1f} KB)')
        
except Exception as e:
    print(f'下载失败: {e}')
    import traceback
    traceback.print_exc()
