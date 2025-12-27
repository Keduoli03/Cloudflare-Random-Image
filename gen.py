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

# 是否使用 JSON 模式 (True/False)
# True: 
#   1. 图片会被转换并存放在 dist/images/ 目录下 (扁平化存储)。
#   2. 生成 /l/, /p/, /all/ 三个目录，里面全是 .json 文件。
#   3. json 文件内容指向 dist/images/ 下的真实图片 URL。
#   4. 优点：极大节省 GitHub 存储空间 (不用双倍/三倍存储图片)。
# False: 
#   1. 图片会被复制/转换到 dist/l/, dist/p/, dist/all/ 目录下。
#   2. 直接是图片文件，直链访问。
USE_JSON_MODE = True

# ===========================================
# 仓库信息配置 (用于拼接 URL)
GITHUB_USERNAME = "Keduoli03"
GITHUB_REPO = "Cloudflare-Random-Image"
GITHUB_BRANCH = "main"

# CDN 加速域名 (可选)
# 如果填写 (例如 "https://gcore.jsdelivr.net")，则拼接为: CDN/gh/User/Repo@Branch/path
# 如果留空 ("")，则使用 GitHub Raw 默认域名: https://raw.githubusercontent.com/User/Repo/Branch/path
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
    # base_url = get_base_url() # 在规则生成中不再使用完整 URL，而是使用相对路径以兼容 Rewrite 规则
    
    # 无论是否为 JSON 模式，Cloudflare 规则都是类似的
    # 如果是 JSON 模式，指向 .json
    # 如果是 图片模式，指向 .webp/.jpg
    
    suffix = ".json" if USE_JSON_MODE else ext
    
    # 使用相对路径，这样既支持 Rewrite (内部重写到 GitHub Pages)，也支持 Redirect (内部跳转)
    # 避免了在 Rewrite 规则中使用绝对 URL 导致的 1035 错误
    # 注意：现在文件都在 /dist/ 目录下，所以重写路径需要加上 /dist/ 前缀
    
    # 1. Landscape (横屏)
    rule_landscape = f'concat("/dist/l/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{suffix}")'
    
    # 2. Portrait (竖屏)
    rule_portrait = f'concat("/dist/p/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{suffix}")'
    
    # 3. All (全局)
    rule_all = f'concat("/dist/all/", substring(uuidv4(cf.random_seed), 0, {hex_len}), "{suffix}")'
    
    
    desc_suffix = "JSON" if USE_JSON_MODE else "Image"
    
    content = [
        "===========================================================",
        "【说明】规则生成 (已更新为相对路径以修复 1035 错误)：",
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

def write_json_files(data_list, output_dir: Path, hex_len: int, subdir_name: str, images_dir_name: str = "images"):
    """
    生成 JSON 文件，内容指向真实图片 URL。
    URL 格式: CDN/gh/User/Repo@Branch/images_dir_name/filename
    """
    if not data_list:
        return

    # 创建子目录 (例如 dist/l/)
    target_dir = output_dir / subdir_name
    ensure_dir(target_dir)

    total_slots = 16 ** hex_len
    buckets = [[] for _ in range(total_slots)]
    
    data_cycle = cycle(data_list)
    for i in range(total_slots):
        buckets[i] = next(data_cycle)
    
    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT
    base_url = get_base_url()

    for i in range(total_slots):
        hex_name = f"{i:0{hex_len}x}"
        
        # 1. 确定这个 slot 指向的真实图片文件名
        source_item = buckets[i]
        # 注意：这里我们假设 source_item['target_filename'] 已经在 process_all_images 阶段被设置好了
        # 或者我们在这里需要知道它在 /images/ 下的文件名
        # 为了简单，我们必须在处理所有图片时，就确定好它们在 /images/ 下的文件名
        
        real_image_filename = source_item.get('target_filename')
        if not real_image_filename:
             print(f"Error: Missing target filename for {source_item['path']}")
             continue
             
        # 2. 构造 URL
        # 格式: base_url/images/filename.ext
        target_url = f"{base_url}/{images_dir_name}/{real_image_filename}"
        
        # 3. 写入 JSON
        json_content = {
            "url": target_url
        }
        
        json_filename = f"{hex_name}.json"
        json_path = target_dir / json_filename
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_content, f)

    print(f"  Generated {total_slots} json files in '{subdir_name}/'")

