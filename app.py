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
    sh = client.open("Joshua_AI_DB")
    return sh

def get_user_info(user_id):
    """Users 시트에서 특정 유저 정보를 가져옴"""
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    records = ws.get_all_records() # 리스트 형태의 딕셔너리 반환
    for record in records:
        if str(record['user_id']) == str(user_id):
            return record
    return None

def update_user_status(user_id, new_status):
    """Users 시트에서 상태(status) 업데이트"""
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    cell = ws.find(user_id) # user_id가 있는 셀 찾기
    # status는 D열(4번째)이라고 가정 (A:id, B:name, C:role, D:status)
    ws.update_cell(cell.row, 4, new_status)
    st.cache_data.clear() # 데이터 갱신을 위해 캐시 초기화

def add_log(user_id, subject, question, answer):
    """Logs 시트에 대화 기록 추가"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    timestamp = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([timestamp, user_id, subject, question, answer])

# [수정된 get_logs 함수]
def get_logs(user_id=None):
    """Logs 시트에서 기록 가져오기 (데이터가 없을 때 에러 방지 포함)"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    records = ws.get_all_records()
    
    # [핵심 수정] 기록이 하나도 없으면 빈 데이터프레임에 컬럼명만 강제로 지정
    if not records:
        df = pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])
    else:
        df = pd.DataFrame(records)
    
    # 만약 데이터는 있는데 'user_id' 컬럼이 없는 경우(헤더 오타 등) 방어 로직
    if 'user_id' not in df.columns:
        # 헤더가 잘못되었을 가능성이 높으므로 일단 빈 DF 반환하거나 에러 방지
        return pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])

    if user_id:
        # 숫자/문자 형식이 다를 수 있어 문자열로 변환 후 비교
        return df[df['user_id'].astype(str) == str(user_id)]
        
    return df

# ---------------------------------------------------------
# 2. 모델 연결 (이전과 동일)
# ---------------------------------------------------------
@st.cache_resource
def load_gemini_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        model_name = next((m for m in available_models if 'flash' in m), 
                          next((m for m in available_models if 'gemini' in m), None))
        return genai.GenerativeModel(model_name) if model_name else None
    except: return None

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
        user_id = st.text_input("아이디")
        password = st.text_input("비밀번호 (오늘 날짜 4자리)", type="password")
        if st.button("로그인", use_container_width=True):
            user_info = get_user_info(user_id)
            today_pw = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%m%d")
            
            # DB에 유저가 있고, 비밀번호가 맞으면 (테스트용 '1234' 포함)
            if user_info and (password == today_pw or password == "1234"):
                st.session_state['user'] = user_info
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("로그인 정보가 올바르지 않습니다.")

# ---------------------------------------------------------
# 4. 학생 페이지
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    # 최신 상태를 DB에서 다시 가져옴 (부모가 바꿨을 수 있으므로)
    current_user_info = get_user_info(user['user_id'])
    status = current_user_info['status']
    
    with st.sidebar:
        st.header(f"🎓 {user['name']}")
        subject = st.radio("과목", ["국어", "영어", "수학", "과학", "기타"])
        
        st.markdown("---")
        st.write(f"**최근 {subject} 기록**")
        # 구글 시트에서 로그 가져오기
        logs_df = get_logs(user['user_id'])
        if not logs_df.empty:
            subj_logs = logs_df[logs_df['subject'] == subject].tail(5)
            # 최신순 정렬을 위해 역순 출력
            for idx, row in subj_logs.iloc[::-1].iterrows():
                with st.expander(f"{row['time'][5:16]}"):
                    st.write(f"Q: {row['question']}")
                    st.caption(f"A: {row['answer']}")

    col1, col2 = st.columns([8, 2])
    with col1: st.title(f"{subject} 학습 튜터")
    with col2:
        if status == 'studying':
            st.markdown('<div class="status-badge status-study">🔥 공부 시간</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-badge status-break">🍀 쉬는 시간</div>', unsafe_allow_html=True)

    # 채팅 UI
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
        
        # [중요] 구글 시트에 저장
        add_log(user['user_id'], subject, prompt, ai_reply)

# ---------------------------------------------------------
# 5. 학부모 페이지
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 관리 모드 (Google Sheets 연동)")
    
    # DB에서 학생 목록 가져오기 (Users 시트 전체 조회)
    sh = get_db_sheet()
    users = sh.worksheet("Users").get_all_records()
    student_list = [u['user_id'] for u in users if u['role'] == 'student']
    
    with st.sidebar:
        target_id = st.selectbox("자녀 선택", student_list)
        # 선택된 자녀 정보 찾기
        target_child = next((u for u in users if u['user_id'] == target_id), None)
        
        if target_child:
            st.info(f"현재 상태: {target_child['status']}")

    # 상태 변경 UI
    st.subheader(f"{target_child['name']} 상태 관리")
    col1, col2 = st.columns([2, 8])
    with col1:
        if target_child['status'] == 'studying':
            if st.button("쉬는 시간으로 변경"):
                update_user_status(target_id, 'break')
                st.success("변경 완료! (약 3초 후 반영)")
                st.rerun()
        else:
            if st.button("공부 시간으로 변경", type="primary"):
                update_user_status(target_id, 'studying')
                st.success("변경 완료! (약 3초 후 반영)")
                st.rerun()
    
    st.markdown("---")
    st.subheader("📝 전체 학습 로그 (실시간)")
    
    # 로그 시트 가져오기
    logs_df = get_logs(target_id)
    if not logs_df.empty:
        # 최신순 정렬
        logs_df = logs_df.sort_values(by='time', ascending=False)
        st.dataframe(logs_df[['time', 'subject', 'question', 'answer']], use_container_width=True)
    else:
        st.caption("기록이 없습니다.")

# ---------------------------------------------------------
# 실행 라우터
# ---------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    login_page()
else:
    with st.sidebar:
        if st.button("로그아웃"):
            st.session_state.clear()
            st.rerun()
            
    if st.session_state['user']['role'] == 'student':
        student_page()
    else:
        parent_page()