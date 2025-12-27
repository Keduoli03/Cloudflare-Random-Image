import json
import math
import shutil
import urllib.parse
import sys
import os
from pathlib import Path
from itertools import cycle

# Try to import Pillow for image dimension detection
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("Warning: Pillow is not installed. Aspect ratio classification will be skipped.")

# ================= 配置区域 =================

# 基础 Hex 长度 (保底)
MIN_HEX_LEN = 1

# 图片源目录 (本地)
SOURCE_DIR = Path("image")

# 输出目录 (本地)
OUTPUT_DIR = Path("dist")

# 是否转换 WebP (True/False)
CONVERT_WEBP = True

# 输出文件后缀
DEFAULT_EXT = ".jpg" 

# 部署域名
DOMAIN = "image.blueke.dpdns.org"

# ===========================================
# 仓库 URL 和 CDN 提供方
REPO_URL = "https://github.com/Keduoli03/Cloudflare-Random-Image"
CDN_PROVIDER = "https://gcore.jsdelivr.net/gh/Keduoli03/Cloudflare-Random-Image@dist"
# ===========================================

def calculate_hex_len(item_count: int, min_len: int) -> int:
    """根据数据量自动计算所需的 Hex 长度"""
    if item_count == 0:
        return min_len
    needed = math.ceil(math.log(item_count, 16))
    return max(min_len, needed)

def generate_cf_rule(hex_len: int) -> str:
    """生成 Cloudflare 规则表达式"""
    
    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT
    
    # 使用 CDN_PROVIDER 拼接完整 URL (Redirect 模式)
    # 如果为空，则回退到相对路径 (Rewrite 模式，虽然用户现在要求用 CDN)
    base_url = CDN_PROVIDER if CDN_PROVIDER else ""
    
    # 1. Landscape (横屏) -> 映射到 CDN/lxxxx.webp
    rule_landscape = f'concat("{base_url}/l", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{ext}")'
    
    # 2. Portrait (竖屏) -> 映射到 CDN/pxxxx.webp
    rule_portrait = f'concat("{base_url}/p", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{ext}")'
    
    # Rule 3: Random (Mixed)
    # 逻辑：取 uuid 第0位字符，若是 0-7 -> l，若是 8-f -> p
    # 使用 regex_replace 在 Redirect Expression 中直接分流，无需拆分规则
    random_char = 'substring(uuidv4(cf.random_seed), 0, 1)'
    prefix_logic = f'regex_replace(regex_replace({random_char}, "[0-7]", "l"), "[89a-f]", "p")'
    
    # 这里的 substring(..., 1, hex_len) 是取文件名部分
    rule_random = f'concat("{base_url}/", {prefix_logic}, substring(uuidv4(cf.random_seed), 1, {hex_len}), "{ext}")'
    
    content = [
        "===========================================================",
        "【Cloudflare 规则配置说明】",
        "现在我们将随机分流逻辑合并到了一条规则中 (Rule 3)。",
        "请在 Redirect Rules 中创建以下 3 条规则。",
        "===========================================================",
        "",
        "--- Rule 1: Landscape (指定横屏) ---",
        "Rule Name: Random Image - Landscape",
        "Match Expression:",
        f'(http.host eq "{DOMAIN}" and http.request.uri.path eq "/l")',
        "Redirect Expression (Dynamic):",
        f'{rule_landscape}',
        "",
        "--- Rule 2: Portrait (指定竖屏) ---",
        "Rule Name: Random Image - Portrait",
        "Match Expression:",
        f'(http.host eq "{DOMAIN}" and http.request.uri.path eq "/p")',
        "Redirect Expression (Dynamic):",
        f'{rule_portrait}',
        "",
        "--- Rule 3: Random (All) ---",
        "Rule Name: Random Image - All",
        "Match Expression (这是兜底规则，放在最后):",
        f'(http.host eq "{DOMAIN}" and (http.request.uri.path eq "/" or (http.request.uri.path ne "/l" and http.request.uri.path ne "/p")))',
        "Redirect Expression (Dynamic - 请点击 Edit expression 粘贴):",
        f'{rule_random}',
        ""
    ]
    
    return "\n".join(content)

