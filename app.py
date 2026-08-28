import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime
import io

# -------------------------------------------------------------
# 1. 페이지 설정 및 모바일 최적화 커스텀 스타일 (CSS)
# -------------------------------------------------------------
st.set_page_config(page_title="스마트 가계부", page_icon="💰", layout="wide")

st.markdown("""
<style>
    /* 1. 우측 상단 GitHub, Deploy, 점 3개 메뉴 영역 숨기기 (왼쪽 ☰ 메뉴는 유지) */
    [data-testid="stToolbar"] {
        display: none !important;
    }
    
    /* 2. 상단 헤더 배경을 투명하게 만들어 화면을 넓게 씀 */
    [data-testid="stHeader"] {
        background-color: transparent !important;
    }

    /* 3. 하단 Streamlit 기본 워터마크(footer) 숨기기 */
    footer {
        display: none !important;
    }
    
    /* 4. Streamlit Cloud 빨간색 하단 호스팅 배너 강제 가리기 (무료버전 워터마크) */
    .viewerBadge_container__1QSob,
    .viewerBadge_link__1S137,
    .viewerBadge_text__1JaDK,
    div[data-testid="stDecoration"],
    #MainMenu {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }

    /* 여백 모바일 최적화 */
    .main .block-container {
        padding-top: 2.5rem; /* ☰ 버튼과 겹치지 않게 상단 여백 살짝 확보 */
        padding-bottom: 2.5rem;
        padding-left: 0.8rem;
        padding-right: 0.8rem;
        max-width: 1000px;
    }
    
    /* 버튼 크기 및 터치 영역 확대 */
    .stButton > button {
        border-radius: 12px;
        font-weight: 600;
        font-size: 15px;
        min-height: 46px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }
    /* 입력 필드 테두리 및 패딩 */
    .stTextInput > div > div > input, 
    .stNumberInput > div > div > input,
    .stSelectbox > div > div {
        border-radius: 10px;
        font-size: 15px;
    }
    /* 통계 지표(Metric) 카드 스타일 */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        padding: 14px 16px;
        border-radius: 14px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        margin-bottom: 8px;
    }
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] {
            background-color: #1e222b;
            border-color: #2f3440;
        }
    }
    /* TOP 3 카테고리 카드 스타일 */
    .top-card {
        background-color: #eef2ff;
        border-left: 4px solid #4f46e5;
        padding: 10px 14px;
        border-radius: 8px;
        margin-bottom: 6px;
        font-size: 14px;
    }
    @media (prefers-color-scheme: dark) {
        .top-card {
            background-color: #262b36;
            border-left-color: #6366f1;
            color: #ffffff;
        }
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "ledger_data.db"

# -------------------------------------------------------------
# 2. SQLite 데이터베이스 초기화 및 테이블 설정
# -------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # 1) 가계부 거래 내역 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            sub_category TEXT,
            amount INTEGER NOT NULL,
            payment_method TEXT,
            is_fixed INTEGER DEFAULT 0,
            memo TEXT
        )
    ''')
    
    # 2) 카테고리/결제수단 설정 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_type TEXT NOT NULL,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    # 3) 정기 고정비 템플릿 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS fixed_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            default_amount INTEGER DEFAULT 0,
            default_payment TEXT NOT NULL,
            memo TEXT
        )
    ''')

    # 4) 월별 목표 예산 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            year_month TEXT PRIMARY KEY,
            budget_amount INTEGER DEFAULT 0
        )
    ''')
    
    # 기본 카테고리 초기 데이터
    c.execute("SELECT COUNT(*) FROM settings")
    if c.fetchone()[0] == 0:
        default_incomes = ["월급", "성과급", "명절보너스", "금융/배당수입", "부수입", "기타수입"]
        default_expenses = ["식비", "주거/통신", "공과금", "보험료", "십일조/기부", "교통/차량", "쇼핑/생활", "문화/여가", "교육", "기타지출"]
        default_payments = ["신한카드", "국민카드", "현대카드", "삼성카드", "체크카드", "급여통장", "계좌이체", "현금"]
        
        for name in default_incomes:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('income', ?)", (name,))
        for name in default_expenses:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('expense', ?)", (name,))
        for name in default_payments:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('payment', ?)", (name,))
        conn.commit()

    # 기본 고정비 템플릿 초기 데이터
    c.execute("SELECT COUNT(*) FROM fixed_templates")
    if c.fetchone()[0] == 0:
        defaults_fixed = [
            ("십일조/기부", "십일조", 0, "계좌이체", "정기 고정비 - 십일조"),
            ("보험료", "본인 종합/실손보험", 0, "계좌이체", "정기 고정비 - 본인보험"),
            ("보험료", "배우자/가족 보험", 0, "계좌이체", "정기 고정비 - 가족보험"),
            ("보험료", "운전자/자동차 보험", 0, "계좌이체", "정기 고정비 - 차량보험"),
            ("보험료", "기타 보장/저축보험", 0, "계좌이체", "정기 고정비 - 기타보험"),
            ("주거/통신", "휴대폰 요금", 0, "신한카드", "정기 고정비 - 이동통신"),
            ("주거/통신", "인터넷/IPTV 요금", 0, "신한카드", "정기 고정비 - 유선통신"),
            ("공과금", "아파트 관리비", 0, "계좌이체", "정기 고정비 - 관리비"),
            ("공과금", "도시가스 요금", 0, "계좌이체", "정기 고정비 - 가스비"),
            ("공과금", "전기/수도 요금", 0, "계좌이체", "정기 고정비 - 공과금"),
            ("문화/여가", "OTT/정기구독료", 0, "현대카드", "정기 고정비 - 구독서비스"),
            ("주거/통신", "월세/대출이자", 0, "계좌이체", "정기 고정비 - 주거비")
        ]
        for item in defaults_fixed:
            c.execute('''
                INSERT INTO fixed_templates (category, sub_category, default_amount, default_payment, memo)
                VALUES (?, ?, ?, ?, ?)
            ''', item)
        conn.commit()

    conn.close()

init_db()

# -------------------------------------------------------------
# 3. 데이터 CRUD 및 헬퍼 함수
# -------------------------------------------------------------
def load_settings():
    conn = get_db()
    df_settings = pd.read_sql_query("SELECT setting_type, name FROM settings", conn)
    conn.close()
    incomes = df_settings[df_settings['setting_type'] == 'income']['name'].tolist()
    expenses = df_settings[df_settings['setting_type'] == 'expense']['name'].tolist()
    payments = df_settings[df_settings['setting_type'] == 'payment']['name'].tolist()
    return incomes, expenses, payments

def add_setting(stype, name):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO settings (setting_type, name) VALUES (?, ?)", (stype, name))
        conn.commit()
    except Exception:
        pass
    conn.close()

def delete_setting(stype, name):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE setting_type = ? AND name = ?", (stype, name))
    conn.commit()
    conn.close()

def load_records():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM records ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

def add_record(date_str, r_type, cat, sub_cat, amount, method, is_fixed, memo):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO records (date, type, category, sub_category, amount, payment_method, is_fixed, memo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (str(date_str), r_type, cat, sub_cat, int(amount), method, 1 if is_fixed else 0, memo))
    conn.commit()
    conn.close()

def upsert_edited_records(original_filtered_df, edited_df):
    conn = get_db()
    c = conn.cursor()
    
    orig_ids = set(original_filtered_df['id'].dropna().astype(int))
    curr_ids = set(edited_df['id'].dropna().astype(int)) if 'id' in edited_df.columns else set()
    deleted_ids = orig_ids - curr_ids
    for d_id in deleted_ids:
        c.execute("DELETE FROM records WHERE id = ?", (d_id,))
        
    for _, row in edited_df.iterrows():
        r_id = row.get('id')
        
        if row.get('삭제') == True:
            if pd.notna(r_id) and str(r_id).isdigit() and int(r_id) > 0:
                c.execute("DELETE FROM records WHERE id = ?", (int(r_id),))
            continue
            
        d_val = row['date']
        d_str = pd.to_datetime(d_val, errors='coerce').strftime("%Y-%m-%d") if pd.notna(d_val) else datetime.today().strftime("%Y-%m-%d")
        
        amt = int(pd.to_numeric(row['amount'], errors='coerce') or 0)
        is_f = 1 if row.get('is_fixed') in [True, 1, '1', 'True', 1.0] else 0
        r_type = str(row['type'])
        cat = str(row['category'])
        sub_cat = str(row.get('sub_category', '') or '')
        pay_m = str(row['payment_method'])
        memo = str(row.get('memo', '') or '')
        
        if pd.notna(r_id) and str(r_id).isdigit() and int(r_id) > 0:
            c.execute('''
                UPDATE records 
                SET date=?, type=?, category=?, sub_category=?, amount=?, payment_method=?, is_fixed=?, memo=?
                WHERE id=?
            ''', (d_str, r_type, cat, sub_cat, amt, pay_m, is_f, memo, int(r_id)))
        else:
            c.execute('''
                INSERT INTO records (date, type, category, sub_category, amount, payment_method, is_fixed, memo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (d_str, r_type, cat, sub_cat, amt, pay_m, is_f, memo))
            
    conn.commit()
    conn.close()

def import_records_from_df(import_df):
    conn = get_db()
    c = conn.cursor()
    required_cols = ['date', 'type', 'category', 'amount', 'payment_method']
    if not all(col in import_df.columns for col in required_cols):
        conn.close()
        return False, "엑셀 필수 열이 누락되었습니다."
    
    count = 0
    for _, row in import_df.iterrows():
        parsed_date = pd.to_datetime(row['date'], errors='coerce')
        date_str = parsed_date.strftime("%Y-%m-%d") if pd.notna(parsed_date) else datetime.today().strftime("%Y-%m-%d")
        
        c.execute('''
            INSERT INTO records (date, type, category, sub_category, amount, payment_method, is_fixed, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str,
            str(row['type']),
            str(row['category']),
            str(row.get('sub_category', '') or ''),
            int(pd.to_numeric(row['amount'], errors='coerce') or 0),
            str(row['payment_method']),
            1 if str(row.get('is_fixed', 0)) in ['1', 'True', '1.0', True] else 0,
            str(row.get('memo', '') or '')
        ))
        count += 1
    conn.commit()
    conn.close()
    return True, f"총 {count}건의 내역을 성공적으로 복원했습니다."

def load_fixed_templates():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM fixed_templates ORDER BY id ASC", conn)
    conn.close()
    return df

def update_template_defaults(t_id, amount, payment):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE fixed_templates 
        SET default_amount = ?, default_payment = ?
        WHERE id = ?
    ''', (int(amount), payment, t_id))
    conn.commit()
    conn.close()

def add_fixed_template(cat, sub_cat, default_amount, default_payment, memo):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO fixed_templates (category, sub_category, default_amount, default_payment, memo)
        VALUES (?, ?, ?, ?, ?)
    ''', (cat, sub_cat, int(default_amount), default_payment, memo))
    conn.commit()
    conn.close()

def update_fixed_template(t_id, cat, sub_cat, default_amount, default_payment, memo):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE fixed_templates 
        SET category = ?, sub_category = ?, default_amount = ?, default_payment = ?, memo = ?
        WHERE id = ?
    ''', (cat, sub_cat, int(default_amount), default_payment, memo, t_id))
    conn.commit()
    conn.close()

def delete_fixed_template(t_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM fixed_templates WHERE id = ?", (t_id,))
    conn.commit()
    conn.close()

def get_budget(ym):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT budget_amount FROM budgets WHERE year_month = ?", (ym,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def set_budget(ym, amount):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO budgets (year_month, budget_amount) VALUES (?, ?)
        ON CONFLICT(year_month) DO UPDATE SET budget_amount = excluded.budget_amount
    ''', (ym, int(amount)))
    conn.commit()
    conn.close()

# -------------------------------------------------------------
# 4. 메인 UI & 메뉴
# -------------------------------------------------------------
income_categories, expense_categories, payment_methods = load_settings()
all_categories = sorted(list(set(expense_categories + income_categories)))

st.title("💰 스마트 가계부")
menu = st.sidebar.radio("📌 바로가기 메뉴", [
    "📝 내역 입력", 
    "📊 월별 단일 분석 & 예산", 
    "📈 월별 지출 비교 (MoM)", 
    "📋 전체 내역 및 바로 수정", 
    "⚙️ 정기 고정비 일괄 등록",
    "🏷️ 분류 및 결제수단 관리"
])

if "amount_input" not in st.session_state:
    st.session_state["amount_input"] = 0

def add_quick_amount(add_val):
    current = st.session_state.get("amount_input", 0)
    st.session_state["amount_input"] = int(current) + add_val

def reset_quick_amount():
    st.session_state["amount_input"] = 0

# -------------------------------------------------------------
# 메뉴 1: 내역 입력
# -------------------------------------------------------------
if menu == "📝 내역 입력":
    st.subheader("📝 새로운 수입 / 지출 입력")
    
    rec_type = st.radio("구분을 선택하세요", ["지출", "수입"], horizontal=True, key="entry_rec_type")
    
    st.caption("⚡️ 빠른 금액 추가 (클릭 시 현재 금액에 누적합산됩니다)")
    btn_cols = st.columns(5)
    btn_cols[0].button("+1만", use_container_width=True, on_click=add_quick_amount, args=(10000,))
    btn_cols[1].button("+5만", use_container_width=True, on_click=add_quick_amount, args=(50000,))
    btn_cols[2].button("+10만", use_container_width=True, on_click=add_quick_amount, args=(100000,))
    btn_cols[3].button("+50만", use_container_width=True, on_click=add_quick_amount, args=(500000,))
    btn_cols[4].button("0원 정정", use_container_width=True, on_click=reset_quick_amount)

    with st.form("record_form"):
        col1, col2 = st.columns(2)
        with col1:
            rec_date = st.date_input("날짜", datetime.today())
        with col2:
            amount = st.number_input(
                "금액 (원)", 
                min_value=0, 
                step=1000, 
                key="amount_input"
            )
            
        col3, col4 = st.columns(2)
        
        if rec_type == "지출":
            with col3:
                category = st.selectbox("지출 카테고리 (대분류)", expense_categories + ["➕ 새 카테고리 직접 입력"], key="exp_cat_select")
                custom_cat = st.text_input("새 지출 카테고리명", placeholder="직접 입력") if category == "➕ 새 카테고리 직접 입력" else None
            with col4:
                sub_category = st.text_input("상세 항목", placeholder="예: 점심식사, 주유비, 커피")
                
            col5, col6 = st.columns(2)
            with col5:
                payment_method = st.selectbox("결제 수단 / 카드", payment_methods + ["➕ 새 결제수단 직접 입력"], key="exp_pay_select")
                custom_method = st.text_input("새 결제수단명", placeholder="직접 입력") if payment_method == "➕ 새 결제수단 직접 입력" else None
            with col6:
                memo = st.text_input("메모 / 사용처", placeholder="예: 스타벅스 남양주점, 쿠팡")
                
            final_category = custom_cat.strip() if custom_cat else category
            final_method = custom_method.strip() if custom_method else payment_method
            
            st.write("")
            is_fixed = st.checkbox("📌 매달 나가는 고정 지출인가요? (공과금, 보험료, 구독료, 통신비 등)")
            
        else:
            with col3:
                category = st.selectbox("수입 항목 (대분류)", income_categories + ["➕ 새 항목 직접 입력"], key="inc_cat_select")
                custom_cat = st.text_input("새 수입 항목명", placeholder="직접 입력") if category == "➕ 새 항목 직접 입력" else None
            with col4:
                sub_category = st.text_input("상세 내용", placeholder="예: 기본급, 추석상여, 배당금")
                
            col5, col6 = st.columns(2)
            with col5:
                inc_pay_options = payment_methods + ["➕ 새 입금수단 직접 입력"]
                default_cash_idx = inc_pay_options.index("현금") if "현금" in inc_pay_options else 0
                payment_method = st.selectbox("입금 계좌 / 수단", inc_pay_options, index=default_cash_idx, key="inc_pay_select")
                custom_method = st.text_input("새 입금수단명", placeholder="직접 입력") if payment_method == "➕ 새 입금수단 직접 입력" else None
            with col6:
                memo = st.text_input("메모 / 비고", placeholder="예: 8월 급여, 용돈 등")
                
            final_category = custom_cat.strip() if custom_cat else category
            final_method = custom_method.strip() if custom_method else payment_method
            is_fixed = False

        st.write("")
        submitted = st.form_submit_button(f"💾 {rec_type} 내역 저장하기", use_container_width=True, type="primary")
        
        if submitted:
            if amount <= 0:
                st.error("금액을 0원보다 크게 입력해주세요.")
            elif not final_category or final_category.startswith("➕"):
                st.error("카테고리명을 정확히 입력해주세요.")
            elif not final_method or final_method.startswith("➕"):
                st.error("결제/입금 수단을 정확히 입력해주세요.")
            else:
                add_record(rec_date, rec_type, final_category, sub_category, amount, final_method, is_fixed, memo)
                if custom_cat:
                    add_setting("expense" if rec_type == "지출" else "income", custom_cat.strip())
                if custom_method:
                    add_setting("payment", custom_method.strip())
                st.session_state["amount_input"] = 0
                st.success(f"🎉 {rec_type} 내역이 성공적으로 저장되었습니다!")
                st.rerun()

# -------------------------------------------------------------
# 메뉴 2: 월별 단일 분석 & 예산
# -------------------------------------------------------------
elif menu == "📊 월별 단일 분석 & 예산":
    st.subheader("📊 월별 수입 / 지출 & 예산 분석")
    df = load_records()
    
    if df.empty:
        st.info("기록된 데이터가 없습니다. 먼저 내역을 입력해주세요.")
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        selected_month = st.selectbox("조회할 월 선택", sorted(df['year_month'].unique(), reverse=True))
        m_df = df[df['year_month'] == selected_month]
        
        income_df = m_df[m_df['type'] == '수입']
        expense_df = m_df[m_df['type'] == '지출']
        
        total_income = income_df['amount'].sum()
        total_expense = expense_df['amount'].sum()
        net_savings = total_income - total_expense
        fixed_expense = expense_df[expense_df['is_fixed'] == 1]['amount'].sum()
        var_expense = expense_df[expense_df['is_fixed'] == 0]['amount'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("총 수입", f"{total_income:,} 원")
        c2.metric("총 지출", f"{total_expense:,} 원")
        c3.metric("순 잉여금(저축)", f"{net_savings:,} 원")
        
        if not expense_df.empty:
            st.write("#### 🏆 이번 달 지출 TOP 3 카테고리")
            top3 = expense_df.groupby('category')['amount'].sum().reset_index().sort_values('amount', ascending=False).head(3)
            t_cols = st.columns(len(top3))
            for i, (_, row) in enumerate(top3.iterrows()):
                pct = (row['amount'] / total_expense * 100) if total_expense > 0 else 0
                with t_cols[i]:
                    st.markdown(f"""
                    <div class="top-card">
                        <strong>{i+1}위. {row['category']}</strong><br/>
                        <span style="font-size: 16px; font-weight: bold; color: #312e81;">{row['amount']:,} 원</span>
                        <span style="font-size: 12px; color: #6b7280;">({pct:.1f}%)</span>
                    </div>
                    """, unsafe_allow_html=True)

        st.write("---")
        st.write("#### 🎯 이번 달 목표 예산 관리")
        current_budget = get_budget(selected_month)
        
        b_col1, b_col2 = st.columns([2, 1])
        with b_col1:
            new_budget = st.number_input(f"{selected_month} 목표 지출 예산 (원)", value=int(current_budget), step=50000)
        with b_col2:
            st.write("")
            st.write("")
            if st.button("예산 저장", use_container_width=True):
                set_budget(selected_month, new_budget)
                st.success("예산이 저장되었습니다.")
                st.rerun()
                
        if current_budget > 0:
            spent_pct = min(total_expense / current_budget, 1.0)
            remaining_budget = current_budget - total_expense
            st.progress(spent_pct, text=f"예산 소진율: {total_expense:,}원 / {current_budget:,}원 ({spent_pct*100:.1f}%)")
            if remaining_budget >= 0:
                st.caption(f"💰 남은 예산: **{remaining_budget:,} 원** 남았습니다.")
            else:
                st.error(f"🚨 예산 초과! **{abs(remaining_budget):,} 원** 더 지출되었습니다.")
        
        st.write("---")
        st.write("#### ⚖️ 고정지출 vs 변동지출")
        fc1, fc2 = st.columns(2)
        fc1.metric("📌 고정지출", f"{fixed_expense:,} 원")
        fc2.metric("🛒 변동지출", f"{var_expense:,} 원")
        
        if total_expense > 0:
            fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.45,
                         title=f"{selected_month} 지출 구조 비율")
            fig.update_layout(margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
            
        st.write("---")
        st.write("#### 💳 결제수단 / 카드별 지출")
        if not expense_df.empty:
            card_sum = expense_df.groupby('payment_method')['amount'].sum().reset_index()
            fig_card = px.bar(card_sum, x='payment_method', y='amount', text_auto=True)
            fig_card.update_layout(margin=dict(t=20, b=20, l=10, r=10), xaxis_title="", yaxis_title="금액(원)")
            st.plotly_chart(fig_card, use_container_width=True)
            
            st.write("#### 🏷️ 카테고리별 지출 비중")
            cat_sum = expense_df.groupby('category')['amount'].sum().reset_index()
            fig_cat = px.pie(cat_sum, values='amount', names='category', hole=0.35)
            fig_cat.update_layout(margin=dict(t=20, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3))
            st.plotly_chart(fig_cat, use_container_width=True)

# -------------------------------------------------------------
# 메뉴 3: 월별 지출 비교 (MoM)
# -------------------------------------------------------------
elif menu == "📈 월별 지출 비교 (MoM)":
    st.subheader("📈 월별 지출 추이 및 전월 대비 비교")
    df = load_records()
    
    if df.empty:
        st.info("비교할 데이터가 없습니다.")
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        exp_df = df[df['type'] == '지출'].copy()
        
        if exp_df.empty:
            st.info("지출 내역이 없습니다.")
        else:
            monthly_summary = exp_df.groupby('year_month').agg(
                총지출=('amount', 'sum'),
                고정지출=('amount', lambda x: x[exp_df.loc[x.index, 'is_fixed'] == 1].sum()),
                변동지출=('amount', lambda x: x[exp_df.loc[x.index, 'is_fixed'] == 0].sum())
            ).reset_index().sort_values('year_month')
            
            monthly_summary['전월대비_증감'] = monthly_summary['총지출'].diff().fillna(0)
            monthly_summary['증감률(%)'] = (monthly_summary['총지출'].pct_change() * 100).fillna(0).round(1)
            
            st.write("#### 📊 월별 총괄 요약")
            st.dataframe(monthly_summary, use_container_width=True)
            
            fig_trend = px.bar(
                monthly_summary, 
                x='year_month', 
                y=['고정지출', '변동지출'], 
                title="월별 지출 구조 추이",
                barmode='stack',
                text_auto=True
            )
            fig_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2), xaxis_title="")
            st.plotly_chart(fig_trend, use_container_width=True)
            
            st.write("---")
            st.write("#### 🏷️ 카테고리별 월간 지출 변화")
            cat_monthly = exp_df.groupby(['year_month', 'category'])['amount'].sum().reset_index()
            
            fig_cat_trend = px.bar(
                cat_monthly,
                x='year_month',
                y='amount',
                color='category',
                title="카테고리별 월별 비교",
                barmode='group',
                text_auto=True
            )
            fig_cat_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3), xaxis_title="")
            st.plotly_chart(fig_cat_trend, use_container_width=True)

# -------------------------------------------------------------
# 메뉴 4: 전체 내역 및 바로 수정
# -------------------------------------------------------------
elif menu == "📋 전체 내역 및 바로 수정":
    st.subheader("📋 전체 내역 관리 및 삭제·수정")
    df = load_records()
    
    tab1, tab2 = st.tabs(["⚡️ 표에서 바로 수정 및 삭제", "💾 엑셀 백업 & 복원(가져오기)"])
    
    with tab1:
        if df.empty:
            st.info("등록된 가계부 내역이 없습니다.")
        else:
            df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
            months = ["전체 월"] + sorted(df['year_month'].unique().tolist(), reverse=True)
            
            s_col1, s_col2 = st.columns([1, 2])
            with s_col1:
                sel_m = st.selectbox("조회할 월 선택", months)
            with s_col2:
                kw = st.text_input("🔎 검색어 (사용처, 상세항목, 카테고리)", placeholder="예: 스타벅스, 신한카드")
                
            filtered_df = df.copy()
            if sel_m != "전체 월":
                filtered_df = filtered_df[filtered_df['year_month'] == sel_m]
            if kw.strip():
                filtered_df = filtered_df[
                    filtered_df['memo'].str.contains(kw, na=False) |
                    filtered_df['sub_category'].str.contains(kw, na=False) |
                    filtered_df['category'].str.contains(kw, na=False)
                ]
                
            st.caption(f"💡 **수정:** 표의 칸을 클릭하여 내용을 변경하세요.<br>💡 **삭제:** 지우고 싶은 항목의 **[🗑️ 삭제]** 체크박스를 누른 후 <b>저장</b>을 누르세요.<br>(조회 항목: 총 {len(filtered_df)}건 / 합계: {filtered_df['amount'].sum():,}원)", unsafe_allow_html=True)
            
            df_edit = filtered_df.drop(columns=['year_month']).copy()
            df_edit.insert(0, '삭제', False)
            
            df_edit['date'] = pd.to_datetime(df_edit['date'], errors='coerce').dt.date
            df_edit['is_fixed'] = df_edit['is_fixed'].apply(lambda x: True if x in [1, '1', True] else False)
            df_edit['amount'] = pd.to_numeric(df_edit['amount'], errors='coerce').fillna(0).astype(int)
            
            edited_data = st.data_editor(
                df_edit,
                column_config={
                    "삭제": st.column_config.CheckboxColumn("🗑️ 삭제", default=False),
                    "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "date": st.column_config.DateColumn("날짜", required=True, format="YYYY-MM-DD"),
                    "type": st.column_config.SelectboxColumn("구분", options=["지출", "수입"], required=True, width="small"),
                    "category": st.column_config.SelectboxColumn("카테고리", options=all_categories, required=True),
                    "sub_category": st.column_config.TextColumn("상세 항목"),
                    "amount": st.column_config.NumberColumn("금액 (원)", min_value=0, step=1000, required=True),
                    "payment_method": st.column_config.SelectboxColumn("결제/입금 수단", options=payment_methods, required=True),
                    "is_fixed": st.column_config.CheckboxColumn("고정지출"),
                    "memo": st.column_config.TextColumn("메모 / 사용처"),
                },
                disabled=["id"],
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic",
                key="ledger_table_editor"
            )
            
            st.write("")
            col_save1, col_save2 = st.columns([2, 1])
            with col_save1:
                if st.button("💾 체크된 항목 삭제 및 수정사항 전체 저장", type="primary", use_container_width=True):
                    upsert_edited_records(filtered_df, edited_data)
                    st.success("🎉 수정한 내용과 삭제된 항목이 안전하게 동기화되었습니다!")
                    st.rerun()
            with col_save2:
                if st.button("🔄 원래대로 복구", use_container_width=True):
                    st.rerun()

    with tab2:
        st.write("#### 📥 1. 현재 가계부 내역 엑셀 다운로드")
        if not df.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='가계부_내역')
            st.download_button(
                label="📥 가계부 전체 엑셀(XLSX) 다운로드 백업",
                data=output.getvalue(),
                file_name=f"가계부_백업_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("백업할 데이터가 없습니다.")
            
        st.write("---")
        st.write("#### 📤 2. 백업 엑셀 파일로 가계부 복원 (가져오기)")
        st.caption("기존에 다운로드해 둔 가계부 엑셀(.xlsx) 파일을 올리면 데이터를 안전하게 DB로 복원합니다.")
        
        uploaded_file = st.file_uploader("백업 엑셀 파일 선택", type=["xlsx", "xls"])
        if uploaded_file is not None:
            try:
                import_df = pd.read_excel(uploaded_file)
                st.write("미리보기:", import_df.head(3))
                if st.button("🚀 이 엑셀 데이터 가계부로 복원하기", use_container_width=True, type="primary"):
                    success, msg = import_records_from_df(import_df)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            except Exception as e:
                st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

# -------------------------------------------------------------
# 메뉴 5: 정기 고정비 일괄 등록
# -------------------------------------------------------------
elif menu == "⚙️ 정기 고정비 일괄 등록":
    st.subheader("⚙️ 정기 고정비 일괄 등록 및 설정")
    tab1, tab2 = st.tabs(["🚀 이번 달 고정비 일괄 등록", "🛠️ 고정비 항목 추가 / 수정 / 삭제"])
    
    with tab1:
        st.info("💡 **입력한 금액과 결제수단은 DB에 자동 기억**되어 다음 달에도 유지됩니다. (0원인 항목은 가계부 등록에서 자동 제외)")
        target_date = st.date_input("등록 기준 일자", datetime.today(), key="fix_target_date")
        
        templates = load_fixed_templates()
        if templates.empty:
            st.warning("등록된 고정비 템플릿 항목이 없습니다. 우측 탭에서 항목을 추가해주세요.")
        else:
            input_values = []
            current_total = 0
            st.write("---")
            
            for idx, row in templates.iterrows():
                t_id = row['id']
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    amt = st.number_input(
                        f"📌 {row['sub_category']} ({row['category']})", 
                        value=int(row['default_amount']), 
                        step=5000, 
                        key=f"tmpl_amt_{t_id}"
                    )
                    current_total += amt
                with col_b:
                    pay_idx = payment_methods.index(row['default_payment']) if row['default_payment'] in payment_methods else 0
                    pay_m = st.selectbox(
                        "결제 수단", 
                        payment_methods, 
                        index=pay_idx, 
                        key=f"tmpl_pay_{t_id}"
                    )
                input_values.append((t_id, row['category'], row['sub_category'], amt, pay_m, row['memo']))
            
            st.write("---")
            st.metric("📊 이번 달 등록 예정 고정비 총액", f"{current_total:,} 원")
            
            save_as_default = st.checkbox("💾 입력/수정한 금액과 결제수단을 다음 달에도 기본값으로 기억하기", value=True)
            
            if st.button("🚀 이번 달 고정비 일괄 가계부 저장", use_container_width=True, type="primary"):
                count = 0
                for t_id, cat, sub, amt, pay_m, memo_txt in input_values:
                    if amt > 0:
                        add_record(target_date, "지출", cat, sub, amt, pay_m, True, memo_txt)
                        count += 1
                    if save_as_default:
                        update_template_defaults(t_id, amt, pay_m)
                
                if count > 0:
                    st.success(f"🎉 총 {count}건({current_total:,}원)의 고정 지출이 가계부에 등록되었으며, 다음 달 기본값으로 안전하게 저장되었습니다!")
                else:
                    if save_as_default:
                        st.success("💾 설정값이 다음 달 기본값으로 저장되었습니다.")
                    else:
                        st.warning("금액이 입력된 항목이 없습니다.")

    with tab2:
        st.write("#### 🛠️ 고정비 항목 관리")
        templates = load_fixed_templates()
        
        st.write("##### 1. 기존 항목 수정 / 삭제")
        if not templates.empty:
            t_options = [f"ID {r['id']} | {r['sub_category']} ({r['category']}) - 기본 {r['default_amount']:,}원 ({r['default_payment']})" for _, r in templates.iterrows()]
            sel_t_opt = st.selectbox("수정 또는 삭제할 항목 선택", t_options)
            
            if sel_t_opt:
                sel_t_id = int(sel_t_opt.split(" | ")[0].replace("ID ", ""))
                t_row = templates[templates['id'] == sel_t_id].iloc[0]
                
                with st.form(f"t_edit_form_{sel_t_id}"):
                    tc1, tc2 = st.columns(2)
                    with tc1:
                        c_idx = expense_categories.index(t_row['category']) if t_row['category'] in expense_categories else 0
                        t_cat = st.selectbox("분류 카테고리", expense_categories, index=c_idx)
                        t_sub = st.text_input("항목명 (예: 본인 실손보험)", value=t_row['sub_category'])
                    with tc2:
                        t_amt = st.number_input("기본 금액 (원)", value=int(t_row['default_amount']), step=5000)
                        p_idx = payment_methods.index(t_row['default_payment']) if t_row['default_payment'] in payment_methods else 0
                        t_pay = st.selectbox("기본 결제수단", payment_methods, index=p_idx)
                    
                    t_memo = st.text_input("메모", value=t_row['memo'])
                    
                    b1, b2 = st.columns(2)
                    with b1:
                        save_t = st.form_submit_button("💾 템플릿 수정 저장", use_container_width=True, type="primary")
                    with b2:
                        del_t = st.form_submit_button("🗑️ 이 항목 삭제", use_container_width=True)
                        
                    if save_t:
                        update_fixed_template(sel_t_id, t_cat, t_sub, t_amt, t_pay, t_memo)
                        st.success(f"'{t_sub}' 항목이 수정되었습니다.")
                        st.rerun()
                    elif del_t:
                        delete_fixed_template(sel_t_id)
                        st.warning("항목이 삭제되었습니다.")
                        st.rerun()
        
        st.write("---")
        st.write("##### 2. 새 고정비 항목 추가")
        with st.form("new_template_form", clear_on_submit=True):
            nc1, nc2 = st.columns(2)
            with nc1:
                new_t_cat = st.selectbox("분류 카테고리", expense_categories)
                new_t_sub = st.text_input("새 항목명 (예: 헬스장 정기권, 부모님 용돈)")
            with nc2:
                new_t_amt = st.number_input("기본 금액 (원)", value=0, step=5000)
                new_t_pay = st.selectbox("기본 결제수단", payment_methods)
            
            new_t_memo = st.text_input("메모", value="정기 고정비")
            add_t_btn = st.form_submit_button("➕ 새 고정비 항목 등록", use_container_width=True, type="primary")
            
            if add_t_btn:
                if not new_t_sub:
                    st.error("항목명을 입력해주세요.")
                else:
                    add_fixed_template(new_t_cat, new_t_sub, new_t_amt, new_t_pay, new_t_memo)
                    st.success(f"'{new_t_sub}' 고정비 항목 추가 완료!")
                    st.rerun()

# -------------------------------------------------------------
# 메뉴 6: 분류 관리
# -------------------------------------------------------------
elif menu == "🏷️ 분류 및 결제수단 관리":
    st.subheader("🏷️ 카테고리 및 결제수단 관리")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("##### 🛒 지출 카테고리")
        st.write(expense_categories)
        new_exp = st.text_input("새 지출 카테고리 추가")
        if st.button("지출 카테고리 추가", use_container_width=True) and new_exp:
            if new_exp not in expense_categories:
                add_setting("expense", new_exp.strip())
                st.success(f"'{new_exp}' 추가 완료!")
                st.rerun()
                
        del_exp = st.selectbox("삭제할 지출 카테고리", ["선택 안 함"] + expense_categories)
        if st.button("지출 카테고리 삭제", use_container_width=True) and del_exp != "선택 안 함":
            delete_setting("expense", del_exp)
            st.warning(f"'{del_exp}' 삭제 완료!")
            st.rerun()

    with col2:
        st.write("##### 💵 수입 카테고리")
        st.write(income_categories)
        new_inc = st.text_input("새 수입 카테고리 추가")
        if st.button("수입 카테고리 추가", use_container_width=True) and new_inc:
            if new_inc not in income_categories:
                add_setting("income", new_inc.strip())
                st.success(f"'{new_inc}' 추가 완료!")
                st.rerun()
                
        del_inc = st.selectbox("삭제할 수입 카테고리", ["선택 안 함"] + income_categories)
        if st.button("수입 카테고리 삭제", use_container_width=True) and del_inc != "선택 안 함":
            delete_setting("income", del_inc)
            st.warning(f"'{del_inc}' 삭제 완료!")
            st.rerun()

    with col3:
        st.write("##### 💳 결제수단 / 카드")
        st.write(payment_methods)
        new_pay = st.text_input("새 카드/결제수단 추가")
        if st.button("결제수단 추가", use_container_width=True) and new_pay:
            if new_pay not in payment_methods:
                add_setting("payment", new_pay.strip())
                st.success(f"'{new_pay}' 추가 완료!")
                st.rerun()
                
        del_pay = st.selectbox("삭제할 결제수단", ["선택 안 함"] + payment_methods)
        if st.button("결제수단 삭제", use_container_width=True) and del_pay != "선택 안 함":
            delete_setting("payment", del_pay)
            st.warning(f"'{del_pay}' 삭제 완료!")
            st.rerun()import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime
import io

# -------------------------------------------------------------
# 1. 페이지 설정 및 모바일 최적화 커스텀 스타일 (CSS)
# -------------------------------------------------------------
st.set_page_config(page_title="스마트 가계부", page_icon="💰", layout="wide")

st.markdown("""
<style>
    /* 상단 우측 메뉴(Fork, GitHub 아이콘 등) 숨기기 (왼쪽 ☰ 메뉴는 유지) */
    [data-testid="stToolbar"] {visibility: hidden !important;}
    .stAppToolbar {display: none !important;}
    
    /* 하단 Hosted with Streamlit 워터마크 완전히 숨기기 */
    footer {display: none !important;}

    /* 여백 모바일 최적화 */
    .main .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2.5rem;
        padding-left: 0.8rem;
        padding-right: 0.8rem;
        max-width: 1000px;
    }
    /* 버튼 크기 및 터치 영역 확대 */
    .stButton > button {
        border-radius: 12px;
        font-weight: 600;
        font-size: 15px;
        min-height: 46px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }
    /* 입력 필드 테두리 및 패딩 */
    .stTextInput > div > div > input, 
    .stNumberInput > div > div > input,
    .stSelectbox > div > div {
        border-radius: 10px;
        font-size: 15px;
    }
    /* 통계 지표(Metric) 카드 스타일 */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        padding: 14px 16px;
        border-radius: 14px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        margin-bottom: 8px;
    }
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] {
            background-color: #1e222b;
            border-color: #2f3440;
        }
    }
    /* TOP 3 카테고리 카드 스타일 */
    .top-card {
        background-color: #eef2ff;
        border-left: 4px solid #4f46e5;
        padding: 10px 14px;
        border-radius: 8px;
        margin-bottom: 6px;
        font-size: 14px;
    }
    @media (prefers-color-scheme: dark) {
        .top-card {
            background-color: #262b36;
            border-left-color: #6366f1;
            color: #ffffff;
        }
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "ledger_data.db"

# -------------------------------------------------------------
# 2. SQLite 데이터베이스 초기화 및 테이블 설정
# -------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # 1) 가계부 거래 내역 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            sub_category TEXT,
            amount INTEGER NOT NULL,
            payment_method TEXT,
            is_fixed INTEGER DEFAULT 0,
            memo TEXT
        )
    ''')
    
    # 2) 카테고리/결제수단 설정 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_type TEXT NOT NULL,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    # 3) 정기 고정비 템플릿 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS fixed_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            default_amount INTEGER DEFAULT 0,
            default_payment TEXT NOT NULL,
            memo TEXT
        )
    ''')

    # 4) 월별 목표 예산 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            year_month TEXT PRIMARY KEY,
            budget_amount INTEGER DEFAULT 0
        )
    ''')
    
    # 기본 카테고리 초기 데이터
    c.execute("SELECT COUNT(*) FROM settings")
    if c.fetchone()[0] == 0:
        default_incomes = ["월급", "성과급", "명절보너스", "금융/배당수입", "부수입", "기타수입"]
        default_expenses = ["식비", "주거/통신", "공과금", "보험료", "십일조/기부", "교통/차량", "쇼핑/생활", "문화/여가", "교육", "기타지출"]
        default_payments = ["신한카드", "국민카드", "현대카드", "삼성카드", "체크카드", "급여통장", "계좌이체", "현금"]
        
        for name in default_incomes:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('income', ?)", (name,))
        for name in default_expenses:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('expense', ?)", (name,))
        for name in default_payments:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('payment', ?)", (name,))
        conn.commit()

    # 기본 고정비 템플릿 초기 데이터
    c.execute("SELECT COUNT(*) FROM fixed_templates")
    if c.fetchone()[0] == 0:
        defaults_fixed = [
            ("십일조/기부", "십일조", 0, "계좌이체", "정기 고정비 - 십일조"),
            ("보험료", "본인 종합/실손보험", 0, "계좌이체", "정기 고정비 - 본인보험"),
            ("보험료", "배우자/가족 보험", 0, "계좌이체", "정기 고정비 - 가족보험"),
            ("보험료", "운전자/자동차 보험", 0, "계좌이체", "정기 고정비 - 차량보험"),
            ("보험료", "기타 보장/저축보험", 0, "계좌이체", "정기 고정비 - 기타보험"),
            ("주거/통신", "휴대폰 요금", 0, "신한카드", "정기 고정비 - 이동통신"),
            ("주거/통신", "인터넷/IPTV 요금", 0, "신한카드", "정기 고정비 - 유선통신"),
            ("공과금", "아파트 관리비", 0, "계좌이체", "정기 고정비 - 관리비"),
            ("공과금", "도시가스 요금", 0, "계좌이체", "정기 고정비 - 가스비"),
            ("공과금", "전기/수도 요금", 0, "계좌이체", "정기 고정비 - 공과금"),
            ("문화/여가", "OTT/정기구독료", 0, "현대카드", "정기 고정비 - 구독서비스"),
            ("주거/통신", "월세/대출이자", 0, "계좌이체", "정기 고정비 - 주거비")
        ]
        for item in defaults_fixed:
            c.execute('''
                INSERT INTO fixed_templates (category, sub_category, default_amount, default_payment, memo)
                VALUES (?, ?, ?, ?, ?)
            ''', item)
        conn.commit()

    conn.close()

init_db()

# -------------------------------------------------------------
# 3. 데이터 CRUD 및 헬퍼 함수
# -------------------------------------------------------------
def load_settings():
    conn = get_db()
    df_settings = pd.read_sql_query("SELECT setting_type, name FROM settings", conn)
    conn.close()
    incomes = df_settings[df_settings['setting_type'] == 'income']['name'].tolist()
    expenses = df_settings[df_settings['setting_type'] == 'expense']['name'].tolist()
    payments = df_settings[df_settings['setting_type'] == 'payment']['name'].tolist()
    return incomes, expenses, payments

def add_setting(stype, name):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO settings (setting_type, name) VALUES (?, ?)", (stype, name))
        conn.commit()
    except Exception:
        pass
    conn.close()

def delete_setting(stype, name):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE setting_type = ? AND name = ?", (stype, name))
    conn.commit()
    conn.close()

def load_records():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM records ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

def add_record(date_str, r_type, cat, sub_cat, amount, method, is_fixed, memo):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO records (date, type, category, sub_category, amount, payment_method, is_fixed, memo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (str(date_str), r_type, cat, sub_cat, int(amount), method, 1 if is_fixed else 0, memo))
    conn.commit()
    conn.close()

def upsert_edited_records(original_filtered_df, edited_df):
    """표에서 수정한 내용(삭제, 업데이트, 신규추가)을 안전하게 반영"""
    conn = get_db()
    c = conn.cursor()
    
    # 1. 기본 UI(휴지통)로 삭제된 행 처리
    orig_ids = set(original_filtered_df['id'].dropna().astype(int))
    curr_ids = set(edited_df['id'].dropna().astype(int)) if 'id' in edited_df.columns else set()
    deleted_ids = orig_ids - curr_ids
    for d_id in deleted_ids:
        c.execute("DELETE FROM records WHERE id = ?", (d_id,))
        
    # 2. 업데이트, 신규 추가, 그리고 체크박스로 삭제된 행 처리
    for _, row in edited_df.iterrows():
        r_id = row.get('id')
        
        # 명시적으로 '삭제' 체크박스에 체크한 경우 삭제 처리
        if row.get('삭제') == True:
            if pd.notna(r_id) and str(r_id).isdigit() and int(r_id) > 0:
                c.execute("DELETE FROM records WHERE id = ?", (int(r_id),))
            continue # 삭제했으므로 업데이트 과정 생략
            
        # 체크되지 않은 일반 데이터는 수정/저장 진행
        d_val = row['date']
        d_str = pd.to_datetime(d_val, errors='coerce').strftime("%Y-%m-%d") if pd.notna(d_val) else datetime.today().strftime("%Y-%m-%d")
        
        amt = int(pd.to_numeric(row['amount'], errors='coerce') or 0)
        is_f = 1 if row.get('is_fixed') in [True, 1, '1', 'True', 1.0] else 0
        r_type = str(row['type'])
        cat = str(row['category'])
        sub_cat = str(row.get('sub_category', '') or '')
        pay_m = str(row['payment_method'])
        memo = str(row.get('memo', '') or '')
        
        if pd.notna(r_id) and str(r_id).isdigit() and int(r_id) > 0:
            c.execute('''
                UPDATE records 
                SET date=?, type=?, category=?, sub_category=?, amount=?, payment_method=?, is_fixed=?, memo=?
                WHERE id=?
            ''', (d_str, r_type, cat, sub_cat, amt, pay_m, is_f, memo, int(r_id)))
        else:
            c.execute('''
                INSERT INTO records (date, type, category, sub_category, amount, payment_method, is_fixed, memo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (d_str, r_type, cat, sub_cat, amt, pay_m, is_f, memo))
            
    conn.commit()
    conn.close()