def write_files_prefix(data_list, output_dir: Path, hex_len: int, subdir_name: str):
    """使用子目录模式写入文件"""
    if not data_list:
        return

    # 创建子目录 (例如 dist/l/)
    target_dir = output_dir / subdir_name
    ensure_dir(target_dir)

    total_slots = 16 ** hex_len
    buckets = [[] for _ in range(total_slots)]
    
    data_cycle = cycle(data_list)
    for i in range(total_slots):
        buckets[i] = next(data_cycle)
    
    ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT

    for i in range(total_slots):
        hex_name = f"{i:0{hex_len}x}"
        target_filename = f"{hex_name}{ext}"
        target_path = target_dir / target_filename
        
        source_item = buckets[i]
        source_path = source_item['path']
        
        process_file(source_path, target_path)

    print(f"  Generated {total_slots} files in '{subdir_name}/'")

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
    if USE_JSON_MODE:
        print("Starting JSON Mode Generation...")
        
        # A. 首先，将所有图片统一处理并存放到 dist/images/ 目录下
        # 保持扁平化结构，文件名可以使用 uuid 或者简单的 hash，或者保留原名
        # 为了避免文件名冲突，建议使用 hash 或 uuid，或者简单的计数
        # 但为了让 JSON 指向稳定，我们需要给每个 item 分配一个固定的文件名
        
        images_dir = OUTPUT_DIR / "images"
        ensure_dir(images_dir)
        
        ext = ".webp" if CONVERT_WEBP else DEFAULT_EXT
        
        print("Processing source images to /images/...")
        for idx, item in enumerate(all_imgs):
            # 给每个图片分配一个唯一文件名，例如 image_0.webp, image_1.webp
            # 或者更短一点: 0.webp, 1.webp ... (基于 all_imgs 的索引)
            # 或者保留原名 (如果不冲突)。为了安全，使用索引或 hash。
            # 这里使用索引，简单可靠。
            target_filename = f"{idx}{ext}"
            target_path = images_dir / target_filename
            
            process_file(item['path'], target_path)
            
            # 将生成的 filename 记录回 item，供后面生成 JSON 使用
            # 注意：all_imgs 中的 item 对象是共享的，landscape 和 portrait 列表里的 item 也是同一个对象的引用
            item['target_filename'] = target_filename
            
        # B. 生成 /l/, /p/, /all/ 下的 JSON 文件
        print("Generating JSON files for /l/...")
        write_json_files(landscape, OUTPUT_DIR, hex_len, "l")
        
        print("Generating JSON files for /p/...")
        write_json_files(portrait, OUTPUT_DIR, hex_len, "p")
        
        print("Generating JSON files for /all/...")
        write_json_files(all_imgs, OUTPUT_DIR, hex_len, "all")
        
    else:
        # 传统模式：图片副本
        print("Starting Image Mode Generation (Shadow Copy)...")
        print("Generating landscape files (/l/)...")
        write_files_prefix(landscape, OUTPUT_DIR, hex_len, "l")
        
        print("Generating portrait files (/p/)...")
        write_files_prefix(portrait, OUTPUT_DIR, hex_len, "p")
        
        print("Generating all files (/all/)...")
        write_files_prefix(all_imgs, OUTPUT_DIR, hex_len, "all")
    
    # 5. 生成 rules.txt
    rules = generate_cf_rule(hex_len)
    with open("rules.txt", 'w', encoding='utf-8') as f:
        f.write(rules)
    
    # 6. 生成 CNAME 文件 (如果配置了域名)
    if DOMAIN:
        with open("CNAME", 'w', encoding='utf-8') as f:
            f.write(DOMAIN)
        print(f"Generated CNAME file: {DOMAIN}")
        
    print("Done! Check 'dist' directory and 'rules.txt'.")

if __name__ == "__main__":
    main()
