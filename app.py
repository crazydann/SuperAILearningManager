import streamlit as st
import google.generativeai as genai
import datetime
import pandas as pd
import os

# ---------------------------------------------------------
# 1. 초기 설정 및 Global State (데이터베이스 대용)
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Super AI Agent")

# CSS 로드
def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

if os.path.exists("style.css"):
    local_css("style.css")

# [핵심] 브라우저 탭 간 데이터 공유를 위한 캐시형 DB
# 실제 서비스에서는 SQL DB를 사용하지만, MVP에서는 이 방식이 가장 효율적입니다.
@st.cache_resource
def get_database():
    return {
        "joshua": {
            "role": "student",
            "name": "Joshua",
            "status": "studying", # studying or break
            # 과목별 대화 기록 저장소
            "history": {"국어": [], "영어": [], "수학": [], "과학": [], "기타": []}
        },
        "david": {
            "role": "student",
            "name": "David",
            "status": "break",
            "history": {"국어": [], "영어": [], "수학": [], "과학": [], "기타": []}
        },
        "myna5004": {
            "role": "parent",
            "name": "부모님"
        }
    }

db = get_database()

# API 키 설정 (secrets.toml 또는 환경변수)
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("API Key가 설정되지 않았습니다.")
    st.stop()

# 모델 로드
# [수정된 코드 시작] ----------------------------------------------------

# 1. 안전하게 사용 가능한 모델 찾기 함수 (이전 MVP 로직 복원)
@st.cache_resource
def load_gemini_model():
    """
    내 API 키로 사용할 수 있는 모델 중 'flash' -> 'gemini-pro' 순서로 찾아서 반환
    """
    try:
        available_models = []
        # 현재 사용 가능한 모델 리스트업
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # 1순위: Flash 모델 찾기 (빠르고 무료 티어에 적합)
        target_model_name = next((m for m in available_models if 'flash' in m), None)
        
        # 2순위: Flash가 없으면 일반 Pro 모델 찾기
        if not target_model_name:
            target_model_name = next((m for m in available_models if 'gemini' in m), None)
            
        if not target_model_name:
            st.error("사용 가능한 Gemini 모델을 찾을 수 없습니다.")
            return None

        # 모델 연결
        return genai.GenerativeModel(target_model_name)

    except Exception as e:
        st.error(f"모델 목록을 가져오는 중 에러 발생: {e}")
        return None

# 2. 모델 로드 실행
model = load_gemini_model()

# [수정된 코드 끝] ------------------------------------------------------

# ---------------------------------------------------------
# 2. AI 응답 생성 로직 (모드에 따른 페르소나 변경)
# ---------------------------------------------------------
def get_ai_response(user_id, subject, question):
    user_data = db[user_id]
    mode = user_data['status']
    
    # 시스템 프롬프트 설계
    if mode == "studying":
        system_prompt = f"""
        당신은 엄격하지만 유능한 {subject} 전담 튜터입니다.
        현재 학생은 '공부 시간' 중입니다.
        
        지침:
        1. 오직 '{subject}' 관련 질문에만 답변하세요.
        2. 학생이 게임, 연예인, 잡담 등 공부와 무관한 이야기를 하면 "지금은 공부 시간입니다. 학습에 집중하세요."라고 단호하게 거절하세요.
        3. 정답을 알려주면서, 헷갈릴 수 있는 개념은 한번 더 짚어주세요.
        """
    else: # break
        system_prompt = f"""
        당신은 학생의 친절한 친구이자 멘토입니다.
        현재 학생은 '쉬는 시간' 중입니다.
        
        지침:
        1. 어떤 주제(게임, 고민, 취미)든 자유롭고 재미있게 대화하세요.
        2. 학생의 스트레스를 풀어주세요.
        3. 너무 길지 않게 친구처럼 대답하세요.
        """
    
    try:
        full_prompt = f"{system_prompt}\n\n[학생 질문]: {question}"
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"AI 연결 오류: {e}"

