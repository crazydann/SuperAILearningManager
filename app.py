import streamlit as st
import google.generativeai as genai
import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import time

# ---------------------------------------------------------
# 1. 초기 설정 및 기본 구성
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Joshua's AI Learning Manager")

# CSS 로드
if os.path.exists("style.css"):
    with open("style.css") as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# API 키 설정 확인
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("🚨 API Key가 설정되지 않았습니다. .streamlit/secrets.toml 파일을 확인해주세요.")
    st.stop()

# ---------------------------------------------------------
# 2. Google Sheets 데이터베이스 연결
# ---------------------------------------------------------
@st.cache_resource
def init_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

def get_db_sheet():
    client = init_connection()
    try:
        # 시트 이름으로 열기
        return client.open("Joshua_AI_DB")
    except gspread.SpreadsheetNotFound:
        st.error("❌ 'Joshua_AI_DB' 시트를 찾을 수 없습니다. 서비스 계정을 시트에 초대했는지 확인하세요.")
        st.stop()

# DB 헬퍼 함수들
def get_user_info(user_id):
    """Users 시트에서 유저 정보 조회"""
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    records = ws.get_all_records()
    for record in records:
        if str(record['user_id']) == str(user_id):
            return record
    return None

def update_user_status(user_id, new_status):
    """학부모가 상태 변경 시 호출"""
    sh = get_db_sheet()
    ws = sh.worksheet("Users")
    try:
        cell = ws.find(user_id)
        # D열(4번째)이 status라고 가정
        ws.update_cell(cell.row, 4, new_status)
        st.cache_data.clear() # 캐시 초기화 (즉시 반영 위함)
    except:
        st.error("유저를 찾을 수 없습니다.")

