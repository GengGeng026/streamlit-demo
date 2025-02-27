import os
import asyncio
import aiohttp
import json
import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv
import random
import logging
import time  # 用于延时

# 設置頁面為寬屏模式，讓內容充分利用窗口寬度
st.set_page_config(layout="wide")

# 自定義 CSS：減少頂部空白並實現響應式佈局
st.markdown(
    """
    <style>
    /* 減少主內容區域頂部空白 */
    .block-container {
        padding-top: 1rem;
    }
    /* 響應式佈局：當窗口寬度大於 1000px 時圖表和表格並排，否則上下堆疊 */
    @media (min-width: 1000px) {
        .chart-container, .table-container {
            width: 50% !important;
            float: left;
        }
    }
    @media (max-width: 999px) {
        .chart-container, .table-container {
            width: 100% !important;
            float: none;
        }
    }
    /* 確保圖表和表格高度一致 */
    .chart-container, .table-container {
        height: 100%;
    }
    </style>
    """,
    unsafe_allow_html=True
)

logging.basicConfig(level=logging.INFO, format='%(message)s')

# 從環境變量中獲取 Notion API Token 與數據庫 ID
API_TOKEN = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_HABITS_DATABASE_ID")

# 定義主題顏色，請根據你的 Streamlit Active Theme 調整
primary_color = "#6d46f9"

# 查詢參數：過濾 Total min Par > 0，排序依據公式屬性 Parent or Sub 降序
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

st.title("Hi, GengGeng")

# 初始化更新狀態
if "update_clicked" not in st.session_state:
    st.session_state["update_clicked"] = False

# 側邊欄控件：圖表類型、圖表高度、是否顯示數據表
chart_type = st.sidebar.selectbox("Type", [
    "Line Chart", "Bar Chart", "Box Plot", "Histogram",
    "Scatter Chart", "Bubble Chart",
    "Pie Chart", "Sunburst Chart",
    "Tree Chart"
], index=0)

if chart_type in ["Bar Chart", "Box Plot", "Histogram"]:
    orientation = st.sidebar.radio("Direction", ["Vertical", "Horizontal"], index=1)
else:
    orientation = None

if chart_type == "Line Chart":
    line_mode = st.sidebar.radio("Mode", ["Line Chart", "Area Chart"], index=0, help="Try different modes")
    curve_option = st.sidebar.radio("Curve", ["Curved", "Straight"], index=0, help="Bold or Wavy")
else:
    line_mode = None
    curve_option = None

chart_height = st.sidebar.slider("Height", min_value=300, max_value=720, value=360, help="Slide me to the desired height")
show_table = st.sidebar.checkbox("Show Table", value=True)

# 創建一個按鈕占位符
button_placeholder = st.empty()

# 僅當不在更新中時顯示 Feed 按鈕
if "updating" not in st.session_state:
    st.session_state["updating"] = False

if not st.session_state["updating"]:
    if button_placeholder.button("Feed"):
        st.session_state["updating"] = True
        button_placeholder.empty()  # 讓按鈕立即消失

# 當處於更新狀態時，顯示 spinner 並更新數據
if st.session_state["updating"]:
    with st.spinner("Baking it now"):
        valid = asyncio.run(get_valid_parent_habits())
        df = pd.DataFrame(list(valid.items()), columns=["Category", "Total Minutes"])
        df.to_csv("habits.csv", index=False)
        msg_placeholder = st.empty()
        msg_placeholder.success("Data updated successfully!")
        time.sleep(3)  # 模擬等待3秒（注意：這會阻塞頁面刷新）
        msg_placeholder.empty()
    st.session_state["updating"] = False