def import_records_from_df(import_df):
    """엑셀 업로드로 데이터베이스 일괄 복원/추가 (다양한 날짜 포맷 자동 정규화)"""
    conn = get_db()
    c = conn.cursor()
    required_cols = ['date', 'type', 'category', 'amount', 'payment_method']
    if not all(col in import_df.columns for col in required_cols):
        conn.close()
        return False, "엑셀 필수 열이 누락되었습니다."
    
    count = 0
    for _, row in import_df.iterrows():
        parsed_date = pd.to_datetime(row['date'], errors='coerce')
        date_str = parsed_date.strftime("%Y-%m-%d") if pd.notna(parsed_date) else datetime.today().strftime("%Y-%m-%d")
        
        c.execute('''
            INSERT INTO records (date, type, category, sub_category, amount, payment_method, is_fixed, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str,
            str(row['type']),
            str(row['category']),
            str(row.get('sub_category', '') or ''),
            int(pd.to_numeric(row['amount'], errors='coerce') or 0),
            str(row['payment_method']),
            1 if str(row.get('is_fixed', 0)) in ['1', 'True', '1.0', True] else 0,
            str(row.get('memo', '') or '')
        ))
        count += 1
    conn.commit()
    conn.close()
    return True, f"총 {count}건의 내역을 성공적으로 복원했습니다."

def load_fixed_templates():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM fixed_templates ORDER BY id ASC", conn)
    conn.close()
    return df

def update_template_defaults(t_id, amount, payment):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE fixed_templates 
        SET default_amount = ?, default_payment = ?
        WHERE id = ?
    ''', (int(amount), payment, t_id))
    conn.commit()
    conn.close()

