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
    .card { background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; border: 1px solid #e5e7eb; }
    .section-title { font-size: 16px; font-weight: bold; color: #374151; margin-bottom: 15px; display: flex; align-items: center; gap: 8px; }
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

def get_user_info(user_id):
    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

def update_user_status(user_id, status_key, new_value):
    supabase.table("users").update({status_key: new_value}).eq("user_id", user_id).execute()

def toggle_bookmark(log_id, current_val):
    supabase.table("logs").update({"is_bookmarked": not current_val}).eq("id", log_id).execute()

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
# 3. AI 모델 로직
# ---------------------------------------------------------
def classify_subject(text):
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
    """오프토픽 감지 프롬프트 적용 [Req 1]"""
    if status == "studying":
        system_content = f"""당신은 '{subject}' 전담 튜터입니다.
        중요: 만약 학생이 공부와 전혀 무관한 질문(게임, 잡담, 연예인 등)을 하면, 반드시 답변 맨 앞에 '[OFF_TOPIC]' 이라는 태그를 붙이고, "지금은 공부에 집중할 시간입니다! 공부와 관련된 질문을 해주세요."라고 단호하게 대답하세요."""
    else:
        system_content = "당신은 친절한 친구입니다. 쉬는 시간이니 어떠한 주제든 자유롭고 재미있게 대화하세요."
        
    completion = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": system_content}, {"role": "user", "content": question}],
        temperature=0.6, max_tokens=1024
    )
    response = completion.choices[0].message.content
    
    log_type = "Text"
    if "[OFF_TOPIC]" in response:
        log_type = "Off_Topic"
        response = response.replace("[OFF_TOPIC]", "").strip()
        
    return response, log_type

@st.cache_data(ttl=600)
def get_ai_recommendations(logs_json):
    """과거 질문 기반 추천 개념 생성 [Req 2]"""
    prompt = f"학생의 최근 질문 기록이야: {logs_json}. 이를 바탕으로 지금 공부하면 좋을 '추천 핵심 개념' 3가지를 불릿 포인트(-)로 짧게 제안해줘."
    completion = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5, max_tokens=300
    )
    return completion.choices[0].message.content

@st.cache_data(ttl=600)
def analyze_vulnerabilities(logs_json):
    """학부모용 과목별 취약점 분석 [Req 3]"""
    prompt = f"학생의 학습 기록이야: {logs_json}. 과목별로 학생이 자주 틀리거나 질문하는 '취약점'을 분석하고, 이를 극복하기 위한 조언을 작성해줘. 마크다운 형식으로 깔끔하게 정리해."
    completion = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=1024
    )
    return completion.choices[0].message.content

