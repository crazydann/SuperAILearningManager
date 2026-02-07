# ---------------------------------------------------------
# 1. 필수 설정 및 도구 가져오기
import os
import sys
import io
import streamlit as st
import pandas as pd
from datetime import datetime
import google.generativeai as genai

# 맥북 한글 깨짐 방지
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LANG"] = "en_US.UTF-8"
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# ---------------------------------------------------------
# 2. 페이지 설정 (가장 먼저!)
st.set_page_config(layout="wide", page_title="Super AI Agent")

# ---------------------------------------------------------
# 🔒 3. 비밀번호 기능 (로그인)
with st.sidebar:
    st.header("🔒 로그인")
    password = st.text_input("비밀번호를 입력하세요", type="password")

# 오늘 날짜를 "260208" 같은 문자로 만듭니다 (%y:년도2자리, %m:월, %d:일)
today_password = datetime.now().strftime("%y%m%d")

if password != today_password:

    st.info("비밀번호를 입력해야 AI 선생님을 만날 수 있습니다.")
    st.stop()  # 여기서 코드 실행 중단

# ---------------------------------------------------------
# 4. API 키 설정
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("🚨 API 키가 없습니다. secrets.toml 파일이나 Streamlit 설정을 확인하세요.")
    st.stop()

# 구글 API 연결
genai.configure(api_key=api_key)

# ---------------------------------------------------------
# 5. 모델 자동 탐지 및 연결
@st.cache_resource
def get_gemini_model():
    try:
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        target_model = next((m for m in available_models if 'flash' in m), None)
        if not target_model:
            target_model = next((m for m in available_models if 'gemini' in m), None)
            
        if not target_model: return None, "모델 없음"
        
        return genai.GenerativeModel(target_model), target_model
    except Exception as e:
        return None, str(e)

model, model_name = get_gemini_model()

# ---------------------------------------------------------
# 6. 채팅 및 UI 구성 (끊겼던 부분 이어짐)

def ask_gemini(user_text):
    if not model: return "모델 연결 실패", "🔴 에러", "시스템", datetime.now().strftime("%H:%M:%S")
    
    current_time = datetime.now().strftime("%H:%M:%S")
    # 여기가 끊겼던 부분입니다. 따옴표를 닫아줍니다.
    system_instruction = """
    [System Instruction]
    너는 '초중고 학습 집중 도우미 AI'야.
    1. 공부 질문 -> 소크라테스식 질문 [STATUS:🟢 학습 몰입 중] [CATEGORY:학습 질문]
    2. 딴짓 -> 단호하게 거절 [STATUS:🔴 집중 이탈 경고] [CATEGORY:딴짓/이탈]
    3. 인사 -> 공부 유도 [STATUS:🟡 일반 대화] [CATEGORY:일반]
    답변 끝에 [STATUS:...] [CATEGORY:...] 태그를 꼭 붙여줘.
    [User Question]
    """
    try:
        response = model.generate_content(system_instruction + user_text)
        full_reply = response.text
        
        if "[STATUS:" in full_reply:
            parts = full_reply.split("[STATUS:")
            ai_reply = parts[0].strip()
            tags = parts[1]
            status = tags.split("]")[0].strip()
            category = tags.split("[CATEGORY:")[1].split("]")[0].strip() if "[CATEGORY:" in tags else "기타"
        else:
            ai_reply, status, category = full_reply, "🟡 일반 대화", "일반"
            
        return ai_reply, status, category, current_time
        
    except Exception as e:
        return f"에러: {e}", "🔴 에러", "시스템", current_time

if 'chat_history' not in st.session_state: st.session_state.chat_history = []
if 'focus_score' not in st.session_state: st.session_state.focus_score = 50

st.title(f"🏫 Super AI Agent (보안 모드)")
if model_name:
    st.caption(f"연결된 모델: {model_name}")

col1, col2 = st.columns([1, 1])

with col1:
    st.header("🧑‍🎓 학생 화면")
    for chat in st.session_state.chat_history:
        with st.chat_message("user"): st.write(chat['user'])
        with st.chat_message("assistant"): st.write(chat['ai'])

    if user_input := st.chat_input("질문하세요..."):
        with st.chat_message("user"): st.write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("생각 중..."):
                reply, status, category, time_stamp = ask_gemini(user_input)
                st.write(reply)
        
        score_chg = 5 if "학습" in status else (-10 if "이탈" in status else 0)
        st.session_state.focus_score = max(0, min(100, st.session_state.focus_score + score_chg))
        st.session_state.chat_history.append({'time': time_stamp, 'user': user_input, 'ai': reply, 'status': status, 'category': category})
        st.rerun()

with col2:
    st.header("👀 학부모 상황실")
    score = st.session_state.focus_score
    st.metric("현재 집중도", f"{score}점")
    st.progress(score / 100)
    
    if st.session_state.chat_history:
        log = st.session_state.chat_history[-1]
        if "이탈" in log['status']: st.error(f"상태: {log['status']}")
        elif "학습" in log['status']: st.success(f"상태: {log['status']}")
        else: st.info(f"상태: {log['status']}")
        
        st.write(f"**최근 활동:** {log['user']}")
        st.divider()
        st.dataframe(pd.DataFrame(st.session_state.chat_history)[['time', 'category', 'status', 'user']], use_container_width=True)