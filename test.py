import streamlit as st
from streamlit_notion import NotionConnection
from dotenv import load_dotenv
import os

load_dotenv() 
# 从环境变量中获取 API 密钥
notion_api_key = os.getenv("NOTION_API_KEY")

# 确保密钥被正确加载
if not notion_api_key:
    st.error("NOTION_API_KEY 未设置")
else:
    # 使用正确的参数初始化连接
    conn = NotionConnection(connection_name="notion", api_key=notion_api_key)

    databases = conn.list_databases()

    for database in databases["results"]:
        r = conn.query(database["id"], page_size=1)
        st.write(r)
