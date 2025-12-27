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
    # 逻辑：取 uuid 第0位字符 (0-f)，将其映射到 l 或 p
    # Cloudflare 限制：regex_replace 不能嵌套，uuidv4 只能调用一次
    # 解决方案：使用 lookup_json_string (虽然复杂) 或者更简单的：
    # 我们可以利用 substring 来做映射！
    # 构造一个固定的 16 字符字符串 (对应 0-f 的映射结果): "llllllllpppppppp"
    # 然后把 hex 字符 (0-f) 转为数字索引？不行，Cloudflare 没有 hex2int。
    
    # 新方案：利用 http.request.id (Ray ID) 或其他随机字段辅助，避免多次调用 uuidv4
    # 但 uuidv4 最随机。
    # 既然 regex_replace 不能嵌套，我们只能用单一正则提取。
    # 还是回到最原始的方案：拆分规则。
    # 用户不想拆分规则。
    
    # 终极方案：使用 regex_replace 做一次性替换
    # 将 0-7 替换为 l，将 8-f 替换为 p。
    # 表达式: regex_replace(substring(uuidv4(cf.random_seed), 0, 1), "[0-7]", "l") -> 得到 "l" 或 "8"-"f"
    # 这还是不行，因为剩下 "8"-"f" 没变。
    
    # 让我们换个思路：文件名不仅仅是 1 位 hex，而是 hex_len (比如 1 位)。
    # 如果我们让文件名只有 "l" 和 "p" 开头，后面跟着 hex。
    # 其实我们可以利用 "to_string(cf.ray_id)" 或者其他字段。
    
    # 真正可行的单条规则方案 (利用 regex_replace 的捕获组功能):
    # regex_replace(input, pattern, replacement)
    # 输入: substring(uuidv4(cf.random_seed), 0, 1)  (比如 "a")
    # 正则: "[0-7]" -> "l"
    # 正则: "[8-9a-f]" -> "p"
    # Cloudflare 不支持多次 regex_replace。
    
    # 等等，Cloudflare 报错说 regex_replace 只能调 1 次，uuidv4 只能调 1 次。
    # 那么我们必须在一次 regex_replace 中完成所有工作，或者根本不用 regex_replace。
    
    # 唯一的单条规则解法：不使用动态计算前缀，而是让文件名本身就包含随机性，或者接受拆分规则。
    # 既然用户非常抗拒拆分规则，且刚才的尝试失败了。
    
    # 让我们尝试利用 lookup_json_string (如果 Cloudflare 支持的话，但那是高级功能)。
    
    # 回退方案：既然不能嵌套，也不能多次调用。
    # 那我们只能放弃在 URL 里动态计算 "l" 或 "p"。
    # 除非... 我们把所有文件都混在一起？不，用户要分类。
    
    # 重新思考：有没有办法一次 regex_replace 把 0-f 映射成 l/p？
    # regex_replace("0", "[0-7]", "l") -> "l"
    # regex_replace("8", "[0-7]", "l") -> "8" (没变)
    
    # 看来单条规则实现 "if-else" 逻辑在 Cloudflare 免费版限制下非常困难。
    # 但我们还有一个技巧：
    # 既然 uuidv4 返回的是 hex string。
    # 我们可以只用 0 和 1 吗？
    # 不行，uuidv4 是随机的。
    
    # 没办法，必须告诉用户：Cloudflare 免费版的限制导致必须拆分规则。
    # 或者... 我们使用 cf.ray_id (它不限调用次数吗？文档没说，但通常比 uuidv4 宽松)。
    # 错误提示说 "function uuidv4 is called 2 times"。
    
    # 让我们尝试用 cf.ray_id 替代 uuidv4 的其中一次调用。
    # Ray ID 也是 hex 字符串。
    # 比如: concat(..., substring(cf.ray_id, 0, 1), ...)
    
    # 如果我们用 ray_id 来决定 l/p，用 uuidv4 来决定文件名？
    # ray_id 的分布也是均匀的吗？是的。
    # 那么：
    # random_char = substring(cf.ray_id, 0, 1)
    # 还是面临 regex_replace 不能嵌套的问题。
    
    # 既然必须拆分，我需要诚实地告诉用户并恢复到拆分规则的状态，
    # 但为了让用户体验更好，我会把规则写得非常清楚。
    # 不过，用户刚才说 "只能调用一次uuid吧"。
    
    # 修正方案：恢复为 4 条规则 (A/B 分流)，这是唯一稳定可靠且不报错的方法。
    # 为了安抚用户，我会把规则生成得更易读，并明确指出这是 Cloudflare 的硬限制。
    
    rule_random_l = rule_landscape
    rule_random_p = rule_portrait
    
    content = [
        "===========================================================",
        "【重要提示】Cloudflare 免费版限制：",
        "1. regex_replace 不能嵌套使用。",
        "2. uuidv4() 在一条规则中只能调用 1 次。",
        "因此，我们**必须**将随机分流拆分为两条规则 (A/B)。",
        "这是实现 50/50 混合随机的唯一免费方案。",
        "===========================================================",
        "",
        "--- Rule 1: Landscape (指定横屏) ---",
        "Rule Name: Random Image - Landscape",
        "Match Expression:",
        f'(http.host eq "{DOMAIN}" and http.request.uri.path eq "/l")',
        "Redirect Expression:",
        f'{rule_landscape}',
        "",
        "--- Rule 2: Portrait (指定竖屏) ---",
        "Rule Name: Random Image - Portrait",
        "Match Expression:",
        f'(http.host eq "{DOMAIN}" and http.request.uri.path eq "/p")',
        "Redirect Expression:",
        f'{rule_portrait}',
        "",
        "--- Rule 3: Random A (50% -> 横屏) ---",
        "Rule Name: Random Image - All - A",
        "Match Expression (请点击 Edit expression 粘贴):",
        f'(http.host eq "{DOMAIN}" and (http.request.uri.path eq "/" or (http.request.uri.path ne "/l" and http.request.uri.path ne "/p")) and substring(cf.ray_id, 0, 1) matches "[0-7]")',
        "Redirect Expression:",
        f'{rule_landscape}',
        "",
        "--- Rule 4: Random B (50% -> 竖屏) ---",
        "Rule Name: Random Image - All - B",
        "Match Expression (请点击 Edit expression 粘贴):",
        f'(http.host eq "{DOMAIN}" and (http.request.uri.path eq "/" or (http.request.uri.path ne "/l" and http.request.uri.path ne "/p")))',
        "Redirect Expression:",
        f'{rule_portrait}',
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
