import os
import asyncio
import aiohttp
import json
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
import random
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

# 从环境变量中获取 Notion API Token 与数据库 ID
API_TOKEN = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_HABITS_DATABASE_ID")

# 查询参数：过滤 Total min Par > 0，排序依据公式属性 Parent or Sub 降序
query_payload = {
    "sorts": [
        {
            "property": "Parent or Sub",
            "direction": "descending"
        }
    ],
    "page_size": 5
}

MAX_RETRIES = 30
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300

async def exponential_backoff(attempt):
    delay = min(MAX_RETRY_DELAY, INITIAL_RETRY_DELAY * (2 ** attempt))
    await asyncio.sleep(delay)

async def smart_retry(func, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return await func(*args, **kwargs)
        except aiohttp.ClientResponseError as e:
            if e.status in {504, 502}:
                logging.warning(f"Server error {e.status} on attempt {attempt+1}/{MAX_RETRIES}")
            elif e.status == 429:
                logging.warning(f"Rate limit exceeded on attempt {attempt+1}/{MAX_RETRIES}")
            else:
                logging.error(f"Client response error: {e.status} on attempt {attempt+1}/{MAX_RETRIES}")
            await exponential_backoff(attempt)
        except Exception as e:
            logging.error(f"Unexpected error: {e} on attempt {attempt+1}/{MAX_RETRIES}")
            await exponential_backoff(attempt)
    raise Exception("Failed after maximum retries")

async def fetch_notion_data(session, start_cursor=None):
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = query_payload.copy()
    if start_cursor:
        payload["start_cursor"] = start_cursor
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    async with session.post(url, json=payload, headers=headers) as response:
        response.raise_for_status()
        return await response.json()

async def get_valid_parent_habits():
    valid_parents = {}  # {name: total_minutes}
    start_cursor = None
    total_retrieved = 0
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                data = await smart_retry(fetch_notion_data, session, start_cursor)
            except Exception as e:
                logging.error(f"Error fetching data: {e}")
                break
            if data is None:
                logging.error("No data returned from Notion API.")
                break
            results = data.get("results", [])
            total_retrieved += len(results)
            for page in results:
                try:
                    name = page["properties"]["Name"]["title"][0]["plain_text"]
                    if name.endswith("*"):
                        total = page["properties"]["Total min Par"]["formula"]["number"]
                        valid_parents[name] = total
                        if len(valid_parents) >= 11:
                            logging.info(f"Found {len(valid_parents)} valid parent's habits after retrieving {total_retrieved} items.")
                            return valid_parents
                except Exception as ex:
                    logging.warning(f"Failed to process page: {ex}")
            start_cursor = data.get("next_cursor")
            logging.info(f"Total items retrieved so far: {total_retrieved}")
            if not start_cursor:
                break
    return valid_parents

# -------------------- Streamlit App 部分 --------------------

st.title("Notion Data Visualization")

# 侧边栏控件：图表类型、图表高度以及是否显示数据表
chart_type = st.sidebar.selectbox("选择图表类型", [
    "Bar Chart", "Scatter Chart", "Tree Chart", "Line Chart", "Pie Chart", 
    "Bubble Chart", "Box Plot", "Histogram", "Sunburst Chart"
])

# 当选择 Bar Chart、Box Plot 或 Histogram 时显示方向切换
if chart_type in ["Bar Chart", "Box Plot", "Histogram"]:
    orientation = st.sidebar.radio("选择方向", ["Vertical", "Horizontal"], index=1)
else:
    orientation = None

# 当选择 Line Chart 时显示两个 radio 按钮：切换折线/面积和线条样式
if chart_type == "Line Chart":
    line_mode = st.sidebar.radio("选择折线模式", ["Line Chart", "Area Chart"], index=0)
    curve_option = st.sidebar.radio("线条样式", ["Straight", "Curved"], index=0)
else:
    line_mode = None
    curve_option = None

chart_height = st.sidebar.slider("图表高度", min_value=300, max_value=1000, value=360)
show_table = st.sidebar.checkbox("显示数据表", value=True)

if st.button("Update Data"):
    valid = asyncio.run(get_valid_parent_habits())
    df = pd.DataFrame(list(valid.items()), columns=["Category", "Total Minutes"])
    df.to_csv("habits.csv", index=False)
    st.success("Data updated and saved to habits.csv")

if os.path.exists("habits.csv"):
    df = pd.read_csv("habits.csv")
    
    fig = None
    if chart_type == "Bar Chart":
        if orientation == "Horizontal":
            fig = px.bar(df, x="Total Minutes", y="Category", text="Total Minutes", title="Bar Chart: Category vs Total Minutes", height=chart_height)
        else:
            fig = px.bar(df, x="Category", y="Total Minutes", text="Total Minutes", title="Bar Chart: Category vs Total Minutes", height=chart_height)
    elif chart_type == "Scatter Chart":
        fig = px.scatter(df, x="Total Minutes", y="Category", text="Total Minutes", title="Scatter Chart: Category vs Total Minutes", height=chart_height)
    elif chart_type == "Tree Chart":
        fig = px.treemap(df, path=["Category"], values="Total Minutes", title="Tree Chart: Category vs Total Minutes", height=chart_height)
    elif chart_type == "Line Chart":
        if line_mode == "Line Chart":
            fig = px.line(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear", title="Line Chart: Category vs Total Minutes", height=chart_height)
        else:
            fig = px.area(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear", title="Area Chart: Category vs Total Minutes", height=chart_height)
    elif chart_type == "Pie Chart":
        fig = px.pie(df, names="Category", values="Total Minutes", title="Pie Chart: Category Distribution", height=chart_height)
    elif chart_type == "Bubble Chart":
        fig = px.scatter(df, x="Category", y="Total Minutes", size="Total Minutes", color="Category", title="Bubble Chart: Category vs Total Minutes", height=chart_height)
    elif chart_type == "Box Plot":
        if orientation == "Horizontal":
            fig = px.box(df, x="Total Minutes", y="Category", title="Box Plot: Category vs Total Minutes", height=chart_height)
        else:
            fig = px.box(df, x="Category", y="Total Minutes", title="Box Plot: Category vs Total Minutes", height=chart_height)
    elif chart_type == "Histogram":
        if orientation == "Horizontal":
            fig = px.histogram(df, x="Total Minutes", title="Histogram: Total Minutes Distribution", height=chart_height)
        else:
            fig = px.histogram(df, x="Category", title="Histogram: Category Distribution", height=chart_height)
    elif chart_type == "Sunburst Chart":
        fig = px.sunburst(df, path=["Category"], values="Total Minutes", title="Sunburst Chart: Category vs Total Minutes", height=chart_height)
    else:
        fig = None

    if fig:
        st.plotly_chart(fig, use_container_width=True)
    
    if show_table:
        st.caption("Data shown on the chart")
        st.dataframe(df)
else:
    st.info("No CSV data found. Please update data first.")