if os.path.exists("habits.csv"):
    df = pd.read_csv("habits.csv")
    
    fig = None
    if chart_type == "Line Chart":
        if line_mode == "Line Chart":
            fig = px.line(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear", title="Category    VS    Total Min", height=chart_height,
                         color_discrete_sequence=[primary_color])
        else:
            fig = px.area(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear", title="Category    VS    Total Min", height=chart_height,
                         color_discrete_sequence=[primary_color])
    elif chart_type == "Bar Chart":
        if orientation == "Horizontal":
            fig = px.bar(df, x="Total Minutes", y="Category", text="Total Minutes", title="Category    VS    Total Min", height=chart_height,
                         color_discrete_sequence=[primary_color])
        else:
            fig = px.bar(df, x="Category", y="Total Minutes", text="Total Minutes", title="Category    VS    Total Min", height=chart_height,
                         color_discrete_sequence=[primary_color])
    elif chart_type == "Bubble Chart":
        fig = px.scatter(df, x="Category", y="Total Minutes", size="Total Minutes", color="Category", title="Category    VS    Total Min", height=chart_height)
    elif chart_type == "Scatter Chart":
        fig = px.scatter(df, x="Total Minutes", y="Category", text="Total Minutes", title="Category    VS    Total Min", height=chart_height,
                         color_discrete_sequence=[primary_color])
    elif chart_type == "Box Plot":
        if orientation == "Horizontal":
            fig = px.box(df, x="Total Minutes", y="Category", title="Category    VS    Total Min", height=chart_height,
                         color_discrete_sequence=[primary_color])
        else:
            fig = px.box(df, x="Category", y="Total Minutes", title="Category    VS    Total Min", height=chart_height,
                         color_discrete_sequence=[primary_color])
    elif chart_type == "Histogram":
        if orientation == "Horizontal":
            fig = px.histogram(df, x="Total Minutes", title="Total Minutes Distribution", height=chart_height,
                         color_discrete_sequence=[primary_color])
        else:
            fig = px.histogram(df, x="Category", title="Category Distribution", height=chart_height,
                         color_discrete_sequence=[primary_color])
    elif chart_type == "Pie Chart":
        fig = px.pie(df, names="Category", values="Total Minutes", title="Category Distribution", height=chart_height)
    elif chart_type == "Sunburst Chart":
        fig = px.sunburst(df, path=["Category"], values="Total Minutes", title="Category    VS    Total Min", height=chart_height)
    elif chart_type == "Tree Chart":
        fig = px.treemap(df, path=["Category"], values="Total Minutes", title="Category   VS   Total Mins", height=chart_height)
    else:
        fig = None

    if fig:
        legend_font_size = max(22, chart_height // 50)  # 根據圖表高度計算字體大小
        fig.update_layout(
            title=dict(
                text=fig.layout.title.text,
                x=0.5,
                xanchor="center"
            ),
            margin=dict(l=20, r=20, t=50, b=20),
            legend=dict(
                font=dict(size=legend_font_size)
            )
        )
        # 使用容器包裹圖表和表格，實現響應式佈局
        with st.container():
            # 圖表區域：用 div 標籤包裹並應用 chart-container 樣式
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
            if show_table:
                # 表格區域：用 div 標籤包裹並應用 table-container 樣式
                st.markdown('<div class="table-container">', unsafe_allow_html=True)
                st.caption("Data shown on the chart")
                df_with_index = df.copy()
                df_with_index.insert(0, "No.", range(1, len(df_with_index) + 1))
                
                # 定義自定義 CSS，用於暗色主題下的表格樣式
                dark_table_css = """
                <style>
                .styled-table {
                    width: 100% !important;
                    margin: 0 auto;
                    border-collapse: separate;
                    border-spacing: 0;
                    border: 1px solid #444;
                    border-radius: 10px;
                    overflow: hidden;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                }
                .styled-table th, .styled-table td {
                    text-align: center !important;
                    padding: 8px 12px;
                }
                /* 表頭使用稍微深一點的背景 */
                .styled-table th {
                    background-color: #333;
                    color: #ddd;
                    font-weight: 600;
                }
                /* 表格數據區域全使用統一的暗色背景 */
                .styled-table td {
                    background-color: #1e1e1e;
                    color: #ddd;
                }
                </style>
                """
                st.markdown(dark_table_css, unsafe_allow_html=True)
                
                # 生成 HTML 表格並應用樣式
                html_table = df_with_index.to_html(index=False)
                html_table = html_table.replace("<table", "<table class='styled-table' style='width:100%;' ")
                st.markdown(html_table, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

else:
    st.info("I'm hungry. You can feed me data.")