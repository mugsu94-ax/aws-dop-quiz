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
# 데이터베이스 동기화 및 사용자 편집 DB (SQLite)
# =========================================
DB_PATH = "dop_c02_user_progress.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 사용자 풀이 이력 및 북마크
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
    # 사용자 직접 수정 문제/정답/해설 저장 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS custom_edits (
            q_id INTEGER PRIMARY KEY,
            question TEXT,
            options TEXT,
            answer TEXT,
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
    opts_json = json.dumps(options_dict, ensure_ascii=False)
    ans_json = json.dumps(answer_list, ensure_ascii=False)
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO custom_edits (q_id, question, options, answer, explanation, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(q_id) DO UPDATE SET
            question=excluded.question,
            options=excluded.options,
            answer=excluded.answer,
            explanation=excluded.explanation,
            updated_at=excluded.updated_at
    """, (q_id, question, opts_json, ans_json, explanation, now))
    conn.commit()
    conn.close()

def db_load_custom_edits():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT q_id, question, options, answer, explanation FROM custom_edits')
    rows = c.fetchall()
    conn.close()
    edits = {}
    for row in rows:
        qid, q_text, opts_str, ans_str, exp_text = row
        edits[qid] = {
            "question": q_text,
            "options": json.loads(opts_str),
            "answer": json.loads(ans_str),
            "explanation": exp_text
        }
    return edits

def db_delete_custom_edit(q_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM custom_edits WHERE q_id=?', (q_id,))
    conn.commit()
    conn.close()

# =========================================
# 하이라이트 자동 생성 헬퍼 함수
# =========================================
def auto_generate_highlights(q_text, options_dict, answer_list):
    # 1. Question Highlight: 지문의 핵심 구문 강조
    sents = [s.strip() for s in re.split(r'[\n\.]', q_text) if len(s.strip()) > 10]
    q_hl = q_text
    if len(sents) >= 2:
        target_sents = sents[-2:]
        for ts in target_sents:
            if ts in q_hl and not '<span' in ts:
                q_hl = q_hl.replace(ts, f'<span style="color: #0073BB; font-weight: bold;">{ts}</span>', 1)
    elif len(sents) == 1:
        ts = sents[0]
        if ts in q_hl:
            q_hl = q_hl.replace(ts, f'<span style="color: #0073BB; font-weight: bold;">{ts}</span>', 1)

    # 2. Options Highlight: 정답 보지의 유일 키워드/문장만 강조
    opts_hl = {}
    incorrect_texts = [options_dict[k] for k in options_dict if k not in answer_list]

    for k, val in options_dict.items():
        if k in answer_list:
            opt_sents = [s.strip() for s in re.split(r'[\n\.]', val) if len(s.strip()) > 5]
            best_clause = None
            for os_item in opt_sents:
                is_shared = False
                for inc_val in incorrect_texts:
                    if os_item[:15].lower() in inc_val.lower():
                        is_shared = True
                        break
                if not is_shared:
                    best_clause = os_item
                    break
            if best_clause and best_clause in val:
                opts_hl[k] = val.replace(best_clause, f':blue[**{best_clause}**]', 1)
            else:
                opts_hl[k] = f':blue[**{val}**]'
        else:
            opts_hl[k] = val

    return q_hl, opts_hl

# =========================================
# 데이터 로드 (파일 + DB 커스텀 편집 오버레이)
# =========================================
def load_questions():
    possible_paths = [
        "dop-c02-questions-v4.json",
        "dop-c02-questions-v3.json",
        "dop-c02-questions-v2.json",
        "dop-c02-questions-v1.json",
        "dop-c02-questions.json",
        "/workspace/artifacts/dop-c02-questions-v4.json",
        "/workspace/artifacts/dop-c02-questions-v3.json",
        "/workspace/artifacts/dop-c02-questions.json"
    ]
    json_path = None
    for p in possible_paths:
        if os.path.exists(p):
            json_path = p
            break
            
    if not json_path:
        st.error("dop-c02-questions.json 데이터 파일을 찾을 수 없습니다.")
        st.stop()
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # DB에 커스텀 수정된 문제 오버레이 적용
    custom_edits = db_load_custom_edits()
    for q in data:
        qid = q["id"]
        if qid in custom_edits:
            ced = custom_edits[qid]
            q["question"] = ced["question"]
            q["options"] = ced["options"]
            q["answer"] = ced["answer"]
            q["explanation"] = ced["explanation"]
            q_hl, opts_hl = auto_generate_highlights(q["question"], q["options"], q["answer"])
            q["question_highlighted"] = q_hl
            q["options_highlighted"] = opts_hl

        # 마크다운 잔여 별표 정제
        q["question"] = re.sub(r'\*\*(.*?)\*\*', r'\1', q["question"])
        if "options" in q and isinstance(q["options"], dict):
            for k in q["options"]:
                q["options"][k] = re.sub(r'\*\*(.*?)\*\*', r'\1', q["options"][k])
        if "explanation" in q:
            q["explanation"] = re.sub(r'\*\*(.*?)\*\*', r'\1', q["explanation"])
            
    return data, json_path

try:
    questions, loaded_json_path = load_questions()
    q_dict = {q["id"]: q for q in questions}
    all_q_ids = [q["id"] for q in questions]
except Exception as e:
    st.error(f"문제 데이터를 불러오는 데 실패했습니다: {e}")
    st.stop()

# =========================================
# 도메인 카테고리 매핑 & 분류
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
# 경량화 TF-IDF 유사도 엔진
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
    
    top_indices = np.argsort(scores)[::-1]
    similar_items = []
    for idx in top_indices:
        qid = all_q_ids[idx]
        if qid != target_q_id and scores[idx] > 0.1:
            similar_items.append((qid, float(scores[idx])))
            if len(similar_items) >= top_k:
                break
    return similar_items

# =========================================
# 세션 상태 초기화
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
if "user_id" not in st.session_state:
    st.session_state.user_id = ""

# DB에서 복원
if st.session_state.user_id and not st.session_state.history:
    hist, bms = db_load_user_data(st.session_state.user_id)
    st.session_state.history = hist
    st.session_state.bookmarks = bms

# =========================================
# 사이드바 설정 & 업무 위장 스텔스 모드
# =========================================
st.sidebar.markdown("### 🏢 업무 위장 모드 (Stealth)")
work_mode = st.sidebar.toggle(
    "업무 모드 (Stealth Mode)",
    value=st.session_state.get("work_mode", False),
    help="켜면 (주)한진 RPA 프로세스 진단 시스템으로 화면이 위장 전환됩니다."
)
st.session_state.work_mode = work_mode

st.sidebar.divider()
st.sidebar.markdown("### 🔄 PC-모바일 실시간 동기화")
input_user_id = st.sidebar.text_input(
    "동기화 ID 입력:",
    value=st.session_state.user_id,
    placeholder="예: hanjin_dev_01",
    help="동일한 ID를 입력하면 PC와 모바일 간 학습 이력 및 북마크가 자동 동기화됩니다."
)
if input_user_id != st.session_state.user_id:
    st.session_state.user_id = input_user_id
    hist, bms = db_load_user_data(input_user_id)
    st.session_state.history = hist
    st.session_state.bookmarks = bms
    st.sidebar.success(f"ID '{input_user_id}' 동기화 완료!")

st.sidebar.divider()
st.sidebar.title("⚙️ 프로세스 점검 메뉴" if work_mode else "⚙️ 시험 및 분석 메뉴")
st.sidebar.markdown(f"**총 점검 항목:** {len(questions)}개" if work_mode else f"**총 문제 수:** {len(questions)}개")

mode_all = "1. 전체 프로세스 점검 (1~427)" if work_mode else "1. 전체 문제 풀이 (1~427)"
mode_select = "2. 특정 트랜잭션 ID 지정" if work_mode else "2. 특정 문제 번호 지정"
mode_range = "3. 구간 선택 점검" if work_mode else "3. 구간 선택 풀이"
mode_short = "4. 핵심 파이프라인별 퀴즈" if work_mode else "4. 핵심 주제별 퀴즈"
mode_note = "5. 예외 조치 & 북마크 로그" if work_mode else "5. 오답노트 & 북마크"
mode_diag = "6. 약점 진단 리포트" if work_mode else "6. [실시간] 나의 약점 진단 리포트"
mode_guide = "7. RPA 업무 프로세스 표준 가이드" if work_mode else "7. DOP-C02 핵심 개념 & 비교 가이드"

mode = st.sidebar.radio(
    "원하시는 운영 방식을 선택하세요:" if work_mode else "원하시는 공부 방식을 선택하세요:",
    [mode_all, mode_select, mode_range, mode_short, mode_note, mode_diag, mode_guide]
)

st.sidebar.divider()

# =========================================
# 약점 분석 로직 계산
# =========================================
cat_stats = {cat: {"total": 0, "correct": 0} for cat in CATEGORY_KEYWORDS.keys()}
cat_stats["기타 DevOps 아키텍처 공통"] = {"total": 0, "correct": 0}

for q_item in questions:
    qid = q_item["id"]
    cats = classify_question(q_item)
    if qid in st.session_state.history:
        is_corr = st.session_state.history[qid]["is_correct"]
        for cat in cats:
            cat_stats[cat]["total"] += 1
            if is_corr:
                cat_stats[cat]["correct"] += 1

# =========================================
# 헤더 출력
# =========================================
if work_mode:
    st.markdown("""
    <div style="background-color: #232F3E; color: #FFFFFF; padding: 24px 32px; border-radius: 8px; margin-bottom: 24px;">
        <h1 style="color: #FFFFFF !important; font-size: 1.8rem !important; margin-bottom: 6px !important;">
            (주)한진 RPA 프로세스 자동화 운영 및 트랜잭션 진단 콘솔
        </h1>
        <p style="color: #D5D9D9 !important; font-size: 0.95rem !important; margin: 0 !important;">
            UiPath 워크플로우 예외 정밀 분석 & 프로세스 자동화 운영 모니터링 시스템
        </p>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="background-color: #232F3E; color: #FFFFFF; padding: 24px 32px; border-radius: 8px; margin-bottom: 24px;">
        <h1 style="color: #FFFFFF !important; font-size: 2.0rem !important; margin-bottom: 6px !important;">
            ☁️ AWS Certified DevOps Engineer Professional (DOP-C02)
        </h1>
        <p style="color: #D5D9D9 !important; font-size: 1.0rem !important; margin: 0 !important;">
            최신 427개 기출 정밀 복원 & 1:1 키워드 핀포인트 암기 노트 & 문제 직접 편집/저장 시스템
        </p>
    </div>
    """, unsafe_allow_html=True)

# =========================================
# 메뉴별 메인 화면 처리
# =========================================
active_q_list = all_q_ids

if mode == mode_guide:
    st.markdown("### 📚 DOP-C02 핵심 아키텍처 & 비교 가이드" if not work_mode else "### 📚 (주)한진 RPA 자동화 프로세스 표준 가이드")
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📌 핵심 아키텍처 요약", "⚖️ 유사 개념 정밀 비교", "🔑 정답 직결 키워드", "❌ 실전 오답 소거 법칙", "🔍 서비스 사전 검색"
    ])
    with tab1:
        st.markdown("""
        #### ☁️ DOP-C02 핵심 서비스 리드인 요약
        * **AWS CodePipeline & CodeDeploy**: 블루/그린 배포, 인플레이스 배포, 카나리 배포 전략 구현
        * **AWS CloudFormation & StackSets**: 멀티 계정, 멀티 리전 인프라의 코드화(IaC) 및 Drift 감지
        * **AWS Systems Manager (SSM)**: Parameter Store, Patch Manager, Run Command 통합 서버 관리
        * **Amazon CloudWatch & EventBridge**: 로그 데이터 보호 마스킹, 지표 경보 및 이벤트 기반 자동 조치
        * **AWS Organizations & SCP**: 중앙 집중식 가드레일 거버넌스 및 명시적 Deny 정책 관리
        """)
    with tab2:
        st.markdown("""
        | 비교 서비스 | 차이점 및 판별 기준 (Triggers) |
        | :--- | :--- |
        | **SSM Parameter Store vs Secrets Manager** | 간단한 환경변수/무료 ➔ Parameter Store / 암호 자동 순환(Rotation), 고급 보안 ➔ Secrets Manager |
        | **In-Place Deployment vs Blue/Green** | 가용성 저하 허용/비용 절감 ➔ In-Place / 무중단, 빠른 롤백 ➔ Blue/Green |
        | **EventBridge vs CloudWatch Alarm** | 상태 변화 기반 이벤트 트리거 ➔ EventBridge / 수치 지표 임계값 초과 ➔ CloudWatch Alarm |
        | **Control Tower vs Organizations** | 멀티 계정 표준 랜딩존 자동 구축 ➔ Control Tower / 계정 그룹 구조 및 SCP 제어 ➔ Organizations |
        """)
    with tab3:
        st.markdown("""
        * **`Emp-\\d{6}` + 로그 직원 ID 마스킹** ➔ CloudWatch Logs Data Protection Policy + `logs:Unmask` Deny
        * **VPC 엔드포인트 간 통신 수집** ➔ VPC Flow Logs
        * **CodePipeline 교차 계정 배포** ➔ S3 버킷 KMS 키 및 타 계정 IAM 역할 수임 (AssumeRole)
        """)
    with tab4:
        st.markdown("""
        1. **수동 조치(Manual step)가 언급된 선택지**: "운영 오버헤드 최소화" 요구조건 시 90% 이상 오답.
        2. **IAM 권한 허용 시 `Action: "*"` 과도 부여**: 최소 권한 원칙 위배로 오답.
        3. **단일 가용영역(Single-AZ) 배치**: 고가용성(High Availability) 요구 시 오답.
        """)
    with tab5:
        search_kw = st.text_input("🔍 서비스 이름 또는 키워드로 검색 (예: CodePipeline, CloudFormation, SSM, Lambda):", "")
        if search_kw:
            st.info(f"'{search_kw}' 키워드로 관련 문제를 풀려면 왼쪽 사이드바의 '4. 핵심 주제별 퀴즈'를 이용하세요.")
    st.stop()

elif mode == mode_diag:
    st.markdown("### 📊 [실시간] 나의 약점 진단 리포트" if not work_mode else "### 📊 RPA 프로세스 예외 진단 리포트")
    total_solved = sum(s["total"] for s in cat_stats.values())
    if total_solved == 0:
        st.info("아직 풀어본 문제 기록이 없습니다. 문제를 푼 후 오시면 약점 진단 결과를 확인하실 수 있습니다.")
    else:
        st.markdown(f"#### 📈 전체 풀이 현황: 총 {total_solved}개 진단 완료")
        for cat, stat in cat_stats.items():
            if stat["total"] > 0:
                acc = (stat["correct"] / stat["total"]) * 100
                st.markdown(f"**{cat}** (정답률: {acc:.1f}% | {stat['correct']}/{stat['total']}개)")
                st.progress(acc / 100.0)
    st.stop()

elif mode == mode_select:
    selected_num = st.sidebar.number_input(
        "트랜잭션 ID 입력 (1~427)" if work_mode else "문제 번호 입력 (1~427)",
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
        "점검 구간 선택" if work_mode else "풀이 구간 선택",
        min_value=min(all_q_ids),
        max_value=max(all_q_ids),
        value=(min(all_q_ids), max(all_q_ids))
    )
    active_q_list = [i for i in all_q_ids if range_start <= i <= range_end]
    if st.session_state.current_q_id not in active_q_list and active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

elif mode == mode_short:
    st.sidebar.markdown("### 🔑 핵심 주제 패턴")
    keywords = list(CATEGORY_KEYWORDS.keys())
    selected_kw = st.sidebar.selectbox("공부할 주제를 선택하세요:", keywords)
    kws = CATEGORY_KEYWORDS[selected_kw]
    
    filtered_q = []
    for q_item in questions:
        text = f"{q_item.get('question', '')} {' '.join(q_item.get('options', {}).values())} {q_item.get('explanation', '')}".lower()
        if any(kw in text for kw in kws):
            filtered_q.append(q_item["id"])
            
    if filtered_q:
        active_q_list = filtered_q
        st.sidebar.caption(f"'{selected_kw}' 관련 문제: 총 {len(filtered_q)}개 발견")
        if st.session_state.current_q_id not in active_q_list:
            st.session_state.current_q_id = active_q_list[0]
            st.session_state.submitted = False
            st.session_state.selected_options = []
    else:
        st.sidebar.warning("해당하는 문제가 없습니다.")

elif mode == mode_note:
    filter_type = st.sidebar.radio("노트 선택", ["📌 북마크한 문제", "❌ 틀린 문제"])
    if filter_type == "📌 북마크한 문제":
        active_q_list = sorted(list(st.session_state.bookmarks))
    else:
        wrong_ids = [qid for qid, h in st.session_state.history.items() if not h["is_correct"]]
        active_q_list = sorted(wrong_ids)
        
    if not active_q_list:
        st.sidebar.info("해당하는 문제가 아직 없습니다.")
        st.info("북마크나 오답 기록이 없습니다.")
        st.stop()
    elif st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

# 사이드바 학습 현황
st.sidebar.divider()
st.sidebar.subheader("📊 진단 현황" if work_mode else "📊 학습 현황")
total_tried = len(st.session_state.history)
correct_cnt = sum(1 for h in st.session_state.history.values() if h["is_correct"])
acc_rate = (correct_cnt / total_tried * 100) if total_tried > 0 else 0.0

st.sidebar.metric("진단 처리 항목" if work_mode else "풀어본 문제 수", f"{total_tried} / {len(questions)}")
st.sidebar.metric("정상 처리율" if work_mode else "정답률", f"{acc_rate:.1f}%", delta=f"{correct_cnt}개 정답")

if st.sidebar.button("🔄 진단 이력 초기화" if work_mode else "🔄 학습 기록 초기화"):
    if st.session_state.get("user_id", ""):
        db_delete_user_data(st.session_state.user_id)
    st.session_state.history = {}
    st.session_state.bookmarks = set()
    st.session_state.submitted = False
    st.rerun()

# =========================================
# 현재 문제 카드 구성
# =========================================
q_data = q_dict[st.session_state.current_q_id]
q_id = q_data["id"]
q_text = q_data["question"]
options = q_data["options"]
correct_ans = q_data["answer"]
is_multi = len(correct_ans) > 1

q_cats = classify_question(q_data)
st.caption("🏷️ **RPA 프로세스 분류:** " if work_mode else "🏷️ **분류 카테고리:** " + ", ".join([f"`{c}`" for c in q_cats]))

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
    is_bookmarked = q_id in st.session_state.bookmarks
    bm_label = "📌 북마크 해제" if is_bookmarked else "📌 북마크 추가"
    if st.button(bm_label, use_container_width=True):
        if is_bookmarked:
            st.session_state.bookmarks.remove(q_id)
            db_save_bookmark(st.session_state.get("user_id", ""), q_id, False)
        else:
            st.session_state.bookmarks.add(q_id)
            db_save_bookmark(st.session_state.get("user_id", ""), q_id, True)
        st.rerun()

# 카드 출력
is_mem_on = st.session_state.get("memory_mode", False)
display_q_text = q_data.get("question_highlighted", q_text) if is_mem_on else q_text
curr_options = q_data.get("options_highlighted", options) if is_mem_on else options

TICKET_TITLE = f"트랜잭션 ID: #RPA-TRX-{q_id} | (주)한진 RPA 프로세스 점검" if work_mode else f"QUESTION NO: #{q_id}"
multi_label = f"(복수 선택 - {len(correct_ans)}개 선택)" if is_multi else "(단일 선택)"

st.markdown(f"""
<div style="background-color: #F8F9FA; border: 1px solid #E0E0E0; border-radius: 8px; padding: 24px; margin-bottom: 20px;">
    <div style="font-size: 1.15rem; font-weight: 700; color: #232F3E; margin-bottom: 12px; border-bottom: 2px solid #0073BB; padding-bottom: 8px;">
        {TICKET_TITLE} <span style="font-size: 0.9rem; font-weight: 500; color: #545B64; margin-left: 8px;">{multi_label}</span>
    </div>
    <div style="font-size: 1.02rem; line-height: 1.7; color: #16191F;">{display_q_text}</div>
</div>
""", unsafe_allow_html=True)

# =========================================
# ✏️ 문제 / 정답 / 해설 즉시 편집 (수정 모드)
# =========================================
with st.expander("✏️ 문제 / 정답 / 해설 즉시 편집 (수정 모드)" if not work_mode else "✏️ 트랜잭션 점검 기준 / 가이드 즉시 편집", expanded=False):
    st.info("💡 잘못된 정답이나 해설을 직접 고치고 저장할 수 있습니다. 저장 시 내장 DB 및 JSON 데이터셋에 즉시 반영됩니다.")
    
    edit_q = st.text_area("질문 지문 수정:", value=q_data["question"], height=120, key=f"edit_q_{q_id}")
    
    st.markdown("##### 보기 항목 수정:")
    edit_opts = {}
    for k_opt, v_opt in q_data["options"].items():
        edit_opts[k_opt] = st.text_area(f"보기 {k_opt} 수정:", value=v_opt, height=70, key=f"edit_opt_{q_id}_{k_opt}")
        
    all_keys = list(q_data["options"].keys())
    edit_ans = st.multiselect(
        "정답 선택 (복수 선택 가능):",
        options=all_keys,
        default=[a for a in q_data["answer"] if a in all_keys],
        key=f"edit_ans_{q_id}"
    )
    
    edit_exp = st.text_area("해설 내용 수정:", value=q_data["explanation"], height=160, key=f"edit_exp_{q_id}")
    
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        if st.button("💾 변경사항 저장", type="primary", use_container_width=True, key=f"save_edit_btn_{q_id}"):
            if not edit_ans:
                st.warning("최소 1개 이상의 정답을 선택하셔야 합니다.")
            else:
                # 1. 데이터 업데이트
                q_data["question"] = edit_q
                q_data["options"] = edit_opts
                q_data["answer"] = sorted(edit_ans)
                q_data["explanation"] = edit_exp
                
                # 2. 하이라이트 재생성
                q_hl, opts_hl = auto_generate_highlights(edit_q, edit_opts, sorted(edit_ans))
                q_data["question_highlighted"] = q_hl
                q_data["options_highlighted"] = opts_hl
                
                # 3. DB에 커스텀 편집 저장
                db_save_custom_edit(q_id, edit_q, edit_opts, sorted(edit_ans), edit_exp)
                
                # 4. JSON 파일로 저장 (v4)
                try:
                    target_json_path = "dop-c02-questions-v4.json"
                    with open(target_json_path, "w", encoding="utf-8") as f_out:
                        json.dump(questions, f_out, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                    
                st.success(f"✅ #{q_id}번 문제/정답/해설이 성공적으로 수정 및 저장되었습니다!")
                st.rerun()
                
    with btn_col2:
        if st.button("🔄 이 문제 편집 내용 초기화 (원본 복원)", use_container_width=True, key=f"reset_edit_btn_{q_id}"):
            db_delete_custom_edit(q_id)
            st.success(f"#{q_id}번 문제가 원본으로 복원되었습니다.")
            st.rerun()

    # 수정본 전체 JSON 다운로드 버튼
    st.divider()
    st.download_button(
        label="📥 수정된 전체 JSON 데이터셋 다운로드 (dop-c02-questions-v4.json)",
        data=json.dumps(questions, ensure_ascii=False, indent=2),
        file_name="dop-c02-questions-v4.json",
        mime="application/json",
        use_container_width=True
    )

# =========================================
# 보기 선택 및 제출 처리
# =========================================
SELECT_HEADER = "📋 워크플로우 예외 조치 가이드 선택" if work_mode else "📋 가장 적절한 답안을 선택하십시오"
BTN_PREV = "◀ 이전 항목" if work_mode else "◀ 이전 문제"
BTN_NEXT = "다음 항목 ▶" if work_mode else "다음 문제 ▶"
BTN_SUBMIT = "▶ 예외 분석 및 모니터링 검증" if work_mode else "▶ 답안 제출 및 해설 확인"
GUIDE_HEADER = "💡 표준 원인 분석 및 조치 가이드라인" if work_mode else "💡 정답 도출 공식 및 해설 가이드"

st.markdown(f"##### {SELECT_HEADER}")
user_selections = []

if is_multi:
    st.caption(f"💡 조치 항목 {len(correct_ans)}개를 복수 선택하세요." if work_mode else f"💡 정답이 {len(correct_ans)}개인 복수 선택 문제입니다.")
    for key_opt, val_opt in curr_options.items():
        checked = st.checkbox(f"**{key_opt}.** {val_opt}", key=f"q_{q_id}_opt_{key_opt}")
        if checked:
            user_selections.append(key_opt)
else:
    radio_opts = [f"{key_opt}. {val_opt}" for key_opt, val_opt in curr_options.items()]
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

# =========================================
# 채점 결과 및 해설
# =========================================
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
        exp_title = "원인 분석 및 조치 가이드라인" if work_mode else "해설"
        st.markdown(f"**{exp_title}:**\n{display_exp}")

st.divider()

# =========================================
# 유사 트랜잭션 / 문제 추천
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
