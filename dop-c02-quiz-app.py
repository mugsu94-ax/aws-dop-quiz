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
# 데이터베이스 동기화 함수 (SQLite)
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

# =========================================
# 데이터 로드
# =========================================
def load_questions():
    possible_paths = [
        "dop-c02-questions-v3.json",
        "dop-c02-questions-v2.json",
        "dop-c02-questions-v1.json",
        "dop-c02-questions.json",
        "/workspace/artifacts/dop-c02-questions-v2.json",
        "/workspace/artifacts/dop-c02-questions-v1.json",
        "/workspace/artifacts/dop-c02-questions.json",
        "/workspace/scratch/dop-c02-questions-v2.json"
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
        
    for q in data:
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
    scores[target_idx] = -1.0
    
    top_indices = np.argsort(scores)[::-1][:top_k]
    results = []
    for idx in top_indices:
        if scores[idx] > 0.1:
            results.append((all_q_ids[idx], float(scores[idx])))
    return results

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

# =========================================
# 🏢 스텔스 / 업무 모드 (한진 RPA 콘솔) 설정
# =========================================
st.sidebar.markdown("### 🏢 스텔스 모드 설정")
work_mode = st.sidebar.toggle(
    "업무 모드 (Stealth Mode)",
    value=st.session_state.get("work_mode", False),
    help="켜면 (주)한진 RPA 프로세스 진단 시스템으로 화면이 위장 전환됩니다."
)
st.session_state.work_mode = work_mode

# PC-모바일 실시간 동기화 ID
st.sidebar.divider()
st.sidebar.markdown("### 🔄 PC-모바일 실시간 동기화")
input_user_id = st.sidebar.text_input(
    "동기화 사용자 ID 입력:",
    value=st.session_state.user_id,
    placeholder="예: hanjin_dev_01"
)
if input_user_id != st.session_state.user_id:
    st.session_state.user_id = input_user_id
    if input_user_id:
        db_hist, db_bms = db_load_user_data(input_user_id)
        st.session_state.history.update(db_hist)
        st.session_state.bookmarks.update(db_bms)
        st.sidebar.success(f"'{input_user_id}' 사용자 데이터 로드 완료!")

st.sidebar.divider()

# 용어 사전 (일반 모드 vs 스텔스 업무 모드)
if work_mode:
    TITLE_TEXT = "(주)한진 RPA 프로세스 자동화 운영 및 트랜잭션 진단 콘솔"
    SUBTITLE_TEXT = "UiPath 워크플로우 예외 정밀 분석 & 프로세스 자동화 운영 모니터링 시스템"
    TICKET_PREFIX = "트랜잭션 ID: #RPA-TRX-"
    TICKET_SUFFIX = " | (주)한진 RPA 프로세스 점검 항목"
    BTN_SUBMIT = "▶ 예외 분석 및 모니터링 검증"
    BTN_PREV = "◀ 이전 프로세스"
    BTN_NEXT = "다음 프로세스 ▶"
    SELECT_HEADER = "📋 워크플로우 예외 조치 가이드 선택"
    GUIDE_HEADER = "💡 표준 원인 분석 및 조치 가이드라인"
    BTN_BOOKMARK_ADD = "📌 관심 프로세스 등록"
    BTN_BOOKMARK_REMOVE = "📌 관심 프로세스 해제"
    
    mode_concept = "📚 UiPath RPA 개발 표준 가이드"
    mode_weakness = "📊 프로세스 예외 분석 리포트"
    mode_all = "🎯 전수 트랜잭션 모니터링 (1~427)"
    mode_select = "🎯 특정 프로세스 ID 직접 조회"
    mode_range = "🔀 구간 트랜잭션 점검"
    mode_short = "⚡ 워크플로우 예외 키워드 점검"
    mode_note = "📌 예외 로그 & 관심 프로세스 노트"
else:
    TITLE_TEXT = "☁️ AWS Certified DevOps Engineer Professional (DOP-C02) 암기 콘솔"
    SUBTITLE_TEXT = "최신 427개 기출 정밀 복원 & 1:1 키워드 핀포인트 암기 모드 시스템"
    TICKET_PREFIX = "QUESTION NO: #"
    TICKET_SUFFIX = ""
    BTN_SUBMIT = "▶ 답안 제출 및 해설 확인"
    BTN_PREV = "◀ 이전 문제"
    BTN_NEXT = "다음 문제 ▶"
    SELECT_HEADER = "가장 적절한 답안을 선택하십시오:"
    GUIDE_HEADER = "💡 정답 도출 공식 및 해설 가이드"
    BTN_BOOKMARK_ADD = "📌 북마크 추가"
    BTN_BOOKMARK_REMOVE = "📌 북마크 해제"
    
    mode_concept = "📚 [합격 보장] DOP-C02 핵심 개념 & 비교 가이드"
    mode_weakness = "📊 [실시간] 나의 약점 진단 리포트"
    mode_all = "1. 전체 문제 풀이 (1~427)"
    mode_select = "2. 특정 문제 번호 직접 선택"
    mode_range = "3. 구간 선택 풀이"
    mode_short = "4. 핵심 주제별 퀴즈"
    mode_note = "5. 오답 & 북마크 노트"

# 메인 헤더
st.markdown(f"""
<div style="background-color: #232F3E; color: #FFFFFF; padding: 24px 32px; border-radius: 8px; margin-bottom: 24px;">
    <h1 style="color: #FFFFFF; font-size: 2.0rem; font-weight: 700; margin-bottom: 6px;">{TITLE_TEXT}</h1>
    <p style="color: #D5D9D9; font-size: 1.0rem; margin: 0;">{SUBTITLE_TEXT}</p>
</div>
""", unsafe_allow_html=True)

# 사이드바 메뉴
st.sidebar.title("⚙️ 업무 진단 메뉴" if work_mode else "⚙️ 시험 및 분석 메뉴")
st.sidebar.markdown(f"**총 {('진단 항목' if work_mode else '문제')} 수:** {len(questions)}개")

mode = st.sidebar.radio(
    "원하시는 기능을 선택하세요:",
    [mode_concept, mode_weakness, mode_all, mode_select, mode_range, mode_short, mode_note]
)

st.sidebar.divider()

# 1. 개념 가이드 화면
if mode == mode_concept:
    st.markdown(f"## {mode_concept}")
    if work_mode:
        st.caption("(주)한진 RPA 프로세스 자동화 시스템 및 UiPath 워크플로우 운영을 위한 내부 개발 표준 가이드라인입니다.")
    else:
        st.caption("DOP-C02 시험 427개 기출 문제를 완벽히 다루기 위한 핵심 아키텍처 흐름, 비교 가이드, 키워드 트라이거 정리입니다.")
        
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📌 1. RPA 아키텍처 표준" if work_mode else "📌 1. 핵심 아키텍처 요약",
        "⚖️ 2. 워크플로우 비교 분석" if work_mode else "⚖️ 2. 유사 개념 정밀 비교",
        "🔑 3. 예외 패턴 대응 키워드" if work_mode else "🔑 3. 정답 직결 키워드 (Triggers)",
        "❌ 4. 프로세스 예외 소거 법칙" if work_mode else "❌ 4. 실전 오답 소거 법칙",
        "🔍 5. RPA 모듈 사전 & 검색" if work_mode else "🔍 5. 전수 서비스 사전 & 검색"
    ])
    
    with tab1:
        st.markdown("""
        ### 📌 1. DOP-C02 5대 핵심 파이프라인 & 거버넌스 아키텍처
        
        #### ① CI/CD 배포 전략 (CodePipeline & CodeDeploy)
        * **In-Place Deployment**: 기존 인스턴스에 직접 배포. (다운타임 가능, 인프라 비용 최소)
        * **Blue/Green Deployment**: 구 버전(Blue)과 신 버전(Green) 환경을 완벽 분리 후 트래픽을 한 번에 스위칭. (다운타임 Zero, 즉시 롤백 가능)
        * **Canary / Linear Deployment**: CodeDeploy에서 10분마다 10%씩 비율을 점진적으로 높여가며 배포하는 방식.

        #### ② Infrastructure as Code & 멀티 계정 관리 (CloudFormation & StackSets)
        * **CloudFormation StackSets**: 하나의 템플릿으로 **수십 개의 AWS 계정 및 다중 리전**에 스택을 자동 생성 및 업데이트.
        * **Drift Detection (드리프트 감지)**: 콘솔에서 수동으로 변경된 리소스와 CloudFormation 템플릿 간의 차이를 자동 감지.
        * **Nested Stacks (중첩 스택)**: 공통 네트워킹/보안 템플릿을 재사용 가능한 컴포넌트로 분리하여 관리.

        #### ③ 중앙 로깅, 데이터 보호 & 추적 (CloudWatch Logs & X-Ray)
        * **CloudWatch Data Protection**: 로그 수집 시점에 민감한 데이터(`Emp-\\d{6}`, 카드번호 등)를 **자동 마스킹**. (`logs:Unmask` 권한 거부 적용)
        * **AWS X-Ray & Service Lens**: 분산 마이크로서비스 환경에서 요청의 엔드투엔드 지연 시간을 추적 및 병목 구간 시각화.

        #### ④ 중앙 규정 준수 & 가드레일 (Control Tower, Config & SCP)
        * **AWS Control Tower & Landing Zone**: 멀티 계정 보안 표준 계정 구조를 자동으로 설치 및 관리.
        * **SCP (Service Control Policy)**: Organizations 상위 OU 수준에서 루트 사용자까지 포함해 특정 작업(`Denied`)을 중앙 강제 차단.
        * **AWS Config & Conformance Packs**: 리소스 설정의 규정 미준수 여부를 지속 감지 및 SSM Automation으로 자동 수정(Remediation).
        """)
        
    with tab2:
        st.markdown("""
        ### ⚖️ 2. 가장 헷갈리기 쉬운 DOP 유사 개념 정밀 비교
        
        #### ① Parameter Store vs Secrets Manager
        * **SSM Parameter Store**: 일반 구성 매개변수 및 단순 문자열 저장. (기본 무료, 주기적 비밀번호 자동 순환 기능 없음)
        * **AWS Secrets Manager**: DB 자격 증명, OAuth 토큰 등 교체 필요한 암호 저장. **(KMS 연동 + Lambda 기반 자동 비밀번호 순환(Rotation) 내장)**

        #### ② EventBridge Rule vs CloudWatch Metric Alarm
        * **EventBridge Rule**: 특정 이벤트 발생 시점(예: EC2 상태 변경, S3 업로드, GuardDuty 알람)에 **실시간 비동기 트리거**.
        * **CloudWatch Metric Alarm**: 메트릭 지표가 특정 임계값을 넘어 지속될 때(예: CPU > 80% 5분 지속) **상태 기반 호출**.

        #### ③ CloudFormation Ref vs Fn::GetAtt vs Fn::ImportValue
        * **Ref**: 리소스의 물리적 ID (예: Ref InstanceId, Ref TopicName) 반환.
        * **Fn::GetAtt**: 리소스의 세부 속성 (예: GetAtt ALB.DNSName, GetAtt EC2.PrivateIp) 반환.
        * **Fn::ImportValue**: 다른 스택에서 `Outputs`로 `Export`한 교차 스택(Cross-Stack) 변수 참조.
        """)
        
    with tab3:
        st.markdown("""
        ### 🔑 3. 지문 요구사항 ➔ 정답 직결 키워드 (Triggers)
        
        | 지문 요구사항 (Pattern) | 정답 직결 서비스 / 기술 |
        | :--- | :--- |
        | 로그 내 민감 정보/직원 ID 자동 마스킹 | **CloudWatch Logs Data Protection Policy + logs:Unmask Deny** |
        | 멀티 계정/다중 리전에 동일 CloudFormation 배포 | **AWS CloudFormation StackSets** |
        | DB 암호 자동 순환(Rotation) 및 암호화 저장 | **AWS Secrets Manager + AWS KMS** |
        | 규정 미준수 리소스 자동 감지 및 자동 수정 | **AWS Config + Systems Manager Automation** |
        | 배포 중 에러 발생 시 자동 롤백 & 트래픽 차단 | **CodeDeploy CloudWatch Alarm / Route 53 Health Check 롤백** |
        | 배포 운영 오버헤드 최소화 서드파티 통합 | **AWS CodePipeline + GitHub Webhook / Jenkins Plugin** |
        """)
        
    with tab4:
        st.markdown("""
        ### ❌ 4. 실전 오답 소거 5대 법칙
        
        1. **'SCP 정책에 Allow 조항을 추가하여 권한 부여'** ➔ SCP는 권한을 부여할 수 없음 (100% 오답).
        2. **'로그 마스킹을 위해 수동 Lambda 로깅 필터 작성'** ➔ 운영 오버헤드가 크므로 CloudWatch Data Protection 선택이 정답.
        3. **'Secrets Manager 대신 Parameter Store로 비밀번호 자동 순환 구성'** ➔ 자동 순환은 Secrets Manager 전용 기능.
        4. **'단순 모니터링 요구 시 EC2 내 수동 크론탭(Crontab) 스크립트 실행'** ➔ 서버리스 EventBridge/CloudWatch 활용이 정답.
        """)

    with tab5:
        st.markdown("### 🔍 5. 전수 핵심 서비스 사전 & 검색")
        search_kw = st.text_input("🔍 서비스 이름 또는 키워드 검색 (예: CloudFormation, Secrets Manager, Pipeline, Logs):", "")
        
        dop_services = {
            "AWS CodePipeline": "소스-빌드-배포 단계를 자동화하는 CI/CD 오케스트레이션 서비스",
            "AWS CodeBuild": "소스 코드를 컴파일하고 테스트를 실행하는 완전 관리형 빌드 서비스",
            "AWS CodeDeploy": "EC2, ECS, Lambda 등에 애플리케이션 배포를 자동화하는 서비스",
            "AWS CloudFormation": "인프라를 코드로 관리(IaC)하고 템플릿으로 자동 생성하는 서비스",
            "AWS Systems Manager (SSM)": "노드 관리, 패치, 파라미터 저장 및 자동화 작업을 수행하는 서비스",
            "Amazon CloudWatch": "AWS 리소스 지표 수집, 중앙 로그 관리 및 알람을 제공하는 모니터링 서비스",
            "AWS Organizations / Control Tower": "멀티 계정 중앙 구조 관리, SCP 보안 가드레일 강제 서비스",
            "AWS Secrets Manager": "데이터베이스 자격 증명 및 API 키를 KMS로 암호화하고 자동 순환하는 서비스"
        }
        
        for name, desc in dop_services.items():
            if not search_kw or search_kw.lower() in name.lower() or search_kw.lower() in desc.lower():
                st.markdown(f"* **{name}**: {desc}")
    st.stop()

