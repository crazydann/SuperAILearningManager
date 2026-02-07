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
    st.error("API Key가 설정되지 않았습니다. .streamlit/secrets.toml 파일을 확인해주세요.")
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
    # [Tip] 시트 이름으로 찾기 (에러나면 open_by_key 사용 권장)
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
    st.cache_data.clear() # 캐시 초기화하여 즉시 반영

def add_log(user_id, subject, question, answer):
    """Logs 시트에 대화 기록 추가 (답변 길면 자름)"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    timestamp = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    
    # [요청 반영 1] 답변이 20자를 넘으면 자르고 '...' 붙임
    short_answer = answer[:20] + "..." if len(answer) > 20 else answer
    
    ws.append_row([timestamp, user_id, subject, question, short_answer])

def get_logs(user_id=None):
    """Logs 시트에서 기록 가져오기"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    records = ws.get_all_records()
    
    # 데이터가 없을 경우 빈 프레임 반환 (에러 방지)
    if not records:
        df = pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])
    else:
        df = pd.DataFrame(records)
    
    # 컬럼 헤더가 잘못되었을 경우 방어 로직
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
    # 무료 한도가 넉넉한 1.5 Flash 모델로 고정
    return genai.GenerativeModel('gemini-1.5-flash')

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
# 3. 로그인 페이지 UI
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
# 4. 학생 페이지 UI
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    # 실시간 상태 확인을 위해 DB 재조회
    current_user_info = get_user_info(user['user_id'])
    status = current_user_info['status']
    
    with st.sidebar:
        st.header(f"🎓 {user['name']}")
        subject = st.radio("과목", ["국어", "영어", "수학", "과학", "기타"])
        
        st.markdown("---")
        st.write(f"**최근 {subject} 기록**")
        logs_df = get_logs(user['user_id'])
        if not logs_df.empty:
            # 해당 과목 로그만 필터링
            subj_logs = logs_df[logs_df['subject'] == subject].tail(5)
            for idx, row in subj_logs.iloc[::-1].iterrows():
                # 시간 포맷 안전 처리
                time_str = str(row['time'])
                display_time = time_str[5:16] if len(time_str) > 10 else time_str
                
                with st.expander(f"{display_time}"):
                    st.write(f"Q: {row['question']}")
                    st.caption(f"A: {row['answer']}") 

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
# 5. 학부모 페이지 UI
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 관리 모드 (Google Sheets)")
    
    sh = get_db_sheet()
    users = sh.worksheet("Users").get_all_records()
    student_list = [u['user_id'] for u in users if u['role'] == 'student']
    
    with st.sidebar:
        st.header("자녀 선택")
        target_id = st.selectbox("관리할 자녀", student_list)
        target_child = next((u for u in users if u['user_id'] == target_id), None)
        
        if target_child:
            st.info(f"현재 상태: {target_child['status']}")

    st.subheader(f"{target_child['name']} 상태 관리")
    col1, col2 = st.columns([2, 8])
    with col1:
        if target_child['status'] == 'studying':
            if st.button("쉬는 시간으로 변경"):
                update_user_status(target_id, 'break')
                st.success("변경 완료! (잠시 후 반영됩니다)")
                st.rerun()
        else:
            if st.button("공부 시간으로 변경", type="primary"):
                update_user_status(target_id, 'studying')
                st.success("변경 완료! (잠시 후 반영됩니다)")
                st.rerun()
    
    st.markdown("---")
    st.subheader("📝 전체 학습 로그 (실시간)")
    
    logs_df = get_logs(target_id)
    if not logs_df.empty:
        # 시간 역순 정렬
        logs_df = logs_df.sort_values(by='time', ascending=False)
        st.dataframe(logs_df[['time', 'subject', 'question', 'answer']], use_container_width=True)
    else:
        st.caption("아직 기록이 없습니다.")

# ---------------------------------------------------------
# 6. 메인 실행 라우터 (이 부분이 빠져서 화면이 안 나왔던 것!)
# ---------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    login_page()
else:
    # 로그인 상태일 때 사이드바에 로그아웃 버튼 표시
    with st.sidebar:
        st.markdown("---")
        if st.button("로그아웃"):
            st.session_state.clear()
            st.rerun()
            
    # 역할에 따라 페이지 분기
    if st.session_state['user']['role'] == 'student':
        student_page()
    else:
        parent_page()