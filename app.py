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
        # settings 시트가 아직 없으면 기본값 사용
        return DEFAULT_INCOME_CATS.copy(), DEFAULT_EXPENSE_CATS.copy(), DEFAULT_PAY_METHODS.copy()

def save_settings(income_cats, expense_cats, pay_methods):
    try:
        # 최대 길이에 맞춰 DataFrame 생성
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
        
        st.divider()
        st.write("#### ⚖️ 고정지출 vs 변동지출 비교")
        fc1, fc2 = st.columns(2)
        fc1.metric("📌 고정지출", f"{fixed_expense:,} 원")
        fc2.metric("🛒 변동지출", f"{var_expense:,} 원")
        
        if total_expense > 0:
            fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.4)
            st.plotly_chart(fig, use_container_width=True)

# -------------------------------------------------------------
# 메뉴 3: 전체 내역 및 관리
# -------------------------------------------------------------
elif menu == "📋 전체 내역 및 관리":
    st.subheader("전체 가계부 내역 관리")
    df = load_data()
    if not df.empty:
        df_sorted = df.sort_values(by=["date", "id"], ascending=[False, False])
        st.dataframe(df_sorted, use_container_width=True)
        
        del_id = st.number_input("삭제할 ID 입력", min_value=1, step=1)
        if st.button("삭제 실행", type="primary"):
            if delete_record(del_id):
                st.success(f"ID {del_id} 내역 삭제 완료!")
                st.rerun()

# -------------------------------------------------------------
# 메뉴 4: 정기 고정비 일괄 등록
# -------------------------------------------------------------
elif menu == "⚙️ 정기 고정비 일괄 등록":
    st.subheader("매달 반복되는 고정비 원클릭 등록")
    target_date = st.date_input("등록 기준 일자", datetime.today())
    
    tithe = st.number_input("십일조 / 헌금 (원)", value=0, step=10000)
    insurance = st.number_input("보험료 (원)", value=0, step=10000)
    telecom = st.number_input("통신비 (원)", value=0, step=5000)
    maintenance = st.number_input("관리비/공과금 (원)", value=0, step=10000)
    
    if st.button("🚀 일괄 전송", use_container_width=True):
        items = [
            ("십일조/기부", "십일조", tithe, "계좌이체"),
            ("보험료", "보장성 보험", insurance, "계좌이체"),
            ("주거/통신", "통신비", telecom, payment_methods[0] if payment_methods else "카드"),
            ("공과금", "관리비", maintenance, "계좌이체")
        ]
        df = load_data()
        start_id = 1 if df.empty or "id" not in df.columns else int(df["id"].max()) + 1
        new_rows = [{"id": start_id + i, "date": str(target_date), "type": "지출", "category": cat,
                     "sub_category": sub, "amount": int(amt), "payment_method": m, "is_fixed": 1, "memo": "고정비 일괄등록"}
                    for i, (cat, sub, amt, m) in enumerate(items) if amt > 0]
        if new_rows and save_data(pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)):
            st.success(f"{len(new_rows)}건 등록 완료!")

# -------------------------------------------------------------
# 메뉴 5: 🏷️ 분류 및 결제수단 관리 (신규 추가)
# -------------------------------------------------------------
elif menu == "🏷️ 분류 및 결제수단 관리":
    st.subheader("🏷️ 카테고리 및 결제수단 맞춤 설정")
    st.caption("새로운 항목을 추가하거나 불필요한 항목을 삭제하면 구글 시트에 저장되어 즉시 반영됩니다.")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("##### 🛒 지출 카테고리")
        st.write(expense_categories)
        new_exp = st.text_input("새 지출 카테고리 추가", placeholder="예: 육아/키즈, 경조사")
        if st.button("지출 카테고리 추가") and new_exp:
            if new_exp not in expense_categories:
                expense_categories.append(new_exp)
                save_settings(income_categories, expense_categories, payment_methods)
                st.success(f"'{new_exp}' 추가 완료!")
                st.rerun()
                
        del_exp = st.selectbox("삭제할 지출 카테고리", ["선택 안 함"] + expense_categories)
        if st.button("지출 카테고리 삭제") and del_exp != "선택 안 함":
            expense_categories.remove(del_exp)
            save_settings(income_categories, expense_categories, payment_methods)
            st.warning(f"'{del_exp}' 삭제 완료!")
            st.rerun()

    with col2:
        st.write("##### 💵 수입 카테고리")
        st.write(income_categories)
        new_inc = st.text_input("새 수입 카테고리 추가", placeholder="예: 중고거래, 강의료")
        if st.button("수입 카테고리 추가") and new_inc:
            if new_inc not in income_categories:
                income_categories.append(new_inc)
                save_settings(income_categories, expense_categories, payment_methods)
                st.success(f"'{new_inc}' 추가 완료!")
                st.rerun()
                
        del_inc = st.selectbox("삭제할 수입 카테고리", ["선택 안 함"] + income_categories)
        if st.button("수입 카테고리 삭제") and del_inc != "선택 안 함":
            income_categories.remove(del_inc)
            save_settings(income_categories, expense_categories, payment_methods)
            st.warning(f"'{del_inc}' 삭제 완료!")
            st.rerun()

    with col3:
        st.write("##### 💳 결제수단 / 카드")
        st.write(payment_methods)
        new_pay = st.text_input("새 카드/결제수단 추가", placeholder="예: 롯데카드, 토스페이")
        if st.button("결제수단 추가") and new_pay:
            if new_pay not in payment_methods:
                payment_methods.append(new_pay)
                save_settings(income_categories, expense_categories, payment_methods)
                st.success(f"'{new_pay}' 추가 완료!")
                st.rerun()
                
        del_pay = st.selectbox("삭제할 결제수단", ["선택 안 함"] + payment_methods)
        if st.button("결제수단 삭제") and del_pay != "선택 안 함":
            payment_methods.remove(del_pay)
            save_settings(income_categories, expense_categories, payment_methods)
            st.warning(f"'{del_pay}' 삭제 완료!")
            st.rerun()