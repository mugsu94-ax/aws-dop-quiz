import streamlit as st
import json
import re
import os
import sqlite3
from datetime import datetime
import numpy as np

# =========================================
# 0. 페이지 기본 설정 & 디자인 테마 CSS
# =========================================
st.set_page_config(
    page_title="AWS DOP-C02 모의고사 & 1:1 키워드 암기 노트",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

PRIMARY_COLOR = "#0073BB"
SECONDARY_COLOR = "#232F3E"
ACCENT_COLOR = "#FF9900"
BG_CARD_COLOR = "#F8F9FA"

# =========================================
# 1. 데이터베이스 동기화 함수 (SQLite)
# =========================================
DB_PATH = "dop_c02_user_progress.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id TEXT,
            q_id INTEGER,
            user_ans TEXT,
            is_correct INTEGER,
            is_bookmarked INTEGER,
            updated_at TIMESTAMP,
            PRIMARY KEY (user_id, q_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS custom_edits (
            q_id INTEGER PRIMARY KEY,
            question TEXT,
            options_json TEXT,
            answer_json TEXT,
            explanation TEXT,
            updated_at TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def db_save_attempt(user_id, q_id, user_ans, is_correct):
    if not user_id:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    uans_json = json.dumps(user_ans)
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO user_progress (user_id, q_id, user_ans, is_correct, is_bookmarked, updated_at)
        VALUES (?, ?, ?, ?, 0, ?)
        ON CONFLICT(user_id, q_id) DO UPDATE SET
            user_ans=excluded.user_ans,
            is_correct=excluded.is_correct,
            updated_at=excluded.updated_at
    """, (user_id, q_id, uans_json, 1 if is_correct else 0, now))
    conn.commit()
    conn.close()

def db_save_bookmark(user_id, q_id, is_bookmarked):
    if not user_id:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO user_progress (user_id, q_id, user_ans, is_correct, is_bookmarked, updated_at)
        VALUES (?, ?, '[]', 0, ?, ?)
        ON CONFLICT(user_id, q_id) DO UPDATE SET
            is_bookmarked=excluded.is_bookmarked,
            updated_at=excluded.updated_at
    """, (user_id, q_id, 1 if is_bookmarked else 0, now))
    conn.commit()
    conn.close()

def db_load_user_data(user_id):
    if not user_id:
        return {}, set()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT q_id, user_ans, is_correct, is_bookmarked FROM user_progress WHERE user_id=?', (user_id,))
    rows = c.fetchall()
    conn.close()
    
    history = {}
    bookmarks = set()
    for row in rows:
        qid, uans_json, is_corr, is_bm = row
        if uans_json and uans_json != '[]':
            history[qid] = {
                "user_ans": json.loads(uans_json),
                "is_correct": bool(is_corr)
            }
        if is_bm:
            bookmarks.add(qid)
    return history, bookmarks

def db_delete_user_data(user_id):
    if not user_id:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM user_progress WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()

def db_save_custom_edit(q_id, question, options_dict, answer_list, explanation):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO custom_edits (q_id, question, options_json, answer_json, explanation, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(q_id) DO UPDATE SET
            question=excluded.question,
            options_json=excluded.options_json,
            answer_json=excluded.answer_json,
            explanation=excluded.explanation,
            updated_at=excluded.updated_at
    """, (q_id, question, json.dumps(options_dict, ensure_ascii=False), json.dumps(answer_list, ensure_ascii=False), explanation, now))
    conn.commit()
    conn.close()

def db_load_custom_edits():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT q_id, question, options_json, answer_json, explanation FROM custom_edits')
    rows = c.fetchall()
    conn.close()
    
    edits = {}
    for row in rows:
        qid, q_text, opts_json, ans_json, exp_text = row
        edits[qid] = {
            "question": q_text,
            "options": json.loads(opts_json),
            "answer": json.loads(ans_json),
            "explanation": exp_text
        }
    return edits

def db_reset_custom_edit(q_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM custom_edits WHERE q_id=?', (q_id,))
    conn.commit()
    conn.close()

# =========================================
# 2. 데이터 로드 (dop-c02-questions.txt 최우선)
# =========================================
def load_questions():
    possible_paths = [
        "dop-c02-questions.txt",
        "/workspace/knowledge/dop-c02-questions.txt",
        "dop-c02-questions-v5.json",
        "dop-c02-questions-v4.json",
        "dop-c02-questions-v3.json",
        "dop-c02-questions-v2.json",
        "dop-c02-questions-v1.json",
        "dop-c02-questions.json",
        "/workspace/artifacts/dop-c02-questions-v5.json",
        "/workspace/artifacts/dop-c02-questions.json"
    ]
    json_path = None
    for p in possible_paths:
        if os.path.exists(p):
            json_path = p
            break
            
    if not json_path:
        st.error("dop-c02-questions.txt 데이터 파일을 찾을 수 없습니다.")
        st.stop()
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # 사용자 맞춤 편집 데이터 병합
    custom_edits = db_load_custom_edits()
    for q in data:
        qid = q["id"]
        if qid in custom_edits:
            edit_item = custom_edits[qid]
            q["question"] = edit_item["question"]
            q["options"] = edit_item["options"]
            q["answer"] = edit_item["answer"]
            q["explanation"] = edit_item["explanation"]
            
        # Clean lingering stars
        q["question"] = re.sub(r'\*\*(.*?)\*\*', r'\1', q["question"])
        if "options" in q and isinstance(q["options"], dict):
            for k in q["options"]:
                q["options"][k] = re.sub(r'\*\*(.*?)\*\*', r'\1', q["options"][k])
        if "explanation" in q:
            q["explanation"] = re.sub(r'\*\*(.*?)\*\*', r'\1', q["explanation"])
            
    return data

try:
    questions = load_questions()
    q_dict = {q["id"]: q for q in questions}
    all_q_ids = [q["id"] for q in questions]
except Exception as e:
    st.error(f"문제 데이터를 불러오는 데 실패했습니다: {e}")
    st.stop()

# =========================================
# 3. 하이라이팅 재생성 도우미 함수
# =========================================
def regenerate_highlights(q_item):
    q_text = q_item["question"]
    opts = q_item["options"]
    ans_keys = q_item["answer"]
    
    # Simple clause highlighting for question
    q_sents = [s.strip() for s in re.split(r'[.\n]', q_text) if len(s.strip()) > 15]
    q_hl = q_text
    if len(q_sents) >= 2:
        for ts in q_sents[-2:]:
            q_hl = q_hl.replace(ts, f'<span style="color: #0073BB; font-weight: bold;">{ts}</span>', 1)
    elif len(q_sents) == 1:
        ts = q_sents[0]
        q_hl = q_hl.replace(ts, f'<span style="color: #0073BB; font-weight: bold;">{ts}</span>', 1)
        
    opts_hl = {}
    for k, v in opts.items():
        if k in ans_keys:
            v_sents = [s.strip() for s in re.split(r'[.\n]', v) if len(s.strip()) > 10]
            if v_sents:
                target_s = v_sents[0]
                opts_hl[k] = v.replace(target_s, f':blue[**{target_s}**]', 1)
            else:
                opts_hl[k] = f':blue[**{v}**]'
        else:
            opts_hl[k] = v
            
    q_item["question_highlighted"] = q_hl
    q_item["options_highlighted"] = opts_hl

# =========================================
# 4. 도메인 카테고리 매핑 & 분류
# =========================================
CATEGORY_KEYWORDS = {
    "CI/CD & 배포 자동화 (CodePipeline, CodeDeploy, Jenkins, Git)": [
        "codepipeline", "codebuild", "codedeploy", "jenkins", "git", "github", "codecommit",
        "release", "deployment", "blue/green", "canary", "in-place", "pipeline", "webhook"
    ],
    "IaC & 구성 관리 (CloudFormation, Systems Manager, AMI)": [
        "cloudformation", "stacksets", "nested stack", "drift", "systems manager", "ssm",
        "parameter store", "patch manager", "run command", "ami", "opsworks", "config"
    ],
    "모니터링, 로깅 & 추적 (CloudWatch, CloudTrail, X-Ray)": [
        "cloudwatch", "logs", "metric", "alarm", "cloudtrail", "x-ray", "opensearch",
        "eventbridge", "insights", "data protection", "masking", "subscription filter"
    ],
    "보안, 규정 준수 & 거버넌스 (Organizations, SCP, IAM, Secrets)": [
        "organizations", "scp", "control tower", "iam", "secrets manager", "kms",
        "guardduty", "security hub", "inspector", "macie", "waf", "shield", "abac"
    ],
    "이벤트 기반 & 복원력 아키텍처 (Auto Scaling, SQS, SNS, EventBridge)": [
        "auto scaling", "sqs", "sns", "eventbridge", "lambda", "dlq", "dead-letter",
        "step functions", "kinesis", "firehose", "rto", "rpo", "failover"
    ],
    "고가용성 & 장애 조치 (Multi-Region, Multi-AZ, Load Balancer, DR)": [
        "multi-region", "multi-az", "alb", "nlb", "route 53", "global accelerator",
        "rds proxy", "aurora global", "dynamodb global", "disaster recovery"
    ]
}

def classify_question(q):
    text = f"{q.get('question', '')} {' '.join(q.get('options', {}).values())} {q.get('explanation', '')}".lower()
    matched = []
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            matched.append(cat)
    if not matched:
        matched.append("기타 DevOps 아키텍처 공통")
    return matched

# =========================================
# 5. 경량화 TF-IDF 유사도 엔진
# =========================================
@st.cache_resource
def init_vector_engine(questions_data):
    docs = []
    for q in questions_data:
        opts_str = " ".join(q["options"].values())
        full_text = f"{q['question']} {opts_str} {q['explanation']}"
        tokens = re.findall(r'[가-힣a-zA-Z0-9]+', full_text.lower())
        docs.append(tokens)
        
    vocab = {}
    for doc in docs:
        for t in doc:
            if len(t) > 1 and t not in vocab:
                vocab[t] = len(vocab)
                
    N = len(docs)
    V = len(vocab)
    df_counts = np.zeros(V)
    for doc in docs:
        unique_tokens = set(doc)
        for t in unique_tokens:
            if t in vocab:
                df_counts[vocab[t]] += 1
                
    idf = np.log((N + 1) / (df_counts + 1)) + 1
    
    matrix = np.zeros((N, V), dtype=np.float32)
    for i, doc in enumerate(docs):
        for t in doc:
            if t in vocab:
                matrix[i, vocab[t]] += 1
        matrix[i] = matrix[i] * idf
        norm = np.linalg.norm(matrix[i])
        if norm > 0:
            matrix[i] = matrix[i] / norm
            
    return matrix

try:
    tfidf_matrix = init_vector_engine(questions)
except Exception:
    tfidf_matrix = None

def get_similar_questions(target_q_id, top_k=3):
    if tfidf_matrix is None:
        return []
    try:
        target_idx = all_q_ids.index(target_q_id)
    except ValueError:
        return []
        
    target_vec = tfidf_matrix[target_idx]
    scores = np.dot(tfidf_matrix, target_vec)
    
    ranked_indices = np.argsort(-scores)
    
    results = []
    for idx in ranked_indices:
        q_id_cand = all_q_ids[idx]
        if q_id_cand != target_q_id:
            results.append((q_id_cand, float(scores[idx])))
            if len(results) >= top_k:
                break
    return results

# =========================================
# 6. 세션 상태 초기화 & 사이드바
# =========================================
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

# 스텔스 모드 설정
st.sidebar.markdown("### 🏢 업무 모드 (Stealth Mode)")
work_mode = st.sidebar.toggle(
    "켜기 (RPA 모니터링 시스템 전환)",
    value=st.session_state.get("work_mode", False),
    key="work_mode_toggle"
)
st.session_state.work_mode = work_mode

st.sidebar.divider()
st.sidebar.markdown("### 🔄 PC-모바일 실시간 동기화")
input_user_id = st.sidebar.text_input(
    "사용자 식별 ID 입력:",
    value=st.session_state.get("user_id", ""),
    placeholder="예: hanjin_dev_01"
)
if input_user_id != st.session_state.get("user_id", ""):
    st.session_state.user_id = input_user_id
    if input_user_id:
        h, b = db_load_user_data(input_user_id)
        st.session_state.history = h
        st.session_state.bookmarks = b
        st.sidebar.success(f"'{input_user_id}' 동기화 완료!")
    st.rerun()

st.sidebar.divider()
st.sidebar.title("⚙️ 업무 점검 메뉴" if work_mode else "⚙️ 시험 및 분석 메뉴")

mode_guide = "📚 [표준 규격] RPA 프로세스 설계 가이드" if work_mode else "📚 DOP-C02 핵심 개념 & 비교 가이드"
mode_diag = "📊 [실시간] 프로세스 건강도 진단" if work_mode else "📊 [실시간] 나의 약점 진단 리포트"
mode_all = "1. 전체 점검 항목 (1~427)" if work_mode else "1. 전체 문제 풀이 (1~427)"
mode_select = "2. 특정 항목 ID 지정" if work_mode else "2. 특정 문제 번호 지정"
mode_range = "3. 범위 선택 점검" if work_mode else "3. 구간 선택 풀이"
mode_short = "4. 주요 기능 모듈별 퀴즈" if work_mode else "4. 핵심 주제별 퀴즈"
mode_note = "5. 점검 예외 & 북마크 로그" if work_mode else "5. 오답노트 & 북마크"

mode = st.sidebar.radio(
    "작업 방식을 선택하세요:" if work_mode else "원하시는 공부 방식을 선택하세요:",
    [mode_guide, mode_diag, mode_all, mode_select, mode_range, mode_short, mode_note],
    index=2
)

# 헤더 텍스트 설정
MAIN_TITLE = "(주)한진 RPA 프로세스 자동화 운영 및 트랜잭션 진단 콘솔" if work_mode else "☁️ AWS Certified DevOps Engineer Professional (DOP-C02)"
SUB_TITLE = "UiPath 워크플로우 예외 정밀 분석 & 프로세스 자동화 운영 모니터링 시스템" if work_mode else "최신 427개 기출 정밀 복원 & 1:1 키워드 핀포인트 암기 노트"
TICKET_PREFIX = "트랜잭션 ID: #RPA-TRX-" if work_mode else "QUESTION NO: #"
SELECT_HEADER = "📋 워크플로우 예외 조치 가이드 선택:" if work_mode else "가장 적절한 답안을 선택하십시오:"
BTN_SUBMIT = "▶ 예외 분석 및 모니터링 검증" if work_mode else "▶ 답안 제출 및 해설 확인"
BTN_NEXT = "다음 트랜잭션 ▶" if work_mode else "다음 문제 ▶"
BTN_PREV = "◀ 이전 트랜잭션" if work_mode else "◀ 이전 문제"
GUIDE_HEADER = "💡 표준 원인 분석 및 조치 가이드라인" if work_mode else "💡 정답 도출 공식 및 해설 가이드"
BTN_BOOKMARK_ADD = "📌 관심 점검 등록" if work_mode else "📌 북마크 추가"
BTN_BOOKMARK_REMOVE = "📌 관심 점검 해제" if work_mode else "📌 북마크 해제"

st.markdown(f"""
<div style="background-color: {SECONDARY_COLOR}; color: #FFFFFF; padding: 24px 32px; border-radius: 8px; margin-bottom: 24px;">
    <h1 style="color: #FFFFFF !important; font-size: 1.8rem !important; margin-bottom: 6px !important;">{MAIN_TITLE}</h1>
    <p style="color: #D5D9D9 !important; font-size: 0.95rem !important; margin: 0 !important;">{SUB_TITLE}</p>
</div>
""", unsafe_allow_html=True)

# 약점 분석 로직
cat_stats = {cat: {"total": 0, "correct": 0} for cat in CATEGORY_KEYWORDS.keys()}
for q_item in questions:
    cats = classify_question(q_item)
    qid = q_item["id"]
    for c in cats:
        if c in cat_stats:
            cat_stats[c]["total"] += 1
            if qid in st.session_state.history and st.session_state.history[qid]["is_correct"]:
                cat_stats[c]["correct"] += 1

# 1. 개념 가이드 모드
if mode == mode_guide:
    st.subheader("📚 DOP-C02 핵심 개념 & 비교 가이드")
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📌 1. 핵심 아키텍처 요약",
        "⚖️ 2. 유사 개념 정밀 비교",
        "🔑 3. 정답 직결 키워드 (Triggers)",
        "❌ 4. 실전 오답 소거 5대 법칙",
        "🔍 5. 전수 서비스 사전 & 검색"
    ])
    
    with tab1:
        st.markdown("""
        ### 🏗️ DOP-C02 6대 핵심 도메인 아키텍처
        1. **SDLC & CI/CD 배포 자동화**: CodePipeline, CodeDeploy(In-Place vs Blue/Green), CodeBuild, Jenkins
        2. **IaC & 구성 관리**: CloudFormation, StackSets, Nested Stacks, Drift Detection, Systems Manager
        3. **모니터링, 로깅 & 추적**: CloudWatch, CloudTrail, X-Ray, OpenSearch, EventBridge
        4. **보안, 규정 준수 & 거버넌스**: Organizations, SCP, IAM ABAC, Secrets Manager, KMS
        5. **이벤트 기반 & 복원력 아키텍처**: Auto Scaling Lifecycle Hooks, SQS DLQ, EventBridge, Lambda
        6. **고가용성 & 장애 조치**: Multi-Region Multi-AZ, Route 53 Failover, Aurora Global DB, RDS Proxy
        """)
    with tab2:
        st.markdown("""
        ### ⚖️ 가장 헷갈리기 쉬운 유사 개념 비교 & 구분법
        * **Systems Manager Parameter Store vs Secrets Manager**:
          * Parameter Store: 단순 구성 데이터, 무료/저비용, 기본 암호화.
          * Secrets Manager: 자동 암호 순환(Rotation), 교체 주기 설정, 비용 발생.
        * **CodeDeploy In-Place vs Blue/Green**:
          * In-Place: 기존 EC2 인스턴스에 직접 배포 (다운타임 가능, 롤백 시간 소요).
          * Blue/Green: 새 인스턴스 그룹 생성 후 트래픽 라우팅 (다운타임 제로, 빠른 롤백).
        * **CloudFormation Stacks vs StackSets**:
          * Stacks: 단일 계정, 단일 리전 배포.
          * StackSets: 다중 계정(Organizations), 다중 리전 일괄 배포.
        """)
    with tab3:
        st.markdown("""
        ### 🔑 지문 키워드 ➔ 정답 기술 1:1 매핑 (Triggers)
        * `RTO < 15분, 자동 장애 조치` ➔ **Route 53 Failover + Multi-Region Read Replica / Aurora Global DB**
        * `민감 로그 마스킹, 권한 제한` ➔ **CloudWatch Data Protection Policy + Action: logs:Unmask Deny**
        * `Lambda DB 연결 폭주, Connection Pool` ➔ **RDS Proxy**
        * `멀티 계정 필수 태그 강제` ➔ **AWS Organizations Tag Policy + SCP**
        """)
    with tab4:
        st.markdown("""
        ### ❌ 실전 오답 소거 5대 법칙
        1. **수동 조치 함정**: '수동으로 작업 실행', '매번 콘솔에서 수정'은 100% 오답 (DevOps 핵심은 자동화).
        2. **과도한 맞춤형 코드**: CloudWatch native 마스킹 대신 '복잡한 Lambda 함수 개발'은 운영 오버헤드로 오답.
        3. **단일 점 장애(SPOF)**: Single AZ, 인스턴스 1대 배포는 고가용성 요구조건 시 오답.
        4. **NotAction Deny 오답**: 특정 권한 차단 시 `NotAction` 거부는 예기치 않은 다른 권한까지 차단하므로 오답.
        5. **권한 오남용**: IAM 사용자 생성 후 하드코딩 키 저장은 오답 (IAM 역할 및 Secrets Manager 사용).
        """)
    with tab5:
        search_kw = st.text_input("🔍 서비스 이름 또는 키워드로 검색 (예: CloudFormation, Secrets Manager, Lambda):", "")
        services_dict = {
            "AWS CodePipeline": "지속적 통합 및 지속적 전달(CI/CD) 파이프라인 자동화 서비스",
            "AWS CodeDeploy": "EC2, ECS, Lambda 등에 대한 자동화된 애플리케이션 배포 서비스",
            "AWS CloudFormation": "코드형 인프라(IaC)를 통해 AWS 리소스를 선언적으로 프로비저닝",
            "AWS Systems Manager (SSM)": "노드 관리, 매개변수 저장, 패치 관리 및 원격 명령 실행",
            "Amazon CloudWatch": "AWS 리소스 및 애플리케이션에 대한 실시간 모니터링 및 로깅",
            "AWS Organizations": "여러 AWS 계정을 중앙에서 통합 관리하고 SCP로 거버넌스 적용"
        }
        for s_name, s_desc in services_dict.items():
            if not search_kw or search_kw.lower() in s_name.lower() or search_kw.lower() in s_desc.lower():
                st.markdown(f"**`{s_name}`**: {s_desc}")
    st.stop()

# 2. 약점 진단 화면
if mode == mode_diag:
    st.subheader("📊 [실시간] 나의 약점 진단 리포트")
    for cat, stat in cat_stats.items():
        tot = stat["total"]
        cor = stat["correct"]
        pct = (cor / tot * 100) if tot > 0 else 0.0
        
        status_icon = "🟢" if pct >= 75 else ("🟡" if pct >= 50 else "🔴")
        st.markdown(f"#### {status_icon} {cat}")
        st.progress(pct / 100.0)
        st.caption(f"정답률: {pct:.1f}% ({cor} / {tot} 문제 완료)")
        st.divider()
    st.stop()

# 3. 일반 문제 풀이 모드 처리
active_q_list = all_q_ids

if mode == mode_select:
    selected_num = st.sidebar.number_input(
        "항목 ID 입력 (1~427)" if work_mode else "문제 번호 입력 (1~427)",
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
        "범위 선택" if work_mode else "구간 선택",
        min_value=min(all_q_ids),
        max_value=max(all_q_ids),
        value=(1, 50)
    )
    active_q_list = [qid for qid in all_q_ids if range_start <= qid <= range_end]
    if not active_q_list:
        active_q_list = all_q_ids
    if st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]

elif mode == mode_short:
    keywords = list(CATEGORY_KEYWORDS.keys())
    selected_kw = st.sidebar.selectbox("모듈 선택:" if work_mode else "공부할 주제를 선택하세요:", keywords)
    filtered_q = [qid for qid in all_q_ids if selected_kw in classify_question(q_dict[qid])]
    if filtered_q:
        active_q_list = filtered_q
        st.sidebar.caption(f"총 {len(filtered_q)}개 발견")
        if st.session_state.current_q_id not in active_q_list:
            st.session_state.current_q_id = active_q_list[0]

elif mode == mode_note:
    filter_type = st.sidebar.radio("노트 선택", ["📌 북마크한 문제", "❌ 틀린 문제"])
    if filter_type == "📌 북마크한 문제":
        filtered_q = [qid for qid in all_q_ids if qid in st.session_state.bookmarks]
    else:
        filtered_q = [qid for qid in all_q_ids if qid in st.session_state.history and not st.session_state.history[qid]["is_correct"]]
        
    if filtered_q:
        active_q_list = filtered_q
        if st.session_state.current_q_id not in active_q_list:
            st.session_state.current_q_id = active_q_list[0]
    else:
        st.sidebar.info("해당하는 문제가 아직 없습니다.")
        active_q_list = all_q_ids

# 학습 현황 사이드바
st.sidebar.divider()
st.sidebar.subheader("📊 모니터링 현황" if work_mode else "📊 학습 현황")
total_tried = len(st.session_state.history)
correct_cnt = sum(1 for h in st.session_state.history.values() if h["is_correct"])
acc_rate = (correct_cnt / total_tried * 100) if total_tried > 0 else 0.0

st.sidebar.metric("진단 항목 수" if work_mode else "풀어본 문제 수", f"{total_tried} / {len(questions)}")
st.sidebar.metric("정상 처리율" if work_mode else "정답률", f"{acc_rate:.1f}%", delta=f"{correct_cnt}개 정상" if work_mode else f"{correct_cnt}개 정답")

if st.sidebar.button("🔄 진단 이력 초기화" if work_mode else "🔄 학습 기록 초기화"):
    if st.session_state.get("user_id", ""):
        db_delete_user_data(st.session_state.user_id)
    st.session_state.history = {}
    st.session_state.bookmarks = set()
    st.session_state.submitted = False
    st.rerun()

# 현재 문제 데이터
q_data = q_dict[st.session_state.current_q_id]
q_id = q_data["id"]
q_text = q_data["question"]
options = q_data["options"]
correct_ans = q_data["answer"]
is_multi = len(correct_ans) > 1

q_cats = classify_question(q_data)
st.caption("🏷️ **" + ("RPA 프로세스 분류:" if work_mode else "분류 카테고리:") + "** " + ", ".join([f"`{c}`" for c in q_cats]))

# 컨트롤 액션바
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 1.5, 1])
curr_idx = active_q_list.index(q_id) if q_id in active_q_list else 0

with ctrl_col1:
    st.caption(f"**{'진단 진행 상황' if work_mode else '진행 상황'}:** {curr_idx + 1} / {len(active_q_list)} 번 (전체 DB ID: #{q_id})")

with ctrl_col2:
    mem_mode = st.toggle(
        "💡 핀포인트 키워드 하이라이트",
        value=st.session_state.get("memory_mode", False),
        key="memory_mode_toggle"
    )
    st.session_state.memory_mode = mem_mode

with ctrl_col3:
    is_bookmarked = q_id in st.session_state.bookmarks
    bm_label = BTN_BOOKMARK_REMOVE if is_bookmarked else BTN_BOOKMARK_ADD
    if st.button(bm_label, use_container_width=True):
        if is_bookmarked:
            st.session_state.bookmarks.remove(q_id)
            db_save_bookmark(st.session_state.get("user_id", ""), q_id, False)
        else:
            st.session_state.bookmarks.add(q_id)
            db_save_bookmark(st.session_state.get("user_id", ""), q_id, True)
        st.rerun()

# 카드 양식 (파란선 완전히 제거: border-bottom 없음!)
is_mem_on = st.session_state.get("memory_mode", False)
display_q_text = q_data.get("question_highlighted", q_text) if is_mem_on else q_text
curr_options = q_data.get("options_highlighted", options) if is_mem_on else options

multi_label = f"(복수 선택 - {len(correct_ans)}개 선택)" if is_multi else "(단일 선택)"
st.markdown(f"""
<div style="background-color: {BG_CARD_COLOR}; border: 1px solid #E0E0E0; border-radius: 8px; padding: 24px; margin-bottom: 20px;">
    <div style="font-size: 1.15rem; font-weight: 700; color: #232F3E; margin-bottom: 12px; padding-bottom: 4px;">
        {TICKET_PREFIX}{q_id} <span style="font-size: 0.9rem; font-weight: 500; color: #545B64; margin-left: 8px;">{multi_label}</span>
    </div>
    <div style="font-size: 1.02rem; line-height: 1.7; color: #16191F;">{display_q_text}</div>
</div>
""", unsafe_allow_html=True)

# 보기 선택 영역
st.markdown(f"##### {SELECT_HEADER}")

user_selections = []

if is_multi:
    st.caption(f"💡 조치 항목 {len(correct_ans)}개를 복수 선택하세요." if work_mode else f"💡 정답이 {len(correct_ans)}개인 복수 선택 문제입니다.")
    for key, val in curr_options.items():
        checked = st.checkbox(f"**{key}.** {val}", key=f"q_{q_id}_opt_{key}")
        if checked:
            user_selections.append(key)
else:
    radio_opts = [f"{key}. {val}" for key, val in curr_options.items()]
    selected_radio = st.radio(
        "적절한 조치 가이드를 선택하십시오:" if work_mode else "가장 적절한 답안을 선택하십시오:",
        options=radio_opts,
        index=None,
        key=f"q_{q_id}_radio"
    )
    if selected_radio:
        user_selections = [selected_radio[0]]

st.write("")

nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])

with nav_col1:
    if st.button(BTN_PREV, disabled=(curr_idx == 0), use_container_width=True):
        st.session_state.current_q_id = active_q_list[curr_idx - 1]
        st.session_state.submitted = False
        st.session_state.selected_options = []
        st.rerun()

with nav_col2:
    submit_btn = st.button(BTN_SUBMIT, type="primary", use_container_width=True, disabled=st.session_state.submitted)

with nav_col3:
    if st.button(BTN_NEXT, disabled=(curr_idx == len(active_q_list) - 1), use_container_width=True):
        st.session_state.current_q_id = active_q_list[curr_idx + 1]
        st.session_state.submitted = False
        st.session_state.selected_options = []
        st.rerun()

if submit_btn:
    if not user_selections:
        st.warning("조치 사항 또는 답안을 먼저 선택해 주십시오.")
    else:
        st.session_state.submitted = True
        st.session_state.selected_options = sorted(user_selections)
        is_correct = sorted(user_selections) == sorted(correct_ans)
        
        st.session_state.history[q_id] = {
            "user_ans": sorted(user_selections),
            "is_correct": is_correct
        }
        if st.session_state.get("user_id", ""):
            db_save_attempt(st.session_state.user_id, q_id, sorted(user_selections), is_correct)
        st.rerun()

# 채점 결과 및 해설
if st.session_state.submitted or (q_id in st.session_state.history):
    history_data = st.session_state.history.get(q_id, {
        "user_ans": st.session_state.selected_options,
        "is_correct": sorted(st.session_state.selected_options) == sorted(correct_ans)
    })
    
    is_correct = history_data["is_correct"]
    user_ans_str = ", ".join(history_data["user_ans"])
    correct_ans_str = ", ".join(correct_ans)
    
    txt_pass = '✓ 정상 검증 완료되었습니다!' if work_mode else '✓ 정답입니다!'
    txt_fail = '✗ 예외 조치 실패 (오류 발생)' if work_mode else '✗ 오답입니다.'
    txt_choice = '선택 항목' if work_mode else '선택한 답안'
    txt_guide = '표준 가이드' if work_mode else '정답'
    
    if is_correct:
        st.markdown(f"""
        <div style="background-color: #F2F9F4; border: 2px solid #2E7D32; padding: 20px; border-radius: 8px; color: #1B5E20; font-weight: 700; font-size: 1.08rem; margin-top: 20px;">
            {txt_pass} ({txt_choice}: {user_ans_str})
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background-color: #FDF2F2; border: 2px solid #D32F2F; padding: 20px; border-radius: 8px; color: #C62828; font-weight: 700; font-size: 1.08rem; margin-top: 20px;">
            {txt_fail} ({txt_choice}: {user_ans_str} | {txt_guide}: {correct_ans_str})
        </div>
        """, unsafe_allow_html=True)
    
    with st.expander(GUIDE_HEADER, expanded=True):
        st.markdown(f"**{'표준 조치 코드' if work_mode else '정답'}:** `{correct_ans_str}`")
        display_exp = re.sub(r'</?(b|strong|span)[^>]*>', '', q_data['explanation'])
        st.markdown(f"**{'원인 분석 및 조치 가이드라인' if work_mode else '해설'}:**\n{display_exp}")

st.divider()

# =========================================
# ✏️ 문제 / 정답 / 해설 즉시 편집 (유사 추천 바로 위!)
# =========================================
edit_title = "✏️ 트랜잭션 점검 기준 / 가이드 즉시 편집 (수정 모드)" if work_mode else "✏️ 문제 / 정답 / 해설 즉시 편집 (수정 모드)"
with st.expander(edit_title, expanded=False):
    st.info("💡 내용에 오타나 잘못된 정답/해설이 있는 경우 즉시 수정하고 저장할 수 있습니다.")
    
    edit_q_text = st.text_area("질문 지문 수정:", value=q_data["question"], height=140)
    
    st.markdown("##### 보기 항목 수정:")
    edit_opts = {}
    opt_cols = st.columns(2)
    for idx, (opt_k, opt_v) in enumerate(q_data["options"].items()):
        col = opt_cols[idx % 2]
        with col:
            edit_opts[opt_k] = st.text_area(f"보기 {opt_k}:", value=opt_v, height=80, key=f"edit_opt_{q_id}_{opt_k}")
            
    all_keys = list(q_data["options"].keys())
    edit_ans = st.multiselect("정답 선택:", options=all_keys, default=q_data["answer"])
    
    edit_exp = st.text_area("해설 내용 수정:", value=q_data["explanation"], height=180)
    
    btn_save, btn_reset, btn_dl = st.columns([1.5, 1.5, 2])
    
    with btn_save:
        if st.button("💾 변경사항 저장", type="primary", use_container_width=True):
            if not edit_ans:
                st.error("최소 1개 이상의 정답을 선택해야 합니다.")
            else:
                db_save_custom_edit(q_id, edit_q_text, edit_opts, edit_ans, edit_exp)
                q_data["question"] = edit_q_text
                q_data["options"] = edit_opts
                q_data["answer"] = edit_ans
                q_data["explanation"] = edit_exp
                regenerate_highlights(q_data)
                st.success(f"#{q_id}번 문제 수정사항이 데이터베이스에 영구 저장되었습니다!")
                st.rerun()
                
    with btn_reset:
        if st.button("🔄 이 문제 원본 복원", use_container_width=True):
            db_reset_custom_edit(q_id)
            st.success(f"#{q_id}번 문제가 원본 데이터로 복원되었습니다.")
            st.rerun()
            
    with btn_dl:
        updated_data_json = json.dumps(questions, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 수정된 dop-c02-questions.txt 다운로드",
            data=updated_data_json,
            file_name="dop-c02-questions.txt",
            mime="application/json",
            use_container_width=True
        )

# =========================================
# 💡 유사 문제 추천 (편집 영역 아래!)
# =========================================
st.markdown("##### 💡 이 항목과 원인/조치 패턴이 유사한 프로세스" if work_mode else "##### 💡 이 문제와 핵심 아키텍처가 유사한 문제")

sim_q_list = get_similar_questions(q_id, top_k=3)

if sim_q_list:
    sim_cols = st.columns(len(sim_q_list))
    for i, (sq_id, score) in enumerate(sim_q_list):
        with sim_cols[i]:
            if st.button(f"📌 #{sq_id}번 ({int(score*100)}% 유사)", key=f"sim_btn_{sq_id}"):
                st.session_state.current_q_id = sq_id
                st.session_state.submitted = False
                st.session_state.selected_options = []
                st.rerun()
