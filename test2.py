import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()
# 从环境变量中获取 Notion API 密钥和数据库 ID
notion_api_key = os.getenv('NOTION_API_KEY')
database_id = os.getenv('NOTION_HABITS_DATABASE_ID')  # 替换为你的数据库ID

# 请求头
headers = {
    'Authorization': f'Bearer {notion_api_key}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}

# 初始请求数据
data = {
    "filter": {
        "property": "Total min Par",
        "number": {
            "greater_than": 0
        }
    },
    "sorts": [
        {
            "property": "Total min Par",
            "direction": "descending"
        }
    ],
    "page_size": 5  # 设置较小的每页返回记录数
}

def fetch_pages(start_cursor=None):
    if start_cursor:
        data["start_cursor"] = start_cursor
    response = requests.post(f'https://api.notion.com/v1/databases/{database_id}/query', headers=headers, json=data, timeout=360)
    return response

# 初始请求
def fetch_all_pages():
    pages_collected = []
    next_cursor = None

    while True:
        response = fetch_pages(start_cursor=next_cursor)
        if response.status_code == 200:
            response_data = response.json()
            pages = response_data.get('results', [])
            pages_collected.extend(pages)
            next_cursor = response_data.get('next_cursor', None)
            
            if not next_cursor:
                break  # 如果没有下一页，停止请求
            
            time.sleep(1)  # 请求之间的延时，避免过于频繁的请求
        else:
            print(f'请求失败，状态码: {response.status_code}')
            print(f'响应内容: {response.text}')
            break

    return pages_collected

# 获取所有页面数据
pages = fetch_all_pages()

# 打印每个页面的标题
for page in pages:
    properties = page.get('properties', {})
    title_property = properties.get('Name', {})  # 假设标题字段的名称是 'Name'
    title = ''
    if title_property.get('type') == 'title':
        title = ''.join([t['plain_text'] for t in title_property.get('title', [])])
    print(f'标题: {title}')

print(f'\n获取到 {len(pages)} 条数据\n')