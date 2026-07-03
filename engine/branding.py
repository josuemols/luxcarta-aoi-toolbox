"""
LuxCarta branding header + password gate — copied from luxcarta-quote-app's
streamlit_app.py so the two apps look and feel like one system.
"""
import os
import base64

import streamlit as st

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(APP_DIR, "assets", "brand")


def page_icon():
    icon = os.path.join(BRAND, "logo_icon.png")
    try:
        from PIL import Image
        return Image.open(icon) if os.path.exists(icon) else "🛰️"
    except Exception:
        return "🛰️"


def _b64(path):
    try:
        return base64.b64encode(open(path, "rb").read()).decode()
    except Exception:
        return ""


def brand_header(title="AOI Toolbox", subtitle="Prepare AOI files (KML/KMZ) for quotes"):
    logo = _b64(os.path.join(BRAND, "logo_blue.png"))
    st.markdown(f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Jost:wght@400;500;600;700&display=swap');
      :root {{ --lux-blue:#206294; --lux-orange:#FF8300; --lux-green:#71BF49;
               --lux-gray:#72808A; --lux-ink:#333333; --lux-bg:#F4F7F9; }}
      html, body, .stApp {{ font-family:'Jost','Century Gothic',sans-serif; color:var(--lux-ink); background:#FFFFFF; }}
      .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ font-family:'Jost','Century Gothic',sans-serif; color:var(--lux-blue); font-weight:600; }}
      [data-testid="stHeadingWithActionElements"] {{ color:var(--lux-blue); }}
      .lux-header {{ display:flex; align-items:center; gap:18px; padding:10px 2px 14px; border-bottom:3px solid var(--lux-orange); margin-bottom:14px; }}
      .lux-header img {{ height:44px; }}
      .lux-header .t {{ font-size:1.5rem; font-weight:600; color:var(--lux-blue); line-height:1.05; }}
      .lux-header .s {{ font-size:.88rem; color:var(--lux-gray); }}
      .stButton > button[kind="primary"] {{ background:var(--lux-orange); border:0; color:#fff; font-weight:600; border-radius:8px; padding:.55rem 1.4rem; }}
      .stButton > button[kind="primary"]:hover {{ background:#e57600; color:#fff; }}
      [data-testid="stMetricValue"] {{ color:var(--lux-blue); font-weight:600; }}
      [data-testid="stMetricLabel"] {{ color:var(--lux-gray); }}
      [data-testid="stSidebar"] {{ background:var(--lux-bg); }}
      [data-testid="stDecoration"] {{ background:linear-gradient(90deg,var(--lux-blue),var(--lux-orange)); }}
      footer {{ visibility:hidden; }}
    </style>
    <div class="lux-header">
      {('<img src="data:image/png;base64,' + logo + '"/>') if logo else ''}
      <div><div class="t">{title}</div><div class="s">{subtitle}</div></div>
    </div>
    """, unsafe_allow_html=True)


def gate():
    """Same optional password gate as the quote app (st.secrets['app_password'])."""
    try:
        pw = st.secrets.get("app_password")
    except Exception:
        pw = None   # no secrets file configured -> open (rely on Streamlit private-app viewer list)
    if not pw:
        return True  # no password configured -> open (set app to "private" in Streamlit settings)
    if st.session_state.get("ok"):
        return True
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Enter") and entered == pw:
            st.session_state["ok"] = True
            st.rerun()
    return False
