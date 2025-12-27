import subprocess
import sys

# ================= 配置区域 =================

# 是否使用 JSON 模式 (True/False)
# True:  生成 JSON 文件 (gen_json.py)，节省空间，需要配合 Cloudflare Worker 或前端解析。
# False: 生成图片副本 (gen_image.py)，直接返回图片，占用更多空间，但兼容性更好。
USE_JSON_MODE = True

# ===========================================

def main():
    if USE_JSON_MODE:
        print("Running in JSON Mode (gen_json.py)...")
        script_name = "gen_json.py"
    else:
        print("Running in Image Mode (gen_image.py)...")
        script_name = "gen_image.py"

    try:
        # 调用相应的脚本
        result = subprocess.run([sys.executable, script_name], check=True)
        print(f"Successfully executed {script_name}")
    except subprocess.CalledProcessError as e:
        print(f"Error executing {script_name}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
