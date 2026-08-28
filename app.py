import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime
import io

# -------------------------------------------------------------
# 1. 페이지 설정 (모바일 최적화)
# -------------------------------------------------------------
st.set_page_config(page_title="스마트 가계부", page_icon="💰", layout="wide")

DB_FILE = "ledger_data.db"

# -------------------------------------------------------------
# 2. SQLite 로컬 데이터베이스 연동 & 초기화
# -------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # 가계부 거래 내역 테이블
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
    # 카테고리 및 결제수단 설정 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_type TEXT NOT NULL, -- 'income', 'expense', 'payment'
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    # 기본 카테고리가 없으면 기본값 삽입
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
    conn.close()

init_db()

# DB CRUD 헬퍼 함수
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

def delete_record(record_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

# -------------------------------------------------------------
# 3. UI 및 내비게이션
# -------------------------------------------------------------
income_categories, expense_categories, payment_methods = load_settings()

st.title("💰 스마트 가계부")
menu = st.sidebar.radio("메뉴 선택", [
    "📝 내역 입력", 
    "📊 월별 분석 및 통계", 
    "📋 전체 내역 및 관리", 
    "⚙️ 정기 고정비 일괄 등록",
    "🏷️ 분류 및 결제수단 관리"
])

# -------------------------------------------------------------
# 메뉴 1: 내역 입력
# -------------------------------------------------------------
if menu == "📝 내역 입력":
    st.subheader("새로운 수입 / 지출 기록")
    
    with st.form("record_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            rec_date = st.date_input("날짜", datetime.today())
            rec_type = st.radio("구분", ["지출", "수입"], horizontal=True)
        with col2:
            amount = st.number_input("금액 (원)", min_value=0, step=1000)
            
        if rec_type == "지출":
            col3, col4 = st.columns(2)
            with col3:
                category = st.selectbox("카테고리", expense_categories + ["➕ 새 카테고리 직접 입력"])
                custom_cat = st.text_input("새 카테고리명 입력") if category == "➕ 새 카테고리 직접 입력" else None
                
                payment_method = st.selectbox("결제 수단 / 카드", payment_methods + ["➕ 새 결제수단 직접 입력"])
                custom_method = st.text_input("새 결제수단명 입력") if payment_method == "➕ 새 결제수단 직접 입력" else None
            with col4:
                is_fixed = st.checkbox("고정 지출 여부 (공과금, 보험료, 구독료 등)")
                sub_category = st.text_input("상세 항목 (예: 점심식사, 주유비)")
        else:
            col3, col4 = st.columns(2)
            with col3:
                category = st.selectbox("수입 항목", income_categories + ["➕ 새 항목 직접 입력"])
                custom_cat = st.text_input("새 수입 항목명 입력") if category == "➕ 새 항목 직접 입력" else None
                payment_method = st.selectbox("입금 수단", ["급여통장", "부계좌", "현금", "기타"])
                custom_method = None
            with col4:
                is_fixed = False
                sub_category = st.text_input("상세 내용 (예: 기본급, 상여금)")

        final_category = custom_cat.strip() if custom_cat else category
        final_method = custom_method.strip() if custom_method else payment_method
        memo = st.text_input("메모 / 사용처", placeholder="예: 스타벅스, 이마트 등")
        submitted = st.form_submit_button("가계부에 저장하기", use_container_width=True, type="primary")
        
        if submitted:
            if amount <= 0:
                st.error("금액을 올바르게 입력해주세요.")
            elif not final_category or final_category.startswith("➕"):
                st.error("카테고리명을 정확히 입력해주세요.")
            else:
                add_record(rec_date, rec_type, final_category, sub_category, amount, final_method, is_fixed, memo)
                # 새로운 카테고리나 결제수단이면 DB 설정에도 자동 등록
                if custom_cat:
                    add_setting("expense" if rec_type == "지출" else "income", custom_cat.strip())
                if custom_method:
                    add_setting("payment", custom_method.strip())
                st.success("🎉 성공적으로 저장되었습니다!")

# -------------------------------------------------------------
# 메뉴 2: 월별 분석 및 통계
# -------------------------------------------------------------
elif menu == "📊 월별 분석 및 통계":
    st.subheader("월별 수입/지출 & 고정비/변동비 분석")
    df = load_records()
    
    if df.empty:
        st.info("기록된 데이터가 없습니다. 먼저 내역을 입력해주세요.")
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        available_months = sorted(df['year_month'].unique(), reverse=True)
        selected_month = st.selectbox("조회할 월 선택", available_months)
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
        c3.metric("순 잉여금(저축)", f"{net_savings:,} 원", delta=f"{net_savings:,} 원")
        
        st.divider()
        st.write("#### ⚖️ 고정지출 vs 변동지출 비교")
        fc1, fc2 = st.columns(2)
        fc1.metric("📌 고정지출 (보험/통신/공과금/십일조 등)", f"{fixed_expense:,} 원")
        fc2.metric("🛒 변동지출 (식비/쇼핑/여가 등)", f"{var_expense:,} 원")
        
        if total_expense > 0:
            fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.4,
                         title=f"{selected_month} 지출 구조 비율")
            st.plotly_chart(fig, use_container_width=True)
            
        st.divider()
        c_col1, c_col2 = st.columns(2)
        with c_col1:
            st.write("#### 💳 결제수단/카드별 지출 현황")
            if not expense_df.empty:
                card_sum = expense_df.groupby('payment_method')['amount'].sum().reset_index()
                st.plotly_chart(px.bar(card_sum, x='payment_method', y='amount', text_auto=True), use_container_width=True)
        with c_col2:
            st.write("#### 🏷️ 카테고리별 지출 비중")
            if not expense_df.empty:
                cat_sum = expense_df.groupby('category')['amount'].sum().reset_index()
                st.plotly_chart(px.pie(cat_sum, values='amount', names='category'), use_container_width=True)

# -------------------------------------------------------------
# 메뉴 3: 전체 내역 관리 및 엑셀 다운로드
# -------------------------------------------------------------
elif menu == "📋 전체 내역 및 관리":
    st.subheader("전체 가계부 내역 관리")
    df = load_records()
    
    if df.empty:
        st.info("등록된 가계부 내역이 없습니다.")
    else:
        # 엑셀 다운로드 기능
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='가계부_내역')
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 전체 가계부 엑셀(XLSX) 다운로드 백업",
            data=excel_data,
            file_name=f"가계부_내역_{datetime.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        st.write("#### 📄 등록된 내역 목록")
        st.dataframe(df, use_container_width=True)
        
        st.divider()
        st.write("#### 🗑️ 내역 삭제")
        col_d1, col_d2 = st.columns([3, 1])
        with col_d1:
            del_id = st.number_input("삭제할 행의 ID 번호 입력", min_value=1, step=1)
        with col_d2:
            st.write("")
            st.write("")
            if st.button("내역 삭제 실행", type="primary", use_container_width=True):
                delete_record(del_id)
                st.success(f"ID {del_id} 내역이 삭제되었습니다.")
                st.rerun()