def analyze_vision_json(b64_encoded_jpeg):
    prompt = """
    이 문제 풀이 사진에는 여러 문제가 포함되어 있을 수 있습니다. 각 문제별로 분석해서 반드시 아래 JSON 형식(배열 포함)으로만 응답해:
    { "results": [ { "question_number": "1번", "is_correct": true, "status_text": "정답입니다!", "detailed_explanation": "해설", "core_concept": "개념" } ] }
    """
    completion = groq.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct", 
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_encoded_jpeg}"}}]}],
        temperature=0.1, max_tokens=2048, response_format={"type": "json_object"}
    )
    return json.loads(completion.choices[0].message.content)

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
# 4. 학생 화면 (스크린샷 UI 완벽 반영)
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    current_info = get_user_info(user['user_id'])
    status = current_info['status'] if current_info else 'studying'
    
    t1, t3 = st.columns([8, 2])
    with t1: st.title("00:45:12 ⏱️")
    st.divider()

    # 🚀 레이아웃: 왼쪽(UI), 중앙(채팅), 오른쪽(사진)
    left_col, center_col, right_col = st.columns([2.5, 4.5, 3])

    with left_col:
        logs = get_logs(user['user_id'])
        
        # [UI 1] 질문 및 응답 수 차트
        st.markdown("<div class='card'><div class='section-title'>💬 질문 및 응답 수</div>", unsafe_allow_html=True)
        if not logs.empty:
            sub_counts = logs['subject'].value_counts()
            st.bar_chart(sub_counts, height=150)
        st.markdown("</div>", unsafe_allow_html=True)
        
        # [UI 2] 지난 질의 (스크롤 적용) [Req 2]
        st.markdown("<div class='card'><div class='section-title'>🕒 지난 질의</div>", unsafe_allow_html=True)
        if not logs.empty:
            with st.container(height=250): # 스크롤 가능한 컨테이너
                for _, row in logs.head(10).iterrows(): # 10개까지 불러와서 3개만 보이고 나머진 스크롤
                    with st.expander(f"Q: {str(row['question'])[:15]}..."):
                        st.write(f"A: {row['answer']}")
                        bm_label = "✅ 북마크 해제" if row.get('is_bookmarked') else "🔖 북마크 하기"
                        if st.button(bm_label, key=f"bm_{row['id']}"):
                            toggle_bookmark(row['id'], row.get('is_bookmarked', False))
                            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        
        # [UI 3] 추천 공부 개념 (AI 자동 분석) [Req 2]
        st.markdown("<div class='card'><div class='section-title'>📖 추천 공부 개념</div>", unsafe_allow_html=True)
        if not logs.empty:
            recent_qs = logs['question'].head(5).tolist()
            recs = get_ai_recommendations(str(recent_qs))
            st.write(recs)
        st.markdown("</div>", unsafe_allow_html=True)
        
        # [UI 4] Bookmarked Answers [Req 2]
        st.markdown("<div class='card'><div class='section-title'>🔖 Bookmarked Answers</div>", unsafe_allow_html=True)
        if not logs.empty and 'is_bookmarked' in logs.columns:
            bm_logs = logs[logs['is_bookmarked'] == True]
            if not bm_logs.empty:
                for idx, row in enumerate(bm_logs.head(5).iterrows()):
                    st.write(f"{idx+1}. {str(row[1]['question'])[:15]}...")
            else:
                st.caption("북마크된 답변이 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    with center_col:
        if status == "studying": st.markdown('<div class="status-study">🔥 현재 집중 학습 중 (공부 관련 질문만 가능합니다)</div><br>', unsafe_allow_html=True)
        else: st.markdown('<div class="status-break">🍀 즐거운 쉬는 시간 (자유롭게 대화하세요!)</div><br>', unsafe_allow_html=True)
        
        if "messages" not in st.session_state: st.session_state.messages = []
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if prompt := st.chat_input("질문을 입력하세요..."):
            st.chat_message("user").markdown(prompt)
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            with st.spinner("AI가 생각 중입니다..."):
                auto_subject = classify_subject(prompt)
                response, log_type = get_text_response(status, auto_subject, prompt) # [Req 1]
                
            st.chat_message("assistant").markdown(f"**[{auto_subject} 튜터]**\n{response}")
            st.session_state.messages.append({"role": "assistant", "content": f"[{auto_subject}] {response}"})
            add_log(user['user_id'], auto_subject, prompt, response, log_type=log_type)

    with right_col:
        st.markdown("<div class='card' style='text-align:center;'>", unsafe_allow_html=True)
        st.info("📷 문제 사진을 올려주세요")
        uploaded_file = st.file_uploader("", type=['jpg', 'jpeg', 'png', 'pdf', 'heic', 'heif'])
        
        if uploaded_file:
            try:
                standard_img = get_standardized_image(uploaded_file)
                st.image(standard_img, use_container_width=True)
                
                if st.button("사진 채점 및 분석 시작", use_container_width=True):
                    with st.spinner("채점 중입니다..."):
                        buffer = io.BytesIO()
                        standard_img.save(buffer, format="JPEG", quality=85)
                        b64_encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
                        
                        file_path = f"{user['user_id']}/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                        supabase.storage.from_("problem_images").upload(file_path, buffer.getvalue())
                        img_url = supabase.storage.from_("problem_images").get_public_url(file_path)
                        
                        auto_subject = classify_subject("이 문제 사진의 과목이 뭐야?") 
                        analysis_data = analyze_vision_json(b64_encoded)
                        add_log(user['user_id'], auto_subject, "사진 채점", json.dumps(analysis_data, ensure_ascii=False), img_url, "Vision")
                        st.success("채점이 완료되었습니다. DB에 저장되었습니다.")
            except Exception as e:
                st.error(f"오류: {e}")
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# 5. 학부모 화면 (오프토픽 감지 및 취약점 분석 반영)
# ---------------------------------------------------------
def parent_page():
    st.title("👨‍👩‍👧‍👦 학부모 모니터링 대시보드")
    res = supabase.table("users").select("*").eq("role", "student").execute()
    students = res.data if res.data else []
    
    if students:
        target_id = st.selectbox("자녀 선택", [u['user_id'] for u in students])
        target_user = next(u for u in students if u['user_id'] == target_id)
        
        # [상태 제어]
        st.subheader("⚙️ 자녀 학습 상태 제어")
        c1, c2 = st.columns(2)
        with c1:
            st.info(f"현재 상태: {target_user['status']}")
            if target_user['status'] == 'studying':
                if st.button("☕️ 쉬는 시간으로 변경 (자유 채팅 허용)"): update_user_status(target_id, 'status', 'break'); st.rerun()
            else:
                if st.button("🔥 공부 시간으로 변경 (딴짓 차단)"): update_user_status(target_id, 'status', 'studying'); st.rerun()
        with c2:
            current_perm = target_user.get('detail_permission', False)
            st.info(f"문제 해설 권한: {'✅ 켜짐' if current_perm else '🔒 꺼짐'}")
            if st.button("권한 토글"):
                update_user_status(target_id, 'detail_permission', not current_perm); st.rerun()
                
        st.divider()
        logs = get_logs(target_id)
        
        if not logs.empty:
            # [Req 1] 딴짓(Off-Topic) 모니터링
            st.subheader("🚨 집중도 모니터링 (공부 중 딴짓 기록)")
            off_topics = logs[logs['log_type'] == 'Off_Topic']
            if not off_topics.empty:
                st.error(f"공부 시간에 시도한 딴짓 질문이 총 {len(off_topics)}건 있습니다.")
                st.dataframe(off_topics[['created_at', 'question', 'answer']], use_container_width=True)
            else:
                st.success("자녀가 공부 시간에 완벽하게 집중하고 있습니다!")
                
            st.divider()
            
            # [Req 3] AI 과목별 취약점 분석
            st.subheader("🧠 AI 과목별 취약점 분석 리포트")
            if st.button("최신 학습 데이터로 분석하기"):
                with st.spinner("AI가 자녀의 모든 학습 로그를 분석하고 있습니다..."):
                    # 데이터가 너무 길면 토큰 초과가 나므로 최근 30개만 추출
                    recent_logs = logs[['subject', 'question', 'answer']].head(30).to_dict('records')
                    analysis_report = analyze_vulnerabilities(str(recent_logs))
                    st.markdown(analysis_report)
        else:
            st.warning("아직 기록된 학습 로그가 없습니다.")

# ---------------------------------------------------------
# 6. 메인 실행 제어
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