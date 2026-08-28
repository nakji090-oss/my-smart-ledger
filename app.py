import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import io

st.set_page_config(page_title="클라우드 스마트 가계부", page_icon="💰", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

# -------------------------------------------------------------
# 1. 기본 분류 데이터 및 설정 로드 함수
# -------------------------------------------------------------
DEFAULT_INCOME_CATS = ["월급", "성과급", "명절보너스", "금융/배당수입", "부수입", "기타수입"]
DEFAULT_EXPENSE_CATS = ["식비", "주거/통신", "공과금", "보험료", "십일조/기부", "교통/차량", "쇼핑/생활", "문화/여가", "교육", "기타지출"]
DEFAULT_PAY_METHODS = ["신한카드", "국민카드", "현대카드", "삼성카드", "체크카드", "계좌이체", "현금"]

def load_settings():
    try:
        df_settings = conn.read(worksheet="settings", ttl=0)
        if df_settings is None or df_settings.empty:
            return DEFAULT_INCOME_CATS.copy(), DEFAULT_EXPENSE_CATS.copy(), DEFAULT_PAY_METHODS.copy()
        
        income_cats = df_settings["income_cats"].dropna().tolist() or DEFAULT_INCOME_CATS
        expense_cats = df_settings["expense_cats"].dropna().tolist() or DEFAULT_EXPENSE_CATS
        pay_methods = df_settings["pay_methods"].dropna().tolist() or DEFAULT_PAY_METHODS
        return income_cats, expense_cats, pay_methods
    except Exception:
        return DEFAULT_INCOME_CATS.copy(), DEFAULT_EXPENSE_CATS.copy(), DEFAULT_PAY_METHODS.copy()

def save_settings(income_cats, expense_cats, pay_methods):
    try:
        max_len = max(len(income_cats), len(expense_cats), len(pay_methods))
        df_new = pd.DataFrame({
            "income_cats": income_cats + [None] * (max_len - len(income_cats)),
            "expense_cats": expense_cats + [None] * (max_len - len(expense_cats)),
            "pay_methods": pay_methods + [None] * (max_len - len(pay_methods))
        })
        conn.update(worksheet="settings", data=df_new)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"설정 저장 실패: {e}")
        return False

# -------------------------------------------------------------
# 2. 거래 내역 CRUD 함수
# -------------------------------------------------------------
COLUMNS = ["id", "date", "type", "category", "sub_category", "amount", "payment_method", "is_fixed", "memo"]

def load_data():
    try:
        df = conn.read(worksheet="Sheet1", ttl=0)
        if df is None or df.empty:
            return pd.DataFrame(columns=COLUMNS)
        df = df.dropna(how="all")
        if not df.empty:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
            df["is_fixed"] = pd.to_numeric(df["is_fixed"], errors="coerce").fillna(0).astype(int)
            df["id"] = pd.to_numeric(df["id"], errors="coerce").fillna(0).astype(int)
            df["date"] = df["date"].astype(str)
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_data(df):
    try:
        conn.update(worksheet="Sheet1", data=df)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")
        return False

def add_record(date_str, r_type, cat, sub_cat, amount, method, is_fixed, memo):
    df = load_data()
    next_id = 1 if df.empty or "id" not in df.columns else int(df["id"].max()) + 1
    new_row = pd.DataFrame([{
        "id": next_id, "date": str(date_str), "type": r_type, "category": cat,
        "sub_category": sub_cat, "amount": int(amount), "payment_method": method,
        "is_fixed": 1 if is_fixed else 0, "memo": memo
    }])
    return save_data(pd.concat([df, new_row], ignore_index=True))

def delete_record(record_id):
    df = load_data()
    if df.empty: return False
    return save_data(df[df["id"] != record_id])

# -------------------------------------------------------------
# 3. UI 및 내비게이션
# -------------------------------------------------------------
income_categories, expense_categories, payment_methods = load_settings()

st.title("💰 클라우드 스마트 가계부")
menu = st.sidebar.radio("메뉴 선택", [
    "📝 내역 입력", 
    "📊 월별 분석 및 통계", 
    "📋 전체 내역 및 관리", 
    "⚙️ 정기 고정비 일괄 등록",
    "🏷️ 분류 및 결제수단 관리"
])

