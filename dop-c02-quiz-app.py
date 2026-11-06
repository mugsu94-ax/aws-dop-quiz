import streamlit as st
import json
import re
import os
import sqlite3
from datetime import datetime

# ==========================================
# 0. 페이지 설정 & AWS 디자인 테마 CSS
# ==========================================
st.set_page_config(
    page_title="AWS DOP-C02 모의고사 & 1:1 키워드 암기 노트",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# AWS 디자인 시스템 컬러
PRIMARY_COLOR = "#0073BB"    # AWS 대표 파란색
SECONDARY_COLOR = "#232F3E"  # AWS 네이비
ACCENT_COLOR = "#FF9900"     # AWS 주황색
BG_CARD_COLOR = "#F8F9FA"

st.markdown(f"""
<style>
    .stApp {{
        background-color: #FFFFFF;
        font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    }}
    .main-header {{
        background-color: {SECONDARY_COLOR};
        color: #FFFFFF;
        padding: 24px 32px;
        border-radius: 8px;
        margin-bottom: 24px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }}
    .main-header h1 {{
        color: #FFFFFF !important;
        font-size: 2.0rem !important;
        font-weight: 700 !important;
        margin-bottom: 6px !important;
    }}
    .main-header p {{
        color: #D5D9D9 !important;
        font-size: 1.0rem !important;
        margin: 0 !important;
    }}
    .aws-card {{
        background-color: {BG_CARD_COLOR};
        border: 1px solid #D5D9D9;
        border-left: 6px solid {PRIMARY_COLOR};
        border-radius: 8px;
        padding: 28px 32px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        margin-bottom: 24px;
    }}
    .q-number-title {{
        color: #16191F;
        font-size: 1.25rem;
        font-weight: 700;
        margin-bottom: 16px;
        padding-bottom: 12px;
        border-bottom: 1px solid #E9EBED;
    }}
    .q-text-body {{
        color: #232F3E;
        font-size: 1.08rem;
        line-height: 1.8;
        font-weight: 400;
        word-break: keep-all;
    }}
    .result-pass {{
        background-color: #F2F9F4;
        border: 2px solid #2E7D32;
        padding: 20px;
        border-radius: 8px;
        color: #1B5E20;
        font-weight: 700;
        font-size: 1.08rem;
        margin-top: 20px;
    }}
    .result-fail {{
        background-color: #FDF2F2;
        border: 2px solid #D32F2F;
        padding: 20px;
        border-radius: 8px;
        color: #C62828;
        font-weight: 700;
        font-size: 1.08rem;
        margin-top: 20px;
    }}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
    <h1>☁️ AWS Certified DevOps Engineer Professional (DOP-C02)</h1>
    <p>최신 427개 기출 정밀 복원 & 1:1 정밀 키워드 암기 모드 시스템</p>
</div>
""", unsafe_allow_html=True)

# DB & Data Loading
DB_PATH = "dop_c02_user_progress.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id TEXT,
            q_id INTEGER,
            user_ans TEXT,
            is_correct INTEGER,
            is_bookmarked INTEGER,
            updated_at TIMESTAMP,
            PRIMARY KEY (user_id, q_id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def load_questions():
    possible_paths = [
        "dop-c02-questions-v1.json",
        "dop-c02-questions.json",
        "/workspace/artifacts/dop-c02-questions-v1.json",
        "/workspace/artifacts/dop-c02-questions.json",
        "/workspace/scratch/dop-c02-questions-v1.json"
    ]
    json_path = None
    for p in possible_paths:
        if os.path.exists(p):
            json_path = p
            break
            
    if not json_path:
        st.error("dop-c02-questions-v1.json 데이터 파일을 찾을 수 없습니다.")
        st.stop()
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    return data

try:
    questions = load_questions()
    q_dict = {q["id"]: q for q in questions}
    all_q_ids = [q["id"] for q in questions]
except Exception as e:
    st.error(f"문제 데이터를 불러오는 데 실패했습니다: {e}")
    st.stop()

# Session State Init
if "current_q_id" not in st.session_state:
    st.session_state.current_q_id = all_q_ids[0]
if "submitted" not in st.session_state:
    st.session_state.submitted = False
if "selected_options" not in st.session_state:
    st.session_state.selected_options = []
if "history" not in st.session_state:
    st.session_state.history = {}
if "bookmarks" not in st.session_state:
    st.session_state.bookmarks = set()
if "memory_mode" not in st.session_state:
    st.session_state.memory_mode = False

# Sidebar Navigation
st.sidebar.title("📌 학습 모드 선택")
mode_all = "1. 전체 문제 풀이 (1~427)"
mode_select = "2. 특정 문제 번호 지정"
mode_range = "3. 구간 선택 풀이"
mode_short = "4. 핵심 주제별 퀴즈"
mode_note = "5. 오답노트 & 북마크"

mode = st.sidebar.radio(
    "원하시는 공부 방식을 선택하세요:",
    [mode_all, mode_select, mode_range, mode_short, mode_note]
)

active_q_list = all_q_ids

if mode == mode_select:
    selected_num = st.sidebar.number_input(
        "문제 번호 입력 (1~427)",
        min_value=min(all_q_ids),
        max_value=max(all_q_ids),
        value=st.session_state.current_q_id if st.session_state.current_q_id in all_q_ids else min(all_q_ids),
        step=1
    )
    if selected_num in q_dict and st.session_state.current_q_id != selected_num:
        st.session_state.current_q_id = selected_num
        st.session_state.submitted = False
        st.session_state.selected_options = []

elif mode == mode_range:
    range_start, range_end = st.sidebar.slider(
        "문제 범위 지정",
        min_value=min(all_q_ids),
        max_value=max(all_q_ids),
        value=(1, 50)
    )
    active_q_list = [qid for qid in all_q_ids if range_start <= qid <= range_end]
    if active_q_list and st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

elif mode == mode_short:
    keywords = [
        "CodePipeline / CodeBuild", "CloudFormation / CDK", "CloudWatch / X-Ray",
        "Organizations / IAM", "Auto Scaling / EC2", "Lambda / ECS", "Security / KMS"
    ]
    selected_kw = st.sidebar.selectbox("주제 선택:", keywords)
    filtered_q = []
    kw_clean = selected_kw.split(" / ")[0]
    for q in questions:
        text = f"{q['question']} {' '.join(q['options'].values())} {q['explanation']}".lower()
        if kw_clean.lower() in text:
            filtered_q.append(q["id"])
    if filtered_q:
        active_q_list = filtered_q
        st.sidebar.caption(f"'{selected_kw}' 관련 문제: {len(filtered_q)}개 발견")
    if active_q_list and st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

elif mode == mode_note:
    filter_type = st.sidebar.radio("노트 선택", ["📌 북마크한 문제", "❌ 틀린 문제"])
    if filter_type == "📌 북마크한 문제":
        active_q_list = sorted(list(st.session_state.bookmarks))
    else:
        active_q_list = [qid for qid, res in st.session_state.history.items() if not res["is_correct"]]
    
    if not active_q_list:
        st.sidebar.info("해당하는 문제가 아직 없습니다.")
        active_q_list = all_q_ids
    if st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

# Sidebar Stats
st.sidebar.divider()
st.sidebar.subheader("📊 학습 현황")
total_tried = len(st.session_state.history)
correct_cnt = sum(1 for v in st.session_state.history.values() if v["is_correct"])
acc_rate = (correct_cnt / total_tried * 100) if total_tried > 0 else 0.0

st.sidebar.metric("풀어본 문제 수", f"{total_tried} / {len(questions)}")
st.sidebar.metric("정답률", f"{acc_rate:.1f}%", delta=f"{correct_cnt}개 정답")

# Current Question Data
q_data = q_dict[st.session_state.current_q_id]
q_id = q_data["id"]
q_text = q_data["question"]
options = q_data["options"]
correct_ans = q_data["answer"]
is_multi = len(correct_ans) > 1

# Control Bar
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 1.5, 1])
curr_idx = active_q_list.index(q_id) if q_id in active_q_list else 0

