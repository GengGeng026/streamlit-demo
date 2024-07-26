import json
import os
import asyncio
import aiohttp
import pandas as pd
import streamlit as st
import requests
from dotenv import load_dotenv
from streamlit_vizzu import Config, Data, VizzuChart
import random
import logging
from typing import List, Dict, Tuple

load_dotenv()
# 从环境变量中获取 Notion API 密钥
notion_api_key = os.getenv('NOTION_API_KEY')
database_id = os.getenv('NOTION_HABITS_DATABASE_ID')

# 请求头
headers = {
    'Authorization': f'Bearer {notion_api_key}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}

# 请求数据
data = {
    "filter": {
        "value": "page",
        "property": "object"
    },
    "sort": {
        "direction": "descending",
        "timestamp": "last_edited_time"
    }
}

# 发送 POST 请求
response = requests.post('https://api.notion.com/v1/search', headers=headers, json=data)

# 输出响应内容
print(response.json())
