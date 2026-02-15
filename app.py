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
# 1. 고도화된 UI 스타일
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Focus-Super-AI | Smart Learning")

st.markdown("""
    <style>
    .stApp { background-color: #f9fafb; }
    .block-container { padding-top: 2rem; max-width: 95%; }
    
    .card { 
        background-color: white; padding: 24px; border-radius: 16px; 
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        border: 1px solid #f3f4f6; margin-bottom: 20px;
    }
    
    .section-title { font-size: 16px; font-weight: 700; color: #111827; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
    .metric-label { font-size: 13px; color: #6b7280; font-weight: 500; text-align: center; margin-bottom: 8px;}
    .metric-value { font-size: 28px; font-weight: 800; color: #2563eb; text-align: center;}
    
    .status-badge { padding: 8px 16px; border-radius: 9999px; font-size: 14px; font-weight: 600; text-align: center; margin-bottom: 16px; }
    .study-mode { background-color: #dbeafe; color: #1e40af; border: 1px solid #bfdbfe; }
    .break-mode { background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }

    .alert-bar { background-color: #fef2f2; color: #b91c1c; padding: 12px 16px; border-radius: 12px; font-size: 13px; font-weight: 600; margin-bottom: 10px; border: 1px solid #fecaca; }
    
    /* 레벨업 및 EXP UI 뱃지 */
    .level-badge { background: linear-gradient(135deg, #f6d365 0%, #fda085 100%); color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: bold; }
    
    button[kind="tertiary"] { text-align: left !important; justify-content: flex-start !important; padding: 8px 4px !important; color: #374151 !important; font-size: 14px !important; }
    [data-testid="stImage"] img { border-radius: 8px; }
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
    return supabase.table("logs").insert({"user_id": user_id, "subject": subject, "question": question, "answer": answer, "image_url": img_url, "log_type": log_type}).execute()

def get_logs(user_id):
    res = supabase.table("logs").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

# [추가] EXP 및 레벨업 시스템 로직
def add_exp(user_id, amount):
    user = get_user_info(user_id)
    if not user: return
    
    current_level = user.get('level', 1)
    current_exp = user.get('exp', 0)
    new_exp = current_exp + amount
    exp_needed = current_level * 100  # 레벨업 필요 경험치 (Lv.1: 100, Lv.2: 200...)
    
    if new_exp >= exp_needed:
        current_level += 1
        new_exp = new_exp - exp_needed
        st.toast(f"🎉 축하합니다! Level {current_level}(으)로 레벨 업 달성!", icon="🏆")
        
    supabase.table("users").update({"level": current_level, "exp": new_exp}).eq("user_id", user_id).execute()
    st.session_state['user'] = get_user_info(user_id) # 세션 갱신

# ---------------------------------------------------------
# 3. AI 모델 로직
# ---------------------------------------------------------
def classify_subject(text):
    prompt = f"다음 내용을 보고 '국어', '영어', '수학', '과학', '기타' 중 딱 하나로 대답해:\n\n{text}"
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

def generate_review_quiz(concepts):
    """오답 노트를 기반으로 복습 퀴즈를 생성하는 AI 함수"""
    concept_str = ", ".join(concepts)
    prompt = f"학생이 최근 틀렸던 핵심 개념들입니다: [{concept_str}]. 이 개념들을 복습할 수 있는 객관식 또는 단답형 문제 3개를 내고, 하단에 정답과 해설을 명확히 분리해서 제공해 주세요."
    return groq.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.5, max_tokens=1024).choices[0].message.content

def get_standardized_image(uploaded_file):
    if uploaded_file.name.split('.')[-1].lower() == 'pdf':
        pix = fitz.open(stream=uploaded_file.read(), filetype="pdf").load_page(0).get_pixmap(dpi=150)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img = Image.open(uploaded_file)
    return img.convert('RGB') if img.mode != 'RGB' else img

# ---------------------------------------------------------
# 4. 팝업(Dialog) UI 설계
# ---------------------------------------------------------
@st.dialog("🧠 AI 과목별 취약점 리포트", width="large")
def ai_report_dialog(recent_logs):
    with st.spinner("최근 학습 데이터를 기반으로 AI가 취약점을 분석 중입니다..."):
        analysis_text = analyze_vulnerabilities(recent_logs)
        st.markdown(analysis_text)
    st.divider()
    if st.button("닫기", use_container_width=True): st.rerun()

@st.dialog("📝 상세 질의 내용")
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
        if c1.button("유사 문제 1개 풀기 (+10 EXP)", key=f"btn_1_{idx}"):
            with st.spinner("생성 중..."):
                probs = generate_and_grade_similar(item.get('core_concept', ''), 1)
                st.session_state.sim_problems_cache[btn1] = probs
                add_log(user_id, subject, f"{q_num} 유사문제 1개", probs, log_type="Similar_Task")
                add_exp(user_id, 10) # 경험치 보상
        if c2.button("유사 문제 3개 풀기 (+30 EXP)", key=f"btn_3_{idx}"):
            with st.spinner("생성 중..."):
                probs = generate_and_grade_similar(item.get('core_concept', ''), 3)
                st.session_state.sim_problems_cache[btn3] = probs
                add_log(user_id, subject, f"{q_num} 유사문제 3개", probs, log_type="Similar_Task")
                add_exp(user_id, 30) # 경험치 보상

        if btn1 in st.session_state.sim_problems_cache: st.info(st.session_state.sim_problems_cache[btn1])
        if btn3 in st.session_state.sim_problems_cache: st.info(st.session_state.sim_problems_cache[btn3])
        st.divider()

@st.dialog("📚 오답 맞춤 복습 퀴즈", width="large")
def review_quiz_dialog(concepts):
    with st.spinner("AI가 오답 노트 개념을 분석하여 맞춤형 모의고사를 출제하고 있습니다..."):
        quiz_text = generate_review_quiz(concepts)
        st.markdown(quiz_text)
    st.divider()
    if st.button("풀이 완료 및 닫기", use_container_width=True): st.rerun()

# ---------------------------------------------------------
# 5. 학생 화면
# ---------------------------------------------------------
def student_page():
    user = st.session_state['user']
    status = user.get('status', 'studying')
    user_level = user.get('level', 1)
    user_exp = user.get('exp', 0)
    exp_needed = user_level * 100
    progress_val = min(user_exp / exp_needed, 1.0)
    
    logs = get_logs(user['user_id'])
    bm_dict = {row['id']: row['is_bookmarked'] for _, row in logs.iterrows()} if not logs.empty else {}

    t1, t2 = st.columns([9, 1])
    with t2:
        if st.button("🔄 새로고침", use_container_width=True): st.session_state['user']=get_user_info(user['user_id']); st.rerun()

    left_col, center_col, right_col = st.columns([2.5, 5, 2.5])

    # 1️⃣ 왼쪽: 대시보드 및 오답 노트
    with left_col:
        with st.container(height=800, border=False):
            # [추가] 게이미피케이션 프로필
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<span class='level-badge'>Lv.{user_level} AI 탐험가</span>", unsafe_allow_html=True)
            st.markdown(f"<div style='margin-top:10px; font-weight:bold;'>경험치: {user_exp} / {exp_needed} EXP</div>", unsafe_allow_html=True)
            st.progress(progress_val)
            st.markdown("</div>", unsafe_allow_html=True)

            # [추가] 나의 오답 노트 기능
            st.markdown("<div class='card'><div class='section-title'>📚 나의 오답 노트</div>", unsafe_allow_html=True)
            wrong_concepts = []
            if not logs.empty:
                vision_logs = logs[logs['log_type'] == 'Vision']
                for _, row in vision_logs.head(10).iterrows():
                    try:
                        data = json.loads(row['answer'])
                        for res in data.get('results', []):
                            if not res.get('is_correct'):
                                concept = res.get('core_concept', '기타')
                                wrong_concepts.append(concept)
                                st.markdown(f"❌ <span style='font-size:13px'>{concept}</span>", unsafe_allow_html=True)
                    except: pass
            
            if wrong_concepts:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("✨ 오답 복습 퀴즈 생성 (+20 EXP)", use_container_width=True, type="primary"):
                    add_exp(user['user_id'], 20)
                    review_quiz_dialog(list(set(wrong_concepts))[:5])
            else:
                st.caption("아직 기록된 오답이 없습니다. 훌륭해요!")
            st.markdown("</div>", unsafe_allow_html=True)
            
            # 기존 북마크 리스트
            st.markdown("<div class='card'><div class='section-title'>🔖 북마크된 답변</div>", unsafe_allow_html=True)
            if not logs.empty and 'is_bookmarked' in logs.columns:
                bm_logs = logs[logs['is_bookmarked'] == True]
                for idx, row in enumerate(bm_logs.head(5).iterrows()):
                    if st.button(f"⭐ {str(row[1]['question'])[:15]}...", key=f"bkmk_{row[1]['id']}", type="tertiary", use_container_width=True):
                        qa_detail_dialog(row[1]['id'], row[1]['question'], row[1]['answer'], True)
            st.markdown("</div>", unsafe_allow_html=True)

    # 2️⃣ 중앙: 채팅 패널
    with center_col:
        if status == "studying": st.markdown('<div class="status-badge study-mode">🔥 집중 학습 모드 활성화 중</div>', unsafe_allow_html=True)
        else: st.markdown('<div class="status-badge break-mode">🍀 쉬는 시간: 자유 대화 모드</div>', unsafe_allow_html=True)
        
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

        if prompt := st.chat_input("공부하다 궁금한 점을 물어보세요! (+10 EXP)"):
            st.session_state.messages.append({"role": "user", "content": prompt}); st.rerun()

        if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
            prompt = st.session_state.messages[-1]["content"]
            with chat_container:
                with st.chat_message("assistant"):
                    with st.spinner("AI가 생각 중입니다..."):
                        auto_subject = classify_subject(prompt)
                        response, log_type = get_text_response(status, auto_subject, prompt)
                        st.markdown(f"**[{auto_subject} 튜터]**\n{response}")
                        res = add_log(user['user_id'], auto_subject, prompt, response, log_type=log_type)
                        new_log_id = res.data[0]['id'] if res.data else None
                        add_exp(user['user_id'], 10) # 질문 완료시 경험치
            st.session_state.messages.append({"role": "assistant", "content": f"**[{auto_subject} 튜터]**\n{response}", "log_id": new_log_id}); st.rerun()

    # 3️⃣ 오른쪽: 사진 업로드 패널
    with right_col:
        with st.container(height=800, border=False):
            st.markdown("<div class='card' style='text-align:center;'><b>📷 문제 사진 업로드</b><br><span style='font-size:12px;color:gray'>정답 맞히면 보너스 EXP 지급!</span></div>", unsafe_allow_html=True)
            uploaded_file = st.file_uploader("", type=['jpg', 'jpeg', 'png', 'pdf', 'heic', 'heif'], label_visibility="collapsed")
            if uploaded_file:
                try:
                    standard_img = get_standardized_image(uploaded_file)
                    st.session_state.current_img_obj = standard_img
                    st.image(standard_img, use_container_width=True)
                    if st.button("✅ 사진 채점 및 분석 시작 (+20 EXP)", use_container_width=True, type="primary"):
                        if "sim_problems_cache" in st.session_state: st.session_state.sim_problems_cache.clear()
                        with st.spinner("AI 비전 모델이 채점 중입니다..."):
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
                            
                            # 경험치 보상 계산
                            correct_count = sum(1 for item in analysis_data.get('results', []) if item.get('is_correct'))
                            earned_exp = 20 + (correct_count * 30) # 기본 20 + 정답당 30
                            add_exp(user['user_id'], earned_exp)
                            
                            grading_dialog(analysis_data, user['user_id'], auto_subject, img_url)
                except Exception as e: st.error(f"오류: {e}")

# ---------------------------------------------------------
# 6. 학부모 화면
# ---------------------------------------------------------
def parent_page():
    st.markdown("<br>", unsafe_allow_html=True) 
    
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
        
        # 1. 지표 카드 (레벨 추가)
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)
        with m1: st.markdown(f"<div class='metric-label'>현재 레벨</div><div class='metric-value'>Lv.{target_user.get('level', 1)}</div>", unsafe_allow_html=True)
        with m2: st.markdown(f"<div class='metric-label'>총 질문 수</div><div class='metric-value'>{total_q}건</div>", unsafe_allow_html=True)
        with m3: st.markdown(f"<div class='metric-label'>정답률</div><div class='metric-value'>{accuracy}%</div>", unsafe_allow_html=True)
        with m4: st.markdown(f"<div class='metric-label'>주간 공부 시간</div><div class='metric-value'>6h 20m</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # 2. 오답 경고 (Alerts)
        if wrong_concepts:
            st.markdown("<div class='section-title'>🚨 자녀가 자주 틀리는 개념</div>", unsafe_allow_html=True)
            for concept in list(set(wrong_concepts))[:3]: 
                st.markdown(f"<div class='alert-bar'>⚠️ '{concept}' 개념의 복습이 시급합니다.</div>", unsafe_allow_html=True)

        # 3. 차트 섹션
        c1, c2 = st.columns([6, 4])
        with c1:
            st.markdown("<div class='card'><div class='section-title'>📊 주간 정답률 추이</div>", unsafe_allow_html=True)
            dummy_line = pd.DataFrame({'일차': ['월','화','수','목','금','토'], '정답률': [75, 80, 78, 85, 90, accuracy]})
            st.plotly_chart(px.line(dummy_line, x='일차', y='정답률', markers=True, height=220), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
        with c2:
            st.markdown("<div class='card'><div class='section-title'>🥧 과목별 질문 비중</div>", unsafe_allow_html=True)
            if not logs.empty: st.plotly_chart(px.pie(logs, names='subject', hole=0.5, height=220), use_container_width=True)
            else: st.info("데이터가 부족합니다.")
            st.markdown("</div>", unsafe_allow_html=True)

        # 4. AI 리포트 팝업 호출
        st.markdown("<div class='card'><div class='section-title'>🧠 AI 과목별 취약점 진단</div>", unsafe_allow_html=True)
        st.markdown("<span style='color:gray; font-size:14px;'>최근 15개의 학습 기록을 바탕으로 취약점을 심층 분석합니다.</span><br><br>", unsafe_allow_html=True)
        if st.button("✨ 팝업으로 AI 분석 리포트 열기", type="primary"):
            recent_logs = logs[['subject', 'question']].head(15).to_dict('records')
            ai_report_dialog(recent_logs)
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# 7. 메인 실행 제어
# ---------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state['logged_in'] = False
if not st.session_state['logged_in']:
    st.markdown("<br><h1 style='text-align: center; color:#1f2937;'>🎓 Focus-Super-AI</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        user_id = st.text_input("아이디 (학생: joshua / 학부모: parent_joshua)")
        password = st.text_input("비밀번호", type="password")
        if st.button("로그인", use_container_width=True, type="primary"):
            user_info = get_user_info(user_id)
            if user_info and password in ["1234", (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%m%d")]:
                st.session_state['user'] = user_info; st.session_state['logged_in'] = True; st.rerun()
            else: st.error("로그인 정보 오류")
        st.markdown("</div>", unsafe_allow_html=True)
else:
    with st.sidebar:
        st.markdown(f"**👤 {st.session_state['user']['name']}님 환영합니다.**")
        if st.button("로그아웃", use_container_width=True): st.session_state.clear(); st.rerun()
    if st.session_state['user']['role'] == 'student': student_page()
    else: parent_page()