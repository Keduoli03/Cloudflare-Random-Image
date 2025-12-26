import json
import math
import shutil
import urllib.parse
from pathlib import Path
from itertools import cycle

# Try to import Pillow for image dimension detection
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("Warning: Pillow not installed. Aspect ratio classification will be skipped.")

# ================= 配置区域 =================

# 基础 Hex 长度 (保底)
# 1 -> 16 files, 2 -> 256 files, 3 -> 4096 files
MIN_HEX_LEN = 1

# 你的 GitHub 用户名/仓库/分支
# 示例: https://gcore.jsdelivr.net/gh/Keduoli03/My_img@main/image/
REPO_USER = "Keduoli03"
REPO_NAME = "Cloudflare-Random-Image"
BRANCH = "main"
CDN_PROVIDER = "https://gcore.jsdelivr.net/gh"

# 图片源目录 (本地)
SOURCE_DIR = Path("Image")

# 输出目录 (本地)
OUTPUT_DIR = Path("dist")

# URL 前缀构建
BASE_URL = f"{CDN_PROVIDER}/{REPO_USER}/{REPO_NAME}@{BRANCH}/image/"

# ===========================================

def calculate_hex_len(item_count: int, min_len: int) -> int:
    """根据数据量自动计算所需的 Hex 长度"""
    if item_count == 0:
        return min_len
    # 计算需要的位数: log16(count)
    needed = math.ceil(math.log(item_count, 16))
    return max(min_len, needed)

def generate_cf_rule(hex_len: int, category_key_len: int = 1) -> str:
    """生成 Cloudflare 规则表达式"""
    
    # 1. 全随机 (No query param or empty)
    # 路径: /all/<hex>.json
    rule_random = f'concat("/all/", substring(uuidv4(cf.random_seed), 0, {hex_len}), ".json")'
    
    # 2. 分类 (With query param)
    # 路径: /<category>/<hex>.json
    rule_category = f'concat("/", substring(http.request.uri.query, 2, {category_key_len}), "/", substring(uuidv4(cf.random_seed), 0, {hex_len}), ".json")'
    
    return f"Random Rule:\n{rule_random}\n\nCategory Rule (e.g. ?c=l):\n{rule_category}"

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

    # 支持的图片扩展名
    exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}
    
    print(f"Scanning images in {source_dir}...")
    
    for file_path in source_dir.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in exts:
            # 1. 构建 URL
            rel_path = file_path.relative_to(source_dir)
            # URL encode
            safe_path = Path(rel_path).as_posix().split('/')
            encoded_path = '/'.join([urllib.parse.quote(p) for p in safe_path])
            
            full_url = f"{BASE_URL}{encoded_path}"
            
            # 默认未知
            img_type = "unknown"
            
            # 2. 分类
            if HAS_PILLOW:
                try:
                    with Image.open(file_path) as img:
                        width, height = img.size
                        if width > height:
                            landscape_imgs.append(None) # Placeholder, we will fill item later
                            img_type = "landscape"
                        else:
                            portrait_imgs.append(None) # Placeholder
                            img_type = "portrait"
                except Exception as e:
                    print(f"Warning: Could not open {file_path}: {e}")
            
            # 构建 JSON 数据
            item = {
                "url": full_url,
                "type": img_type
            }
            
            all_imgs.append(item)
            
            # 更新分类列表中的最后一个元素
            if img_type == "landscape":
                landscape_imgs[-1] = item
            elif img_type == "portrait":
                portrait_imgs[-1] = item

    return all_imgs, landscape_imgs, portrait_imgs

def write_files(data_list, output_subdir: Path, hex_len: int):
    """将数据分片写入文件 (Fill-Full 策略)"""
    if not output_subdir.exists():
        output_subdir.mkdir(parents=True)

    if not data_list:
        print(f"  [Warning] No data for {output_subdir.name}")
        return

    total_slots = 16 ** hex_len
    buckets = [[] for _ in range(total_slots)]
    
    # 循环分发
    data_cycle = cycle(data_list)
    for i in range(total_slots):
        buckets[i] = next(data_cycle)
    
    # 写入 JSON
    for i in range(total_slots):
        # hex filename
        hex_name = f"{i:0{hex_len}x}" # e.g. 0a, ff
        file_path = output_subdir / f"{hex_name}.json"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(buckets[i], f, ensure_ascii=False) 

    print(f"  Generated {total_slots} files in {output_subdir}")

def main():
    # 1. 扫描
    all_imgs, landscape, portrait = scan_images(SOURCE_DIR)
    
    print(f"Found {len(all_imgs)} images.")
    print(f"  Landscape: {len(landscape)}")
    print(f"  Portrait:  {len(portrait)}")
    
    if len(all_imgs) == 0:
        print("No images found. Exiting.")
        return

    # 2. 计算 Hex 长度
    hex_len = calculate_hex_len(len(all_imgs), MIN_HEX_LEN)
    print(f"Calculated Hex Length: {hex_len} (Max capacity: {16**hex_len})")
    
    # 3. 清理并生成目录
    ensure_dir(OUTPUT_DIR)
    
    # 4. 写入文件 (JSON)
    write_files(all_imgs, OUTPUT_DIR / "all", hex_len)
    
    write_files(landscape, OUTPUT_DIR / "categories" / "l", hex_len)
    write_files(portrait, OUTPUT_DIR / "categories" / "p", hex_len)
    
    # 5. 生成 categories.json
    cats = {
        "l": {"name": "Landscape (横屏)", "count": len(landscape)},
        "p": {"name": "Portrait (竖屏)", "count": len(portrait)}
    }
    with open(OUTPUT_DIR / "categories.json", 'w', encoding='utf-8') as f:
        json.dump(cats, f, indent=2, ensure_ascii=False)
        
    # 6. 生成 rules.txt
    rules = generate_cf_rule(hex_len, category_key_len=1)
    with open(OUTPUT_DIR / "rules.txt", 'w', encoding='utf-8') as f:
        f.write(rules)
        
    print("Done! Check 'dist' directory.")

if __name__ == "__main__":
    main()