# 2. 약점 진단 화면
elif mode == mode_weakness:
    st.markdown(f"## {mode_weakness}")
    st.caption("프로세스 풀이 데이터를 정밀 분석하여 업무 도메인별 예외 조치 취약 영역을 분석합니다." if work_mode else "풀이 데이터를 분석하여 DOP-C02 핵심 도메인별 취약 영역을 실시간 분석합니다.")
    
    cat_stats = {cat: {"total": 0, "correct": 0} for cat in CATEGORY_KEYWORDS.keys()}
    cat_stats["기타 DevOps 아키텍처 공통"] = {"total": 0, "correct": 0}
    
    for q_id, res in st.session_state.history.items():
        if q_id in q_dict:
            q_item = q_dict[q_id]
            cats = classify_question(q_item)
            for c in cats:
                cat_stats[c]["total"] += 1
                if res["is_correct"]:
                    cat_stats[c]["correct"] += 1
                    
    total_solved = len(st.session_state.history)
    
    if total_solved == 0:
        st.info("💡 아직 진단 이력이 없습니다. 항목을 검증하면 도메인별 취약점이 실시간 계산됩니다!")
    else:
        st.markdown(f"### 📈 전체 운영 진단 현황: **{total_solved}개** 처리 완료" if work_mode else f"### 📈 전체 풀이 현황: **{total_solved}개** 문제 완료")
        col1, col2, col3 = st.columns(3)
        total_correct = sum(1 for h in st.session_state.history.values() if h["is_correct"])
        overall_acc = (total_correct / total_solved * 100) if total_solved > 0 else 0
        
        with col1:
            st.metric("진단 항목 수" if work_mode else "총 풀이 문제 수", f"{total_solved}개")
        with col2:
            st.metric("정상 처리 수" if work_mode else "총 정답 문제 수", f"{total_correct}개")
        with col3:
            st.metric("자동화 정상 처리율" if work_mode else "전체 평균 정답률", f"{overall_acc:.1f}%")
            
        st.divider()
        st.markdown("### 🔍 도메인별 예외 조치 정밀 진단" if work_mode else "### 🔍 도메인별 정답률 정밀 진단")
        
        for cat, s in cat_stats.items():
            if s["total"] > 0:
                acc = (s["correct"] / s["total"]) * 100
                status_icon = "🟢 양호" if acc >= 75 else ("🟡 보완 권장" if acc >= 50 else "🔴 취약 (집중 학습 필요)")
                st.markdown(f"#### {cat} — **{acc:.1f}%** ({s['correct']}/{s['total']}개 성공) | {status_icon}")
                st.progress(int(acc))
                st.divider()
    st.stop()

