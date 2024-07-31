# https://www.kaggle.com/code/subinium/storytelling-with-data-netflix-ver/notebook
# https://ipyvizzu.vizzuhq.com/latest/examples/presets
import pandas as pd
from ipyvizzu import Chart, Data, Config, Style
from streamlit.components.v1 import html
import numpy as np
from collections import Counter
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
import uuid

logging.basicConfig(level=logging.INFO, format='%(message)s')

# File to store settings
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
        data = Data()
        data.add_df(df)

        chart = VizzuChart(width=width, height=height)
        chart.animate(data)

        return chart, data


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

# Constants
SETTINGS_FILE = 'chart_settings.json'
CSV_FILE = 'data/habits.csv'

# Helper functions
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
        st.session_state[key] = default_value
    return st.session_state[key]

# Load data
@st.cache_data
def load_data():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        if 'Visible' not in df.columns:
            df['Visible'] = True
        return df
    return None

# Create or update chart
def update_chart(chart, df, chart_type, orientation):
    # Clear existing animations to avoid replaying history
    chart = VizzuChart()

    data = Data()
    data.add_df(df)
    chart.animate(data)

    config = {
        "channels": {
            "x": {"set": ["Category"]},
            "y": {"set": ["Total Minutes"]},
            "color": {"set": ["Category"]},
            "label": {"set": ["Total Minutes"]}
        },
        "title": "My Habits",
        "geometry": "rectangle"
    }

    if chart_type == 'bar':
        if orientation == 'horizontal':
            config["channels"]["x"]["set"] = ["Total Minutes"]
            config["channels"]["y"]["set"] = ["Category"]
        config["title"] += f" ({orientation.capitalize()} Bar Chart)"
    elif chart_type == 'scatter':
        config["channels"]["x"]["set"] = ["Total Minutes"]
        config["channels"]["y"]["set"] = ["Category"]
        config["channels"]["size"] = {"set": ["Total Minutes"]}
        config["geometry"] = "circle"
        config["title"] += " (Scatter Plot)"
    elif chart_type == 'treemap':
        config["channels"] = {
            "size": {"set": ["Total Minutes"]},
            "color": {"set": ["Category"]},
            "label": {"set": ["Category", "Total Minutes"]}
        }
        config["title"] += " (Treemap)"

    chart.animate(Config(config))
    return chart

# Main app
def main():
    st.session_state.chart = None
    st.set_page_config(layout="wide")

    # Initialize settings
    settings = load_settings()
    for key, value in settings.items():
        get_setting(key, value)

    # Load data
    df = load_data()
    if df is None:
        st.error("No data found. Please generate the CSV file first.")
        return

    # Sidebar controls
    with st.sidebar:
        st.header("Chart Controls")
        chart_type = st.selectbox("Select Chart Type", ["bar", "scatter", "treemap"], key="chart_type")
        orientation = st.radio("Bar Chart Orientation", ["vertical", "horizontal"], key="orientation") if chart_type == "bar" else "vertical"
        
        # Display slider with current value
        num_items = st.slider("Number of items to display", 1, len(df), key="num_items")
        
        chart_height = st.slider("Chart Height", 300, 1000, key="chart_height")
        show_table = st.checkbox("Show Data Table", key="show_table")

    # Update visible items
    df['Visible'] = False
    df.iloc[:num_items, df.columns.get_loc('Visible')] = True

    # Create or update chart
    st.session_state.chart = update_chart(st.session_state.chart, df[df['Visible']], chart_type, orientation)
    st.session_state.chart.show()

    # Display editable data table
    if show_table:
        st.subheader("Data Table")
        edited_df = st.data_editor(df, key="data_editor", use_container_width=True)
        if not df.equals(edited_df):
            df = edited_df
            st.session_state.data = df
            st.rerun()

    # Save settings
    settings_to_save = {
        'chart_type': chart_type,
        'orientation': orientation,
        'num_items': num_items,
        'chart_height': chart_height,
        'show_table': show_table
    }
    save_settings(settings_to_save)

if __name__ == "__main__":
    main()