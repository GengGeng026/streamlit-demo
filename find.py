import os

# 获取环境变量
notion_api_key = os.getenv("NOTION_API_KEY")

# 打印环境变量
print(f"NOTION_API_KEY: {notion_api_key}")
