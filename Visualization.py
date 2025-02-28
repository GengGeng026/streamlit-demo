import os
import asyncio
import aiohttp
import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv
import logging
import time
import streamlit.components.v1 as components

# 設置頁面為寬屏模式並初始收起側邊欄（必須是第一個 Streamlit 命令）
st.set_page_config(layout="wide", initial_sidebar_state="collapsed")

# 自定義 CSS 實現響應式佈局與表格樣式統一
st.markdown(
    """
    <style>
    /* 主容器預留邊距 */
    .block-container {
        padding: 0.5rem 10rem; /* 四周 1rem 邊距 */
        margin: 0;
        max-width: 100%;
        min-height: 100vh; /* 確保填滿視口 */
    }
    /* 響應式 Grid 佈局 */
    .grid-container {
        display: grid;
        grid-template-columns: repeat(2, 1fr); /* 寬屏時兩列 */
        gap: 15px; /* 增加間距 */
        align-items: stretch; /* 確保子元素高度一致 */
        width: calc(100% - 2rem); /* 左右各留 1rem */
        margin: 0 auto; /* 居中 */
    }
    @media (max-width: 1000px) { /* 窄屏斷點為 1000px */
        .grid-container {
            grid-template-columns: 1fr; /* 窄屏時一列 */
        }
        .chart-wrapper, .table-wrapper {
            height: auto !important; /* 窄屏時自適應 */
        }
    }
    /* 當表格隱藏時，圖表佔據全寬 */
    .grid-container.no-table {
        grid-template-columns: 1fr; /* 圖表全寬 */
    }
    /* 確保圖表和表格容器高度匹配 */
    .chart-wrapper, .table-wrapper {
        display: flex;
        flex-direction: column;
        height: auto; /* 自適應高度 */
    }
    /* 當表格顯示時，強制同步高度 */
    .grid-container:not(.no-table) .chart-wrapper,
    .grid-container:not(.no-table) .table-wrapper {
        height: 20vh; /* 放大至 80% 視口高度 */
    }
    /* 統一表格樣式 */
    .legend-table, .styled-table {
        width: 100%;
        height: 10vh; /* 與圖表一致 */
        border-collapse: separate;
        border-spacing: 0;
        border: 1px solid #444;
        border-radius: 10px;
        overflow-y: auto; /* 僅垂直滾動 */
        font-family: 'Segoe UI', sans-serif;
        font-size: 16px; /* 增大字體 */
        background-color: rgba(1, 1, 1, 1);
    }
    .legend-table th, .legend-table td, .styled-table th, .styled-table td {
        text-align: center;
        padding: 0.3em; /* 增大內邊距 */
    }
    .legend-table th, .styled-table th {
        background-color: rgba(51, 51, 51, 0.7);
        color: #ddd;
        font-weight: 600;
    }
    .legend-table td, .styled-table td {
        color: #ddd;
    }
    h1 {
        margin-bottom: 0.1rem; /* 標題底部留少量空間 */
    }
    </style>
    """,
    unsafe_allow_html=True
)

# JavaScript 腳本：監聽 < 按鈕並完全收起側邊欄
collapse_script = """
<script>
    document.addEventListener("DOMContentLoaded", function() {
        const collapseBtn = document.querySelector('button[aria-label="Collapse sidebar"]');
        if (collapseBtn) {
            collapseBtn.addEventListener('click', function(event) {
                event.preventDefault();
                event.stopPropagation();
                const sidebar = document.querySelector('[data-testid="stSidebar"]');
                sidebar.style.setProperty('width', '0px', 'important');
                sidebar.style.setProperty('min-width', '0px', 'important');
                sidebar.style.setProperty('padding', '0px', 'important');
                sidebar.style.setProperty('visibility', 'hidden', 'important');
                sidebar.style.setProperty('overflow', 'hidden', 'important');
                document.querySelector('[data-testid="stSidebarNav"]').style.setProperty('display', 'none', 'important');
                const content = document.querySelector('.stSidebar > div');
                if (content) content.style.setProperty('display', 'none', 'important');
                sidebar.classList.add('st-sidebar--collapsed');
            });
        }
    });
</script>
"""
components.html(collapse_script, height=0)

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

