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
from functools import lru_cache
from streamlit_elements import mui, dashboard, elements, html, sync, lazy

logging.basicConfig(level=logging.INFO, format='%(message)s')

# File to store settings
SETTINGS_FILE = 'chart_settings.json'
PROGRESS_FILE = 'progress.json'

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
        self.database_id = os.getenv("NOTION_DATABASE_ID")
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
                f.write(f"NOTION_DATABASE_ID={self.database_id}\n")
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

        fig.update_layout(
            title={
                'text': 'My Habits',
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top',
                'font': {
                    'size': 30,
                    'family': 'Arial',
                    'color': 'White'
                },
                'pad': {
                    't': 100
                }
            },
            margin=dict(t=100, l=0, r=0, b=0)
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

        # Ensure the 'Data' directory exists
        data_dir = 'data'
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            logging.info(f"Created directory: {data_dir}")

        # Save the CSV file in the 'Data' directory
        csv_path = os.path.join(data_dir, 'habits.csv')
        df.to_csv(csv_path, index=False)
        logging.info(f"Generated {csv_path} file")


# # Custom CSS for centering the title
# custom_css = """
# <style>
# h1 {
#     text-align: left;
# }
# </style>
# """
# st.markdown(custom_css, unsafe_allow_html=True)

# # Main title
# st.markdown("<h1>DASH</h1>", unsafe_allow_html=True)

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

@lru_cache(maxsize=1)
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)

def get_setting(key, default_value):
    if key not in st.session_state:
        saved_settings = load_settings()
        st.session_state[key] = saved_settings.get(key, default_value) if saved_settings else default_value
    return st.session_state[key]

def set_setting(key, value):
    if st.session_state.get(key) != value:
        st.session_state[key] = value
        save_settings({k: v for k, v in st.session_state.items() if not k.startswith('_') and not isinstance(v, pd.DataFrame)})

# Initialize settings
show_tools = get_setting('show_tools', False)
show_table = get_setting('show_table', False)
num_items = get_setting('num_items', 20)
selected_chart_type = get_setting('selected_chart_type', 'bar')
orientation = get_setting('orientation', 'vertical')
chart_width = get_setting('chart_width', 700)
chart_height = get_setting('chart_height', 500)

# Initialize session state
if 'show_loader' not in st.session_state:
    st.session_state.show_loader = False
if 'data_table' not in st.session_state:
    st.session_state.data_table = None
if 'show_config_message' not in st.session_state:
    st.session_state.show_config_message = False
if 'show_tools' not in st.session_state:
    st.session_state.show_tools = False
if 'show_table' not in st.session_state:
    st.session_state.show_table = False
if 'num_items' not in st.session_state:
    st.session_state.num_items = 20
if 'selected_chart_type' not in st.session_state:
    st.session_state.selected_chart_type = 'bar'
if 'orientation' not in st.session_state:
    st.session_state.orientation = 'horizontal'
if 'csv_checked' not in st.session_state:
    st.session_state.csv_checked = True

# Show "配置已加载" message if needed
if st.session_state.show_config_message and visualizer.is_configured:
    st.success("配置已加载")
    st.session_state.show_config_message = False

# Create a row for the checkbox and buttons
col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

with col1:
    if os.path.exists('data/habits.csv'):
        if st.button("Re-FETCH", key="re_fetch", help="重新获取数据"):
            clear_progress_and_regenerate()
    else:
        if not st.session_state.show_loader and visualizer.is_configured:
            if st.button("Generate Visualization", key="generate", help="生成可视化"):
                st.session_state.show_loader = True
                # Perform async task without st.rerun()
                df = asyncio.run(visualizer.generate_visualization())
                if df is not None:
                    st.session_state.data_table = df
                    st.session_state.csv_checked = True
                else:
                    st.error("数据处理失败，请检查 API 配置和数据。")
                st.session_state.show_loader = False

