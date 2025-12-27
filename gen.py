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
# 1 -> 16 files, 2 -> 256 files, 3 -> 4096 files
MIN_HEX_LEN = 1

# 图片源目录 (本地)
SOURCE_DIR = Path("image")

# 输出目录 (本地)
OUTPUT_DIR = Path("dist")

# 自定义加速域名 (如果使用 JSON 模式)
# 示例: https://gcore.jsdelivr.net/gh/Keduoli03/My_img@main/image/
# 注意：此变量目前在文件模式下不直接使用，但为了兼容性保留
CDN_PROVIDER = "https://gcore.jsdelivr.net/gh"
REPO_USER = "Keduoli03"
REPO_NAME = "Cloudflare-Random-Image"
BRANCH = "main"
BASE_URL = f"{CDN_PROVIDER}/{REPO_USER}/{REPO_NAME}@{BRANCH}/image/"

# 输出模式: "local" (生成文件), "json" (生成 JSON URL), "redirect" (生成 HTML 跳转)
# 目前强制为 "local" 以支持直接返回图片
MODE = "local"

# 是否转换 WebP (True/False)
CONVERT_WEBP = True

# 输出文件后缀 (如果 CONVERT_WEBP=False，将动态获取原图后缀)
DEFAULT_EXT = ".jpg" 

# ===========================================

def calculate_hex_len(item_count: int, min_len: int) -> int:
    """根据数据量自动计算所需的 Hex 长度"""
    if item_count == 0:
        return min_len
    needed = math.ceil(math.log(item_count, 16))
    return max(min_len, needed)

def generate_cf_rule(hex_len: int) -> str:
    """生成 Cloudflare 规则表达式"""
    
    # 注意：如果不转换 WebP，这里的后缀可能需要通配或者统一
    # 这里我们假设所有输出文件都被重命名/统一为同一个后缀，或者规则使用 substring 匹配
    # 为了简单起见，如果 CONVERT_WEBP 为 False，我们依然强制使用 .jpg 作为统一后缀（会重命名文件）
    # 或者，如果原图格式混杂，建议开启 CONVERT_WEBP
    
    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT
    
    # 1. Landscape
    rule_landscape = f'concat("/categories/l/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{ext}")'
    
    # 2. Portrait
    rule_portrait = f'concat("/categories/p/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{ext}")'
    
    # 3. All
    rule_all = f'concat("/all/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{ext}")'
    
    content = [
        "===========================================================",
        "请在 Cloudflare -> Rules -> Transform Rules 中创建以下 3 条规则",
        "建议顺序: 1. Landscape, 2. Portrait, 3. Random (All)",
        "注意：如果更改了文件后缀配置，请更新规则中的扩展名。",
        "===========================================================",
        "",
        "--- Rule 1: Landscape (横屏) ---",
        "Rule Name: Random Image - Landscape",
        'When incoming requests match: (http.request.uri.query contains "c=l")',
        "Path Rewrite: Dynamic",
        f"Expression: {rule_landscape}",
        "",
        "--- Rule 2: Portrait (竖屏) ---",
        "Rule Name: Random Image - Portrait",
        'When incoming requests match: (http.request.uri.query contains "c=p")',
        "Path Rewrite: Dynamic",
        f"Expression: {rule_portrait}",
        "",
        "--- Rule 3: Random (全随机) ---",
        "Rule Name: Random Image - All",
        'When incoming requests match: (not http.request.uri.query contains "c=")',
        "Path Rewrite: Dynamic",
        f"Expression: {rule_all}",
        ""
    ]
    
    return "\n".join(content)

def ensure_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)

def scan_images(source_dir: Path):
    """扫描所有图片并分类"""
    all_imgs = []
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
            
            # 分类
            try:
                if HAS_PILLOW:
                    with Image.open(file_path) as img:
                        width, height = img.size
                        if width > height:
                            landscape_imgs.append(item)
                        else:
                            portrait_imgs.append(item)
                else:
                    # 没有 Pillow，全部归为 all
                    pass
            except Exception as e:
                print(f"Warning: Could not open {file_path}: {e}")
            
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
        # 直接复制
        shutil.copy2(source_path, target_path)

def create_symlink_or_copy(target: Path, link_name: Path):
    """创建软链接，如果失败则复制"""
    try:
        relative_target = os.path.relpath(target, link_name.parent)
        os.symlink(relative_target, link_name)
    except (OSError, AttributeError):
        shutil.copy2(target, link_name)

def write_files(data_list, output_subdir: Path, hex_len: int, is_primary_store=False, source_map=None):
    """
    is_primary_store: 是否为主存储 (dist/all)，如果是，则生成实体文件
    source_map: 映射表，用于查找主存储中的文件位置
    """
    if not output_subdir.exists():
        output_subdir.mkdir(parents=True)

    if not data_list:
        return {}

    total_slots = 16 ** hex_len
    buckets = [[] for _ in range(total_slots)]
    
    data_cycle = cycle(data_list)
    for i in range(total_slots):
        buckets[i] = next(data_cycle)
    
    generated_map = {} 

    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT

    for i in range(total_slots):
        hex_name = f"{i:0{hex_len}x}"
        target_filename = f"{hex_name}{ext}"
        target_path = output_subdir / target_filename
        
        source_item = buckets[i]
        source_path = source_item['path']
        
        if is_primary_store:
            # 实体写入 (dist/all)
            process_file(source_path, target_path)
            generated_map[source_path] = target_path
        else:
            # 软链写入 (dist/categories/...)
            if source_map and source_path in source_map:
                real_target = source_map[source_path]
                create_symlink_or_copy(real_target, target_path)
            else:
                # 降级
                process_file(source_path, target_path)

    print(f"  Generated {total_slots} files in {output_subdir}")
    return generated_map

def main():
    # 1. 扫描
    all_imgs, landscape, portrait = scan_images(SOURCE_DIR)
    
    print(f"Found {len(all_imgs)} images.")
    print(f"  Landscape: {len(landscape)}")
    print(f"  Portrait:  {len(portrait)}")
    
    if len(all_imgs) == 0:
        print("Error: No images found.")
        sys.exit(1)

    # 2. 计算 Hex 长度
    hex_len = calculate_hex_len(len(all_imgs), MIN_HEX_LEN)
    print(f"Calculated Hex Length: {hex_len}")
    
    # 3. 清理并生成目录
    ensure_dir(OUTPUT_DIR)
    
    # 4. 生成文件
    print("Generating 'all' directory (Entity files)...")
    all_map = write_files(all_imgs, OUTPUT_DIR / "all", hex_len, is_primary_store=True)
    
    print("Generating 'categories/l' directory (Symlinks)...")
    write_files(landscape, OUTPUT_DIR / "categories" / "l", hex_len, is_primary_store=False, source_map=all_map)
    
    print("Generating 'categories/p' directory (Symlinks)...")
    write_files(portrait, OUTPUT_DIR / "categories" / "p", hex_len, is_primary_store=False, source_map=all_map)
    
    # 5. 生成 rules.txt
    rules = generate_cf_rule(hex_len)
    with open(OUTPUT_DIR / "rules.txt", 'w', encoding='utf-8') as f:
        f.write(rules)
        
    print("Done! Check 'dist' directory.")

if __name__ == "__main__":
    main()
