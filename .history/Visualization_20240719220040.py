import os
import asyncio
import aiohttp
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv, set_key

# Constants
TASK_NOTION_NAME = 'Name'
TOTAL_ELAPSED_TIME_NOTION_NAME = 'Total mins rollup'
RANK_API_NOTION_NAME = 'rankAPI'
PARENT_RELATION_PROPERTY = 'Parent Hab'

class NotionDataVisualizer:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("NOTION_API_KEY")
        self.database_id = os.getenv("NOTION_HABITS_DATABASE_ID")
        self.proxy_url = os.getenv("PROXY_URL")

        if not self.token:
            self.token = st.text_input("请输入Notion API Token:")
        if not self.database_id:
            self.database_id = st.text_input("请输入Notion数据库ID:")

        if st.button("保存配置"):
            self.save_config()
        
    def save_config(self):
        if self.token and self.database_id:
            with open('.env', 'w') as f:
                f.write(f"NOTION_API_KEY={self.token}\n")
                f.write(f"NOTION_HABITS_DATABASE_ID={self.database_id}\n")
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
            showlegend=True,  # 显示图例
            legend=dict(
                orientation="v",  # 垂直排列
                xanchor="left",  # 图例位置
                x=1.05,  # 图例右侧位置
                y=1  # 图例顶部位置
            )
        )
        return fig

async def main():
    visualizer = NotionDataVisualizer()
    if not visualizer.token or not visualizer.database_id:
        return None, None
    
    raw_data = await visualizer.get_notion_data()
    if raw_data:
        processed_data, total_minutes = await visualizer.process_data(raw_data)
        fig = visualizer.visualize_data(processed_data, total_minutes)
        return fig
    return None, None

# Streamlit app
st.title("Notion Data Visualization")

# Container for button and loader
button_container = st.empty()
loader_container = st.empty()  # Separate container for loader

# Define custom CSS for animated emoji loader
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
  background-color: rgba(0, 0, 0, 0.5); /* Dark background for dark mode */
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
    }, 1000); // Match this time with the CSS fade-out duration
}
function showLoader() {
    const loader = document.getElementById('loader');
    loader.style.display = 'flex';
    loader.style.opacity = '1';
}
window.addEventListener('load', showLoader);
</script>
"""

def handle_loader():
    if st.session_state.show_loader:
        loader_container.markdown(custom_loader, unsafe_allow_html=True)
        fig, error_msg = asyncio.run(main())
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("数据处理失败，请检查 API 配置和数据。")
        loader_container.markdown("<script>document.getElementById('loader').style.opacity = '0'; setTimeout(function() { document.getElementById('loader').style.display = 'none'; }, 1000);</script>", unsafe_allow_html=True)
        st.session_state.show_loader = False
    else:
        button_container.button("Generate Visualization", on_click=lambda: st.session_state.update({"show_loader": True}))

if 'show_loader' not in st.session_state:
    st.session_state.show_loader = False

# Display the input fields and save button
visualizer = NotionDataVisualizer()

# Handle loader logic
handle_loader()