# -------------------------------------------------------------
# 메뉴 4: 정기 고정비 세부 일괄 등록
# -------------------------------------------------------------
elif menu == "⚙️ 정기 고정비 일괄 등록":
    st.subheader("⚙️ 매달 반복되는 정기 고정비 세부 일괄 등록")
    st.caption("항목별로 금액과 결제수단을 입력하세요. 0원인 항목은 자동으로 제외되어 저장됩니다.")
    
    target_date = st.date_input("등록 기준 일자", datetime.today())
    st.write("---")
    
    # 1. 십일조 / 기부
    st.write("#### 1️⃣ 십일조 및 헌금/기부")
    col1, col2 = st.columns([2, 1])
    with col1:
        tithe_amt = st.number_input("십일조 금액 (원)", value=0, step=10000, key="tithe_amt")
    with col2:
        tithe_pay = st.selectbox("결제/이체 수단", payment_methods, index=payment_methods.index("계좌이체") if "계좌이체" in payment_methods else 0, key="tithe_pay")

    col3, col4 = st.columns([2, 1])
    with col3:
        donation_amt = st.number_input("기타 헌금 / 정기 후원금 (원)", value=0, step=10000, key="don_amt")
    with col4:
        donation_pay = st.selectbox("결제/이체 수단", payment_methods, index=payment_methods.index("계좌이체") if "계좌이체" in payment_methods else 0, key="don_pay")

    st.write("---")
    # 2. 보험료 세부
    st.write("#### 2️⃣ 보험료 세부 항목")
    b1, b2 = st.columns([2, 1])
    with b1:
        ins_main = st.number_input("본인 종합/실손보험 (원)", value=0, step=5000, key="ins_main")
    with b2:
        ins_main_pay = st.selectbox("결제 수단", payment_methods, key="ins_main_pay")

    b3, b4 = st.columns([2, 1])
    with b3:
        ins_spouse = st.number_input("배우자/가족 보험 (원)", value=0, step=5000, key="ins_spouse")
    with b4:
        ins_spouse_pay = st.selectbox("결제 수단", payment_methods, key="ins_spouse_pay")

    b5, b6 = st.columns([2, 1])
    with b5:
        ins_car = st.number_input("자동차/운전자 보험 (원)", value=0, step=5000, key="ins_car")
    with b6:
        ins_car_pay = st.selectbox("결제 수단", payment_methods, key="ins_car_pay")

    b7, b8 = st.columns([2, 1])
    with b7:
        ins_other = st.number_input("기타 보장/저축성 보험 (원)", value=0, step=5000, key="ins_other")
    with b8:
        ins_other_pay = st.selectbox("결제 수단", payment_methods, key="ins_other_pay")

    st.write("---")
    # 3. 통신비 세부
    st.write("#### 3️⃣ 통신비 세부 항목")
    t1, t2 = st.columns([2, 1])
    with t1:
        tel_mobile = st.number_input("본인/가족 휴대폰 요금 (원)", value=0, step=5000, key="tel_mobile")
    with t2:
        tel_mobile_pay = st.selectbox("결제 수단", payment_methods, key="tel_mobile_pay")

    t3, t4 = st.columns([2, 1])
    with t3:
        tel_net = st.number_input("집 인터넷 / IPTV 요금 (원)", value=0, step=5000, key="tel_net")
    with t4:
        tel_net_pay = st.selectbox("결제 수단", payment_methods, key="tel_net_pay")

    st.write("---")
    # 4. 관리비 및 공과금 세부
    st.write("#### 4️⃣ 관리비 및 공과금 세부 항목")
    u1, u2 = st.columns([2, 1])
    with u1:
        util_apt = st.number_input("아파트/주택 관리비 (원)", value=0, step=10000, key="util_apt")
    with u2:
        util_apt_pay = st.selectbox("결제 수단", payment_methods, key="util_apt_pay")

    u3, u4 = st.columns([2, 1])
    with u3:
        util_gas = st.number_input("도시가스 / 난방비 (원)", value=0, step=5000, key="util_gas")
    with u4:
        util_gas_pay = st.selectbox("결제 수단", payment_methods, key="util_gas_pay")

    u5, u6 = st.columns([2, 1])
    with u5:
        util_elec = st.number_input("전기 / 수도세 (별도 납부 시) (원)", value=0, step=5000, key="util_elec")
    with u6:
        util_elec_pay = st.selectbox("결제 수단", payment_methods, key="util_elec_pay")

    st.write("---")
    # 5. 구독료 및 주거비
    st.write("#### 5️⃣ OTT 구독료 / 기타 정기지출")
    s1, s2 = st.columns([2, 1])
    with s1:
        sub_ott = st.number_input("OTT / 음원 구독료 (넷플릭스, 유튜브 등) (원)", value=0, step=1000, key="sub_ott")
    with s2:
        sub_ott_pay = st.selectbox("결제 수단", payment_methods, key="sub_ott_pay")

    s3, s4 = st.columns([2, 1])
    with s3:
        sub_rent = st.number_input("주거 월세 / 대출이자 (원)", value=0, step=10000, key="sub_rent")
    with s4:
        sub_rent_pay = st.selectbox("결제 수단", payment_methods, index=payment_methods.index("계좌이체") if "계좌이체" in payment_methods else 0, key="sub_rent_pay")

    st.write("---")
    if st.button("🚀 이번 달 고정비 일괄 저장", use_container_width=True, type="primary"):
        fixed_items = [
            ("십일조/기부", "십일조", tithe_amt, tithe_pay, "정기 고정비 - 십일조"),
            ("십일조/기부", "기타 헌금/후원", donation_amt, donation_pay, "정기 고정비 - 후원금"),
            ("보험료", "본인 종합/실손보험", ins_main, ins_main_pay, "정기 고정비 - 본인보험"),
            ("보험료", "배우자/가족 보험", ins_spouse, ins_spouse_pay, "정기 고정비 - 가족보험"),
            ("보험료", "운전자/자동차 보험", ins_car, ins_car_pay, "정기 고정비 - 차량보험"),
            ("보험료", "기타 보험", ins_other, ins_other_pay, "정기 고정비 - 기타보험"),
            ("주거/통신", "휴대폰 요금", tel_mobile, tel_mobile_pay, "정기 고정비 - 이동통신"),
            ("주거/통신", "인터넷/IPTV 요금", tel_net, tel_net_pay, "정기 고정비 - 유선통신"),
            ("공과금", "아파트 관리비", util_apt, util_apt_pay, "정기 고정비 - 관리비"),
            ("공과금", "도시가스 요금", util_gas, util_gas_pay, "정기 고정비 - 가스비"),
            ("공과금", "전기/수도 요금", util_elec, util_elec_pay, "정기 고정비 - 공과금"),
            ("문화/여가", "OTT/정기구독료", sub_ott, sub_ott_pay, "정기 고정비 - 구독서비스"),
            ("주거/통신", "월세/대출이자", sub_rent, sub_rent_pay, "정기 고정비 - 주거비")
        ]

        count = 0
        for cat, sub, amt, pay_m, memo_txt in fixed_items:
            if amt > 0:
                add_record(target_date, "지출", cat, sub, amt, pay_m, True, memo_txt)
                count += 1

        if count > 0:
            st.success(f"🎉 총 {count}건의 세부 고정 지출이 안전하게 저장되었습니다!")
        else:
            st.warning("금액이 입력된 항목이 없습니다.")

