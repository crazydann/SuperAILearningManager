import streamlit as st
from supabase import create_client, Client
from groq import Groq
import pandas as pd
import plotly.express as px
import datetime
import base64
import os

# ---------------------------------------------------------
# 1. 초기 설정 및 UI 스타일 (스크린샷 반영)
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Focus-Super-AI Learning Manager")

st.markdown("""
    <style>
    .status-study { color: white; background-color: #ef4444; padding: 5px 10px; border-radius: 5px; font-weight: bold;}
    .status-break { color: white; background-color: #22c55e; padding: 5px 10px; border-radius: 5px; font-weight: bold;}
    .card { background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. Supabase 및 Groq 연결
# ---------------------------------------------------------
@st.cache_resource
def init_clients():
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    return supabase, groq_client

supabase, groq = init_clients()

# --- DB 헬퍼 함수 (Supabase 버전으로 변경) ---
def get_user_info(user_id):
    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

def update_user_status(user_id, new_status):
    supabase.table("users").update({"status": new_status}).eq("user_id", user_id).execute()

def add_log(user_id, subject, question, answer, img_url=None, log_type="Text"):
    supabase.table("logs").insert({
        "user_id": user_id, "subject": subject, 
        "question": question, "answer": answer,
        "image_url": img_url, "log_type": log_type
    }).execute()

def get_logs(user_id):
    res = supabase.table("logs").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

# ---------------------------------------------------------
# 3. AI 모델 로직 (기존 MVP 완벽 반영 + Vision 추가)
# ---------------------------------------------------------
def get_text_response(status, subject, question):
    """기존 MVP의 페르소나 텍스트 튜터"""
    if status == "studying":
        system_content = f"당신은 '{subject}' 전담 튜터입니다. 공부 무관 질문은 거절하고, 스스로 생각하게 힌트를 주세요."
    else:
        system_content = "당신은 친절한 친구입니다. 쉬는 시간이니 자유롭고 재미있게 대화하세요."
        
    completion = groq.chat.completions.create(
        model="llama-3.3-70b-versatile", # 기존 속도/성능 최강 모델 유지
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": question}
        ],
        temperature=0.6, max_tokens=1024
    )
    return completion.choices[0].message.content

def analyze_vision_response(image_file, subject):
    """새로 추가된 사진 분석 튜터"""
    img_b64 = base64.b64encode(image_file.getvalue()).decode()
    prompt = f"이 {subject} 문제 풀이를 분석해서 틀린 부분을 찾아 힌트를 주고, 정답률을 %로 알려줘."
    completion = groq.chat.completions.create(
        model="llama-3.2-11b-vision-preview", # Vision 전용 무료 모델
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ]}],
        temperature=0.5
    )
    return completion.choices[0].message.content

# ---------------------------------------------------------
# 4. 학생 화면 (스크린샷 2번 구조)
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    current_info = get_user_info(user['user_id'])
    status = current_info['status']
    
    # 상단 헤더 (타이머 및 과목 선택)
    t1, t2, t3 = st.columns([2, 6, 2])
    with t1: st.title("00:45:12 ⏱️")
    with t3: subject = st.selectbox("과목", ["국어", "영어", "수학", "과학", "기타"], label_visibility="collapsed")
    st.divider()

    # 좌/중/우 3단 레이아웃
    left_col, center_col, right_col = st.columns([2, 5, 3])

    with left_col:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.caption("📈 질문 및 응답 수")
        st.bar_chart({"국":3, "영":7, "수":12, "과":4})
        st.divider()
        st.caption(f"최근 {subject} 질의 (기존 MVP 기능)")
        logs = get_logs(user['user_id'])
        if not logs.empty:
            for _, row in logs[logs['subject'] == subject].head(3).iterrows():
                with st.expander(f"Q: {str(row['question'])[:15]}..."):
                    st.write(row['answer'])
        st.markdown("</div>", unsafe_allow_html=True)

    with center_col:
        if status == "studying": st.markdown('<div class="status-study">🔥 현재 집중 학습 중</div>', unsafe_allow_html=True)
        else: st.markdown('<div class="status-break">🍀 즐거운 쉬는 시간</div>', unsafe_allow_html=True)
        
        # 채팅 UI
        if "messages" not in st.session_state: st.session_state.messages = []
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if prompt := st.chat_input("학습 관련 질문을 입력하세요..."):
            st.chat_message("user").markdown(prompt)
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.spinner("AI 선생님이 생각 중입니다..."):
                response = get_text_response(status, subject, prompt) # 텍스트 AI 호출
            st.chat_message("assistant").markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
            add_log(user['user_id'], subject, prompt, response)

    with right_col:
        st.markdown("<div class='card' style='text-align:center;'>", unsafe_allow_html=True)
        st.info("📷 문제 사진을 올려주세요\n풀이 과정을 AI가 채점해드려요!")
        uploaded_file = st.file_uploader("", type=['jpg', 'png'])
        if uploaded_file:
            st.image(uploaded_file, use_container_width=True)
            if st.button("사진 분석 시작", use_container_width=True):
                with st.spinner("이미지 분석 중..."):
                    # 1. 스토리지 업로드
                    file_path = f"{user['user_id']}/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    supabase.storage.from_("problem_images").upload(file_path, uploaded_file.getvalue())
                    img_url = supabase.storage.from_("problem_images").get_public_url(file_path)
                    
                    # 2. 비전 AI 호출
                    analysis = analyze_vision_response(uploaded_file, subject)
                    st.success("채점 완료!")
                    st.write(analysis)
                    add_log(user['user_id'], subject, "사진 업로드 분석", analysis, img_url, "Vision")
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# 5. 학부모 화면 (스크린샷 1번 구조 + 기존 통제 로직)
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 모니터링 대시보드")
    
    # 1. 상단: 학생 상태 제어 (기존 MVP의 핵심 기능)
    res = supabase.table("users").select("*").eq("role", "student").execute()
    students = res.data if res.data else []
    
    if students:
        target_id = st.selectbox("자녀 선택", [u['user_id'] for u in students])
        target_user = next(u for u in students if u['user_id'] == target_id)
        
        col_ctrl1, col_ctrl2 = st.columns([2, 8])
        with col_ctrl1:
            st.info(f"현재 상태: {target_user['status']}")
            if target_user['status'] == 'studying':
                if st.button("☕️ 쉬는 시간으로 변경"): update_user_status(target_id, 'break'); st.rerun()
            else:
                if st.button("🔥 공부 시간으로 변경"): update_user_status(target_id, 'studying'); st.rerun()
                
        # 2. 하단: 통계 차트 (스크린샷 반영)
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("오늘 공부 시간", "6h", "추천 목표 달성")
        m2.metric("질문 수", "74건")
        m3.metric("평균 정답률", "78%")
        
        st.subheader("📅 요일별 공부 시간")
        day_df = pd.DataFrame({'요일': ['월','화','수','목','금','토','일'], '시간': [40, 65, 35, 70, 55, 85, 25]})
        st.plotly_chart(px.bar(day_df, x='요일', y='시간', color_discrete_sequence=['#3b82f6']), use_container_width=True)

# ---------------------------------------------------------
# 6. 메인 실행 (기존 로그인 로직 유지)
# ---------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    st.markdown("<br><h1 style='text-align: center;'>🏫 Focus-Super-AI Login</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        user_id = st.text_input("아이디 (joshua / parent_joshua)")
        password = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            user_info = get_user_info(user_id)
            today_pw = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%m%d")
            
            # 기존 MVP의 비번 로직 (날짜 or 1234)
            if user_info and (password == today_pw or password == "1234"):
                st.session_state['user'] = user_info
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("로그인 정보가 올바르지 않습니다.")
else:
    with st.sidebar:
        if st.button("로그아웃"):
            st.session_state.clear()
            st.rerun()
            
    if st.session_state['user']['role'] == 'student':
        student_page()
    else:
        parent_page()