# -------------------------------------------------------------
# 메뉴 1: 내역 입력 (+ 직접 입력 지원)
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
                sub_category = st.text_input("상세 항목 (예: 아파트관리비, 점심식사)")
        else:
            col3, col4 = st.columns(2)
            with col3:
                category = st.selectbox("수입 항목", income_categories + ["➕ 새 항목 직접 입력"])
                custom_cat = st.text_input("새 수입 항목명 입력") if category == "➕ 새 항목 직접 입력" else None
                payment_method = st.selectbox("입금 수단", ["급여통장", "부계좌", "현금", "기타"])
                custom_method = None
            with col4:
                is_fixed = False
                sub_category = st.text_input("상세 내용 (예: 기본급, 배당금)")

        final_category = custom_cat.strip() if custom_cat else category
        final_method = custom_method.strip() if custom_method else payment_method
        memo = st.text_input("메모 / 사용처", placeholder="예: 스타벅스, 마트 장보기 등")
        submitted = st.form_submit_button("구글 시트에 저장하기", use_container_width=True)
        
        if submitted:
            if amount <= 0:
                st.error("금액을 올바르게 입력해주세요.")
            elif not final_category or final_category.startswith("➕"):
                st.error("카테고리명을 입력해주세요.")
            else:
                with st.spinner("구글 시트에 저장 중..."):
                    if add_record(rec_date, rec_type, final_category, sub_category, amount, final_method, is_fixed, memo):
                        st.success("구글 시트에 성공적으로 동기화되었습니다!")

# -------------------------------------------------------------
# 메뉴 2: 월별 분석 및 통계
# -------------------------------------------------------------
elif menu == "📊 월별 분석 및 통계":
    st.subheader("월별 수입/지출 & 고정비/변동비 분석")
    df = load_data()
    
    if df.empty:
        st.info("기록된 데이터가 없습니다.")
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
        c3.metric("순 잉여금(저축)", f"{net_savings:,} 원")
        
        st.divider()
        st.write("#### ⚖️ 고정지출 vs 변동지출 비교")
        fc1, fc2 = st.columns(2)
        fc1.metric("📌 고정지출", f"{fixed_expense:,} 원")
        fc2.metric("🛒 변동지출", f"{var_expense:,} 원")
        
        if total_expense > 0:
            fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.4)
            st.plotly_chart(fig, use_container_width=True)
            
        st.divider()
        c_col1, c_col2 = st.columns(2)
        with c_col1:
            st.write("#### 💳 결제수단/카드별 지출")
            if not expense_df.empty:
                card_sum = expense_df.groupby('payment_method')['amount'].sum().reset_index()
                st.plotly_chart(px.bar(card_sum, x='payment_method', y='amount', text_auto=True), use_container_width=True)
        with c_col2:
            st.write("#### 🏷️ 카테고리별 지출")
            if not expense_df.empty:
                cat_sum = expense_df.groupby('category')['amount'].sum().reset_index()
                st.plotly_chart(px.pie(cat_sum, values='amount', names='category'), use_container_width=True)

# -------------------------------------------------------------
# 메뉴 3: 전체 내역 및 관리
# -------------------------------------------------------------
elif menu == "📋 전체 내역 및 관리":
    st.subheader("전체 가계부 내역 관리")
    df = load_data()
    if not df.empty:
        df_sorted = df.sort_values(by=["date", "id"], ascending=[False, False])
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_sorted.to_excel(writer, index=False, sheet_name='가계부_내역')
        st.download_button(
            label="📥 현재 내역 엑셀(XLSX) 다운로드",
            data=output.getvalue(),
            file_name=f"가계부_내역_{datetime.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        st.dataframe(df_sorted, use_container_width=True)
        
        del_id = st.number_input("삭제할 ID 번호 입력", min_value=1, step=1)
        if st.button("삭제 실행", type="primary"):
            if delete_record(del_id):
                st.success(f"ID {del_id} 내역 삭제 완료!")
                st.rerun()

# -------------------------------------------------------------
# 메뉴 4: 정기 고정비 일괄 등록 (세부 입력 업그레이드)
# -------------------------------------------------------------
elif menu == "⚙️ 정기 고정비 일괄 등록":
    st.subheader("⚙️ 매달 반복되는 정기 고정비 세부 일괄 등록")
    st.caption("항목별로 금액과 결제수단을 세부 입력하세요. 0원인 항목은 자동으로 제외되고 등록됩니다.")
    
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
    
    # 2. 보험료 세부 (본인, 배우자, 자녀, 실비, 암, 운전자 등)
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

    # 3. 통신료 세부 (휴대폰 vs 인터넷/TV)
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

    u3, u4 = st.columns(