# -------------------------------------------------------------
# 메뉴 5: 분류 관리
# -------------------------------------------------------------
elif menu == "🏷️ 분류 및 결제수단 관리":
    st.subheader("🏷️ 카테고리 및 결제수단 맞춤 설정")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("##### 🛒 지출 카테고리")
        st.write(expense_categories)
        new_exp = st.text_input("새 지출 카테고리 추가")
        if st.button("지출 카테고리 추가") and new_exp:
            if new_exp not in expense_categories:
                add_setting("expense", new_exp.strip())
                st.success(f"'{new_exp}' 추가 완료!")
                st.rerun()
                
        del_exp = st.selectbox("삭제할 지출 카테고리", ["선택 안 함"] + expense_categories)
        if st.button("지출 카테고리 삭제") and del_exp != "선택 안 함":
            delete_setting("expense", del_exp)
            st.warning(f"'{del_exp}' 삭제 완료!")
            st.rerun()

    with col2:
        st.write("##### 💵 수입 카테고리")
        st.write(income_categories)
        new_inc = st.text_input("새 수입 카테고리 추가")
        if st.button("수입 카테고리 추가") and new_inc:
            if new_inc not in income_categories:
                add_setting("income", new_inc.strip())
                st.success(f"'{new_inc}' 추가 완료!")
                st.rerun()
                
        del_inc = st.selectbox("삭제할 수입 카테고리", ["선택 안 함"] + income_categories)
        if st.button("수입 카테고리 삭제") and del_inc != "선택 안 함":
            delete_setting("income", del_inc)
            st.warning(f"'{del_inc}' 삭제 완료!")
            st.rerun()

    with col3:
        st.write("##### 💳 결제수단 / 카드")
        st.write(payment_methods)
        new_pay = st.text_input("새 카드/결제수단 추가")
        if st.button("결제수단 추가") and new_pay:
            if new_pay not in payment_methods:
                add_setting("payment", new_pay.strip())
                st.success(f"'{new_pay}' 추가 완료!")
                st.rerun()
                
        del_pay = st.selectbox("삭제할 결제수단", ["선택 안 함"] + payment_methods)
        if st.button("결제수단 삭제") and del_pay != "선택 안 함":
            delete_setting("payment", del_pay)
            st.warning(f"'{del_pay}' 삭제 완료!")
            st.rerun()