# 3. 일반 문제 풀이 모드 처리
active_q_list = all_q_ids

if mode == mode_select:
    selected_num = st.sidebar.number_input(
        "프로세스 ID 입력 (1~427)" if work_mode else "문제 번호 입력 (1~427)",
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
        "모니터링 범위 지정" if work_mode else "문제 범위 지정",
        min_value=min(all_q_ids),
        max_value=max(all_q_ids),
        value=(1, 50)
    )
    active_q_list = [qid for qid in all_q_ids if range_start <= qid <= range_end]
    if not active_q_list:
        active_q_list = all_q_ids
    if st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

elif mode == mode_short:
    keywords = ["CodePipeline", "CloudFormation", "CloudWatch", "Systems Manager", "Secrets Manager", "Organizations", "Auto Scaling", "Lambda"]
    selected_kw = st.sidebar.selectbox("예외 키워드 선택:" if work_mode else "핵심 주제 선택:", keywords)
    filtered_q = []
    for q in questions:
        text = f"{q['question']} {' '.join(q['options'].values())} {q['explanation']}"
        if selected_kw.lower() in text.lower():
            filtered_q.append(q["id"])
    if filtered_q:
        active_q_list = filtered_q
    if st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

elif mode == mode_note:
    filter_type = st.sidebar.radio("노트 선택", ["📌 관심 프로세스", "❌ 예외 발생 항목"] if work_mode else ["📌 북마크한 문제", "❌ 틀린 문제"])
    if "북마크" in filter_type or "관심" in filter_type:
        active_q_list = sorted(list(st.session_state.bookmarks))
    else:
        active_q_list = [qid for qid, res in st.session_state.history.items() if not res["is_correct"]]
    if not active_q_list:
        st.sidebar.info("해당하는 항목이 아직 없습니다.")
        active_q_list = all_q_ids
    if st.session_state.current_q_id not in active_q_list:
        st.session_state.current_q_id = active_q_list[0]
        st.session_state.submitted = False
        st.session_state.selected_options = []

