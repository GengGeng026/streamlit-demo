import os
import asyncio
import aiohttp
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

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

    def save_config(self):
        if self.token and self.database_id:
            with open('.env', 'w') as f:
                f.write(f"NOTION_API_KEY={self.token}\n")
                f.write(f"NOTION_HABITS_DATABASE_ID={self.database_id}\n")
            st.session_state['config_saved'] = True
            st.success("配置已保存到 .env 文件中")

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
            for i, result in enumerate(data['results']):
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
        
        fig = go.Figure(data=[go.Pie(
            labels=names,
            values=proportions,
            textinfo='percent',
            insidetextorientation='radial'
        )])
        fig.update_layout(
            title_text="Notion Habits Visualization",
            template='plotly',
            showlegend=True,
            legend=dict(
                orientation="v",
                xanchor="left",
                x=1.05,
                y=1
            )
        )
        return fig

async def fetch_data():
    visualizer = NotionDataVisualizer()
    if visualizer.is_configured:
        raw_data = await visualizer.get_notion_data()
        if raw_data:
            processed_data, total_minutes = await visualizer.process_data(raw_data)
            fig = visualizer.visualize_data(processed_data, total_minutes)
            return fig
    return None

# Streamlit app
st.title("Notion Data Visualization")

# Custom CSS for input field color change
custom_css = """
<style>
input#token:valid, input#database_id:valid {
    border-color: #00FF00; /* Green color when valid */
}
input#token:invalid, input#database_id:invalid {
    border-color: #FF0000; /* Red color when invalid */
}
</style>
"""

# Apply custom CSS
st.markdown(custom_css, unsafe_allow_html=True)

if 'config_saved' not in st.session_state:
    st.session_state.config_saved = False

if st.session_state.config_saved:
    st.session_state.show_loader = True
    st.experimental_rerun()
else:
    if not st.session_state.get('is_configured', False):
        token = st.text_input("请输入Notion API Token:", key='token', placeholder='请输入有效的 API Token', help="确保 Token 长度符合要求")
        database_id = st.text_input("请输入Notion数据库ID:", key='database_id', placeholder='请输入有效的数据库 ID', help="确保数据库 ID 长度符合要求")
        if st.button("保存配置"):
            if is_valid_token(token) and is_valid_database_id(database_id):
                visualizer = NotionDataVisualizer()
                visualizer.token = token
                visualizer.database_id = database_id
                visualizer.save_config()
                st.session_state.is_configured = True
                st.session_state.config_saved = True
                st.experimental_rerun()
            else:
                st.warning("请确保输入的 Notion API Token 和数据库 ID 符合格式要求。")
    else:
        st.session_state.show_loader = True
        fig = asyncio.run(fetch_data())
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("数据处理失败，请检查 API 配置和数据。")
