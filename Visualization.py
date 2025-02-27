import os
import asyncio
import aiohttp
import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv
import logging
import time

# 設置頁面為寬屏模式
st.set_page_config(layout="wide")

# 自定義 CSS 實現響應式佈局與樣式優化
st.markdown(
    """
    <style>
    /* 減少頂部空白 */
    .block-container {
        padding-top: 1rem;
    }
    /* 響應式 Grid 佈局 */
    .grid-container {
        display: grid;
        grid-template-columns: repeat(2, 1fr); /* 寬屏時兩列 */
        gap: 15px; /* 增加間距 */
    }
    @media (max-width: 768px) { /* 窄屏斷點調整為 768px */
        .grid-container {
            grid-template-columns: 1fr; /* 窄屏時一列 */
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(message)s')

# 從環境變量獲取 Notion API 相關信息
API_TOKEN = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_HABITS_DATABASE_ID")

# 主題顏色（可根據您的主題調整）
primary_color = "#6d46f9"

# Notion 查詢參數
query_payload = {
    "sorts": [{"property": "Parent or Sub", "direction": "descending"}],
    "page_size": 5
}

# 重試參數
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
            await exponential_backoff(attempt)
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
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
    valid_parents = {}
    start_cursor = None
    total_retrieved = 0
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                data = await smart_retry(fetch_notion_data, session, start_cursor)
                results = data.get("results", [])
                total_retrieved += len(results)
                for page in results:
                    name = page["properties"]["Name"]["title"][0]["plain_text"]
                    if name.endswith("*"):
                        total = page["properties"]["Total min Par"]["formula"]["number"]
                        valid_parents[name] = total
                        if len(valid_parents) >= 11:
                            return valid_parents
                start_cursor = data.get("next_cursor")
                if not start_cursor:
                    break
            except Exception as e:
                logging.error(f"Error fetching data: {e}")
                break
    return valid_parents

# -------------------- Streamlit App --------------------

st.title("Hi, GengGeng")

# 初始化狀態
if "updating" not in st.session_state:
    st.session_state["updating"] = False

# 側邊欄控件
chart_type = st.sidebar.selectbox("Type", [
    "Line Chart", "Bar Chart", "Box Plot", "Histogram",
    "Scatter Chart", "Bubble Chart", "Pie Chart", "Sunburst Chart", "Tree Chart"
], index=0)

orientation = st.sidebar.radio("Direction", ["Vertical", "Horizontal"], index=1) if chart_type in ["Bar Chart", "Box Plot", "Histogram"] else None
line_mode = st.sidebar.radio("Mode", ["Line Chart", "Area Chart"], index=0) if chart_type == "Line Chart" else None
curve_option = st.sidebar.radio("Curve", ["Curved", "Straight"], index=0) if chart_type == "Line Chart" else None

chart_height = st.sidebar.slider("Height", min_value=300, max_value=720, value=360)
show_table = st.sidebar.checkbox("Show Table", value=True)

# 更新數據按鈕
button_placeholder = st.empty()
if not st.session_state["updating"]:
    if button_placeholder.button("Feed"):
        st.session_state["updating"] = True
        button_placeholder.empty()

# 數據更新邏輯
if st.session_state["updating"]:
    with st.spinner("Baking it now"):
        valid = asyncio.run(get_valid_parent_habits())
        df = pd.DataFrame(list(valid.items()), columns=["Category", "Total Minutes"])
        df.to_csv("habits.csv", index=False)
        msg_placeholder = st.empty()
        msg_placeholder.success("Data updated successfully!")
        time.sleep(1)  # 縮短等待時間，避免過長阻塞
        msg_placeholder.empty()
    st.session_state["updating"] = False

# 數據可視化
if os.path.exists("habits.csv"):
    df = pd.read_csv("habits.csv")
    
    # 圖表生成
    fig = None
    if chart_type == "Line Chart":
        fig = px.line(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear",
                      title="Category vs Total Min", height=chart_height, color_discrete_sequence=[primary_color]) if line_mode == "Line Chart" else \
              px.area(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear",
                      title="Category vs Total Min", height=chart_height, color_discrete_sequence=[primary_color])
    elif chart_type == "Bar Chart":
        fig = px.bar(df, x="Total Minutes" if orientation=="Horizontal" else "Category", y="Category" if orientation=="Horizontal" else "Total Minutes",
                     text="Total Minutes", title="Category vs Total Min", height=chart_height, color_discrete_sequence=[primary_color])
    elif chart_type == "Bubble Chart":
        fig = px.scatter(df, x="Category", y="Total Minutes", size="Total Minutes", color="Category", title="Category vs Total Min", height=chart_height)
    elif chart_type == "Scatter Chart":
        fig = px.scatter(df, x="Total Minutes", y="Category", text="Total Minutes", title="Category vs Total Min", height=chart_height, color_discrete_sequence=[primary_color])
    elif chart_type == "Box Plot":
        fig = px.box(df, x="Total Minutes" if orientation=="Horizontal" else "Category", y="Category" if orientation=="Horizontal" else "Total Minutes",
                     title="Category vs Total Min", height=chart_height, color_discrete_sequence=[primary_color])
    elif chart_type == "Histogram":
        fig = px.histogram(df, x="Total Minutes" if orientation=="Horizontal" else "Category", title="Distribution", height=chart_height, color_discrete_sequence=[primary_color])
    elif chart_type == "Pie Chart":
        fig = px.pie(df, names="Category", values="Total Minutes", title="Category Distribution", height=chart_height)
    elif chart_type == "Sunburst Chart":
        fig = px.sunburst(df, path=["Category"], values="Total Minutes", title="Category vs Total Min", height=chart_height)
    elif chart_type == "Tree Chart":
        fig = px.treemap(df, path=["Category"], values="Total Minutes", title="Category vs Total Min", height=chart_height)

    if fig:
        fig.update_layout(
            title=dict(text=fig.layout.title.text, x=0.5, xanchor="center"),
            margin=dict(l=20, r=20, t=50, b=20),
            legend=dict(font=dict(size=max(22, chart_height // 50)))
        )
        
        # 響應式佈局容器
        with st.container():
            st.markdown('<div class="grid-container">', unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                st.plotly_chart(fig, use_container_width=True)
            if show_table:
                with col2:
                    st.caption("Data shown on the chart")
                    df_with_index = df.copy()
                    df_with_index.insert(0, "No.", range(1, len(df_with_index) + 1))
                    
                    # 自定義表格樣式（暗色主題）
                    dark_table_css = """
                    <style>
                    .styled-table {
                        width: 100%;
                        border-collapse: separate;
                        border-spacing: 0;
                        border: 1px solid #444;
                        border-radius: 10px;
                        overflow: hidden;
                        font-family: 'Segoe UI', sans-serif;
                    }
                    .styled-table th, .styled-table td {
                        text-align: center;
                        padding: 10px;
                    }
                    .styled-table th {
                        background-color: #333;
                        color: #ddd;
                        font-weight: 600;
                    }
                    .styled-table td {
                        background-color: #1e1e1e;
                        color: #ddd;
                    }
                    </style>
                    """
                    st.markdown(dark_table_css, unsafe_allow_html=True)
                    html_table = df_with_index.to_html(index=False).replace("<table", "<table class='styled-table' ")
                    st.markdown(html_table, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
else:
    st.info("I'm hungry. You can feed me data.")