# 사이드바 현황
st.sidebar.divider()
st.sidebar.subheader("📊 운영 진단 현황" if work_mode else "📊 학습 현황")
total_tried = len(st.session_state.history)
correct_cnt = sum(1 for v in st.session_state.history.values() if v["is_correct"])
acc_rate = (correct_cnt / total_tried * 100) if total_tried > 0 else 0.0

st.sidebar.metric("진단 처리 항목 수" if work_mode else "풀어본 문제 수", f"{total_tried} / {len(questions)}")
st.sidebar.metric("자동화 정상 처리율" if work_mode else "정답률", f"{acc_rate:.1f}%", delta=f"{correct_cnt}개 정상" if work_mode else f"{correct_cnt}개 정답")

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

# 카테고리 표시
q_cats = classify_question(q_data)
st.caption("🏷️ **RPA 프로세스 분류:** " if work_mode else "🏷️ **분류 카테고리:** " + ", ".join([f"`{c}`" for c in q_cats]))

# 액션바
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 1.5, 1])
curr_idx = active_q_list.index(q_id) if q_id in active_q_list else 0

with ctrl_col1:
    st.caption(f"**진행 상황:** {curr_idx + 1} / {len(active_q_list)} 번 (전체 DB ID: #{q_id})")

with ctrl_col2:
    mem_mode = st.toggle(
        "💡 핵심 워크플로우 하이라이트" if work_mode else "💡 암기 모드 (키워드 강조)",
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

# 카드 양식
is_mem_on = st.session_state.get("memory_mode", False)
display_q_text = q_data.get("question_highlighted", q_text) if is_mem_on else q_text
curr_options = q_data.get("options_highlighted", options) if is_mem_on else options

multi_label = f"(복수 선택 - {len(correct_ans)}개 선택)" if is_multi else "(단일 선택)"
st.markdown(f"""
<div style="background-color: #F8F9FA; border: 1px solid #D5D9D9; border-left: 6px solid #0073BB; border-radius: 8px; padding: 32px; margin-bottom: 24px;">
    <div style="color: #16191F; font-size: 1.25rem; font-weight: 700; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #E9EBED;">
        {TICKET_PREFIX}{q_id}{TICKET_SUFFIX} <span style="font-size: 0.9rem; font-weight: 500; color: #545B64; margin-left: 8px;">{multi_label}</span>
    </div>
    <div style="color: #232F3E; font-size: 1.08rem; line-height: 1.8; font-weight: 400; word-break: keep-all;">{display_q_text}</div>
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

# 유사 트랜잭션 추천
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
