import os
import asyncio
import aiohttp
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_vizzu import Config, Data, VizzuChart

# Constants
TASK_NOTION_NAME = 'Name'
TOTAL_ELAPSED_TIME_NOTION_NAME = 'Total mins rollup'
RANK_API_NOTION_NAME = 'rankAPI'
PARENT_RELATION_PROPERTY = 'Parent Hab'

# Function to validate Notion API Token
def is_valid_token(token):
    return len(token) >= 20

# Function to validate Notion Database ID
def is_valid_database_id(database_id):
    return len(database_id) == 32

class NotionDataVisualizer:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("NOTION_API_KEY")
        self.database_id = os.getenv("NOTION_HABITS_DATABASE_ID")
        self.proxy_url = os.getenv("PROXY_URL")

        self.is_configured = self.token and self.database_id

        if not self.is_configured:
            self.token = st.text_input("请输入Notion API Token:", key='token', placeholder='请输入有效的 API Token', help="确保 Token 长度符合要求")
            self.database_id = st.text_input("请输入Notion数据库ID:", key='database_id', placeholder='请输入有效的数据库 ID', help="确保数据库 ID 长度符合要求")
            self.show_save_button()
        else:
            if 'configuration_loaded' not in st.session_state:
                st.session_state.configuration_loaded = False

            if not st.session_state.configuration_loaded:
                st.session_state.configuration_loaded = True

    def save_config(self):
        if self.token and self.database_id:
            with open('.env', 'w') as f:
                f.write(f"NOTION_API_KEY={self.token}\n")
                f.write(f"NOTION_HABITS_DATABASE_ID={self.database_id}\n")
            st.success("配置已保存到 .env 文件中")
            self.is_configured = True
            st.session_state.configuration_loaded = False  # Reset the flag to show the success message again
            st.session_state.show_config_message = True
            st.rerun()

    def show_save_button(self):
        if is_valid_token(self.token) and is_valid_database_id(self.database_id):
            if st.button("保存配置"):
                self.save_config()
        else:
            st.warning("请确保输入的 Notion API Token 和数据库 ID 符合格式要求。")

    async def fetch(self, session, url, method='GET', **kwargs):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28"
        }
        try:
            async with session.request(method, url, headers=headers, **kwargs) as response:
                if response.content_type == 'application/json':
                    return await response.json()
                else:
                    content = await response.text()
                    st.error(f"Unexpected content type: {response.content_type}")
                    st.error(f"Response content: {content}")
                    return None
        except Exception as e:
            st.error(f"请求失败: {e}")
            return None

    async def get_notion_data(self):
        url = f"https://api.notion.com/v1/databases/{self.database_id}/query"
        async with aiohttp.ClientSession() as session:
            response = await self.fetch(session, url, method='POST', json={})
        return response

    async def get_page_name(self, session, page_id):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        page_data = await self.fetch(session, url)
        if page_data and 'properties' in page_data and TASK_NOTION_NAME in page_data['properties']:
            return page_data['properties'][TASK_NOTION_NAME]['title'][0]['plain_text']
        return "Unknown"

    async def process_data(self, data):
        categories = {}
        total_minutes = 0
        async with aiohttp.ClientSession() as session:
            tasks = []
            for result in data['results']:
                parent = result['properties'].get(PARENT_RELATION_PROPERTY, {})
                total_mins = result['properties'].get(TOTAL_ELAPSED_TIME_NOTION_NAME, {}).get('rollup', {}).get('number', 0)

                if 'relation' in parent and parent['relation']:
                    parent_id = parent['relation'][0]['id']
                    tasks.append(self.get_page_name(session, parent_id))
                else:
                    if 'No Parent' not in categories:
                        categories['No Parent'] = 0
                    categories['No Parent'] += total_mins

                total_minutes += total_mins

            parent_names = await asyncio.gather(*tasks)
            for parent_name in parent_names:
                if parent_name not in categories:
                    categories[parent_name] = 0
                categories[parent_name] += total_mins

        return categories, total_minutes

    def visualize_data(self, data, total_minutes):
        names = list(data.keys())
        values = [data[name] for name in names]
        proportions = [value / total_minutes * 100 for value in values]
        
        df = pd.DataFrame({
            'Parent Category': names,
            'Proportion': proportions
        })

        chart = VizzuChart()
        data_vizzu = Data()
        data_vizzu.add_df(df)
        chart.animate(data_vizzu)
        
        config = Config({
            "channels": {
                "color": {"set": ["Parent Category"]},
                "size": {"set": ["Proportion"]}
            },
            "title": "主习惯大类占比",
            "geometry": "circle"
        })
        
        chart.animate(config)

        return chart

    async def generate_visualization(self):
        raw_data = await self.get_notion_data()
        if raw_data:
            processed_data, total_minutes = await self.process_data(raw_data)
            chart = self.visualize_data(processed_data, total_minutes)
            return chart
        return None

# Streamlit app
st.title("Notion Data Visualization")

# Custom CSS for input field color change
custom_css = """
<style>
input#token:valid, input#database_id:valid {
    border-color: #00FF00;
}
input#token:invalid, input#database_id:invalid {
    border-color: #FF0000;
}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# Initialize visualizer
visualizer = NotionDataVisualizer()

# Initialize session state
if 'show_loader' not in st.session_state:
    st.session_state.show_loader = False
if 'visualization_fig' not in st.session_state:
    st.session_state.visualization_fig = None
if 'show_config_message' not in st.session_state:
    st.session_state.show_config_message = False

# Show "配置已加载" message if needed
if st.session_state.show_config_message and visualizer.is_configured:
    st.success("配置已加载")
    st.session_state.show_config_message = False

# Show "Generate Visualization" button only if not loading
if not st.session_state.show_loader and visualizer.is_configured:
    if st.button("Generate Visualization"):
        st.session_state.show_loader = True
        st.rerun()

# Handle loader logic and visualization generation
if st.session_state.show_loader:
    with st.spinner("正在生成可视化..."):
        chart = asyncio.run(visualizer.generate_visualization())
    
    if chart:
        st.session_state.visualization_fig = chart
    else:
        st.error("数据处理失败，请检查 API 配置和数据。")
    
    st.session_state.show_loader = False  # Hide loader
    st.rerun()  # Rerun to show the button again

# Display the generated visualization if available
if st.session_state.visualization_fig:
    st.session_state.visualization_fig.show()