# 更新數據按鈕
button_placeholder = st.empty()
if not st.session_state.get("updating", False):
    if button_placeholder.button("Refresh"):
        st.session_state["updating"] = True
        button_placeholder.empty()

st.title("Hi, GengGeng")

# 初始化狀態
if "updating" not in st.session_state:
    st.session_state["updating"] = False
if "show_table" not in st.session_state:
    st.session_state["show_table"] = True  # 初始狀態為勾選，顯示表格

# 側邊欄控件
chart_type = st.sidebar.selectbox("Type", [
    "Pie Chart", "Sunburst Chart", 
    "Line Chart", "Bar Chart", "Box Plot", "Histogram",
    "Scatter Chart", "Bubble Chart", "Tree Chart"
], index=0)

orientation = st.sidebar.radio("Direction", ["Vertical", "Horizontal"], index=1) if chart_type in ["Bar Chart", "Box Plot", "Histogram"] else None
line_mode = st.sidebar.radio("Mode", ["Area Chart", "Line Chart"], index=0) if chart_type == "Line Chart" else None
curve_option = st.sidebar.radio("Curve", ["Curved", "Straight"], index=0) if chart_type == "Line Chart" else None

# 動態調整 Show Table 的標籤，並與狀態同步
show_table_label = "Hide Table" if st.session_state["show_table"] else "Show Table"
show_table = st.sidebar.checkbox(show_table_label, value=st.session_state["show_table"], key="show_table")

# 數據更新邏輯
if st.session_state["updating"]:
    with st.spinner("Fetching latest data . . ."):
        valid = asyncio.run(get_valid_parent_habits())
        df = pd.DataFrame(list(valid.items()), columns=["Category", "Total Minutes"])
        df.to_csv("habits.csv", index=False)
        msg_placeholder = st.empty()
        msg_placeholder.success("Data updated successfully!")
        time.sleep(1)
        msg_placeholder.empty()
    st.session_state["updating"] = False
    st.rerun()  # 添加刷新以恢復按鈕