def add_log(user_id, subject, question, answer):
    """대화 로그 저장 (답변 20자 제한)"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    timestamp = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    
    # [요청 반영] 답변이 길면 20자로 자르고 '...' 추가
    short_answer = answer[:20] + "..." if len(answer) > 20 else answer
    
    ws.append_row([timestamp, user_id, subject, question, short_answer])

def get_logs(user_id=None):
    """로그 조회 (빈 시트 에러 방지 포함)"""
    sh = get_db_sheet()
    ws = sh.worksheet("Logs")
    records = ws.get_all_records()
    
    # 데이터가 없거나 헤더만 있는 경우 방어 로직
    if not records:
        return pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])
    
    df = pd.DataFrame(records)
    
    # 필수 컬럼이 없는 경우(시트 생성 직후) 방어
    if 'user_id' not in df.columns:
        return pd.DataFrame(columns=['time', 'user_id', 'subject', 'question', 'answer'])

    if user_id:
        return df[df['user_id'].astype(str) == str(user_id)]
        
    return df

# ---------------------------------------------------------
# 3. AI 모델 연결 (여기가 수정된 핵심 부분!)
# ---------------------------------------------------------
@st.cache_resource
def load_gemini_model():
    """
    무료 사용량이 넉넉한 1.5 Flash 모델만 강제로 찾아서 연결합니다.
    (하루 20회 제한인 2.5 버전이나 실험용 버전은 절대 연결하지 않음)
    """
    try:
        # 1. 내 키로 접근 가능한 모든 모델 리스트업
        all_models = [m.name for m in genai.list_models()]
        
        target_model_name = None
        
        # 2. 필터링 로직: 'flash'와 '1.5'가 들어간 모델만 찾음
        # 예: models/gemini-1.5-flash-001, models/gemini-1.5-flash
        candidates = []
        for m in all_models:
            # 2.5 버전이나 실험용(experimental)은 무조건 제외 (중요!)
            if '2.5' in m or 'experimental' in m:
                continue
            
            # 1.5 버전이고 flash인 경우만 후보에 등록
            if '1.5' in m and 'flash' in m:
                candidates.append(m)
        
        # 3. 후보 중 가장 짧은 이름(표준 이름)을 선호
        if candidates:
            target_model_name = sorted(candidates, key=len)[0]
            
        # 4. 만약 1.5 Flash가 없으면 1.0 Pro라도 찾음 (비상용)
        if not target_model_name:
             target_model_name = next((m for m in all_models if 'gemini-1.0-pro' in m), None)

        if target_model_name:
            # 최종 연결
            return genai.GenerativeModel(target_model_name)
        else:
            st.error("사용 가능한 1.5 Flash 모델을 찾을 수 없습니다. API 키 권한을 확인해주세요.")
            return None
            
    except Exception as e:
        st.error(f"모델 연결 실패: {e}")
        return None

# 모델 로드 실행
model = load_gemini_model()

def get_ai_response(status, subject, question):
    if not model: return "AI 모델이 연결되지 않았습니다."
    
    # 페르소나 설정
    if status == "studying":
        system_prompt = f"""
        당신은 [Joshua's AI Learning Manager]의 '{subject}' 전담 튜터입니다.
        현재 학생은 '공부 시간' 중입니다.
        
        [행동 지침]
        1. 오직 '{subject}' 교과 내용과 관련된 질문에만 답변하세요.
        2. 학생이 게임, 연예인, 가십 등 공부와 무관한 이야기를 하면 "지금은 공부 시간입니다. 학습에 집중해주세요."라고 단호하게 거절하세요.
        3. 정답을 바로 알려주기보다, 힌트를 주고 유도 질문을 던지세요.
        """
    else:
        system_prompt = f"""
        당신은 [Joshua's AI Learning Manager]의 친절한 친구입니다.
        현재 학생은 '쉬는 시간' 중입니다.
        
        [행동 지침]
        1. 학생과 자유롭고 재미있게 대화하세요.
        2. 공감해주고 격려해주세요.
        """
        
    try:
        response = model.generate_content(f"{system_prompt}\n\n[학생 질문]: {question}")
        return response.text
    except Exception as e:
        return f"AI 응답 오류: {e}"

# ---------------------------------------------------------
# 4. 페이지 UI: 로그인
# ---------------------------------------------------------
def login_page():
    st.markdown("<br><br><h1 style='text-align: center;'>🏫 Joshua's AI Learning Manager</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.info("""
        **[테스트 계정 정보]**
        - 학생: `joshua`, `david`
        - 부모: `myna5004`
        - 비번: 오늘날짜
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
                st.error("아이디 또는 비밀번호가 틀렸습니다.")

# ---------------------------------------------------------
# 5. 페이지 UI: 학생 (Joshua, David)
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    # 실시간 상태 확인 (부모가 변경했을 수 있으므로)
    current_info = get_user_info(user['user_id'])
    status = current_info['status'] if current_info else user['status']
    
    with st.sidebar:
        st.header(f"🎓 {user['name']}")
        st.markdown(f"Status: **{status}**")
        st.divider()
        
        st.subheader("과목 선택")
        subject = st.radio("Subject", ["국어", "영어", "수학", "과학", "기타"], label_visibility="collapsed")
        
        st.divider()
        st.caption(f"최근 {subject} 질문")
        logs = get_logs(user['user_id'])
        if not logs.empty:
            # 해당 과목 & 최신순 5개
            my_logs = logs[logs['subject'] == subject].tail(5).iloc[::-1]
            for _, row in my_logs.iterrows():
                # 시간 깔끔하게 (시:분)
                t_str = str(row['time'])
                time_only = t_str[11:16] if len(t_str) > 15 else t_str
                with st.expander(f"[{time_only}] {row['question'][:10]}..."):
                    st.write(f"Q: {row['question']}")
                    st.caption(f"A: {row['answer']}") # 여기는 전체 내용 보여줘도 됨 (읽기용이니까)

    # 메인 화면
    col1, col2 = st.columns([8, 2])
    with col1:
        st.title(f"{subject} 튜터 🤖")
    with col2:
        if status == "studying":
            st.markdown('<div class="status-badge status-study">🔥 공부 시간</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-badge status-break">🍀 쉬는 시간</div>', unsafe_allow_html=True)
            
    # 채팅 인터페이스
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("질문을 입력하세요..."):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.spinner("AI 선생님이 생각 중입니다..."):
            response = get_ai_response(status, subject, prompt)
        
        st.chat_message("assistant").markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
        
        # 로그 저장 (답변은 함수 내부에서 20자로 잘림)
        add_log(user['user_id'], subject, prompt, response)

# ---------------------------------------------------------
# 6. 페이지 UI: 부모님 (Myna5004)
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 관리 대시보드")
    st.info("실시간으로 자녀의 학습 상태를 제어하고 기록을 확인합니다.")
    
    sh = get_db_sheet()
    users = sh.worksheet("Users").get_all_records()
    students = [u for u in users if u['role'] == 'student']
    student_ids = [u['user_id'] for u in students]
    
    with st.sidebar:
        st.header("자녀 선택")
        target_id = st.selectbox("학생", student_ids)
        target_user = next((u for u in students if u['user_id'] == target_id), None)
        
        st.divider()
        if st.button("로그아웃"):
            st.session_state.clear()
            st.rerun()

    # 메인 제어 패널
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("상태 제어")
        st.write(f"현재 상태: **{target_user['status']}**")
        
        if target_user['status'] == 'studying':
            if st.button("☕️ 쉬는 시간으로 변경", use_container_width=True):
                update_user_status(target_id, 'break')
                st.success("변경되었습니다!")
                time.sleep(1)
                st.rerun()
        else:
            if st.button("🔥 공부 시간으로 변경", type="primary", use_container_width=True):
                update_user_status(target_id, 'studying')
                st.success("변경되었습니다!")
                time.sleep(1)
                st.rerun()
                
    with col2:
        st.subheader("실시간 학습 로그")
        logs = get_logs(target_id)
        if not logs.empty:
            # 최신순 정렬
            logs = logs.sort_values(by='time', ascending=False)
            st.dataframe(
                logs[['time', 'subject', 'question', 'answer']], 
                use_container_width=True,
                hide_index=True
            )
        else:
            st.warning("아직 학습 기록이 없습니다.")

# ---------------------------------------------------------
# 7. 메인 라우터 (앱 실행 진입점)
# ---------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    login_page()
else:
    # 학생/부모 분기
    if st.session_state['user']['role'] == 'student':
        # 학생은 사이드바에 로그아웃 버튼을 따로 둠
        with st.sidebar:
            if st.button("로그아웃"):
                st.session_state.clear()
                st.rerun()
        student_page()
    else:
        parent_page()