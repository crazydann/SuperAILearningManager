import streamlit as st
import google.generativeai as genai
import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

# ---------------------------------------------------------
# 1. 초기 설정 및 Google Sheets 연결
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Joshua's AI Learning Manager")

# CSS 로드
if os.path.exists("style.css"):
    with open("style.css") as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# API 키 설정
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("API Key가 설정되지 않았습니다.")
    st.stop()

# [핵심] 구글 시트 연결 함수 (캐싱하여 속도 최적화)
@st.cache_resource
def init_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

# 시트 데이터 가져오기/쓰기 헬퍼 함수들
def get_db_sheet():
    client = init_connection()
    # 시트 이름이 'Joshua_AI_DB'라고 가정 (다르면 수정 필요)
    # [Tip] 에러가 나면 open_by_key("시트ID") 방식을 쓰세요.
    sh = client.open("Joshua_AI_DB") 
    return sh

def get_user_info(user_id):
    """Users 시트에서 특정 유저 정보를 가져옴"""
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    records = ws.get_all_records()
    for record in records:
        if str(record['user_id']) == str(user_id):
            return record
    return None

def update_user_status(user_id, new_status):
    """Users 시트에서 상태(status) 업데이트"""
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    cell = ws.find(user_id)
    # status는 D열(4번째)이라고 가정
    ws.update_cell(cell.row, 4, new_status)
    st.cache_data.clear()

def add_log(user_id, subject, question, answer):
    """Logs 시트에 대화 기록 추가 (답변 길면 자름)"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    timestamp = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    
    # [요청 반영 1] 답변이 20자를 넘으면 자르고 '...' 붙임 (셀이 너무 커지는 것 방지)
    short_answer = answer[:20] + "..." if len(answer) > 20 else answer
    
    ws.append_row([timestamp, user_id, subject, question, short_answer])

def get_logs(user_id=None):
    """Logs 시트에서 기록 가져오기"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    records = ws.get_all_records()
    
    if not records:
        df = pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])
    else:
        df = pd.DataFrame(records)
    
    if 'user_id' not in df.columns:
        return pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])

    if user_id:
        return df[df['user_id'].astype(str) == str(user_id)]
        
    return df

# ---------------------------------------------------------
# 2. 모델 연결
# ---------------------------------------------------------
@st.cache_resource
def load_gemini_model():
    # 복잡하게 찾지 말고, 가장 안정적이고 무료 용량이 큰 모델을 콕 집어서 연결
    return genai.GenerativeModel('gemini-1.5-flash')

# [중요 수정] 함수를 호출해서 실제 model 변수를 만들어야 합니다! (이전 코드에서 누락됨)
model = load_gemini_model()

def get_ai_response(status, subject, question):
    if not model: return "AI 모델 연결 실패"
    
    if status == "studying":
        system_prompt = f"당신은 {subject} 튜터입니다. 공부 질문에만 답하고, 잡담은 단호히 거절하세요."
    else:
        system_prompt = "당신은 친절한 친구입니다. 자유롭게 대화하세요."
        
    try:
        return model.generate_content(f"{system_prompt}\n\n[질문]: {question}").text
    except Exception as e:
        return f"에러: {e}"

# ---------------------------------------------------------
# 3. 로그인 페이지
# ---------------------------------------------------------
def login_page():
    st.markdown("<h1 style='text-align: center;'>🏫 Joshua's AI Learning Manager</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        # [요청 반영 2] MVP 테스트 편의를 위한 계정 정보 노출
        st.info("""
        **[MVP 테스트 계정 정보]**
        * **학생:** joshua, david
        * **부모:** myna5004
        * **비번:** 1234 (또는 오늘 날짜 4자리)
        """)
        
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
                st.error("로그인 실패! 아이디와 비밀번호를 확인하세요.")

# ---------------------------------------------------------
# 4. 학생 페이지
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    current_user_info = get_user_info(user['user_id'])
    status = current_user_info['status']
    
    with st.sidebar:
        st.header(f"🎓 {user['name']}")
        subject = st.radio("과목", ["국어", "영어", "수학", "과학", "기타"])
        
        st.markdown("---")
        st.write(f"**최근 {subject} 기록**")
        logs_df = get_logs(user['user_id'])
        if not logs_df.empty:
            subj_logs = logs_df[logs_df['subject'] == subject].tail(5)
            for idx, row in subj_logs.iloc[::-1].iterrows():
                with st.expander(f"{row['time'][5:16]}"):
                    st.write(f"Q: {row['question']}")
                    st.caption(f"A: {row['answer']}") # 여기는 보여줄 때라 긴 내용 다 보여줌

    col1, col2 = st.columns([8, 2])
    with col1: st.title(f"{subject} 학습 튜터")
    with col2:
        if status == 'studying':
            st.markdown('<div class="status-badge status-study">🔥 공부 시간</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-badge status-break">🍀 쉬는 시간</div>', unsafe_allow_html=True)

    if "messages" not in st.session_state: st.session_state.messages = []
    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if prompt := st.chat_input("질문 입력..."):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.spinner("생각 중..."):
            ai_reply = get_ai_response(status, subject, prompt)
        
        st.chat_message("assistant").markdown(ai_reply)
        st.session_state.messages.append({"role": "assistant", "content": ai_reply})
        
        add_log(user['user_id'], subject, prompt, ai_reply)

# ---------------------------------------------------------
# 5. 학부모 페이지
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 관리 모드 (Google Sheets 연동)")
    
    sh = get_db_sheet()
    users = sh.worksheet("Users").get_all_records()
    student_