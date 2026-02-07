import streamlit as st
from groq import Groq
import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import time

# ---------------------------------------------------------
# 1. 초기 설정
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Joshua's AI Learning Manager")

# CSS 로드
if os.path.exists("style.css"):
    with open("style.css") as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# Groq API 키 확인
if "GROQ_API_KEY" not in st.secrets:
    st.error("🚨 Groq API Key가 없습니다. .streamlit/secrets.toml을 확인해주세요.")
    st.stop()

# ---------------------------------------------------------
# 2. Google Sheets 연결 (기존과 동일)
# ---------------------------------------------------------
@st.cache_resource
def init_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    return gspread.authorize(creds)

def get_db_sheet():
    client = init_connection()
    try:
        return client.open("Joshua_AI_DB")
    except gspread.SpreadsheetNotFound:
        st.error("❌ 'Joshua_AI_DB' 시트를 찾을 수 없습니다.")
        st.stop()

# DB 헬퍼 함수들
def get_user_info(user_id):
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    records = ws.get_all_records()
    for record in records:
        if str(record['user_id']) == str(user_id):
            return record
    return None

def update_user_status(user_id, new_status):
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    try:
        cell = ws.find(user_id)
        ws.update_cell(cell.row, 4, new_status)
        st.cache_data.clear()
    except:
        st.error("유저를 찾을 수 없습니다.")

def add_log(user_id, subject, question, answer):
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    timestamp = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    short_answer = answer[:20] + "..." if len(answer) > 20 else answer
    ws.append_row([timestamp, user_id, subject, question, short_answer])

def get_logs(user_id=None):
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    records = ws.get_all_records()
    
    if not records:
        return pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])
    
    df = pd.DataFrame(records)
    if 'user_id' not in df.columns:
        return pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])

    if user_id:
        return df[df['user_id'].astype(str) == str(user_id)]
    return df

# ---------------------------------------------------------
# 3. AI 모델 연결 (Groq 버전) 🚀
# ---------------------------------------------------------
@st.cache_resource
def load_groq_client():
    return Groq(api_key=st.secrets["GROQ_API_KEY"])

client = load_groq_client()

def get_ai_response(status, subject, question):
    if not client: return "AI 클라이언트 연결 실패"
    
    # 1. 시스템 페르소나 설정 (AI의 역할 부여)
    if status == "studying":
        system_content = f"""
        당신은 [Joshua's AI Learning Manager]의 '{subject}' 전담 튜터입니다.
        현재 학생은 '공부 시간'입니다.
        
        지침:
        1. 오직 '{subject}' 관련 질문에만 답변하세요.
        2. 공부와 무관한 질문(게임, 잡담 등)은 "지금은 공부 시간입니다."라고 정중히 거절하세요.
        3. 정답을 바로 주지 말고, 스스로 생각할 수 있게 힌트를 주세요.
        4. 답변은 한국어로 친절하게 해주세요.
        """
    else:
        system_content = f"""
        당신은 [Joshua's AI Learning Manager]의 친절한 친구입니다.
        현재 학생은 '쉬는 시간'입니다. 자유롭고 재미있게 한국어로 대화하세요.
        """
        
    try:
        # 2. Groq에게 질문 던지기 (모델: Llama 3.3 70B - 성능/속도 최강)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": question}
            ],
            temperature=0.6, # 창의성 조절 (0.5~0.7 적당)
            max_tokens=1024, # 답변 최대 길이
            top_p=1,
            stream=False,
            stop=None,
        )
        
        return completion.choices[0].message.content
        
    except Exception as e:
        return f"⚠️ Groq 에러 발생: {e}"

# ---------------------------------------------------------
# 4. UI 및 실행 로직
# ---------------------------------------------------------
def login_page():
    st.markdown("<br><h1 style='text-align: center;'>🏫 Joshua's AI Learning Manager</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.info("테스트 계정: joshua / david / myna5004 (비번: 오늘날짜)")
        user_id = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            user_info = get_user_info(user_id)
            today_pw = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%m%d")
            
            if user_info and (password == today_pw or password == "1234"):
                st.session_state['user'] = user_info
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("로그인 정보가 올바르지 않습니다.")

def student_page():
    user = st.session_state['user']
    current_info = get_user_info(user['user_id'])
    status = current_info['status'] if current_info else user['status']
    
    with st.sidebar:
        st.header(f"🎓 {user['name']}")
        st.markdown(f"Status: **{status}**")
        st.divider()
        subject = st.radio("과목", ["국어", "영어", "수학", "과학", "기타"], label_visibility="collapsed")
        
        st.divider()
        st.caption(f"최근 {subject} 질문")
        logs = get_logs(user['user_id'])
        if not logs.empty:
            my_logs = logs[logs['subject'] == subject].tail(5).iloc[::-1]
            for _, row in my_logs.iterrows():
                t_str = str(row['time'])
                time_only = t_str[11:16] if len(t_str) > 15 else t_str
                with st.expander(f"[{time_only}] {str(row['question'])[:10]}..."):
                    st.write(f"Q: {row['question']}")
                    st.caption(f"A: {row['answer']}")

    col1, col2 = st.columns([8, 2])
    with col1: st.title(f"{subject} 튜터 🤖")
    with col2:
        if status == "studying":
            st.markdown('<div class="status-badge status-study">🔥 공부 시간</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-badge status-break">🍀 쉬는 시간</div>', unsafe_allow_html=True)
            
    if "messages" not in st.session_state: st.session_state.messages = []
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if prompt := st.chat_input("질문을 입력하세요..."):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.spinner("AI 선생님이 생각 중입니다..."):
            response = get_ai_response(status, subject, prompt)
        st.chat_message("assistant").markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
        add_log(user['user_id'], subject, prompt, response)

def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 모드")
    sh = get_db_sheet()
    users = sh.worksheet("Users").get_all_records()
    students = [u for u in users if u['role'] == 'student']
    student_ids = [u['user_id'] for u in students]
    
    with st.sidebar:
        target_id = st.selectbox("자녀 선택", student_ids)
        target_user = next((u for u in students if u['user_id'] == target_id), None)
        st.divider()
        if st.button("로그아웃"):
            st.session_state.clear()
            st.rerun()

    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("상태 제어")
        st.info(f"현재: {target_user['status']}")
        if target_user['status'] == 'studying':
            if st.button("☕️ 쉬는 시간으로 변경", use_container_width=True):
                update_user_status(target_id, 'break')
                st.rerun()
        else:
            if st.button("🔥 공부 시간으로 변경", type="primary", use_container_width=True):
                update_user_status(target_id, 'studying')
                st.rerun()
    with col2:
        st.subheader("학습 로그")
        logs = get_logs(target_id)
        if not logs.empty:
            logs = logs.sort_values(by='time', ascending=False)
            st.dataframe(logs[['time', 'subject', 'question', 'answer']], use_container_width=True, hide_index=True)
        else:
            st.warning("기록 없음")

# ---------------------------------------------------------
# 5. 메인 실행
# ---------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    login_page()
else:
    if st.session_state['user']['role'] == 'student':
        with st.sidebar:
            if st.button("로그아웃"):
                st.session_state.clear()
                st.rerun()
        student_page()
    else:
        parent_page()
