import streamlit as st
import time

# Function to display a message with a fade-out effect
def show_fadeout_message(message, duration=5):
    st.markdown(f"""
    <div id="fadeout-message" style="opacity: 1; transition: opacity 2s;">
        {message}
    </div>
    <script>
    setTimeout(function() {{
        var element = document.getElementById('fadeout-message');
        element.style.opacity = '0';
    }}, {duration * 1000});  // duration in milliseconds
    </script>
    """, unsafe_allow_html=True)

# Example usage in a Streamlit app
st.title("Streamlit Fade-Out Example")

# Display a message that will fade out after 5 seconds
show_fadeout_message("配置已保存到 .env 文件中", duration=5)

# Additional Streamlit code
st.write("其他内容在这里...")
