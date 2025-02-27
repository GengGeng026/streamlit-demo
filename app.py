import streamlit as st

st.title("動態獲取並更新瀏覽器高度")

# 注入父頁面 JS：監聽消息並更新所有 iframe 的高度
st.markdown(
    """
    <script>
    window.addEventListener("message", (event) => {
        if (event.data && event.data.newHeight) {
            // 這裡可以加判斷，只修改特定 iframe
            let iframes = document.getElementsByTagName("iframe");
            for (let i = 0; i < iframes.length; i++) {
                iframes[i].style.height = event.data.newHeight + "px";
            }
        }
    });
    </script>
    """,
    unsafe_allow_html=True
)

html_code = """
<script>
// 定义一个函数，每次更新窗口大小时调用
function updateHeight() {
    let width = window.innerWidth;
    let height = window.innerHeight;
    document.getElementById("window-size").innerText = `當前視窗大小：${width} x ${height}`;
    // 向父页面发送消息，包含新的高度
    window.parent.postMessage({newHeight: height}, "*");
}
window.onload = updateHeight;
window.onresize = updateHeight;
</script>
<div id="window-size" style="font-size: 1.5rem; text-align: center;">正在獲取視窗大小...</div>
"""

# 设置一个初始较大的高度，這裡我們設為 150（你可以調整）
st.components.v1.html(html_code, height=720)
