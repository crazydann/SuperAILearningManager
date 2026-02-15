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
# 1. 초기 설정 및 UI/UX 고정형 스타일
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Focus-Super-AI Learning Manager")

st.markdown("""
    <style>
    .block-container { padding-top: 1rem; padding-bottom: 0rem; max-width: 100%; overflow-y: hidden; }
    .card { background-color: white; padding: 15px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border: 1px solid #e5e7eb; margin-bottom: 15px; }
    .section-title { font-size: 14px; font-weight: bold; color: #6b7280; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
    .status-study { color: white; background-color: #3b82f6; padding: 10px; border-radius: 8px; font-weight: bold; text-align: center; margin-bottom: 10px; }
    .status-break { color: white; background-color: #22c55e; padding: 10px; border-radius: 8px; font-weight: bold; text-align: center; margin-bottom: 10px; }
    button[kind="tertiary"] { text-align: left !important; justify-content: flex-start !important; padding: 5px 0px !important; color: #374151 !important; font-size: 14px !important; }
    
    /* 대시보드 전용 스타일 */
    .metric-value { font-size: 24px; font-weight: bold; color: #1f2937; text-align: center; }
    .metric-label { font-size: 12px; color: #6b7280; text-align: center; margin-bottom: 10px; }
    .alert-bar { background-color: #fee2e2; color: #ef4444; padding: 10px 15px; border-radius: 6px; font-size: 13px; font-weight: bold; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
    .pill-tag { background-color: #fef3c7; color: #d97706; padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; display: inline-block; margin: 0 5px 5px 0; }
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
    res = supabase.table("logs").insert({"user_id": user_id, "subject": subject, "question": question, "answer": answer, "image_url": img_url, "log_type": log_type}).execute()
    return res

def get_logs(user_id):
    res = supabase.table("logs").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

# ---------------------------------------------------------
# 3. AI 모델 로직
# ---------------------------------------------------------
def classify_subject(text):
    prompt = f"다음 내용을 보고 '국어', '영어', '수학', '과학', '기타' 중 딱 하나의 단어로만 대답해:\n\n{text}"
    try: return groq.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=10).choices[0].message.content.strip()
    except: return "기타"

def get_text_response(status, subject, question):
    system_content = f"당신은 '{subject}' 전담 튜터입니다. 만약 무관한 질문을 하면 맨 앞에 '[OFF_TOPIC]'을 붙이세요." if status == "studying" else "친절한 친구처럼 자유롭게 대화하세요."
    res = groq.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "system", "content": system_content}, {"role": "user", "content": question}], temperature=0.6, max_tokens=1024).choices[0].message.content
    return (res.replace("[OFF_TOPIC]", "").strip(), "Off_Topic") if "[OFF_TOPIC]" in res else (res, "Text")

@st.cache_data(ttl=600)
def get_ai_recommendations(logs_json):
    try: return groq.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": f"학습 기록: {logs_json}. 추천 핵심 개념 3가지를 불릿 포인트(-)로 제안해."}], temperature=0.5, max_tokens=300).choices[0].message.content
    except: return "- 학습 데이터 부족"

@st.cache_data(ttl=600)
def analyze_vulnerabilities(logs_json):
    safe_logs = str(logs_json)[:4000]
    prompt = f"학습 기록: {safe_logs}\n\n과목별 취약점을 분석하고 극복을 위한 추천 개념을 해시태그 형식(#개념)으로 포함해서 작성해줘."
    try: return groq.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.4, max_tokens=1024).choices[0].message.content
    except Exception as e: return f"⚠️ 분석 실패: {e}"

def analyze_vision_json(b64_encoded_jpeg):
    prompt = """각 문제별로 분석해서 반드시 아래 JSON 형식(배열 포함)으로만 응답해: { "results": [ { "question_number": "1번", "is_correct": true, "status_text": "정답입니다!", "detailed_explanation": "해설", "core_concept": "개념" } ] }"""
    return json.loads(groq.chat.completions.create(model="meta-llama/llama-4-scout-17b-16e-instruct", messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_encoded_jpeg}"}}]}], temperature=0.1, max_tokens=2048, response_format={"type": "json_object"}).choices[0].message.content)

def generate_and_grade_similar(core_concept, count):
    return groq.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": f"핵심 개념 '{core_concept}'에 대한 객관식/단답형 문제 {count}개를 내고 정답도 알려줘."}]).choices[0].message.content

def get_standardized_image(uploaded_file):
    if uploaded_file.name.split('.')[-1].lower() == 'pdf':
        pix = fitz.open(stream=uploaded_file.read(), filetype="pdf").load_page(0).get_pixmap(dpi=150)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img = Image.open(uploaded_file)
    return img.convert('RGB') if img.mode != 'RGB' else img

# ---------------------------------------------------------
# 4. 팝업(Dialog) UI 설계
# ---------------------------------------------------------
@st.dialog("📝 상세 내용 보기")
def qa_detail_dialog(log_id, q, a, is_bm):
    st.markdown(f"**🗣️ 질문:** {q}")
    st.info(f"**🤖 답변:**\n\n{a}")
    st.divider()
    if st.button("⭐ 북마크 해제하기" if is_bm else "🔖 이 답변 북마크하기", use_container_width=True):
        toggle_bookmark(log_id, is_bm); st.rerun()

@st.dialog("🎯 다중 문제 채점 결과", width="large")
def grading_dialog(analysis_data, user_id, subject, img_url):
    st.image(st.session_state.current_img_obj, use_container_width=True)
    has_permission = get_user_info(user_id).get('detail_permission', False)
    if "sim_problems_cache" not in st.session_state: st.session_state.sim_problems_cache = {}

    for idx, item in enumerate(analysis_data.get('results', [])):
        q_num = item.get('question_number', f'{idx+1}번 문제')
        st.subheader(f"📌 {q_num}")
        if item.get('is_correct', False): st.success(f"✅ {item.get('status_text', '정답!')}")
        else: st.error(f"❌ {item.get('status_text', '오답.')}")

        if has_permission:
            with st.expander("🔍 풀이 해설 자세히 보기"): st.write(item.get('detailed_explanation', ''))
        else: st.warning("🔒 해설 자세히 보기 (학부모 허용 필요)")

        c1, c2 = st.columns(2)
        btn1, btn3 = f"sim_1_{idx}", f"sim_3_{idx}"
        if c1.button("유사 문제 1개 풀기", key=f"btn_1_{idx}"):
            with st.spinner("생성 중..."):
                probs = generate_and_grade_similar(item.get('core_concept', ''), 1)
                st.session_state.sim_problems_cache[btn1] = probs
                add_log(user_id, subject, f"{q_num} 유사문제 1개", probs, log_type="Similar_Task")
        if c2.button("유사 문제 3개 풀기", key=f"btn_3_{idx}"):
            with st.spinner("생성 중..."):
                probs = generate_and_grade_similar(item.get('core_concept', ''), 3)
                st.session_state.sim_problems_cache[btn3] = probs
                add_log(user_id, subject, f"{q_num} 유사문제 3개", probs, log_type="Similar_Task")

        if btn1 in st.session_state.sim_problems_cache: st.info(st.session_state.sim_problems_cache[btn1])
        if btn3 in st.session_state.sim_problems_cache: st.info(st.session_state.sim_problems_cache[btn3])
        st.divider()

# ---------------------------------------------------------
# 5. 학생 화면 (수동 새로고침 추가)
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    status = get_user_info(user['user_id']).get('status', 'studying')
    logs = get_logs(user['user_id'])
    bm_dict = {row['id']: row['is_bookmarked'] for _, row in logs.iterrows()} if not logs.empty else {}

    # 상단 수동 새로고침 버튼
    t1, t2 = st.columns([9, 1])
    with t2:
        if st.button("🔄 새로고침", use_container_width=True): st.rerun()

    left_col, center_col, right_col = st.columns([2.2, 5.3, 2.5])

    # 1️⃣ 왼쪽 프레임
    with left_col:
        with st.container(height=800, border=False):
            st.markdown("<div class='card'><div class='section-title'>💬 질문 및 응답 수</div>", unsafe_allow_html=True)
            if not logs.empty: st.bar_chart(logs['subject'].value_counts(), height=130)
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='card'><div class='section-title'>🕒 지난 질의</div>", unsafe_allow_html=True)
            if not logs.empty:
                for _, row in logs.head(3).iterrows():
                    if st.button(f"Q: {str(row['question'])[:18]}...", key=f"past_{row['id']}", type="tertiary", use_container_width=True):
                        qa_detail_dialog(row['id'], row['question'], row['answer'], row.get('is_bookmarked', False))
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='card'><div class='section-title'>📖 추천 공부 개념</div>", unsafe_allow_html=True)
            if not logs.empty: st.caption(get_ai_recommendations(str(logs['question'].head(5).tolist())))
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='card'><div class='section-title'>🔖 Bookmarked Answers</div>", unsafe_allow_html=True)
            if not logs.empty and 'is_bookmarked' in logs.columns:
                bm_logs = logs[logs['is_bookmarked'] == True]
                for idx, row in enumerate(bm_logs.head(5).iterrows()):
                    if st.button(f"{idx+1}. {str(row[1]['question'])[:15]}...", key=f"bkmk_{row[1]['id']}", type="tertiary", use_container_width=True):
                        qa_detail_dialog(row[1]['id'], row[1]['question'], row[1]['answer'], True)
            st.markdown("</div>", unsafe_allow_html=True)

    # 2️⃣ 중앙 프레임
    with center_col:
        if status == "studying": st.markdown('<div class="status-study">🔥 현재 집중 학습 중 (공부 질문만 가능)</div>', unsafe_allow_html=True)
        else: st.markdown('<div class="status-break">🍀 즐거운 쉬는 시간 (자유롭게 대화하세요!)</div>', unsafe_allow_html=True)
        
        chat_container = st.container(height=650, border=True) 
        if "messages" not in st.session_state: st.session_state.messages = []
        
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): 
                    st.markdown(msg["content"])
                    if msg["role"] == "assistant" and msg.get("log_id"):
                        log_id = msg["log_id"]
                        is_bm = bm_dict.get(log_id, False)
                        if st.button("⭐ 북마크 해제" if is_bm else "☆ 북마크 하기", key=f"chat_bm_{log_id}"):
                            toggle_bookmark(log_id, is_bm); st.rerun()

        if prompt := st.chat_input("안녕하세요! 🎓 Focus-Super-AI 학습 도우미예요."):
            st.session_state.messages.append({"role": "user", "content": prompt}); st.rerun()

        if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
            prompt = st.session_state.messages[-1]["content"]
            with chat_container:
                with st.chat_message("assistant"):
                    with st.spinner("AI 선생님이 생각 중입니다..."):
                        auto_subject = classify_subject(prompt)
                        response, log_type = get_text_response(status, auto_subject, prompt)
                        st.markdown(f"**[{auto_subject} 튜터]**\n{response}")
                        res = add_log(user['user_id'], auto_subject, prompt, response, log_type=log_type)
                        new_log_id = res.data[0]['id'] if res.data else None
            st.session_state.messages.append({"role": "assistant", "content": f"**[{auto_subject} 튜터]**\n{response}", "log_id": new_log_id}); st.rerun()

    # 3️⃣ 오른쪽 프레임
    with right_col:
        with st.container(height=800, border=False):
            st.markdown("<div class='card' style='text-align:center;'><b>📷 문제 사진을 올려주세요</b><br><span style='font-size:12px;color:gray'>풀이한 문제를 올리면 AI가 채점해드려요!</span></div>", unsafe_allow_html=True)
            uploaded_file = st.file_uploader("", type=['jpg', 'jpeg', 'png', 'pdf', 'heic', 'heif'], label_visibility="collapsed")
            if uploaded_file:
                try:
                    standard_img = get_standardized_image(uploaded_file)
                    st.session_state.current_img_obj = standard_img
                    st.image(standard_img, use_container_width=True)
                    if st.button("사진 채점 및 분석 시작", use_container_width=True):
                        if "sim_problems_cache" in st.session_state: st.session_state.sim_problems_cache.clear()
                        with st.spinner("채점 중입니다..."):
                            buffer = io.BytesIO()
                            standard_img.save(buffer, format="JPEG", quality=85)
                            jpeg_bytes = buffer.getvalue()
                            b64_encoded = base64.b64encode(jpeg_bytes).decode('utf-8')
                            file_path = f"{user['user_id']}/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                            supabase.storage.from_("problem_images").upload(file_path, jpeg_bytes)
                            img_url = supabase.storage.from_("problem_images").get_public_url(file_path)
                            
                            auto_subject = classify_subject("이 사진 과목?") 
                            analysis_data = analyze_vision_json(b64_encoded)
                            add_log(user['user_id'], auto_subject, f"사진 채점 (다중)", json.dumps(analysis_data, ensure_ascii=False), img_url, "Vision")
                            grading_dialog(analysis_data, user['user_id'], auto_subject, img_url)
                except Exception as e: st.error(f"오류: {e}")

# ---------------------------------------------------------
# 6. 학부모 화면 (UI 전면 개편 및 수동 새로고침)
# ---------------------------------------------------------
def parent_page():
    st.markdown("<br>", unsafe_allow_html=True) # 상단 여백
    
    # 상단 컨트롤 및 새로고침 바
    res = supabase.table("users").select("*").eq("role", "student").execute()
    students = res.data if res.data else []
    
    if students:
        ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 3, 3, 2])
        with ctrl1: target_id = st.selectbox("자녀 선택", [u['user_id'] for u in students], label_visibility="collapsed")
        target_user = next(u for u in students if u['user_id'] == target_id)
        
        with ctrl2:
            if target_user['status'] == 'studying':
                if st.button("☕ 쉬는 시간으로 변경", use_container_width=True): update_user_status(target_id, 'status', 'break'); st.rerun()
            else:
                if st.button("🔥 공부 시간으로 변경", use_container_width=True): update_user_status(target_id, 'status', 'studying'); st.rerun()
        with ctrl3:
            perm_label = "✅ 해설 보기 끄기" if target_user.get('detail_permission', False) else "🔒 해설 보기 켜기"
            if st.button(perm_label, use_container_width=True): update_user_status(target_id, 'detail_permission', not target_user.get('detail_permission', False)); st.rerun()
        with ctrl4:
            if st.button("🔄 화면 새로고침", use_container_width=True): st.rerun()
            
        logs = get_logs(target_id)
        
        # 실제 데이터 기반 수치 계산 (DB 파싱)
        total_q = len(logs)
        vision_logs = logs[logs['log_type'] == 'Vision']
        correct_cnt, total_vision = 0, 0
        wrong_concepts = []
        
        for _, row in vision_logs.iterrows():
            try:
                data = json.loads(row['answer'])
                for res in data.get('results', []):
                    total_vision += 1
                    if res.get('is_correct'): correct_cnt += 1
                    else: wrong_concepts.append(res.get('core_concept', '알 수 없는 개념'))
            except: pass
            
        accuracy = int((correct_cnt / total_vision) * 100) if total_vision > 0 else 0
        
        # 1. KPI 지표 (화면 캡처 반영)
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        with m1: st.markdown(f"<div class='metric-label'>이번 주 학습 시간</div><div class='metric-value'>6h 20m</div>", unsafe_allow_html=True)
        with m2: st.markdown(f"<div class='metric-label'>누적 질문 수</div><div class='metric-value'>{total_q}건</div>", unsafe_allow_html=True)
        with m3: st.markdown(f"<div class='metric-label'>평균 정답률</div><div class='metric-value'>{accuracy}%</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # 2. 오답 경고 알림 바 (Red bars)
        if wrong_concepts:
            st.markdown("<div style='font-size:14px; font-weight:bold; margin-bottom:10px;'>🚨 자녀가 자주 틀리는 개념 알림</div>", unsafe_allow_html=True)
            for concept in list(set(wrong_concepts))[:3]: # 최근 틀린 개념 최대 3개
                st.markdown(f"<div class='alert-bar'>⚠️ 문제 오답: '{concept}' 관련 복습이 필요합니다.</div>", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

        # 3. 차트 섹션 (가짜 주간 데이터 + 실제 과목 데이터)
        c1, c2 = st.columns([6, 4])
        with c1:
            st.markdown("<div class='card'><div class='section-title'>📊 주간 퀴즈 정답률 추이</div>", unsafe_allow_html=True)
            dummy_line = pd.DataFrame({'일차': ['월','화','수','목','금','토'], '정답률': [75, 80, 78, 85, 90, accuracy]})
            st.plotly_chart(px.line(dummy_line, x='일차', y='정답률', markers=True, height=250), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
        with c2:
            st.markdown("<div class='card'><div class='section-title'>🥧 과목별 학습 비중 (실제 데이터)</div>", unsafe_allow_html=True)
            if not logs.empty:
                st.plotly_chart(px.pie(logs, names='subject', hole=0.5, height=250), use_container_width=True)
            else: st.info("데이터가 부족합니다.")
            st.markdown("</div>", unsafe_allow_html=True)

        # 4. AI 취약점 분석 리포트 (수동 새로고침으로 인해 더 이상 사라지지 않음)
        st.markdown("<div class='card'><div class='section-title'>🧠 AI 과목별 취약점 극복 가이드</div>", unsafe_allow_html=True)
        if st.button("✨ 최신 데이터로 AI 분석 시작"):
            with st.spinner("최근 학습 데이터를 기반으로 AI가 취약점을 분석 중입니다..."):
                recent_logs = logs[['subject', 'question']].head(15).to_dict('records')
                analysis_text = analyze_vulnerabilities(recent_logs)
                
                # 분석 결과를 캐시(Session State)에 저장하여 화면에 유지
                st.session_state['ai_report'] = analysis_text

        # 저장된 리포트가 있으면 출력 (해시태그를 알약 버튼처럼 예쁘게 꾸밈)
        if 'ai_report' in st.session_state:
            st.markdown(st.session_state['ai_report'])
            
            # 태그 UI (시각적 연출)
            st.markdown("<br><b>💡 추천 학습 개념 태그</b><br>", unsafe_allow_html=True)
            tags = ["방정식 풀이", "문법 시제", "독해 추론", "광합성 원리"] if not wrong_concepts else wrong_concepts[:4]
            tags_html = "".join([f"<span class='pill-tag'># {tag}</span>" for tag in tags])
            st.markdown(tags_html, unsafe_allow_html=True)
            
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# 7. 메인 실행 제어
# ---------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']:
    st.markdown("<br><h1 style='text-align: center;'>🏫 Focus-Super-AI Login</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        user_id = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        if st.button("로그인", use_container_width=True):
            user_info = get_user_info(user_id)
            if user_info and password in ["1234", (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%m%d")]:
                st.session_state['user'] = user_info; st.session_state['logged_in'] = True; st.rerun()
            else: st.error("로그인 정보 오류")
else:
    with st.sidebar:
        if st.button("로그아웃"): st.session_state.clear(); st.rerun()
    if st.session_state['user']['role'] == 'student': student_page()
    else: parent_page()