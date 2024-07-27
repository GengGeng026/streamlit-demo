import json
import os
import asyncio
import aiohttp
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_vizzu import Config, Data, VizzuChart
import random
import logging
from typing import List, Dict, Tuple
import plotly.express as px
import plotly.graph_objects as go

# Constants
TASK_NOTION_NAME = 'Name'
TOTAL_ELAPSED_TIME_FOR_SUB_HABIT = 'Total mins rollup'
TOTAL_MINUTES_FOR_PARENT_HABIT = 'Total min Par'
RANK_API_NOTION_NAME = 'rankAPI'
PARENT_RELATION_PROPERTY = 'Parent Hab'
MAX_RETRIES = 30
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300
FETCH_TIMEOUT = 900
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
    "page_size": 5
}

logging.basicConfig(level=logging.INFO, format='%(message)s')

PROGRESS_FILE = 'progress.json'

# Function to validate Notion API Token
def is_valid_token(token):
    return len(token) >= 20

# Function to validate Notion Database ID
def is_valid_database_id(database_id):
    return len(database_id) == 32

async def check_network():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.notion.com", timeout=10) as response:
                if response.status == 200:
                    logging.info("Network check passed. Notion API is reachable.")
                else:
                    logging.warning(f"Network check failed. Status: {response.status}")
    except Exception as e:
        logging.error(f"Network check failed. Error: {e}")

async def exponential_backoff(attempt):
    delay = min(MAX_RETRY_DELAY, INITIAL_RETRY_DELAY * (2 ** attempt))
    jitter = random.uniform(0, 0.1 * delay)
    total_delay = delay + jitter
    logging.info(f"Backing off for {total_delay:.2f} seconds")
    await asyncio.sleep(total_delay)

