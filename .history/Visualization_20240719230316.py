import os
import asyncio
import aiohttp
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

# ... [previous imports and constants remain unchanged]

class NotionDataVisualizer:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("NOTION_API_KEY")
        self.database_id = os.getenv("NOTION_HABITS_DATABASE_ID")
        self.proxy_url = os.getenv("PROXY_URL")

        self.is_configured = self.token and self.database_id

        if not self.is_configured:
            self.show_config_inputs()
        else:
            self.show_generate_button()

    def show_config_inputs(self):
        with st.container():
            self.token = st.text_input("请输入Notion API Token:", key='token', placeholder='请输入有效的 API Token', help="确保 Token 长度符合要求")
            self.database_id = st.text_input("请输入Notion数据库ID:", key='database_id', placeholder='请输入有效的数据库 ID', help="确保数据库 ID 长度符合要求")
            self.show_save_button()

    def show_generate_button(self):
        if st.button("Generate Visualization"):
            st.session_state.show_loader = True
            st.rerun()

    def save_config(self):
        if self.token and self.database_id:
            with open('.env', 'w') as f:
                f.write(f"NOTION_API_KEY={self.token}\n")
                f.write(f"NOTION_HABITS_DATABASE_ID={self.database_id}\n")
            st.session_state.config_saved = True
            self.is_configured = True

    def show_save_button(self):
        if is_valid_token(self.token) and is_valid_database_id(self.database_id):
            if st.button("保存配置"):
                self.save_config()
                st.rerun()
        else:
            st.warning("请确保输入的 Notion API Token 和数据库 ID 符合格式要求。")

    # ... [rest of the class methods remain unchanged]

# Streamlit app
st.title("Notion Data Visualization")

# Custom CSS for input field color change and smooth transitions
custom_css = """
<style>
input#token:valid, input#database_id:valid {
    border-color: #00FF00; /* Green color when valid */
}
input#token:invalid, input#database_id:invalid {
    border-color: #FF0000; /* Red color when invalid */
}
.fade-out {
    opacity: 0;
    transition: opacity 1s ease-out;
}
.success-message {
    opacity: 1;
    transition: opacity 1s ease-in;
}
</style>
"""

# Custom JavaScript for smooth transitions
custom_js = """
<script>
function fadeOutInputs() {
    const inputs = document.querySelectorAll('.stTextInput, .stButton');
    inputs.forEach(input => {
        input.classList.add('fade-out');
    });
    setTimeout(() => {
        inputs.forEach(input => {
            input.style.display = 'none';
        });
        showSuccessMessage();
    }, 1000);
}

function showSuccessMessage() {
    const message = document.createElement('div');
    message.textContent = '配置已保存到 .env 文件中';
    message.classList.add('success-message');
    document.body.appendChild(message);
    setTimeout(() => {
        message.classList.add('fade-out');
    }, 3000);
}

if (window.location.href.includes('config_saved=true')) {
    fadeOutInputs();
}
</script>
"""

# Apply custom CSS and JavaScript
st.markdown(custom_css, unsafe_allow_html=True)
st.markdown(custom_js, unsafe_allow_html=True)

# Initialize session state
if 'show_loader' not in st.session_state:
    st.session_state.show_loader = False
if 'config_saved' not in st.session_state:
    st.session_state.config_saved = False

# Handle loader logic
if st.session_state.show_loader:
    # ... [loader logic remains unchanged]
    pass
else:
    visualizer = NotionDataVisualizer()

# Check if config was just saved
if st.session_state.config_saved:
    st.markdown("<script>fadeOutInputs();</script>", unsafe_allow_html=True)
    st.session_state.config_saved = False