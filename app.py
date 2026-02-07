# ---------------------------------------------------------
# 1. 필수 설정 및 도구 가져오기 (가장 먼저!)
import os
import sys
import io
import streamlit as st
import pandas as pd
from datetime import datetime
import google.generativeai as genai

# 맥북 한글 깨짐 방지 설정
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LANG"] = "en_US.UTF-8"
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# ---------------------------------------------------------
# 2. 페이지 설정 (무조건 st 명령 중 가장 먼저 나와야 함)
st.set_page_config(layout="wide", page_title="Super AI Agent")

# ---------------------------------------------------------
# 🔒 3. 비밀번호 기능 (문지기)
# 사이드바에 비밀번호 입력창을 만듭니다.
with st.sidebar:
    st.header("🔒 로그인")
    password = st.text_input("비밀번호를 입력하세요", type="password")

# 비밀번호가 틀리면 여기서 멈춥니다! (아래 코드는 실행 안 됨)
# 원하는 비밀번호로 "1234" 부분을 수정하세요.
if password != "1234":
    st.info("비밀번호를 입력해야 AI 선생님을 만날 수 있습니다.")
    st.stop()  # 🛑 여기서 코드 실행 중단!

# ---------------------------------------------------------
# 4. API 키 설정 (로컬/클라우드 자동 호환)
try:
    # secrets.toml(로컬) 또는 Secrets(클라우드)에서 키를 가져옴
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("🚨 API 키를 찾을 수 없습니다. secrets.toml을 확인하세요.")