# ---------------------------------------------------------
# 3. 화면 UI: 로그인 페이지
# ---------------------------------------------------------
def login_page():
    st.markdown("<h1 style='text-align: center;'>Joshua's AI Learning Manager</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.info("오늘의 날짜(4자리, 예: 0208)가 비밀번호입니다.")
        user_id = st.text_input("아이디 (joshua / david / myna5004)")
        password = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            # 비밀번호 로직: 현재 날짜(MMDD)
            today_pw = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%m%d")
            
            if user_id in db and password == today_pw:
                st.session_state['user_id'] = user_id
                st.session_state['role'] = db[user_id]['role']
                st.session_state['logged_in'] = True
                st.rerun()
            elif user_id in db and password == "1234": # 테스트용 백도어
                st.session_state['user_id'] = user_id
                st.session_state['role'] = db[user_id]['role']
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error(f"로그인 실패. (오늘의 비번: {today_pw})")

# ---------------------------------------------------------
# 4. 화면 UI: 학생 페이지
# ---------------------------------------------------------
def student_page():
    user_id = st.session_state['user_id']
    user_data = db[user_id]
    
    # [사이드바] 과목 선택 및 학습 기록
    with st.sidebar:
        st.header(f"🧑‍🎓 {user_data['name']}")
        
        st.markdown("### 📚 과목 선택")
        subject = st.radio("공부할 과목을 선택하세요", ["국어", "영어", "수학", "과학", "기타"])
        
        st.markdown("---")
        st.markdown(f"### 🕒 최근 {subject} 기록")
        # 최근 5개 기록 역순 표시
        recent_logs = user_data['history'][subject][-5:]
        for log in reversed(recent_logs):
            with st.expander(f"{log['time']} - Q"):
                st.write(f"Q: {log['q']}")
                st.caption(f"A: {log['a']}")

    # [메인] 상단 상태바 및 채팅
    col1, col2 = st.columns([8, 2])
    with col1:
        st.title(f"{subject} AI 튜터")
    with col2:
        # 상태 표시 배지
        if user_data['status'] == 'studying':
            st.markdown('<div class="status-badge status-study">🔥 공부 시간</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-badge status-break">🍀 쉬는 시간</div>', unsafe_allow_html=True)

    # 채팅 인터페이스
    # (Streamlit은 리런 시 화면이 초기화되므로, 현재 세션의 대화 내용만 보여줍니다)
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("질문을 입력하세요..."):
        # 유저 메시지 표시
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # AI 응답 생성
        with st.spinner("AI가 생각 중입니다..."):
            ai_reply = get_ai_response(user_id, subject, prompt)
        
        # AI 메시지 표시
        st.chat_message("assistant").markdown(ai_reply)
        st.session_state.messages.append({"role": "assistant", "content": ai_reply})
        
        # DB에 영구 저장 (학부모 확인용)
        timestamp = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%H:%M")
        db[user_id]['history'][subject].append({"time": timestamp, "q": prompt, "a": ai_reply})

# ---------------------------------------------------------
# 5. 화면 UI: 학부모 페이지
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 통합 관리")
    
    # [사이드바] 자녀 선택 및 요약
    with st.sidebar:
        st.header("자녀 선택")
        # 학생 역할인 유저만 필터링
        student_list = [uid for uid, info in db.items() if info['role'] == 'student']
        target_child = st.selectbox("관리할 자녀를 선택하세요", student_list)
        
        child_data = db[target_child]
        
        st.markdown("---")
        st.markdown(f"### {child_data['name']}의 최근 학습")
        # 모든 과목의 기록을 합쳐서 최신순 정렬
        all_logs = []
        for subj, logs in child_data['history'].items():
            for log in logs:
                log['subject'] = subj
                all_logs.append(log)
        
        if all_logs:
            last_log = all_logs[-1]
            st.info(f"마지막 질문 ({last_log['time']}):\n{last_log['q']}")
        else:
            st.caption("아직 학습 기록이 없습니다.")

    # [메인] 자녀 상태 제어 및 상세 히스토리
    child_data = db[target_child]
    
    # 1. 상태 제어 패널
    st.subheader(f"⚙️ {child_data['name']} 상태 설정")
    
    col1, col2, col3 = st.columns([2, 2, 6])
    
    current_status = child_data['status']
    
    with col1:
        st.markdown(f"현재 상태: **{'🔥 공부 중' if current_status == 'studying' else '🍀 쉬는 중'}**")
    
    with col2:
        # 버튼을 누르면 DB 상태가 즉시 변경됨 -> 학생 화면에 반영
        if current_status == 'studying':
            if st.button("쉬는 시간으로 변경"):
                db[target_child]['status'] = 'break'
                st.rerun()
        else:
            if st.button("공부 시간으로 변경", type="primary"):
                db[target_child]['status'] = 'studying'
                st.rerun()

    st.markdown("---")
    
    # 2. 상세 히스토리 (최근 5개 + 스크롤)
    st.subheader("📝 상세 학습 내역")
    
    # 모든 기록을 시간 역순 정렬 (단순화를 위해 리스트 순서대로 뒤집음)
    # 실제로는 datetime 객체로 변환해서 정렬해야 정확함
    sorted_logs = sorted(all_logs, key=lambda x: x['time'], reverse=True)
    
    # 최근 5개만 카드 형태로 보여주고, 나머지는 데이터프레임으로
    top_logs = sorted_logs[:5]
    
    for log in top_logs:
        with st.container():
            st.markdown(f"**[{log['subject']}]** {log['time']}")
            st.text(f"Q: {log['q']}")
            st.caption(f"A: {log['a']}")
            st.divider()
            
    if len(sorted_logs) > 5:
        with st.expander("이전 기록 더보기"):
            df = pd.DataFrame(sorted_logs[5:])
            st.dataframe(df)

# ---------------------------------------------------------
# 6. 메인 실행 라우터
# ---------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    login_page()
else:
    # 로그아웃 버튼 (사이드바 하단)
    with st.sidebar:
        st.markdown("---")
        if st.button("로그아웃"):
            st.session_state['logged_in'] = False
            st.session_state.messages = [] # 대화 내용 초기화
            st.rerun()

    # 역할에 따른 페이지 라우팅
    if st.session_state['role'] == 'student':
        student_page()
    elif st.session_state['role'] == 'parent':
        parent_page()