def add_fixed_template(cat, sub_cat, default_amount, default_payment, memo):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO fixed_templates (category, sub_category, default_amount, default_payment, memo)
        VALUES (?, ?, ?, ?, ?)
    ''', (cat, sub_cat, int(default_amount), default_payment, memo))
    conn.commit()
    conn.close()

def update_fixed_template(t_id, cat, sub_cat, default_amount, default_payment, memo):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE fixed_templates 
        SET category = ?, sub_category = ?, default_amount = ?, default_payment = ?, memo = ?
        WHERE id = ?
    ''', (cat, sub_cat, int(default_amount), default_payment, memo, t_id))
    conn.commit()
    conn.close()

def delete_fixed_template(t_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM fixed_templates WHERE id = ?", (t_id,))
    conn.commit()
    conn.close()

def get_budget(ym):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT budget_amount FROM budgets WHERE year_month = ?", (ym,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def set_budget(ym, amount):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO budgets (year_month, budget_amount) VALUES (?, ?)
        ON CONFLICT(year_month) DO UPDATE SET budget_amount = excluded.budget_amount
    ''', (ym, int(amount)))
    conn.commit()
    conn.close()

# -------------------------------------------------------------
# 4. 메인 UI & 메뉴
# -------------------------------------------------------------
income_categories, expense_categories, payment_methods = load_settings()
all_categories = sorted(list(set(expense_categories + income_categories)))

st.title("💰 스마트 가계부")
menu = st.sidebar.radio("📌 바로가기 메뉴", [
    "📝 내역 입력", 
    "📊 월별 단일 분석 & 예산", 
    "📈 월별 지출 비교 (MoM)", 
    "📋 전체 내역 및 바로 수정", 
    "⚙️ 정기 고정비 일괄 등록",
    "🏷️ 분류 및 결제수단 관리"
])

if "amount_input" not in st.session_state:
    st.session_state["amount_input"] = 0

def add_quick_amount(add_val):
    current = st.session_state.get("amount_input", 0)
    st.session_state["amount_input"] = int(current) + add_val

def reset_quick_amount():
    st.session_state["amount_input"] = 0

# -------------------------------------------------------------
# 메뉴 1: 내역 입력
# -------------------------------------------------------------
if menu == "📝 내역 입력":
    st.subheader("📝 새로운 수입 / 지출 입력")
    
    rec_type = st.radio("구분을 선택하세요", ["지출", "수입"], horizontal=True, key="entry_rec_type")
    
    st.caption("⚡️ 빠른 금액 추가 (클릭 시 현재 금액에 누적합산됩니다)")
    btn_cols = st.columns(5)
    btn_cols[0].button("+1만", use_container_width=True, on_click=add_quick_amount, args=(10000,))
    btn_cols[1].button("+5만", use_container_width=True, on_click=add_quick_amount, args=(50000,))
    btn_cols[2].button("+10만", use_container_width=True, on_click=add_quick_amount, args=(100000,))
    btn_cols[3].button("+50만", use_container_width=True, on_click=add_quick_amount, args=(500000,))
    btn_cols[4].button("0원 정정", use_container_width=True, on_click=reset_quick_amount)

    with st.form("record_form"):
        col1, col2 = st.columns(2)
        with col1:
            rec_date = st.date_input("날짜", datetime.today())
        with col2:
            amount = st.number_input(
                "금액 (원)", 
                min_value=0, 
                step=1000, 
                key="amount_input"
            )
            
        col3, col4 = st.columns(2)
        
        if rec_type == "지출":
            with col3:
                category = st.selectbox("지출 카테고리 (대분류)", expense_categories + ["➕ 새 카테고리 직접 입력"], key="exp_cat_select")
                custom_cat = st.text_input("새 지출 카테고리명", placeholder="직접 입력") if category == "➕ 새 카테고리 직접 입력" else None
            with col4:
                sub_category = st.text_input("상세 항목", placeholder="예: 점심식사, 주유비, 커피")
                
            col5, col6 = st.columns(2)
            with col5:
                payment_method = st.selectbox("결제 수단 / 카드", payment_methods + ["➕ 새 결제수단 직접 입력"], key="exp_pay_select")
                custom_method = st.text_input("새 결제수단명", placeholder="직접 입력") if payment_method == "➕ 새 결제수단 직접 입력" else None
            with col6:
                memo = st.text_input("메모 / 사용처", placeholder="예: 스타벅스 남양주점, 쿠팡")
                
            final_category = custom_cat.strip() if custom_cat else category
            final_method = custom_method.strip() if custom_method else payment_method
            
            st.write("")
            is_fixed = st.checkbox("📌 매달 나가는 고정 지출인가요? (공과금, 보험료, 구독료, 통신비 등)")
            
        else:
            with col3:
                category = st.selectbox("수입 항목 (대분류)", income_categories + ["➕ 새 항목 직접 입력"], key="inc_cat_select")
                custom_cat = st.text_input("새 수입 항목명", placeholder="직접 입력") if category == "➕ 새 항목 직접 입력" else None
            with col4:
                sub_category = st.text_input("상세 내용", placeholder="예: 기본급, 추석상여, 배당금")
                
            col5, col6 = st.columns(2)
            with col5:
                inc_pay_options = payment_methods + ["➕ 새 입금수단 직접 입력"]
                default_cash_idx = inc_pay_options.index("현금") if "현금" in inc_pay_options else 0
                payment_method = st.selectbox("입금 계좌 / 수단", inc_pay_options, index=default_cash_idx, key="inc_pay_select")
                custom_method = st.text_input("새 입금수단명", placeholder="직접 입력") if payment_method == "➕ 새 입금수단 직접 입력" else None
            with col6:
                memo = st.text_input("메모 / 비고", placeholder="예: 8월 급여, 용돈 등")
                
            final_category = custom_cat.strip() if custom_cat else category
            final_method = custom_method.strip() if custom_method else payment_method
            is_fixed = False

        st.write("")
        submitted = st.form_submit_button(f"💾 {rec_type} 내역 저장하기", use_container_width=True, type="primary")
        
        if submitted:
            if amount <= 0:
                st.error("금액을 0원보다 크게 입력해주세요.")
            elif not final_category or final_category.startswith("➕"):
                st.error("카테고리명을 정확히 입력해주세요.")
            elif not final_method or final_method.startswith("➕"):
                st.error("결제/입금 수단을 정확히 입력해주세요.")
            else:
                add_record(rec_date, rec_type, final_category, sub_category, amount, final_method, is_fixed, memo)
                if custom_cat:
                    add_setting("expense" if rec_type == "지출" else "income", custom_cat.strip())
                if custom_method:
                    add_setting("payment", custom_method.strip())
                st.session_state["amount_input"] = 0
                st.success(f"🎉 {rec_type} 내역이 성공적으로 저장되었습니다!")
                st.rerun()

# -------------------------------------------------------------
# 메뉴 2: 월별 단일 분석 & 예산
# -------------------------------------------------------------
elif menu == "📊 월별 단일 분석 & 예산":
    st.subheader("📊 월별 수입 / 지출 & 예산 분석")
    df = load_records()
    
    if df.empty:
        st.info("기록된 데이터가 없습니다. 먼저 내역을 입력해주세요.")
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        selected_month = st.selectbox("조회할 월 선택", sorted(df['year_month'].unique(), reverse=True))
        m_df = df[df['year_month'] == selected_month]
        
        income_df = m_df[m_df['type'] == '수입']
        expense_df = m_df[m_df['type'] == '지출']
        
        total_income = income_df['amount'].sum()
        total_expense = expense_df['amount'].sum()
        net_savings = total_income - total_expense
        fixed_expense = expense_df[expense_df['is_fixed'] == 1]['amount'].sum()
        var_expense = expense_df[expense_df['is_fixed'] == 0]['amount'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("총 수입", f"{total_income:,} 원")
        c2.metric("총 지출", f"{total_expense:,} 원")
        c3.metric("순 잉여금(저축)", f"{net_savings:,} 원")
        
        if not expense_df.empty:
            st.write("#### 🏆 이번 달 지출 TOP 3 카테고리")
            top3 = expense_df.groupby('category')['amount'].sum().reset_index().sort_values('amount', ascending=False).head(3)
            t_cols = st.columns(len(top3))
            for i, (_, row) in enumerate(top3.iterrows()):
                pct = (row['amount'] / total_expense * 100) if total_expense > 0 else 0
                with t_cols[i]:
                    st.markdown(f"""
                    <div class="top-card">
                        <strong>{i+1}위. {row['category']}</strong><br/>
                        <span style="font-size: 16px; font-weight: bold; color: #312e81;">{row['amount']:,} 원</span>
                        <span style="font-size: 12px; color: #6b7280;">({pct:.1f}%)</span>
                    </div>
                    """, unsafe_allow_html=True)

        st.write("---")
        st.write("#### 🎯 이번 달 목표 예산 관리")
        current_budget = get_budget(selected_month)
        
        b_col1, b_col2 = st.columns([2, 1])
        with b_col1:
            new_budget = st.number_input(f"{selected_month} 목표 지출 예산 (원)", value=int(current_budget), step=50000)
        with b_col2:
            st.write("")
            st.write("")
            if st.button("예산 저장", use_container_width=True):
                set_budget(selected_month, new_budget)
                st.success("예산이 저장되었습니다.")
                st.rerun()
                
        if current_budget > 0:
            spent_pct = min(total_expense / current_budget, 1.0)
            remaining_budget = current_budget - total_expense
            st.progress(spent_pct, text=f"예산 소진율: {total_expense:,}원 / {current_budget:,}원 ({spent_pct*100:.1f}%)")
            if remaining_budget >= 0:
                st.caption(f"💰 남은 예산: **{remaining_budget:,} 원** 남았습니다.")
            else:
                st.error(f"🚨 예산 초과! **{abs(remaining_budget):,} 원** 더 지출되었습니다.")
        
        st.write("---")
        st.write("#### ⚖️ 고정지출 vs 변동지출")
        fc1, fc2 = st.columns(2)
        fc1.metric("📌 고정지출", f"{fixed_expense:,} 원")
        fc2.metric("🛒 변동지출", f"{var_expense:,} 원")
        
        if total_expense > 0:
            fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.45,
                         title=f"{selected_month} 지출 구조 비율")
            fig.update_layout(margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
            
        st.write("---")
        st.write("#### 💳 결제수단 / 카드별 지출")
        if not expense_df.empty:
            card_sum = expense_df.groupby('payment_method')['amount'].sum().reset_index()
            fig_card = px.bar(card_sum, x='payment_method', y='amount', text_auto=True)
            fig_card.update_layout(margin=dict(t=20, b=20, l=10, r=10), xaxis_title="", yaxis_title="금액(원)")
            st.plotly_chart(fig_card, use_container_width=True)
            
            st.write("#### 🏷️ 카테고리별 지출 비중")
            cat_sum = expense_df.groupby('category')['amount'].sum().reset_index()
            fig_cat = px.pie(cat_sum, values='amount', names='category', hole=0.35)
            fig_cat.update_layout(margin=dict(t=20, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3))
            st.plotly_chart(fig_cat, use_container_width=True)

# -------------------------------------------------------------
# 메뉴 3: 월별 지출 비교 (MoM)
# -------------------------------------------------------------
elif menu == "📈 월별 지출 비교 (MoM)":
    st.subheader("📈 월별 지출 추이 및 전월 대비 비교")
    df = load_records()
    
    if df.empty:
        st.info("비교할 데이터가 없습니다.")
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        exp_df = df[df['type'] == '지출'].copy()
        
        if exp_df.empty:
            st.info("지출 내역이 없습니다.")
        else:
            monthly_summary = exp_df.groupby('year_month').agg(
                총지출=('amount', 'sum'),
                고정지출=('amount', lambda x: x[exp_df.loc[x.index, 'is_fixed'] == 1].sum()),
                변동지출=('amount', lambda x: x[exp_df.loc[x.index, 'is_fixed'] == 0].sum())
            ).reset_index().sort_values('year_month')
            
            monthly_summary['전월대비_증감'] = monthly_summary['총지출'].diff().fillna(0)
            monthly_summary['증감률(%)'] = (monthly_summary['총지출'].pct_change() * 100).fillna(0).round(1)
            
            st.write("#### 📊 월별 총괄 요약")
            st.dataframe(monthly_summary, use_container_width=True)
            
            fig_trend = px.bar(
                monthly_summary, 
                x='year_month', 
                y=['고정지출', '변동지출'], 
                title="월별 지출 구조 추이",
                barmode='stack',
                text_auto=True
            )
            fig_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2), xaxis_title="")
            st.plotly_chart(fig_trend, use_container_width=True)
            
            st.write("---")
            st.write("#### 🏷️ 카테고리별 월간 지출 변화")
            cat_monthly = exp_df.groupby(['year_month', 'category'])['amount'].sum().reset_index()
            
            fig_cat_trend = px.bar(
                cat_monthly,
                x='year_month',
                y='amount',
                color='category',
                title="카테고리별 월별 비교",
                barmode='group',
                text_auto=True
            )
            fig_cat_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3), xaxis_title="")
            st.plotly_chart(fig_cat_trend, use_container_width=True)

# -------------------------------------------------------------
# 메뉴 4: 전체 내역 및 바로 수정
# -------------------------------------------------------------
elif menu == "📋 전체 내역 및 바로 수정":
    st.subheader("📋 전체 내역 관리 및 삭제·수정")
    df = load_records()
    
    tab1, tab2 = st.tabs(["⚡️ 표에서 바로 수정 및 삭제", "💾 엑셀 백업 & 복원(가져오기)"])
    
    with tab1:
        if df.empty:
            st.info("등록된 가계부 내역이 없습니다.")
        else:
            df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
            months = ["전체 월"] + sorted(df['year_month'].unique().tolist(), reverse=True)
            
            s_col1, s_col2 = st.columns([1, 2])
            with s_col1:
                sel_m = st.selectbox("조회할 월 선택", months)
            with s_col2:
                kw = st.text_input("🔎 검색어 (사용처, 상세항목, 카테고리)", placeholder="예: 스타벅스, 신한카드")
                
            filtered_df = df.copy()
            if sel_m != "전체 월":
                filtered_df = filtered_df[filtered_df['year_month'] == sel_m]
            if kw.strip():
                filtered_df = filtered_df[
                    filtered_df['memo'].str.contains(kw, na=False) |
                    filtered_df['sub_category'].str.contains(kw, na=False) |
                    filtered_df['category'].str.contains(kw, na=False)
                ]
                
            st.caption(f"💡 **수정:** 표의 칸을 클릭하여 내용을 변경하세요.<br>💡 **삭제:** 지우고 싶은 항목의 **[🗑️ 삭제]** 체크박스를 누른 후 <b>저장</b>을 누르세요.<br>(조회 항목: 총 {len(filtered_df)}건 / 합계: {filtered_df['amount'].sum():,}원)", unsafe_allow_html=True)
            
            df_edit = filtered_df.drop(columns=['year_month']).copy()
            df_edit.insert(0, '삭제', False)
            
            df_edit['date'] = pd.to_datetime(df_edit['date'], errors='coerce').dt.date
            df_edit['is_fixed'] = df_edit['is_fixed'].apply(lambda x: True if x in [1, '1', True] else False)
            df_edit['amount'] = pd.to_numeric(df_edit['amount'], errors='coerce').fillna(0).astype(int)
            
            edited_data = st.data_editor(
                df_edit,
                column_config={
                    "삭제": st.column_config.CheckboxColumn("🗑️ 삭제", default=False),
                    "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "date": st.column_config.DateColumn("날짜", required=True, format="YYYY-MM-DD"),
                    "type": st.column_config.SelectboxColumn("구분", options=["지출", "수입"], required=True, width="small"),
                    "category": st.column_config.SelectboxColumn("카테고리", options=all_categories, required=True),
                    "sub_category": st.column_config.TextColumn("상세 항목"),
                    "amount": st.column_config.NumberColumn("금액 (원)", min_value=0, step=1000, required=True),
                    "payment_method": st.column_config.SelectboxColumn("결제/입금 수단", options=payment_methods, required=True),
                    "is_fixed": st.column_config.CheckboxColumn("고정지출"),
                    "memo": st.column_config.TextColumn("메모 / 사용처"),
                },
                disabled=["id"],
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic",
                key="ledger_table_editor"
            )
            
            st.write("")
            col_save1, col_save2 = st.columns([2, 1])
            with col_save1:
                if st.button("💾 체크된 항목 삭제 및 수정사항 전체 저장", type="primary", use_container_width=True):
                    upsert_edited_records(filtered_df, edited_data)
                    st.success("🎉 수정한 내용과 삭제된 항목이 안전하게 동기화되었습니다!")
                    st.rerun()
            with col_save2:
                if st.button("🔄 원래대로 복구", use_container_width=True):
                    st.rerun()

    with tab2:
        st.write("#### 📥 1. 현재 가계부 내역 엑셀 다운로드")
        if not df.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='가계부_내역')
            st.download_button(
                label="📥 가계부 전체 엑셀(XLSX) 다운로드 백업",
                data=output.getvalue(),
                file_name=f"가계부_백업_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("백업할 데이터가 없습니다.")
            
        st.write("---")
        st.write("#### 📤 2. 백업 엑셀 파일로 가계부 복원 (가져오기)")
        st.caption("기존에 다운로드해 둔 가계부 엑셀(.xlsx) 파일을 올리면 데이터를 안전하게 DB로 복원합니다.")
        
        uploaded_file = st.file_uploader("백업 엑셀 파일 선택", type=["xlsx", "xls"])
        if uploaded_file is not None:
            try:
                import_df = pd.read_excel(uploaded_file)
                st.write("미리보기:", import_df.head(3))
                if st.button("🚀 이 엑셀 데이터 가계부로 복원하기", use_container_width=True, type="primary"):
                    success, msg = import_records_from_df(import_df)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            except Exception as e:
                st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

# -------------------------------------------------------------
# 메뉴 5: 정기 고정비 일괄 등록
# -------------------------------------------------------------
elif menu == "⚙️ 정기 고정비 일괄 등록":
    st.subheader("⚙️ 정기 고정비 일괄 등록 및 설정")
    tab1, tab2 = st.tabs(["🚀 이번 달 고정비 일괄 등록", "🛠️ 고정비 항목 추가 / 수정 / 삭제"])
    
    with tab1:
        st.info("💡 **입력한 금액과 결제수단은 DB에 자동 기억**되어 다음 달에도 유지됩니다. (0원인 항목은 가계부 등록에서 자동 제외)")
        target_date = st.date_input("등록 기준 일자", datetime.today(), key="fix_target_date")
        
        templates = load_fixed_templates()
        if templates.empty:
            st.warning("등록된 고정비 템플릿 항목이 없습니다. 우측 탭에서 항목을 추가해주세요.")
        else:
            input_values = []
            current_total = 0
            st.write("---")
            
            for idx, row in templates.iterrows():
                t_id = row['id']
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    amt = st.number_input(
                        f"📌 {row['sub_category']} ({row['category']})", 
                        value=int(row['default_amount']), 
                        step=5000, 
                        key=f"tmpl_amt_{t_id}"
                    )
                    current_total += amt
                with col_b:
                    pay_idx = payment_methods.index(row['default_payment']) if row['default_payment'] in payment_methods else 0
                    pay_m = st.selectbox(
                        "결제 수단", 
                        payment_methods, 
                        index=pay_idx, 
                        key=f"tmpl_pay_{t_id}"
                    )
                input_values.append((t_id, row['category'], row['sub_category'], amt, pay_m, row['memo']))
            
            st.write("---")
            st.metric("📊 이번 달 등록 예정 고정비 총액", f"{current_total:,} 원")
            
            save_as_default = st.checkbox("💾 입력/수정한 금액과 결제수단을 다음 달에도 기본값으로 기억하기", value=True)
            
            if st.button("🚀 이번 달 고정비 일괄 가계부 저장", use_container_width=True, type="primary"):
                count = 0
                for t_id, cat, sub, amt, pay_m, memo_txt in input_values:
                    if amt > 0:
                        add_record(target_date, "지출", cat, sub, amt, pay_m, True, memo_txt)
                        count += 1
                    if save_as_default:
                        update_template_defaults(t_id, amt, pay_m)
                
                if count > 0:
                    st.success(f"🎉 총 {count}건({current_total:,}원)의 고정 지출이 가계부에 등록되었으며, 다음 달 기본값으로 안전하게 저장되었습니다!")
                else:
                    if save_as_default:
                        st.success("💾 설정값이 다음 달 기본값으로 저장되었습니다.")
                    else:
                        st.warning("금액이 입력된 항목이 없습니다.")

    with tab2:
        st.write("#### 🛠️ 고정비 항목 관리")
        templates = load_fixed_templates()
        
        st.write("##### 1. 기존 항목 수정 / 삭제")
        if not templates.empty:
            t_options = [f"ID {r['id']} | {r['sub_category']} ({r['category']}) - 기본 {r['default_amount']:,}원 ({r['default_payment']})" for _, r in templates.iterrows()]
            sel_t_opt = st.selectbox("수정 또는 삭제할 항목 선택", t_options)
            
            if sel_t_opt:
                sel_t_id = int(sel_t_opt.split(" | ")[0].replace("ID ", ""))
                t_row = templates[templates['id'] == sel_t_id].iloc[0]
                
                with st.form(f"t_edit_form_{sel_t_id}"):
                    tc1, tc2 = st.columns(2)
                    with tc1:
                        c_idx = expense_categories.index(t_row['category']) if t_row['category'] in expense_categories else 0
                        t_cat = st.selectbox("분류 카테고리", expense_categories, index=c_idx)
                        t_sub = st.text_input("항목명 (예: 본인 실손보험)", value=t_row['sub_category'])
                    with tc2:
                        t_amt = st.number_input("기본 금액 (원)", value=int(t_row['default_amount']), step=5000)
                        p_idx = payment_methods.index(t_row['default_payment']) if t_row['default_payment'] in payment_methods else 0
                        t_pay = st.selectbox("기본 결제수단", payment_methods, index=p_idx)
                    
                    t_memo = st.text_input("메모", value=t_row['memo'])
                    
                    b1, b2 = st.columns(2)
                    with b1:
                        save_t = st.form_submit_button("💾 템플릿 수정 저장", use_container_width=True, type="primary")
                    with b2:
                        del_t = st.form_submit_button("🗑️ 이 항목 삭제", use_container_width=True)
                        
                    if save_t:
                        update_fixed_template(sel_t_id, t_cat, t_sub, t_amt, t_pay, t_memo)
                        st.success(f"'{t_sub}' 항목이 수정되었습니다.")
                        st.rerun()
                    elif del_t:
                        delete_fixed_template(sel_t_id)
                        st.warning("항목이 삭제되었습니다.")
                        st.rerun()
        
        st.write("---")
        st.write("##### 2. 새 고정비 항목 추가")
        with st.form("new_template_form", clear_on_submit=True):
            nc1, nc2 = st.columns(2)
            with nc1:
                new_t_cat = st.selectbox("분류 카테고리", expense_categories)
                new_t_sub = st.text_input("새 항목명 (예: 헬스장 정기권, 부모님 용돈)")
            with nc2:
                new_t_amt = st.number_input("기본 금액 (원)", value=0, step=5000)
                new_t_pay = st.selectbox("기본 결제수단", payment_methods)
            
            new_t_memo = st.text_input("메모", value="정기 고정비")
            add_t_btn = st.form_submit_button("➕ 새 고정비 항목 등록", use_container_width=True, type="primary")
            
            if add_t_btn:
                if not new_t_sub:
                    st.error("항목명을 입력해주세요.")
                else:
                    add_fixed_template(new_t_cat, new_t_sub, new_t_amt, new_t_pay, new_t_memo)
                    st.success(f"'{new_t_sub}' 고정비 항목 추가 완료!")
                    st.rerun()

# -------------------------------------------------------------
# 메뉴 6: 분류 관리
# -------------------------------------------------------------
elif menu == "🏷️ 분류 및 결제수단 관리":
    st.subheader("🏷️ 카테고리 및 결제수단 관리")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("##### 🛒 지출 카테고리")
        st.write(expense_categories)
        new_exp = st.text_input("새 지출 카테고리 추가")
        if st.button("지출 카테고리 추가", use_container_width=True) and new_exp:
            if new_exp not in expense_categories:
                add_setting("expense", new_exp.strip())
                st.success(f"'{new_exp}' 추가 완료!")
                st.rerun()
                
        del_exp = st.selectbox("삭제할 지출 카테고리", ["선택 안 함"] + expense_categories)
        if st.button("지출 카테고리 삭제", use_container_width=True) and del_exp != "선택 안 함":
            delete_setting("expense", del_exp)
            st.warning(f"'{del_exp}' 삭제 완료!")
            st.rerun()

    with col2:
        st.write("##### 💵 수입 카테고리")
        st.write(income_categories)
        new_inc = st.text_input("새 수입 카테고리 추가")
        if st.button("수입 카테고리 추가", use_container_width=True) and new_inc:
            if new_inc not in income_categories:
                add_setting("income", new_inc.strip())
                st.success(f"'{new_inc}' 추가 완료!")
                st.rerun()
                
        del_inc = st.selectbox("삭제할 수입 카테고리", ["선택 안 함"] + income_categories)
        if st.button("수입 카테고리 삭제", use_container_width=True) and del_inc != "선택 안 함":
            delete_setting("income", del_inc)
            st.warning(f"'{del_inc}' 삭제 완료!")
            st.rerun()

    with col3:
        st.write("##### 💳 결제수단 / 카드")
        st.write(payment_methods)
        new_pay = st.text_input("새 카드/결제수단 추가")
        if st.button("결제수단 추가", use_container_width=True) and new_pay:
            if new_pay not in payment_methods:
                add_setting("payment", new_pay.strip())
                st.success(f"'{new_pay}' 추가 완료!")
                st.rerun()
                
        del_pay = st.selectbox("삭제할 결제수단", ["선택 안 함"] + payment_methods)
        if st.button("결제수단 삭제", use_container_width=True) and del_pay != "선택 안 함":
            delete_setting("payment", del_pay)
            st.warning(f"'{del_pay}' 삭제 완료!")
            st.rerun()
