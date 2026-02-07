import streamlit as st
import google.generativeai as genai

# [마법의 코드]
# 1. 로컬에서 실행할 땐? -> .streamlit/secrets.toml 파일을 찾아서 읽음 (성공!)
# 2. 클라우드에서 실행할 땐? -> 웹사이트에 입력한 Secrets를 찾아서 읽음 (성공!)
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except FileNotFoundError:
    st.error("비밀번호 파일(secrets.toml)을 찾을 수 없습니다.")
    st.stop()

genai.configure(api_key=api_key)
# ... 이후 코드는 그대로 ...
# ---------------------------------------------------------
# [필수] 맥북 한글 에러 방지 (맨 위에 유지)
import os
import sys
import io

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LANG"] = "en_US.UTF-8"
os.environ["LC_ALL"] = "en_US.UTF-8"

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')
# ---------------------------------------------------------

import streamlit as st
import pandas as pd
from datetime import datetime
import google.generativeai as genai

# ---------------------------------------------------------
# 🔑 [중요] 여기에 구글 Gemini API 키를 넣으세요!
api_key = st.secrets["GOOGLE_API_KEY"]
# ---------------------------------------------------------

st.set_page_config(layout="wide", page_title="Super AI Agent (Auto)")

# --- 1. 모델 자동 탐지 로직 (핵심) ---
@st.cache_resource
def get_gemini_model(api_key):
    try:
        genai.configure(api_key=api_key)
        # 구글에 사용 가능한 모델 목록을 요청합니다.
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # 1순위: flash (빠름), 2순위: pro (똑똑함), 3순위: 아무거나
        target_model_name = None
        for name in available_models:
            if 'flash' in name:
                target_model_name = name
                break
        
        if not target_model_name:
            for name in available_models:
                if 'gemini' in name:
                    target_model_name = name
                    break
        
        if not target_model_name:
            return None, "사용 가능한 Gemini 모델을 찾을 수 없습니다."

        model = genai.GenerativeModel(target_model_name)
        return model, target_model_name
        
    except Exception as e:
        return None, f"API 키 에러 또는 연결 실패: {str(e)}"

# 모델 연결 시도
model, model_info = get_gemini_model(api_key)

# --- 2. AI 질문 함수 ---
def ask_gemini(user_text):
    if not model:
        return "모델 연결 실패", "🔴 에러", "시스템", datetime.now().strftime("%H:%M:%S")

    current_time = datetime.now().strftime("%H:%M:%S")
    
    system_instruction = """
    [System Instruction]
    너는 '초중고 학습 집중 도우미 AI'야.
    1. 공부 질문 -> 소크라테스식 질문 [STATUS:🟢 학습 몰입 중] [CATEGORY:학습 질문]
    2. 딴짓 -> 단호하게 거절 [STATUS:🔴 집중 이탈 경고] [CATEGORY:딴짓/이탈]
    3. 인사 -> 공부 유도 [STATUS:🟡 일반 대화] [CATEGORY:일반]
    답변 끝에 [STATUS:...] [CATEGORY:...] 태그를 꼭 붙여줘.
    
    [User Question]
    """
    final_prompt = system_instruction + user_text

    try:
        response = model.generate_content(final_prompt)
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
        return f"응답 생성 에러: {str(e)}", "🔴 에러", "시스템 에러", current_time

# --- 3. UI 구성 ---
if 'chat_history' not in st.session_state: st.session_state.chat_history = []
if 'focus_score' not in st.session_state: st.session_state.focus_score = 50

st.title("🏫 Super AI Agent : 자동 모델 연결")

# 상단에 연결된 모델 정보 표시
if model:
    st.success(f"✅ AI 모델 연결 성공! (사용 중인 모델: `{model_info}`)")
else:
    st.error(f"❌ 연결 실패: {model_info}")

col1, col2 = st.columns([1, 1])

with col1:
    st.header("🧑‍🎓 학생 화면")
    for chat in st.session_state.chat_history:
        with st.chat_message("user"): st.write(chat['user'])
        with st.chat_message("assistant"): st.write(chat['ai'])

    if user_input := st.chat_input("질문하세요..."):
        with st.chat_message("user"): st.write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("AI 선생님 생각 중..."):
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