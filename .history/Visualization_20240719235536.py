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

        if not self.is_configured:
            self.token = st.text_input("请输入Notion API Token:", key='token', placeholder='请输入有效的 API Token', help="确保 Token 长度符合要求")
            self.database_id = st.text_input("请输入Notion数据库ID:", key='database_id', placeholder='请输入有效的数据库 ID', help="确保数据库 ID 长度符合要求")
            self.show_save_button()
        else:
            st.success("配置已加载")

    def save_config(self):
        if self.token and self.database_id:
            with open('.env', 'w') as f:
                f.write(f"NOTION_API_KEY={self.token}\n")
                f.write(f"NOTION_HABITS_DATABASE_ID={self.database_id}\n")
            st.session_state.config_saved = True
            st.rerun()  # Force rerun to clear inputs and show success message

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

async def main():
    visualizer = NotionDataVisualizer()
    if visualizer.is_configured:
        data = await visualizer.get_notion_data()
        categories, total_minutes = await visualizer.process_data(data)
        fig = visualizer.visualize_data(categories, total_minutes)
        return fig, None
    else:
        return None, "配置无效，请检查 API Token 和数据库 ID"

def run_async(func, *args):
    return asyncio.run(func(*args))

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

# Initialize session state
if 'config_saved' not in st.session_state:
    st.session_state.config_saved = False
if 'show_loader' not in st.session_state:
    st.session_state.show_loader = False

if st.session_state.config_saved:
    st.success("配置已保存到 .env 文件中")
    if st.button("Generate Visualization"):
        st.session_state.show_loader = True
        # Display loader
        loader_container = st.empty()
        custom_loader = """
        <style>
        @keyframes wave {
          0% { transform: translateY(0); }
          50% { transform: translateY(-20px); }
          100% { transform: translateY(0); }
        }
        @keyframes fadeOut {
          0% { opacity: 1; }
          100% { opacity: 0; }
        }
        .emoji-container {
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          display: flex;
          justify-content: center;
          align-items: center;
          background-color: rgba(0, 0, 0, 0.5);
          z-index: 9999;
          transition: opacity 1s ease-out;
        }
        .emoji {
          font-size: 50px;
          animation: wave 1.5s infinite;
        }
        .emoji:nth-child(2) {
          animation-delay: 0.3s;
        }
        .emoji:nth-child(3) {
          animation-delay: 0.6s;
        }
        </style>
        <div class="emoji-container" id="loader">
          <div class="emoji">🌊</div>
          <div class="emoji">🌊</div>
          <div class="emoji">🌊</div>
        </div>
        <script>
        function hideLoader() {
            const loader = document.getElementById('loader');
            loader.style.opacity = '0';
            setTimeout(function() {
                loader.style.display = 'none';
            }, 1000);
        }
        function showLoader() {
            const loader = document.getElementById('loader');
            loader.style.display = 'flex';
            loader.style.opacity = '1';
        }
        window.addEventListener('load', showLoader);
        </script>
        """
        loader_container.markdown(custom_loader, unsafe_allow_html=True)

        fig, error_msg = run_async(main)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("数据处理失败，请检查 API 配置和数据。")

        # Hide loader after processing
        loader_container.markdown("<script>document.getElementById('loader').style.opacity = '0'; setTimeout(function() { document.getElementById('loader').style.display = 'none'; }, 1000);</script>", unsafe_allow_html=True)
        st.session_state.show_loader = False
else:
    # Handle loader logic if needed
    if st.session_state.show_loader:
        loader_container = st.empty()
        custom_loader = """
        <style>
        @keyframes wave {
          0% { transform: translateY(0); }
          50% { transform: translateY(-20px); }
          100% { transform: translateY(0); }
        }
        @keyframes fadeOut {
          0% { opacity: 1; }
          100% { opacity: 0; }
        }
        .emoji-container {
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          display: flex;
          justify-content: center;
          align-items: center;
          background-color: rgba(0, 0, 0, 0.5);
          z-index: 9999;
          transition: opacity 1s ease-out;
        }
        .emoji {
          font-size: 50px;
          animation: wave 1.5s infinite;
        }
        .emoji:nth-child(2) {
          animation-delay: 0.3s;
        }
        .emoji:nth-child(3) {
          animation-delay: 0.6s;
        }
        </style>
        <div class="emoji-container" id="loader">
          <div class="emoji">🌊</div>
          <div class="emoji">🌊</div>
          <div class="emoji">🌊</div>
        </div>
        <script>
        function hideLoader() {
            const loader = document.getElementById('loader');
            loader.style.opacity = '0';
            setTimeout(function() {
                loader.style.display = 'none';
            }, 1000);
        }
        function showLoader() {
            const loader = document.getElementById('loader');
            loader.style.display = 'flex';
            loader.style.opacity = '1';
        }
        window.addEventListener('load', showLoader);
        </script>
        """
        loader_container.markdown(custom_loader, unsafe_allow_html=True)