# 數據可視化
if os.path.exists("habits.csv"):
    df = pd.read_csv("habits.csv")
    
    # 圖表生成與顏色映射
    fig = None
    color_map = {}  # 在生成圖表時記錄顏色
    colors = px.colors.qualitative.Plotly  # 使用 Plotly 的預設顏色序列
    if chart_type == "Pie Chart":
        df_sorted = df.sort_values("Total Minutes", ascending=False)
        fig = px.pie(df_sorted, names="Category", values="Total Minutes", title="Category Distribution", 
                     height=500, color_discrete_sequence=colors)
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df_sorted["Category"].unique())}
    elif chart_type == "Sunburst Chart":
        df_sorted = df.sort_values("Total Minutes", ascending=False)
        fig = px.sunburst(df_sorted, path=["Category"], values="Total Minutes", title="Category vs Total Min", 
                          height=500, color_discrete_sequence=colors)
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df_sorted["Category"].unique())}
    elif chart_type == "Line Chart":
        fig = px.line(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear",
                      title="Category vs Total Min", height=500, 
                      color_discrete_sequence=[primary_color]) if line_mode == "Line Chart" else \
              px.area(df, x="Category", y="Total Minutes", line_shape="spline" if curve_option=="Curved" else "linear",
                      title="Category vs Total Min", height=500, 
                      color_discrete_sequence=[primary_color])
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df["Category"].unique())}
    elif chart_type == "Bar Chart":
        df_sorted = df.sort_values("Total Minutes", ascending=True)
        fig = px.bar(df_sorted, x="Total Minutes" if orientation=="Horizontal" else "Category", y="Category" if orientation=="Horizontal" else "Total Minutes",
                     text="Total Minutes", title="Category vs Total Min", 
                     height=500, color_discrete_sequence=[primary_color])
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df_sorted["Category"].unique())}
    elif chart_type == "Bubble Chart":
        df_sorted = df.sort_values("Total Minutes", ascending=True)
        fig = px.scatter(df_sorted, x="Category", y="Total Minutes", size="Total Minutes", color="Category", 
                         title="Category vs Total Min", height=500, 
                         color_discrete_sequence=colors)
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df_sorted["Category"].unique())}
    elif chart_type == "Scatter Chart":
        df_sorted = df.sort_values("Total Minutes", ascending=True)
        fig = px.scatter(df_sorted, x="Total Minutes", y="Category", text="Total Minutes", title="Category vs Total Min", 
                         height=500, color_discrete_sequence=[primary_color])
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df_sorted["Category"].unique())}
    elif chart_type == "Box Plot":
        df_sorted = df.sort_values("Total Minutes", ascending=True)
        fig = px.box(df_sorted, x="Total Minutes" if orientation=="Horizontal" else "Category", y="Category" if orientation=="Horizontal" else "Total Minutes",
                     title="Category vs Total Min", height=500, 
                     color_discrete_sequence=[primary_color])
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df_sorted["Category"].unique())}
    elif chart_type == "Histogram":
        fig = px.histogram(df, x="Total Minutes" if orientation=="Horizontal" else "Category", title="Distribution", 
                           height=500, color_discrete_sequence=[primary_color])
    elif chart_type == "Tree Chart":
        df_sorted = df.sort_values("Total Minutes", ascending=False)
        fig = px.treemap(df_sorted, path=["Category"], values="Total Minutes", title="Category vs Total Min", 
                         height=500, color_discrete_sequence=colors)
        color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(df_sorted["Category"].unique())}

    if fig:
        # 根據圖表類型決定是否顯示內建 Legend
        show_legend = chart_type not in ["Pie Chart", "Sunburst Chart", "Bubble Chart", "Tree Chart"]
        fig.update_layout(
            title=dict(text=fig.layout.title.text, x=0.5, xanchor="center"),
            margin=dict(l=20, r=20, t=50, b=20 if st.session_state["show_table"] else 50),
            showlegend=show_legend,
            legend=dict(
                orientation="v",
                yanchor="auto",
                y=1,
                xanchor="auto",
                x=1,
                font=dict(size=12)
            )
        )
        
        # 響應式佈局容器
        grid_class = "grid-container no-table" if not st.session_state["show_table"] else "grid-container"
        with st.container():
            st.markdown(f'<div class="{grid_class}">', unsafe_allow_html=True)
            if st.session_state["show_table"]:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown('<div class="chart-wrapper">', unsafe_allow_html=True)
                    st.plotly_chart(fig, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                with col2:
                    st.markdown('<div class="table-wrapper">', unsafe_allow_html=True)
                    col1, col2 = st.columns([4, 3])
                    if chart_type in ["Pie Chart", "Sunburst Chart", "Bubble Chart", "Tree Chart"]:
                        legend_df = df.sort_values("Total Minutes", ascending=False)
                        legend_df = legend_df[["Category", "Total Minutes"]].copy()
                        legend_df.insert(0, "Color", ["<span style='color:{}; font-size: 15px; display: inline-block; width: 20px; height: 20px; border-radius: 50%;'>{}</span>".format(color_map.get(cat, '#000000'), '●') for cat in legend_df["Category"]])
                        legend_html = legend_df.to_html(index=False, escape=False).replace("<table", "<table class='legend-table' ")
                        st.markdown(legend_html, unsafe_allow_html=True)
                    else:
                        df_with_index = df.copy()
                        df_with_index = df.sort_values("Total Minutes", ascending=False)
                        df_with_index.insert(0, "No.", range(1, len(df_with_index) + 1))
                        html_table = df_with_index.to_html(index=False).replace("<table", "<table class='styled-table' ")
                        st.markdown(html_table, unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="chart-wrapper">', unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
else:
    st.info("Try Refreshing the Data")