with ctrl_col1:
    st.caption(f"**진행 상황:** {curr_idx + 1} / {len(active_q_list)} 번 (전체 DB ID: #{q_id})")

with ctrl_col2:
    mem_mode = st.toggle(
        "💡 암기 모드 (키워드 강조)",
        value=st.session_state.get("memory_mode", False),
        key="memory_mode_toggle"
    )
    st.session_state.memory_mode = mem_mode

with ctrl_col3:
    is_bm = q_id in st.session_state.bookmarks
    bm_label = "📌 북마크 해제" if is_bm else "📌 북마크 추가"
    if st.button(bm_label, use_container_width=True):
        if is_bm:
            st.session_state.bookmarks.remove(q_id)
        else:
            st.session_state.bookmarks.add(q_id)
        st.rerun()

# Display Card
is_mem_on = st.session_state.get("memory_mode", False)
display_q_text = q_data.get("question_highlighted", q_text) if is_mem_on else q_text
curr_options = q_data.get("options_highlighted", options) if is_mem_on else options

multi_label = f"(복수 선택 - {len(correct_ans)}개 선택)" if is_multi else "(단일 선택)"
st.markdown(f"""
<div class="aws-card">
    <div class="q-number-title">
        QUESTION NO: {q_id} <span style="font-size: 0.9rem; font-weight: 500; color: #545B64; margin-left: 8px;">{multi_label}</span>
    </div>
    <div class="q-text-body">{display_q_text}</div>
</div>
""", unsafe_allow_html=True)