async def smart_retry(func, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return await func(*args, **kwargs)
        except aiohttp.ClientResponseError as e:
            if e.status == 504:
                logging.warning(f"Gateway Timeout. Attempt {attempt + 1}/{MAX_RETRIES}")
            elif e.status == 429:
                logging.warning(f"Rate limit exceeded. Attempt {attempt + 1}/{MAX_RETRIES}")
            else:
                logging.error(f"Client response error: {e.status}. Attempt {attempt + 1}/{MAX_RETRIES}")
            await exponential_backoff(attempt)
        except asyncio.TimeoutError:
            logging.error(f"Timeout error. Attempt {attempt + 1}/{MAX_RETRIES}")
            await exponential_backoff(attempt)
        except Exception as e:
            logging.error(f"Unexpected error: {e}. Attempt {attempt + 1}/{MAX_RETRIES}")
            await exponential_backoff(attempt)
    raise Exception(f"Failed after {MAX_RETRIES} retries")

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as file:
            return json.load(file)
    return {'start_cursor': None, 'total_retrieved': 0, 'queried_page_ids': []}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as file:
        json.dump(progress, file)

def check_csv_and_generate_chart():
    if os.path.exists('habits.csv'):
        df = pd.read_csv('habits.csv')
        chart = create_chart(df)
        st.session_state.visualization_fig = chart
        st.session_state.data_table = df
        return True
    return False

def clear_progress_and_regenerate():
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    
    st.session_state.show_loader = True
    st.session_state.csv_checked = False
    st.session_state.visualization_fig = None
    st.session_state.data_table = None

    st.rerun()


class NotionDataVisualizer:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("NOTION_API_KEY")
        self.database_id = os.getenv("NOTION_HABITS_DATABASE_ID")
        self.proxy_url = os.getenv("PROXY_URL")

        self.is_configured = self.token and self.database_id

        if not self.is_configured:
            self.token = st.text_input("請輸入Notion API Token:", key='token', placeholder='請輸入有效的 API Token', help="確保 Token 長度符合要求")
            self.database_id = st.text_input("請輸入Notion數據庫ID:", key='database_id', placeholder='請輸入有效的數據庫 ID', help="確保數據庫 ID 長度符合要求")
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
            st.session_state.configuration_loaded = False
            st.session_state.show_config_message = True
            st.rerun()

    def show_save_button(self):
        if is_valid_token(self.token) and is_valid_database_id(self.database_id):
            if st.button("保存配置"):
                self.save_config()
        else:
            st.warning("請確保輸入的 Notion API Token 和數據庫 ID 符合格式要求。")

    data = {
        "filter": {
            "value": "page",
            "property": "object"
        },
        "sort": {
            "direction": "descending",
            "formula": TOTAL_MINUTES_FOR_PARENT_HABIT
        }
    }

    async def fetch(self, session, url, method='POST', query_params=None, headers=None, **kwargs):
        headers = headers or {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28"
        }
        
        if "databases" in url:
            headers["Content-Type"] = "application/json"
        
        if query_params is None:
            query_params = {}
        
        query_params.update(data)
        
        try:
            async with session.request(method, url, headers=headers, json=query_params, **kwargs) as response:
                response.raise_for_status()
                
                rate_limit_info = {
                    'remaining': int(response.headers.get('Rate-Limit-Remaining', '0')),
                    'limit': int(response.headers.get('Rate-Limit-Limit', '0')),
                }
                
                if response.content_type == 'application/json':
                    return await response.json()
                else:
                    content = await response.text()
                    st.error(f"Unexpected content type: {response.content_type}")
                    st.error(f"Response content: {content}")
                    return None
        except Exception as e:
            st.error(f"Request failed: {e}")
            return None

    async def get_notion_data(self, start_cursor=None, total_retrieved=0, queried_page_ids=None):
        url = f"https://api.notion.com/v1/databases/{self.database_id}/query"
        async with aiohttp.ClientSession() as session:
            has_more = True
            results = []
            page_count = total_retrieved
            queried_page_ids = set(queried_page_ids or [])

            while has_more:
                page_size = 5

                query_params = {"page_size": page_size}
                if start_cursor:
                    query_params['start_cursor'] = start_cursor

                try:
                    response = await smart_retry(self.fetch, session, url, method='POST', query_params=query_params)
                    
                    if response:
                        fetched_results = response.get('results', [])
                        new_results = [page for page in fetched_results if page['id'] not in queried_page_ids]
                        
                        if not new_results:
                            logging.warning(f"No new results found in this batch. Current page count: {page_count}")
                            start_cursor = response.get('next_cursor')
                            if not start_cursor:
                                logging.info("No more pages to retrieve.")
                                break
                            continue

                        page_count += len(new_results)
                        results.extend(new_results)
                        queried_page_ids.update(page['id'] for page in new_results)
                        
                        has_more = response.get('has_more', False)
                        start_cursor = response.get('next_cursor')

                        page_names = [page['properties']['Name']['title'][0]['plain_text'] for page in new_results if 'properties' in page and 'Name' in page['properties'] and 'title' in page['properties']['Name']]
                        
                        logging.info(f"Current page count: {page_count}")
                        if start_cursor:
                            logging.info(f"Next start_cursor: {page_names[-1] if page_names else 'Unknown'}")
                        else:
                            logging.info("No more pages to retrieve.")

                        save_progress({
                            'start_cursor': start_cursor, 
                            'total_retrieved': page_count,
                            'queried_page_ids': list(queried_page_ids)
                        })

                        await asyncio.sleep(1)
                    else:
                        has_more = False

                except Exception as e:
                    logging.error(f"Unexpected error during pagination: {e}")
                    break

        logging.info(f"Total items retrieved: {page_count}")
        return {'results': results, 'total_retrieved': page_count, 'queried_page_ids': list(queried_page_ids), 'start_cursor': start_cursor}

    async def get_page_name(self, session, page_id):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        page_data = await self.fetch(session, url)
        if page_data and 'properties' in page_data and TASK_NOTION_NAME in page_data['properties'] and '*' in page_data['properties'][TASK_NOTION_NAME]['title'][0]['plain_text']:
            return page_data['properties'][TASK_NOTION_NAME]['title'][0]['plain_text']
        else:
            return "Unknown"
            
    async def process_data(self, data):
        categories = {}
        async with aiohttp.ClientSession() as session:
            tasks = []
            for result in data['results']:
                parent = result['properties'].get(PARENT_RELATION_PROPERTY, {})
                total_mins = result['properties'].get(TOTAL_MINUTES_FOR_PARENT_HABIT, {}).get('formula', {}).get('number', 0)

                if 'relation' in parent and parent['relation']:
                    parent_id = parent['relation'][0]['id']
                    tasks.append(self.get_page_name(session, parent_id))
                else:
                    categories[result['properties']['Name']['title'][0]['plain_text']] = total_mins

            parent_names = await asyncio.gather(*tasks)
            for parent_name in parent_names:
                if parent_name not in categories:
                    categories[parent_name] = 0
                categories[parent_name] += total_mins

        sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        df = pd.DataFrame(sorted_categories, columns=["Category", "Total Minutes"])
        return df

    def create_chart(self, df, chart_type='bar', orientation='horizontal', height=450, width=1080):
        if chart_type == 'bar':
            if orientation == 'horizontal':
                fig = px.bar(df, x='Total Minutes', y='Category', orientation='h', height=height, width=width)
            else:
                fig = px.bar(df, x='Category', y='Total Minutes', height=height, width=width)
        elif chart_type == 'scatter':
            fig = px.scatter(df, x='Total Minutes', y='Category', size='Total Minutes', height=height, width=width)
        elif chart_type == 'treemap':
            fig = px.treemap(df, path=['Category'], values='Total Minutes', height=height, width=width)

        # Update layout to center the title, set font size, and adjust padding
        fig.update_layout(
            title={
                'text': 'My Habits',
                'x': 0.5,  # Center the title horizontally
                'xanchor': 'center',  # Anchor the title in the center horizontally
                'yanchor': 'top',  # Anchor the title to the top vertically
                'font': {
                    'size': 30,  # Font size of the title
                    'family': 'Arial',  # Font family of the title
                    'color': 'White'  # Font color of the title
                },
                'pad': {
                    't': 100  # Padding above the title (distance from the chart)
                }
            },
            margin=dict(t=100, l=0, r=0, b=0)  # Adjust the margin to add space around the chart, reduce top margin
        )

        return fig

    async def generate_visualization(self):
        start_cursor = None
        total_retrieved = 0
        queried_page_ids = set()

        all_results = []
        page_limit = 600
        last_total_retrieved = 0

        while total_retrieved < page_limit:
            data = await self.get_notion_data(start_cursor=start_cursor, total_retrieved=total_retrieved, queried_page_ids=queried_page_ids)
            all_results.extend(data['results'])
            total_retrieved = data['total_retrieved']
            queried_page_ids = set(data['queried_page_ids'])
            start_cursor = data['start_cursor']
            
            logging.info(f"Total items retrieved: {total_retrieved}")

            if total_retrieved == last_total_retrieved:
                logging.warning("No new items retrieved in this iteration. Breaking the loop.")
                break

            last_total_retrieved = total_retrieved

            if total_retrieved >= 400 and total_retrieved < page_limit:
                logging.info("Reached 400 pages. Continuing to retrieve up to 600 pages.")
                await asyncio.sleep(30)

            save_progress({
                'start_cursor': start_cursor, 
                'total_retrieved': total_retrieved,
                'queried_page_ids': list(queried_page_ids)
            })

            if not start_cursor or total_retrieved >= page_limit:
                logging.info(f"Reached page limit of {page_limit} or no more pages to retrieve.")
                break

        logging.info(f"Finished retrieving data. Total pages: {total_retrieved}")

        df = await self.process_data({'results': all_results})
        
        df.to_csv('habits.csv', index=False)
        logging.info("Generated habits.csv file")

        return df


# Custom CSS for centering the title
custom_css = """
<style>
h1 {
    text-align: left;
}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# Main title
st.markdown("<h1>DASH</h1>", unsafe_allow_html=True)

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
if 'data_table' not in st.session_state:
    st.session_state.data_table = None
if 'show_config_message' not in st.session_state:
    st.session_state.show_config_message = False
if 'is_vertical' not in st.session_state:
    st.session_state.is_vertical = False
if 'show_tools' not in st.session_state:
    st.session_state.show_tools = False  # 默认隐藏工具
if 'show_table' not in st.session_state:
    st.session_state.show_table = False  # 默认隐藏表格
if 'num_items' not in st.session_state:
    st.session_state.num_items = 20  # 默认显示的项目数
if 'selected_chart_type' not in st.session_state:
    st.session_state.selected_chart_type = 'bar'  # 默认图表类型
if 'orientation' not in st.session_state:
    st.session_state.orientation = 'horizontal'  # 默认方向

# Show "配置已加载" message if needed
if st.session_state.show_config_message and visualizer.is_configured:
    st.success("配置已加载")
    st.session_state.show_config_message = False

# Create a row for the checkbox and buttons
col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

with col1:
    if os.path.exists('habits.csv'):
        if st.button("Re-FETCH", key="re_fetch", help="重新获取数据"):
            clear_progress_and_regenerate()
    else:
        if not st.session_state.show_loader and visualizer.is_configured:
            if st.button("Generate Visualization", key="generate", help="生成可视化"):
                st.session_state.show_loader = True
                st.rerun()

with col4:
    # 使用复选框来控制工具的显示状态
    show_tools = st.checkbox("HIDE TOOLS" if st.session_state.show_tools else "TOOLS", value=st.session_state.show_tools)

    # 更新 session state 中的工具显示状态
    if show_tools != st.session_state.show_tools:
        st.session_state.show_tools = show_tools
        st.rerun()  # 强制重新渲染页面

with col3:
    # 使用复选框来控制表格的显示状态
    show_table = st.checkbox("TABLE", value=st.session_state.show_table)

    # 更新 session state 中的表格显示状态
    if show_table != st.session_state.show_table:
        st.session_state.show_table = show_table
        st.rerun()  # 强制重新渲染页面

# 定义 num_items、selected_chart_type 和 orientation，确保它们在任何情况下都被定义
if st.session_state.show_tools:
    # Add chart type selector
    chart_types = ['bar', 'scatter', 'treemap']
    st.session_state.selected_chart_type = st.selectbox("Select Chart Type", chart_types)

    # 添加方向选择器（仅适用于条形图）
    if st.session_state.selected_chart_type == 'bar':
        st.session_state.orientation = st.radio("Select Orientation", ['horizontal', 'vertical'])
    else:
        st.session_state.orientation = 'horizontal'  # 默认值，不会用于非条形图

    # 添加滑块来选择显示的项目数量
    df = st.session_state.data_table if st.session_state.data_table is not None else pd.read_csv('habits.csv') if os.path.exists('habits.csv') else pd.DataFrame()
    st.session_state.num_items = st.slider("Number of items to display", min_value=5, max_value=len(df) if len(df) > 0 else 20, value=st.session_state.num_items)

    # 添加图表尺寸的滑块
    col1, col2 = st.columns(2)
    with col1:
        chart_width = st.slider("Chart Width", min_value=400, max_value=1200, value=700)
    with col2:
        chart_height = st.slider("Chart Height", min_value=300, max_value=1000, value=500)
else:
    # 如果工具被隐藏，设置默认值
    chart_width = 700
    chart_height = 500

# 处理加载逻辑和可视化生成
if st.session_state.show_loader:
    with st.spinner("正在获取页面 ..."):
        try:
            df = asyncio.run(visualizer.generate_visualization())
            if df is not None:
                st.session_state.data_table = df
                st.session_state.csv_checked = True
            else:
                st.error("数据处理失败，请检查 API 配置和数据。")
        except Exception as e:
            st.error(f"生成可视化时发生错误: {e}")
    
    st.session_state.show_loader = False
    st.rerun()

# 检查 habits.csv 是否存在并生成图表
if 'csv_checked' not in st.session_state:
    st.session_state.csv_checked = os.path.exists('habits.csv')

# 如果数据可用，显示生成的可视化
if st.session_state.data_table is not None or (st.session_state.csv_checked and os.path.exists('habits.csv')):
    if st.session_state.data_table is None:
        df = pd.read_csv('habits.csv')
    else:
        df = st.session_state.data_table
    
    # 按 Total Minutes 排序数据框并选择前 n 项
    df_display = df.sort_values('Total Minutes', ascending=False).head(st.session_state.num_items)
    
    # 创建基于选定类型、方向和尺寸的图表
    fig = visualizer.create_chart(df_display, chart_type=st.session_state.selected_chart_type, orientation=st.session_state.orientation, height=chart_height, width=chart_width)
    
    # 显示图表
    st.plotly_chart(fig)

# 如果可用且选中，显示数据表
if st.session_state.show_table:
    st.caption("Data shown on the chart")
    # 确保 data_table 已经正确加载
    if st.session_state.data_table is not None:
        st.dataframe(st.session_state.data_table)
    elif os.path.exists('habits.csv'):
        df = pd.read_csv('habits.csv')
        st.dataframe(df)
    else:
        st.warning("数据表尚未加载。")