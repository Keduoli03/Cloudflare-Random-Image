import json
import math
import shutil
import urllib.parse
import sys
import os
from pathlib import Path
from itertools import cycle

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
# 仓库信息配置 (用于拼接 URL)
GITHUB_USERNAME = "Keduoli03"
GITHUB_REPO = "Cloudflare-Random-Image"
GITHUB_BRANCH = "main"

# CDN 加速域名 (可选)
CDN_DOMAIN = "https://gcore.jsdelivr.net"
# ===========================================


def calculate_hex_len(item_count: int, min_len: int) -> int:
    """根据数据量自动计算所需的 Hex 长度"""
    if item_count == 0:
        return min_len
    needed = math.ceil(math.log(item_count, 16))
    return max(min_len, needed)

def get_base_url() -> str:
    """根据配置生成基础 URL"""
    if CDN_DOMAIN:
        # 使用 jsDelivr 格式: https://cdn/gh/User/Repo@Branch/dist
        return f"{CDN_DOMAIN}/gh/{GITHUB_USERNAME}/{GITHUB_REPO}@{GITHUB_BRANCH}/dist"
    else:
        # 使用 GitHub Raw 格式: https://raw.githubusercontent.com/User/Repo/Branch/dist
        return f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/{GITHUB_BRANCH}/dist"

def generate_cf_rule(hex_len: int) -> str:
    """生成 Cloudflare 规则表达式"""
    
    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT
    suffix = ".json"
    
    # 1. Landscape (横屏)
    rule_landscape = f'concat("/dist/l/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{suffix}")'
    
    # 2. Portrait (竖屏)
    rule_portrait = f'concat("/dist/p/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{suffix}")'
    
    # 3. All (全局)
    rule_all = f'concat("/dist/all/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{suffix}")'
    
    desc_suffix = "JSON"
    
    content = [
        "===========================================================",
        "【说明】规则生成 (JSON 模式)：",
        f"模式: {desc_suffix} Mode",
        f"存储结构: /l/, /p/, /all/ 指向 {suffix} 文件",
        "注意：请在 Cloudflare 中使用 'Transform Rules' (重写) 或 'Redirect Rules' (重定向)",
        "如果使用 Rewrite (重写)，必须使用相对路径（如下所示）。",
        "===========================================================",
        "",
        f"--- Rule 1: Landscape (指定横屏 -> {suffix}) ---",
        f"Rule Name: Random Image - Landscape - {desc_suffix}",
        "Match Expression:",
        f'(http.host eq "{DOMAIN}" and http.request.uri.path eq "/l")',
        "Redirect Expression:",
        f'{rule_landscape}',
        "",
        f"--- Rule 2: Portrait (指定竖屏 -> {suffix}) ---",
        f"Rule Name: Random Image - Portrait - {desc_suffix}",
        "Match Expression:",
        f'(http.host eq "{DOMAIN}" and http.request.uri.path eq "/p")',
        "Redirect Expression:",
        f'{rule_portrait}',
        "",
        f"--- Rule 3: Random All (全局随机 -> {suffix}) ---",
        f"Rule Name: Random Image - All - {desc_suffix}",
        "Match Expression (请点击 Edit expression 粘贴):",
        f'(http.host eq "{DOMAIN}" and (http.request.uri.path eq "/" or (http.request.uri.path ne "/l" and http.request.uri.path ne "/p")))',
        "Redirect Expression:",
        f'{rule_all}',
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
            
            is_portrait = False
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

def write_json_files(data_list, output_dir: Path, hex_len: int, subdir_name: str, images_dir_name: str = "images"):
    """
    生成 JSON 文件，内容指向真实图片 URL。
    """
    if not data_list:
        return

    target_dir = output_dir / subdir_name
    ensure_dir(target_dir)

    total_slots = 16 ** hex_len
    buckets = [[] for _ in range(total_slots)]
    
    data_cycle = cycle(data_list)
    for i in range(total_slots):
        buckets[i] = next(data_cycle)
    
    base_url = get_base_url()

    for i in range(total_slots):
        hex_name = f"{i:0{hex_len}x}"
        
        source_item = buckets[i]
        real_image_filename = source_item.get('target_filename')
        if not real_image_filename:
             print(f"Error: Missing target filename for {source_item['path']}")
             continue
             
        target_url = f"{base_url}/{images_dir_name}/{real_image_filename}"
        
        json_content = {
            "url": target_url
        }
        
        json_filename = f"{hex_name}.json"
        json_path = target_dir / json_filename
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_content, f)

    print(f"  Generated {total_slots} json files in '{subdir_name}/'")

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
    print("Starting JSON Mode Generation...")
    
    images_dir = OUTPUT_DIR / "images"
    ensure_dir(images_dir)
    
    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT
    
    print("Processing source images to /images/...")
    for idx, item in enumerate(all_imgs):
        target_filename = f"{idx}{ext}"
        target_path = images_dir / target_filename
        
        process_file(item['path'], target_path)
        item['target_filename'] = target_filename
        
    print("Generating JSON files for /l/...")
    write_json_files(landscape, OUTPUT_DIR, hex_len, "l")
    
    print("Generating JSON files for /p/...")
    write_json_files(portrait, OUTPUT_DIR, hex_len, "p")
    
    print("Generating JSON files for /all/...")
    write_json_files(all_imgs, OUTPUT_DIR, hex_len, "all")
    
    # 5. 生成 rules.txt
    rules = generate_cf_rule(hex_len)
    with open("rules.txt", 'w', encoding='utf-8') as f:
        f.write(rules)
    
    # 6. 生成 CNAME 文件
    if DOMAIN:
        with open("CNAME", 'w', encoding='utf-8') as f:
            f.write(DOMAIN)
        print(f"Generated CNAME file: {DOMAIN}")
    
    # 7. 生成 index.html
    with open("index.html", 'w', encoding='utf-8') as f:
        f.write("<h1>Cloudflare Random Image API</h1><p>Visit <a href='/rules.txt'>/rules.txt</a> for configuration.</p>")
    print("Generated index.html")
        
    print("Done! Check 'dist' directory and 'rules.txt'.")

if __name__ == "__main__":
    main()
