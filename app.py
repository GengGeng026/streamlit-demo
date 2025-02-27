import streamlit as st

st.title("動態獲取瀏覽器視窗大小")

html_code = """
<script>
function sendWindowSize() {
    let width = window.innerWidth;
    let height = window.innerHeight;
    document.getElementById("window-size").innerText = `當前視窗大小：${width} x ${height}`;
}
window.onload = sendWindowSize;
window.onresize = sendWindowSize;
</script>
<div id="window-size">正在獲取視窗大小...</div>
"""
# 將高度從 50 提高到 150
st.components.v1.html(html_code, height=150)
