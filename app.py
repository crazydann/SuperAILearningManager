import streamlit as st
from supabase import create_client, Client
from groq import Groq
import pandas as pd
import plotly.express as px
import datetime
import base64
import json
import io
from PIL import Image

import fitz  # PyMuPDF
from pillow_heif import register_heif_opener
register_heif_opener()

# ---------------------------------------------------------
# 1. 초기 설정 및 UI 스타일
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Focus-Super-AI Learning Manager")

st.markdown("""
    <style>
    .status-study { color: white; background-color: #ef4444; padding: 5px 10px; border-radius: 5px; font-weight: bold; text-align: center; }
    .status-break { color: white; background-color: #22c55e; padding: 5px 10px; border-radius: 5px; font-weight: bold; text-align: center; }
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

# --- DB 헬퍼 함수 ---
def get_user_info(user_id):
    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

def update_user_status(user_id, status_key, new_value):
    """상태(studying/break) 또는 권한(detail_permission) 업데이트"""
    supabase.table("users").update({status_key: new_value}).eq("user_id", user_id).execute()

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
# 3. AI 모델 로직 (과목 자동 분류 및 JSON 채점)
# ---------------------------------------------------------
def classify_subject(text):
    """질문을 보고 자동으로 과목을 파악합니다 [Req 1]"""
    prompt = f"다음 질문이나 내용을 보고 '국어', '영어', '수학', '과학', '기타' 중 딱 하나의 단어로만 대답해:\n\n{text}"
    completion = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1, max_tokens=10
    )
    res = completion.choices[0].message.content.strip()
    for sub in ["국어", "영어", "수학", "과학"]:
        if sub in res: return sub
    return "기타"

def get_text_response(status, subject, question):
    system_content = f"당신은 '{subject}' 전담 튜터입니다." if status == "studying" else "당신은 친절한 친구입니다."
    completion = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": system_content}, {"role": "user", "content": question}],
        temperature=0.6, max_tokens=1024
    )
    return completion.choices[0].message.content

def analyze_vision_json(b64_encoded_jpeg):
    """사진 분석 후 정답/오답, 해설, 핵심 개념을 JSON 구조로 반환합니다 [Req 3]"""
    prompt = """
    이 문제 풀이 사진을 분석해서 반드시 아래 JSON 형식으로만 응답해. 마크다운 없이 순수 JSON만 출력해:
    {
        "is_correct": true/false (정답 여부),
        "status_text": "정답입니다! / 아쉽지만 오답입니다.",
        "detailed_explanation": "학생의 풀이에서 틀린 부분에 대한 상세 해설",
        "core_concept": "이 문제의 핵심 학습 개념"
    }
    """
    completion = groq.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct", 
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_encoded_jpeg}"}}
        ]}],
        temperature=0.1, max_tokens=1024, response_format={"type": "json_object"}
    )
    return json.loads(completion.choices[0].message.content)

def generate_and_grade_similar(core_concept, count):
    """유사 문제를 생성하고 즉석에서 채점할 수 있는 텍스트를 제공합니다"""
    prompt = f"핵심 개념 '{core_concept}'에 대한 객관식 또는 단답형 문제 {count}개를 내줘. 문제 아래에 바로 정답도 알려줘."
    completion = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content

def get_standardized_image(uploaded_file):
    file_ext = uploaded_file.name.split('.')[-1].lower()
    if file_ext == 'pdf':
        pdf_document = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        pix = pdf_document.load_page(0).get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    else:
        img = Image.open(uploaded_file)
        if img.mode != 'RGB': img = img.convert('RGB')
    return img

# ---------------------------------------------------------
# 4. 팝업(Dialog) UI 설계 [Req 3]
# ---------------------------------------------------------
@st.dialog("📝 AI 유사 문제 풀이")
def similar_problem_dialog(concept, count, user_id, subject):
    st.write(f"**{concept}** 개념을 복습하기 위한 {count}개의 문제입니다.")
    with st.spinner("문제 생성 중..."):
        problems = generate_and_grade_similar(concept, count)
        st.info(problems)
        add_log(user_id, subject, f"유사 문제 {count}개 요청 ({concept})", problems, log_type="Similar_Task")

@st.dialog("🎯 채점 결과")
def grading_dialog(analysis_data, user_id, subject, img_url):
    st.image(st.session_state.current_img_obj, width=300)
    
    # 1. 정답/오답 심플 표기
    if analysis_data['is_correct']:
        st.success(f"✅ {analysis_data['status_text']}")
    else:
        st.error(f"❌ {analysis_data['status_text']}")

    # 2. 자세히 보기 권한 체크 및 노출
    user_info = get_user_info(user_id)
    has_permission = user_info.get('detail_permission', False)

    if has_permission:
        with st.expander("🔍 풀이 해설 자세히 보기 (권한 활성화 됨)"):
            st.write(analysis_data['detailed_explanation'])
    else:
        st.warning("🔒 해설 자세히 보기 (학부모 권한 필요 - 대시보드에서 허용해주세요)")

    # 3. 오답일 경우 유사 문제 풀기 트리거
    if not analysis_data['is_correct']:
        st.divider()
        st.write("💡 이 개념을 완벽하게 익혀볼까요?")
        c1, c2 = st.columns(2)
        if c1.button("유사 문제 1개 풀기"):
            similar_problem_dialog(analysis_data['core_concept'], 1, user_id, subject)
        if c2.button("유사 문제 3개 풀기"):
            similar_problem_dialog(analysis_data['core_concept'], 3, user_id, subject)

# ---------------------------------------------------------
# 5. 학생 화면
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    current_info = get_user_info(user['user_id'])
    status = current_info['status'] if current_info else 'studying'
    
    t1, t3 = st.columns([8, 2])
    with t1: st.title("00:45:12 ⏱️")
    st.divider()

    left_col, center_col, right_col = st.columns([2, 5, 3])

    with left_col:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.caption("📈 누적 학습 로그 [Req 2, 4]")
        logs = get_logs(user['user_id'])
        if not logs.empty:
            # DB에 저장된 과목 정보를 기반으로 통계 표시
            sub_counts = logs['subject'].value_counts()
            st.bar_chart(sub_counts)
            st.divider()
            for _, row in logs.head(3).iterrows():
                with st.expander(f"[{row['subject']}] {str(row['question'])[:10]}..."):
                    st.write(row['answer'])
        st.markdown("</div>", unsafe_allow_html=True)

    with center_col:
        if status == "studying": st.markdown('<div class="status-study">🔥 현재 집중 학습 중</div><br>', unsafe_allow_html=True)
        else: st.markdown('<div class="status-break">🍀 즐거운 쉬는 시간</div><br>', unsafe_allow_html=True)
        
        if "messages" not in st.session_state: st.session_state.messages = []
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if prompt := st.chat_input("질문을 입력하세요. AI가 과목을 자동 파악합니다!"):
            st.chat_message("user").markdown(prompt)
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            with st.spinner("AI가 과목을 파악하고 답변을 준비 중입니다..."):
                auto_subject = classify_subject(prompt) # 과목 자동 분류 [Req 1]
                response = get_text_response(status, auto_subject, prompt)
                
            st.chat_message("assistant").markdown(f"**[{auto_subject} 튜터]**\n{response}")
            st.session_state.messages.append({"role": "assistant", "content": f"[{auto_subject}] {response}"})
            add_log(user['user_id'], auto_subject, prompt, response) # 파악된 과목 DB 저장 [Req 1, 4]

    with right_col:
        st.markdown("<div class='card' style='text-align:center;'>", unsafe_allow_html=True)
        st.info("📷 문제 사진을 올려주세요\nAI가 채점 후 팝업으로 결과를 알려드려요!")
        uploaded_file = st.file_uploader("", type=['jpg', 'jpeg', 'png', 'pdf', 'heic', 'heif'])
        
        if uploaded_file:
            try:
                standard_img = get_standardized_image(uploaded_file)
                st.session_state.current_img_obj = standard_img
                st.image(standard_img, use_container_width=True)
                
                if st.button("사진 채점 및 분석 시작", use_container_width=True):
                    with st.spinner("채점 중입니다..."):
                        buffer = io.BytesIO()
                        standard_img.save(buffer, format="JPEG", quality=85)
                        jpeg_bytes = buffer.getvalue()
                        b64_encoded = base64.b64encode(jpeg_bytes).decode('utf-8')
                        
                        # 1. 스토리지 업로드
                        file_path = f"{user['user_id']}/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                        supabase.storage.from_("problem_images").upload(file_path, jpeg_bytes)
                        img_url = supabase.storage.from_("problem_images").get_public_url(file_path)
                        
                        # 2. 과목 추출 및 채점 JSON 파싱
                        auto_subject = classify_subject("이 문제 사진의 과목이 뭐야?") 
                        analysis_data = analyze_vision_json(b64_encoded)
                        
                        # 3. DB 저장 [Req 4]
                        add_log(user['user_id'], auto_subject, f"사진 채점", json.dumps(analysis_data, ensure_ascii=False), img_url, "Vision")
                        
                        # 4. 팝업 호출 [Req 3]
                        grading_dialog(analysis_data, user['user_id'], auto_subject, img_url)
                        
            except Exception as e:
                st.error(f"오류: {e}")
                
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# 6. 학부모 화면 (대시보드 및 권한 제어) [Req 2, 3]
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 모니터링 대시보드")
    res = supabase.table("users").select("*").eq("role", "student").execute()
    students = res.data if res.data else []
    
    if students:
        target_id = st.selectbox("자녀 선택", [u['user_id'] for u in students])
        target_user = next(u for u in students if u['user_id'] == target_id)
        
        # --- 권한 및 상태 제어 ---
        st.subheader("⚙️ 자녀 학습 권한 제어")
        c1, c2 = st.columns(2)
        with c1:
            st.info(f"현재 상태: {target_user['status']}")
            if target_user['status'] == 'studying':
                if st.button("☕️ 쉬는 시간으로 변경"): update_user_status(target_id, 'status', 'break'); st.rerun()
            else:
                if st.button("🔥 공부 시간으로 변경"): update_user_status(target_id, 'status', 'studying'); st.rerun()
        with c2:
            current_perm = target_user.get('detail_permission', False)
            st.info(f"문제 풀이 해설 허용: {'✅ 켜짐' if current_perm else '🔒 꺼짐'}")
            if not current_perm:
                if st.button("🔓 자녀에게 '자세히 보기' 허용하기"): update_user_status(target_id, 'detail_permission', True); st.rerun()
            else:
                if st.button("🔒 자녀의 '자세히 보기' 차단하기"): update_user_status(target_id, 'detail_permission', False); st.rerun()
                
        st.divider()
        
        # --- 대시보드 (자동 파악된 과목 데이터 활용) [Req 2] ---
        st.subheader("📊 학습 현황 (AI 자동 분류 기반)")
        logs = get_logs(target_id)
        if not logs.empty:
            m1, m2 = st.columns(2)
            with m1:
                st.write("**최근 학습 과목 비율**")
                fig = px.pie(logs, names='subject', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
            with m2:
                st.write("**최근 질문 및 채점 기록**")
                st.dataframe(logs[['created_at', 'subject', 'log_type']], hide_index=True)
        else:
            st.warning("아직 기록된 학습 로그가 없습니다.")

# ---------------------------------------------------------
# 7. 메인 실행 제어
# ---------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    st.markdown("<br><h1 style='text-align: center;'>🏫 Focus-Super-AI Login</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        user_id = st.text_input("아이디 (joshua / parent_joshua)")
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
else:
    with st.sidebar:
        if st.button("로그아웃"): st.session_state.clear(); st.rerun()
            
    if st.session_state['user']['role'] == 'student':
        student_page()
    else:
        parent_page()