def ensure_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)

def scan_images(source_dir: Path):
    """扫描所有图片并分类"""
    all_imgs = [] # 这里 all_imgs 实际上只是用来计数总量的
    landscape_imgs = []
    portrait_imgs = []
    
    if not source_dir.exists():
        print(f"Error: Source directory '{source_dir}' does not exist.")
        return [], [], []

    exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}
    
    print(f"Scanning images in {source_dir}...")
    
    for file_path in source_dir.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in exts:
            
            item = {'path': file_path}
            
            is_portrait = False
            # 分类
            try:
                if HAS_PILLOW:
                    with Image.open(file_path) as img:
                        width, height = img.size
                        if width > height:
                            landscape_imgs.append(item)
                        else:
                            portrait_imgs.append(item)
                            is_portrait = True
                else:
                    # 默认横屏
                    landscape_imgs.append(item)
            except Exception as e:
                print(f"Warning: Could not open {file_path}: {e}")
                continue
            
            all_imgs.append(item)

    return all_imgs, landscape_imgs, portrait_imgs

def process_file(source_path: Path, target_path: Path):
    """处理文件：转换或复制"""
    if CONVERT_WEBP:
        try:
            with Image.open(source_path) as img:
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                     pass 
                else:
                     img = img.convert('RGB')
                img.save(target_path, 'WEBP', quality=85)
        except Exception as e:
            print(f"Error converting {source_path}: {e}")
    else:
        shutil.copy2(source_path, target_path)

def write_files_prefix(data_list, output_dir: Path, hex_len: int, prefix: str):
    """使用前缀写入文件"""
    if not data_list:
        return

    total_slots = 16 ** hex_len
    buckets = [[] for _ in range(total_slots)]
    
    data_cycle = cycle(data_list)
    for i in range(total_slots):
        buckets[i] = next(data_cycle)
    
    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT

    for i in range(total_slots):
        hex_name = f"{i:0{hex_len}x}"
        # 文件名格式: prefixhex.ext (e.g., l0a.webp)
        target_filename = f"{prefix}{hex_name}{ext}"
        target_path = output_dir / target_filename
        
        source_item = buckets[i]
        source_path = source_item['path']
        
        process_file(source_path, target_path)

    print(f"  Generated {total_slots} files with prefix '{prefix}' in {output_dir}")

def main():
    # 1. 扫描
    all_imgs, landscape, portrait = scan_images(SOURCE_DIR)
    
    print(f"Found {len(all_imgs)} images.")
    print(f"  Landscape: {len(landscape)}")
    print(f"  Portrait:  {len(portrait)}")
    
    if len(all_imgs) == 0:
        print("Error: No images found.")
        sys.exit(1)

    # 2. 计算 Hex 长度 (分别计算，或者统一计算)
    # 为了简化 Cloudflare 规则，建议统一长度，取最大值
    max_count = max(len(landscape), len(portrait))
    hex_len = calculate_hex_len(max_count, MIN_HEX_LEN)
    print(f"Calculated Hex Length: {hex_len}")
    
    # 3. 清理并生成目录
    ensure_dir(OUTPUT_DIR)
    
    # 4. 生成文件 (前缀模式，扁平化存储)
    # 这里的 OUTPUT_DIR 就是 dist/
    print("Generating landscape files (l-xx)...")
    write_files_prefix(landscape, OUTPUT_DIR, hex_len, "l")
    
    print("Generating portrait files (p-xx)...")
    write_files_prefix(portrait, OUTPUT_DIR, hex_len, "p")
    
    # 5. 生成 rules.txt
    rules = generate_cf_rule(hex_len)
    with open(OUTPUT_DIR / "rules.txt", 'w', encoding='utf-8') as f:
        f.write(rules)
        
    print("Done! Check 'dist' directory.")

if __name__ == "__main__":
    main()