# Option Selections
st.markdown("##### 📝 보기 선택")
user_selections = []

if is_multi:
    st.caption(f"💡 정답이 {len(correct_ans)}개인 복수 선택 문제입니다. {len(correct_ans)}개의 항목을 선택하세요.")
    for key, val in curr_options.items():
        checked = st.checkbox(f"**{key}.** {val}", key=f"q_{q_id}_opt_{key}")
        if checked:
            user_selections.append(key)
else:
    radio_opts = [f"{key}. {val}" for key, val in curr_options.items()]
    selected_radio = st.radio(
        "가장 적절한 답안을 선택하십시오:",
        options=radio_opts,
        index=None,
        key=f"q_{q_id}_radio"
    )
    if selected_radio:
        user_selections = [selected_radio[0]]

st.write("")

# Navigation Buttons
nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])

with nav_col1:
    if st.button("◀ 이전 문제", disabled=(curr_idx == 0), use_container_width=True):
        st.session_state.current_q_id = active_q_list[curr_idx - 1]
        st.session_state.submitted = False
        st.session_state.selected_options = []
        st.rerun()

with nav_col2:
    submit_btn = st.button("정답 확인 및 제출", type="primary", use_container_width=True, disabled=st.session_state.submitted)

with nav_col3:
    if st.button("다음 문제 ▶", disabled=(curr_idx == len(active_q_list) - 1), use_container_width=True):
        st.session_state.current_q_id = active_q_list[curr_idx + 1]
        st.session_state.submitted = False
        st.session_state.selected_options = []
        st.rerun()

if submit_btn:
    if not user_selections:
        st.warning("답안을 먼저 선택해 주십시오.")
    else:
        st.session_state.submitted = True
        st.session_state.selected_options = sorted(user_selections)
        is_correct = sorted(user_selections) == sorted(correct_ans)
        
        st.session_state.history[q_id] = {
            "user_ans": sorted(user_selections),
            "is_correct": is_correct
        }
        st.rerun()

# Grading & Explanation Result
if st.session_state.submitted or (q_id in st.session_state.history):
    history_data = st.session_state.history.get(q_id, {
        "user_ans": st.session_state.selected_options,
        "is_correct": sorted(st.session_state.selected_options) == sorted(correct_ans)
    })
    
    is_correct = history_data["is_correct"]
    user_ans_str = ", ".join(history_data["user_ans"])
    correct_ans_str = ", ".join(correct_ans)
    
    if is_correct:
        st.markdown(f"""
        <div class="result-pass">
            ✓ 정답입니다! (선택한 답안: {user_ans_str})
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="result-fail">
            ✗ 오답입니다. (선택한 답안: {user_ans_str} | 정답: {correct_ans_str})
        </div>
        """, unsafe_allow_html=True)
    
    with st.expander("💡 정답 및 상세 해설 보기", expanded=True):
        st.markdown(f"**정답:** `{correct_ans_str}`")
        clean_exp = re.sub(r'</?(b|strong|span)[^>]*>', '', q_data['explanation'])
        st.markdown(f"**해설:**\n{clean_exp}")
