import os
import asyncio
import aiohttp
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
import time

# ... (previous code remains the same)

class NotionDataVisualizer:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("NOTION_API_KEY")
        self.database_id = os.getenv("NOTION_HABITS_DATABASE_ID")
        self.proxy_url = os.getenv("PROXY_URL")

        self.is_configured = self.token and self.database_id

        if not self.is_configured:
            self.show_config_inputs()
        else:
            self.show_generate_button()

    def show_config_inputs(self):
        with st.container():
            self.token = st.text_input("请输入Notion API Token:", key='token_input', placeholder='请输入有效的 API Token', help="确保 Token 长度符合要求")
            self.database_id = st.text_input("请输入Notion数据库ID:", key='database_id_input', placeholder='请输入有效的数据库 ID', help="确保数据库 ID 长度符合要求")
            self.show_save_button()

    def show_generate_button(self):
        if st.button("Generate Visualization", key='generate_button'):
            st.session_state.show_loader = True
            st.rerun()

    def save_config(self):
        if self.token and self.database_id:
            with open('.env', 'w') as f:
                f.write(f"NOTION_API_KEY={self.token}\n")
                f.write(f"NOTION_HABITS_DATABASE_ID={self.database_id}\n")
            st.session_state.config_saved = True
            self.is_configured = True

    def show_save_button(self):
        if is_valid_token(self.token) and is_valid_database_id(self.database_id):
            if st.button("保存配置", key='save_config_button'):
                self.save_config()
                st.rerun()
        else:
            st.warning("请确保输入的 Notion API Token 和数据库 ID 符合格式要求。")

    # ... (rest of the class methods remain the same)

# ... (rest of the code remains the same)

# Show generate button if configured
if visualizer.is_configured:
    visualizer.show_generate_button()