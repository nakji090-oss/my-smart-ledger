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

# 스마트폰 화면 맞춤 스타일 적용
st.markdown("""
<style>
    /* 상하좌우 여백 모바일 최적화 */
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
        font-size: 16px;
        min-height: 48px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.08);
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
    /* 다크모드 대응 메트릭 배경 */
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] {
            background-color: #1e222b;
            border-color: #2f3440;
        }
    }
    /* 고정비 체크박스 강조 영역 */
    .fixed-check-box {
        background-color: #f1f5f9;
        padding: 10px 14px;
        border-radius: 10px;
        margin-top: 8px;
        margin-bottom: 8px;
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
    
    # 기본 카테고리 데이터
    c.execute("SELECT COUNT(*) FROM settings")
    if c.fetchone()[0] == 0:
        default_incomes = ["월급", "성과급", "명절보너스", "금융/배당수입", "부수입", "기타수입"]
        default_expenses = ["식비", "주거/통신", "공과금", "보험료", "십일조/기부", "교통/차량", "쇼핑/생활", "문화/여가", "교육", "기타지출"]
        default_payments = ["신한카드", "국민카드", "현대카드", "삼성카드", "체크카드", "계좌이체", "현금"]
        
        for name in default_incomes:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('income', ?)", (name,))
        for name in default_expenses:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('expense', ?)", (name,))
        for name in default_payments:
            c.execute("INSERT OR IGNORE INTO settings (setting_type, name) VALUES ('payment', ?)", (name,))
        conn.commit()

    # 기본 고정비 템플릿 데이터 (기타헌금/후원금 제외)
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
# 3. 데이터 CRUD 함수
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

def update_record(r_id, date_str, r_type, cat, sub_cat, amount, method, is_fixed, memo):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE records 
        SET date = ?, type = ?, category = ?, sub_category = ?, amount = ?, payment_method = ?, is_fixed = ?, memo = ?
        WHERE id = ?
    ''', (str(date_str), r_type, cat, sub_cat, int(amount), method, 1 if is_fixed else 0, memo, r_id))
    conn.commit()
    conn.close()

def delete_record(record_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

def load_fixed_templates():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM fixed_templates ORDER BY id ASC", conn)
    conn.close()
    return df

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

# -------------------------------------------------------------
# 4. 메인 UI & 메뉴
# -------------------------------------------------------------
income_categories, expense_categories, payment_methods = load_settings()

st.title("💰 스마트 가계부")
menu = st.sidebar.radio("📌 바로가기 메뉴", [
    "📝 내역 입력", 
    "📊 월별 단일 분석", 
    "📈 월별 지출 비교 (MoM)", 
    "📋 전체 내역 및 수정·관리", 
    "⚙️ 정기 고정비 일괄 등록",
    "🏷️ 분류 및 결제수단 관리"
])

# -------------------------------------------------------------
# 메뉴 1: 내역 입력 (모바일 직관적 배치 & 고정지출 최하단 배치)
# -------------------------------------------------------------
if menu == "📝 내역 입력":
    st.subheader("📝 새로운 수입 / 지출 입력")
    
    with st.form("record_form", clear_on_submit=True):
        # 1. 구분 선택 (라디오 버튼 - 큼직하게 상단 배치)
        rec_type = st.radio("구분", ["지출", "수입"], horizontal=True)
        
        # 2. 날짜 및 금액 (모바일에서 깔끔하게 정렬)
        col1, col2 = st.columns(2)
        with col1:
            rec_date = st.date_input("날짜", datetime.today())
        with col2:
            amount = st.number_input("금액 (원)", min_value=0, step=1000, value=0)
            
        # 3. 카테고리 및 상세항목
        col3, col4 = st.columns(2)
        if rec_type == "지출":
            with col3:
                category = st.selectbox("카테고리 (대분류)", expense_categories + ["➕ 새 카테고리 직접 입력"])
                custom_cat = st.text_input("새 카테고리명 입력") if category == "➕ 새 카테고리 직접 입력" else None
            with col4:
                sub_category = st.text_input("상세 항목", placeholder="예: 점심식사, 주유비, 커피")
                
            # 4. 결제 수단
            col5, col6 = st.columns(2)
            with col5:
                payment_method = st.selectbox("결제 수단 / 카드", payment_methods + ["➕ 새 결제수단 직접 입력"])
                custom_method = st.text_input("새 결제수단명 입력") if payment_method == "➕ 새 결제수단 직접 입력" else None
            with col6:
                memo = st.text_input("메모 / 사용처", placeholder="예: 스타벅스 강남점, 쿠팡")
                
            final_category = custom_cat.strip() if custom_cat else category
            final_method = custom_method.strip() if custom_method else payment_method
            
            # 5. 📌 고정 지출 여부 체크박스 (맨 아래 배치)
            st.write("")
            is_fixed = st.checkbox("📌 매달 나가는 고정 지출인가요? (공과금, 보험료, 구독료, 통신비 등)")
            
        else:  # 수입인 경우
            with col3:
                category = st.selectbox("수입 항목 (대분류)", income_categories + ["➕ 새 항목 직접 입력"])
                custom_cat = st.text_input("새 수입 항목명 입력") if category == "➕ 새 항목 직접 입력" else None
            with col4:
                sub_category = st.text_input("상세 내용", placeholder="예: 기본급, 추석상여, 배당금")
                
            col5, col6 = st.columns(2)
            with col5:
                payment_method = st.selectbox("입금 계좌 / 수단", ["급여통장", "부계좌", "현금", "기타"])
                custom_method = None
            with col6:
                memo = st.text_input("메모 / 비고", placeholder="예: 8월 성과급")
                
            final_category = custom_cat.strip() if custom_cat else category
            final_method = custom_method.strip() if custom_method else payment_method
            is_fixed = False

        st.write("")
        # 6. 저장 버튼 (터치하기 쉬운 풀 너비 버튼)
        submitted = st.form_submit_button("💾 가계부에 저장하기", use_container_width=True, type="primary")
        
        if submitted:
            if amount <= 0:
                st.error("금액을 0원보다 크게 입력해주세요.")
            elif not final_category or final_category.startswith("➕"):
                st.error("카테고리명을 정확히 입력해주세요.")
            else:
                add_record(rec_date, rec_type, final_category, sub_category, amount, final_method, is_fixed, memo)
                if custom_cat:
                    add_setting("expense" if rec_type == "지출" else "income", custom_cat.strip())
                if custom_method:
                    add_setting("payment", custom_method.strip())
                st.success("🎉 성공적으로 저장되었습니다!")

# -------------------------------------------------------------
# 메뉴 2: 월별 단일 분석 (모바일 카드 뷰 강화)
# -------------------------------------------------------------
elif menu == "📊 월별 단일 분석":
    st.subheader("📊 월별 수입 / 지출 분석")
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
        
        # 3단 메트릭 카드
        c1, c2, c3 = st.columns(3)
        c1.metric("총 수입", f"{total_income:,} 원")
        c2.metric("총 지출", f"{total_expense:,} 원")
        c3.metric("순 잉여금(저축)", f"{net_savings:,} 원")
        
        st.write("---")
        st.write("#### ⚖️ 고정지출 vs 변동지출")
        fc1, fc2 = st.columns(2)
        fc1.metric("📌 고정지출 (보험/통신/공과금 등)", f"{fixed_expense:,} 원")
        fc2.metric("🛒 변동지출 (식비/쇼핑/여가 등)", f"{var_expense:,} 원")
        
        if total_expense > 0:
            fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.45,
                         title=f"{selected_month} 지출 구조 비율")
            fig.update_layout(margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
            
        st.write("---")
        # 카드별 & 카테고리별 차트
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
# 메뉴 4: 전체 내역 및 수정·관리
# -------------------------------------------------------------
elif menu == "📋 전체 내역 및 수정·관리":
    st.subheader("📋 전체 내역 관리 및 선택 수정")
    df = load_records()
    
    if df.empty:
        st.info("등록된 가계부 내역이 없습니다.")
    else:
        # 엑셀 다운로드
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='가계부_내역')
        st.download_button(
            label="📥 전체 가계부 엑셀(XLSX) 다운로드 백업",
            data=output.getvalue(),
            file_name=f"가계부_내역_{datetime.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        st.write("#### 📄 등록된 내역 목록")
        st.dataframe(df, use_container_width=True)
        
        st.write("---")
        st.write("#### ✏️ 내역 선택 수정 및 삭제")
        record_options = [f"ID {row['id']} | {row['date']} | {row['type']} | {row['category']}({row['sub_category']}) | {row['amount']:,}원 | {row['memo']}" 
                          for _, row in df.iterrows()]
        
        selected_option = st.selectbox("수정 또는 삭제할 항목 선택", record_options)
        
        if selected_option:
            selected_id = int(selected_option.split(" | ")[0].replace("ID ", ""))
            target_row = df[df['id'] == selected_id].iloc[0]
            
            with st.form(f"edit_form_{selected_id}"):
                st.write(f"##### 🛠️ ID [{selected_id}] 수정 양식")
                e_type = st.radio("구분", ["지출", "수입"], index=0 if target_row['type'] == "지출" else 1, horizontal=True)
                
                e_col1, e_col2 = st.columns(2)
                with e_col1:
                    e_date = st.date_input("날짜", datetime.strptime(str(target_row['date']), "%Y-%m-%d"))
                with e_col2:
                    e_amount = st.number_input("금액 (원)", value=int(target_row['amount']), min_value=0, step=1000)
                
                e_col3, e_col4 = st.columns(2)
                with e_col3:
                    cat_list = expense_categories if e_type == "지출" else income_categories
                    cur_cat_idx = cat_list.index(target_row['category']) if target_row['category'] in cat_list else 0
                    e_category = st.selectbox("카테고리", cat_list, index=cur_cat_idx)
                with e_col4:
                    e_sub = st.text_input("상세 항목", value=str(target_row['sub_category'] or ""))
                    
                e_col5, e_col6 = st.columns(2)
                with e_col5:
                    cur_pay_idx = payment_methods.index(target_row['payment_method']) if target_row['payment_method'] in payment_methods else 0
                    e_payment = st.selectbox("결제/입금 수단", payment_methods, index=cur_pay_idx)
                with e_col6:
                    e_memo = st.text_input("메모 / 사용처", value=str(target_row['memo'] or ""))
                
                # 수정 화면에서도 고정지출 체크박스는 하단 배치
                e_fixed = st.checkbox("📌 고정 지출 여부", value=bool(target_row['is_fixed'])) if e_type == "지출" else False
                
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    save_edit = st.form_submit_button("💾 수정사항 저장", use_container_width=True, type="primary")
                with btn_col2:
                    delete_item = st.form_submit_button("🗑️ 이 내역 삭제", use_container_width=True)
                
                if save_edit:
                    update_record(selected_id, e_date, e_type, e_category, e_sub, e_amount, e_payment, e_fixed, e_memo)
                    st.success(f"ID {selected_id} 내역 수정 완료!")
                    st.rerun()
                elif delete_item:
                    delete_record(selected_id)
                    st.warning(f"ID {selected_id} 내역 삭제 완료!")
                    st.rerun()

# -------------------------------------------------------------
# 메뉴 5: 정기 고정비 일괄 등록
# -------------------------------------------------------------
elif menu == "⚙️ 정기 고정비 일괄 등록":
    st.subheader("⚙️ 정기 고정비 일괄 등록 및 설정")
    tab1, tab2 = st.tabs(["🚀 이번 달 고정비 일괄 등록", "🛠️ 고정비 항목 추가 / 수정 / 삭제"])
    
    with tab1:
        st.caption("설정된 고정비 항목들의 금액을 확인 후 한 번에 가계부에 등록합니다. 0원인 항목은 자동 제외됩니다.")
        target_date = st.date_input("등록 기준 일자", datetime.today(), key="fix_target_date")
        
        templates = load_fixed_templates()
        if templates.empty:
            st.warning("등록된 고정비 템플릿 항목이 없습니다. 우측 탭에서 항목을 추가해주세요.")
        else:
            input_values = []
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
                with col_b:
                    pay_idx = payment_methods.index(row['default_payment']) if row['default_payment'] in payment_methods else 0
                    pay_m = st.selectbox(
                        "결제 수단", 
                        payment_methods, 
                        index=pay_idx, 
                        key=f"tmpl_pay_{t_id}"
                    )
                input_values.append((row['category'], row['sub_category'], amt, pay_m, row['memo']))
            
            st.write("---")
            if st.button("🚀 이번 달 고정비 일괄 가계부 저장", use_container_width=True, type="primary"):
                count = 0
                for cat, sub, amt, pay_m, memo_txt in input_values:
                    if amt > 0:
                        add_record(target_date, "지출", cat, sub, amt, pay_m, True, memo_txt)
                        count += 1
                if count > 0:
                    st.success(f"🎉 총 {count}건의 고정 지출이 정상적으로 등록되었습니다!")
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