with col4:
    new_show_tools = st.checkbox("HIDE TOOLS" if show_tools else "TOOLS", value=show_tools)
    if new_show_tools != show_tools:
        set_setting('show_tools', new_show_tools)
        st.session_state.show_tools = new_show_tools

with col3:
    new_show_table = st.checkbox("TABLE", value=show_table)
    if new_show_table != show_table:
        set_setting('show_table', new_show_table)
        st.session_state.show_table = new_show_table

# Show tools if the checkbox is checked
if st.session_state.show_tools:
    col1, col2 = st.columns(2)
    
    with col1:
        # Dropdown menu for chart type
        chart_options = ["bar", "scatter", "treemap"]
        selected_chart_type = st.selectbox(
            "Select Chart Type",
            options=chart_options,
            index=chart_options.index(st.session_state.selected_chart_type)
        )
        if selected_chart_type != st.session_state.selected_chart_type:
            set_setting('selected_chart_type', selected_chart_type)
            st.session_state.selected_chart_type = selected_chart_type
            st.session_state.orientation = "vertical"  # Reset orientation when changing chart type
        
        # Show orientation option if bar chart is selected
        if selected_chart_type == "bar":
            orientation_options = ["vertical", "horizontal"]
            orientation = st.radio(
                "Select Bar Chart Orientation",
                options=orientation_options,
                index=orientation_options.index(st.session_state.orientation)
            )
            if orientation != st.session_state.orientation:
                set_setting('orientation', orientation)
                st.session_state.orientation = orientation
    
    with col2:
        new_chart_width = st.slider("Chart Width", min_value=400, max_value=1200, value=chart_width)
        if new_chart_width != chart_width:
            set_setting('chart_width', new_chart_width)
            st.session_state.chart_width = new_chart_width
    
    with col2:
        new_chart_height = st.slider("Chart Height", min_value=300, max_value=1000, value=chart_height)
        if new_chart_height != chart_height:
            set_setting('chart_height', new_chart_height)
            st.session_state.chart_height = new_chart_height
    
    # Number of items slider
    if os.path.exists('data/habits.csv'):
        df = pd.read_csv('data/habits.csv')
        max_num_items = len(df)
    else:
        max_num_items = 20  # Default max value

    new_num_items = st.slider("Number of items to display", min_value=5, max_value=max_num_items, value=num_items)
    if new_num_items != num_items:
        set_setting('num_items', new_num_items)
        st.session_state.num_items = new_num_items
        
        # Update data table display
        if st.session_state.data_table is not None:
            st.session_state.data_table = st.session_state.data_table.head(new_num_items)

# 处理加载逻辑和可视化生成
if st.session_state.data_table is not None or (st.session_state.csv_checked and os.path.exists('data/habits.csv')):
    if st.session_state.data_table is None:
        df = pd.read_csv('data/habits.csv')
    else:
        df = st.session_state.data_table

    # Ensure the number of items displayed matches the slider value
    df = df.head(st.session_state.num_items)

    # Add 'Visible' column if it does not exist
    if 'Visible' not in df.columns:
        df['Visible'] = True

    # Create and display the chart
    fig = visualizer.create_chart(
        df[df['Visible']].sort_values('Total Minutes', ascending=False),
        chart_type=st.session_state.selected_chart_type,
        orientation=st.session_state.orientation,
        height=st.session_state.chart_height,
        width=st.session_state.chart_width
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Display the editable data table below the chart
    if st.session_state.show_table:
        st.write("Data Table")

        # Watch for changes in the editable data table
        edited_df = st.data_editor(df, key="data_editor_key", use_container_width=True)

        # Sync the data table with the slider value
        if not df.equals(edited_df):
            st.session_state.data_table = edited_df
            visible_items = edited_df.loc[edited_df['Visible'], :]
            num_visible_items = len(visible_items)
            if st.session_state.num_items != num_visible_items:
                st.session_state.num_items = num_visible_items
                set_setting('num_items', num_visible_items)