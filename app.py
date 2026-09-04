import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io

# -------------------------------------------------------------
# 1. 패키지 로드 및 구글 시트 연동 검사
# -------------------------------------------------------------
try:
    from streamlit_gsheets import GSheetsConnection
except ImportError:
    st.error("🚨 `st-gsheets-connection` 패키지가 설치되지 않았습니다. GitHub의 `requirements.txt`를 확인해 주세요.")
    st.stop()

st.set_page_config(page_title="스마트 가계부", page_icon="💰", layout="wide")

if "connections" not in st.secrets or "gsheets" not in st.secrets["connections"]:
    st.error("🚨 구글 시트 연동 설정이 안 되어 있습니다!\n\nGitHub 저장소에 `.streamlit/secrets.toml` 파일을 만들고 서비스 계정 키를 등록해야 합니다.")
    st.stop()

conn = st.connection("gsheets", type=GSheetsConnection)

# -------------------------------------------------------------
# 2. 세션 상태 초기화
# -------------------------------------------------------------
if 'last_date' not in st.session_state:
    st.session_state.last_date = datetime.today()
if 'last_payment' not in st.session_state:
    st.session_state.last_payment = None
if 'confirm_batch' not in st.session_state:
    st.session_state.confirm_batch = False

# -------------------------------------------------------------
# 3. 모바일 최적화 커스텀 스타일 (CSS)
# -------------------------------------------------------------
st.markdown("""
<style>
    [data-testid="stHeaderActionElements"], div[class^="viewerBadge"], footer { display: none !important; }
    
    .main .block-container {
        padding-top: 4rem !important; 
        padding-bottom: 2.5rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        max-width: 1000px;
    }
    .stButton > button {
        border-radius: 12px; font-weight: 600; font-size: 15px; min-height: 46px; box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }
    .stTextInput > div > div > input, .stNumberInput > div > div > input, .stSelectbox > div > div {
        border-radius: 10px; font-size: 15px;
    }
    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 14px 16px; border-radius: 14px; margin-bottom: 8px;
    }
    .top-card {
        background-color: #eef2ff; border-left: 4px solid #4f46e5; padding: 10px 14px; border-radius: 8px; margin-bottom: 6px; font-size: 14px;
    }
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] { background-color: #1e222b; border-color: #2f3440; }
        .top-card { background-color: #262b36; border-left-color: #6366f1; color: #ffffff; }
    }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 4. 구글 시트 DB 헬퍼 함수
# -------------------------------------------------------------
def load_gsheet(worksheet_name, default_cols):
    try:
        df = conn.read(worksheet=worksheet_name, ttl=0)
        if df.empty and len(df.columns) == 0:
            return pd.DataFrame(columns=default_cols)
        return df.dropna(how='all')
    except Exception as e:
        st.error("🚨 구글 서버와의 통신이 일시적으로 지연되었습니다. 데이터 덮어쓰기 방지를 위해 앱을 일시 정지합니다. 화면을 새로고침 해주세요.")
        st.stop()

def save_gsheet(worksheet_name, df):
    conn.update(worksheet=worksheet_name, data=df)

def load_settings():
    df = load_gsheet("settings", ['setting_type', 'name'])
    if df.empty:
        return [], []
        
    expenses = df[df['setting_type'] == 'expense']['name'].dropna().tolist()
    payments = df[df['setting_type'] == 'payment']['name'].dropna().tolist()
    return expenses, payments

def add_setting(stype, name):
    df = load_gsheet("settings", ['setting_type', 'name'])
    if not ((df['setting_type'] == stype) & (df['name'] == name)).any():
        new_row = pd.DataFrame([{'setting_type': stype, 'name': name}])
        df = pd.concat([df, new_row], ignore_index=True)
        save_gsheet("settings", df)

def load_records():
    df = load_gsheet("records", ['id', 'date', 'category', 'sub_category', 'amount', 'payment_method', 'is_fixed', 'memo'])
    if not df.empty:
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0).astype(int)
    return df

def add_record(date_str, cat, sub_cat, amount, method, is_fixed, memo):
    df = load_records()
    new_id = int(df['id'].max() + 1) if not df.empty and pd.notna(df['id'].max()) else 1
    new_row = pd.DataFrame([{
        'id': new_id, 'date': str(date_str), 'category': cat, 'sub_category': sub_cat,
        'amount': int(amount), 'payment_method': method, 'is_fixed': 1 if is_fixed else 0, 'memo': memo
    }])
    df = pd.concat([df, new_row], ignore_index=True) if not df.empty else new_row
    save_gsheet("records", df)

def upsert_edited_records(original_filtered_df, edited_df):
    df = load_records()
    orig_ids = set(original_filtered_df['id'].dropna().astype(int))
    curr_ids = set(edited_df['id'].dropna().astype(int)) if 'id' in edited_df.columns else set()
    deleted_ids = orig_ids - curr_ids

    for _, row in edited_df.iterrows():
        if row.get('삭제') == True and pd.notna(row.get('id')):
            deleted_ids.add(int(row['id']))

    df = df[~df['id'].isin(deleted_ids)]

    new_rows = []
    for _, row in edited_df.iterrows():
        if row.get('삭제') == True:
            continue
        r_id = row.get('id')
        parsed_date = pd.to_datetime(row['date'], errors='coerce')
        d_str = parsed_date.strftime("%Y-%m-%d") if pd.notna(parsed_date) else datetime.today().strftime("%Y-%m-%d")
        amt = int(pd.to_numeric(row['amount'], errors='coerce') or 0)
        is_f = 1 if row.get('is_fixed') in [True, 1, '1', 'True', 1.0] else 0

        if pd.notna(r_id) and r_id in df['id'].values:
            idx = df.index[df['id'] == r_id][0]
            df.at[idx, 'date'] = d_str
            df.at[idx, 'category'] = str(row['category'])
            df.at[idx, 'sub_category'] = str(row.get('sub_category', '') or '')
            df.at[idx, 'amount'] = amt
            df.at[idx, 'payment_method'] = str(row['payment_method'])
            df.at[idx, 'is_fixed'] = is_f
            df.at[idx, 'memo'] = str(row.get('memo', '') or '')
        else:
            new_id = int(df['id'].max() + 1) if not df.empty else (len(new_rows) + 1)
            new_rows.append({
                'id': new_id, 'date': d_str, 'category': str(row['category']),
                'sub_category': str(row.get('sub_category', '') or ''), 'amount': amt,
                'payment_method': str(row['payment_method']), 'is_fixed': is_f, 'memo': str(row.get('memo', '') or '')
            })

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    save_gsheet("records", df)

def import_records_from_df(import_df):
    df = load_records()
    required_cols = ['date', 'category', 'amount', 'payment_method']
    if not all(col in import_df.columns for col in required_cols):
        return False, "엑셀 필수 열이 누락되었습니다."
    
    new_rows = []
    for _, row in import_df.iterrows():
        parsed_date = pd.to_datetime(row['date'], errors='coerce')
        d_str = parsed_date.strftime("%Y-%m-%d") if pd.notna(parsed_date) else datetime.today().strftime("%Y-%m-%d")
        new_id = int(df['id'].max() + 1) if not df.empty else (len(new_rows) + 1)
        new_rows.append({
            'id': new_id, 'date': d_str, 'category': str(row['category']),
            'sub_category': str(row.get('sub_category', '') or ''),
            'amount': int(pd.to_numeric(row['amount'], errors='coerce') or 0),
            'payment_method': str(row['payment_method']),
            'is_fixed': 1 if str(row.get('is_fixed', 0)) in ['1', 'True', '1.0', True] else 0,
            'memo': str(row.get('memo', '') or '')
        })
        
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True) if not df.empty else pd.DataFrame(new_rows)
        save_gsheet("records", df)
    return True, f"총 {len(new_rows)}건의 내역 복원 완료"

def load_fixed_templates():
    df = load_gsheet("fixed_templates", ['id', 'category', 'sub_category', 'default_amount', 'default_payment', 'memo'])
    if not df.empty:
        df['default_amount'] = pd.to_numeric(df['default_amount'], errors='coerce').fillna(0).astype(int)
    return df

def save_edited_fixed_templates(orig_df, edited_df):
    df = load_fixed_templates()
    orig_ids = set(orig_df['id'].dropna().astype(int))
    curr_ids = set(edited_df['id'].dropna().astype(int)) if 'id' in edited_df.columns else set()
    deleted_ids = orig_ids - curr_ids

    for _, row in edited_df.iterrows():
        if row.get('템플릿 삭제') == True and pd.notna(row.get('id')):
            deleted_ids.add(int(row['id']))

    df = df[~df['id'].isin(deleted_ids)]

    new_rows = []
    for _, row in edited_df.iterrows():
        if row.get('템플릿 삭제') == True:
            continue
        r_id = row.get('id')
        cat = str(row['category'])
        sub = str(row.get('sub_category', ''))
        amt = int(pd.to_numeric(row['default_amount'], errors='coerce') or 0)
        pay = str(row['default_payment'])
        memo = str(row.get('memo', ''))

        if pd.notna(r_id) and r_id in df['id'].values:
            idx = df.index[df['id'] == r_id][0]
            df.at[idx, 'category'] = cat
            df.at[idx, 'sub_category'] = sub
            df.at[idx, 'default_amount'] = amt
            df.at[idx, 'default_payment'] = pay
            df.at[idx, 'memo'] = memo
        else:
            new_id = int(df['id'].max() + 1) if not df.empty else (len(new_rows) + 1)
            new_rows.append({
                'id': new_id, 'category': cat, 'sub_category': sub,
                'default_amount': amt, 'default_payment': pay, 'memo': memo
            })

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True) if not df.empty else pd.DataFrame(new_rows)
    save_gsheet("fixed_templates", df)

def update_template_defaults(t_id, amount, payment):
    df = load_fixed_templates()
    if pd.notna(t_id) and t_id in df['id'].values:
        idx = df.index[df['id'] == t_id][0]
        df.at[idx, 'default_amount'] = int(amount)
        df.at[idx, 'default_payment'] = payment
        save_gsheet("fixed_templates", df)

# -------------------------------------------------------------
# 5. 메인 UI & 메뉴
# -------------------------------------------------------------
expense_categories, payment_methods = load_settings()

st.title("💰 스마트 가계부")
menu = st.sidebar.radio("📌 바로가기 메뉴", [
    "📝 지출 내역 입력", 
    "📊 월별 지출 분석", 
    "📈 월별 지출 비교", 
    "📋 전체 내역 및 바로 수정", 
    "⚙️ 정기 고정비 일괄 등록",
    "🏷️ 분류 및 결제수단 관리"
])

# -------------------------------------------------------------
# 메뉴 1: 지출 내역 입력
# -------------------------------------------------------------
if menu == "📝 지출 내역 입력":
    st.subheader("📝 새로운 지출 입력")
    
    with st.form("record_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            rec_date = st.date_input("날짜", st.session_state.last_date)
        with col2:
            amount = st.number_input("금액 (원)", min_value=0, step=1000, value=0, format="%d")
            
        col3, col4 = st.columns(2)
        with col3:
            category = st.selectbox("지출 카테고리 (대분류)", expense_categories + ["➕ 새 카테고리 직접 입력"])
            custom_cat = st.text_input("새 지출 카테고리명", placeholder="직접 입력") if category == "➕ 새 카테고리 직접 입력" else None
        with col4:
            sub_category = st.text_input("상세 항목", placeholder="예: 점심식사, 주유비, 커피")
            
        col5, col6 = st.columns(2)
        with col5:
            pay_idx = payment_methods.index(st.session_state.last_payment) if st.session_state.last_payment in payment_methods else 0
            payment_options = payment_methods + ["➕ 새 결제수단 직접 입력"]
            payment_method = st.selectbox("결제 수단 / 카드", payment_options, index=pay_idx)
            custom_method = st.text_input("새 결제수단명", placeholder="직접 입력") if payment_method == "➕ 새 결제수단 직접 입력" else None
        with col6:
            memo = st.text_input("메모 / 사용처", placeholder="예: 스타벅스 남양주점, 쿠팡")
            
        final_category = custom_cat.strip() if custom_cat else category
        final_method = custom_method.strip() if custom_method else payment_method
        
        st.write("")
        is_fixed = st.checkbox("📌 매달 나가는 고정 지출인가요? (공과금, 보험료, 구독료, 통신비 등)")

        st.write("")
        submitted = st.form_submit_button("💾 지출 내역 저장하기", use_container_width=True, type="primary")
        
        if submitted:
            if amount <= 0:
                st.error("금액을 0원보다 크게 입력해주세요.")
            elif not final_category or final_category.startswith("➕"):
                st.error("카테고리명을 정확히 입력해주세요.")
            elif not final_method or final_method.startswith("➕"):
                st.error("결제 수단을 정확히 입력해주세요.")
            else:
                add_record(rec_date, final_category, sub_category, amount, final_method, is_fixed, memo)
                if custom_cat:
                    add_setting("expense", custom_cat.strip())
                if custom_method:
                    add_setting("payment", custom_method.strip())
                
                st.session_state.last_date = rec_date
                st.session_state.last_payment = final_method
                
                st.success("🎉 지출 내역이 성공적으로 저장되었습니다!")
                st.rerun()

# -------------------------------------------------------------
# 메뉴 2: 월별 지출 분석 (변동지출 비중 차트 추가)
# -------------------------------------------------------------
elif menu == "📊 월별 지출 분석":
    st.subheader("📊 월별 지출 심층 분석")
    df = load_records()
    
    current_ym = datetime.today().strftime('%Y-%m')
    
    if df.empty:
        df['year_month'] = []
        all_months = [current_ym]
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        all_months = sorted(list(set(df['year_month'].tolist() + [current_ym])), reverse=True)
    
    default_idx = all_months.index(current_ym) if current_ym in all_months else 0
    selected_month = st.selectbox("조회할 월 선택", all_months, index=default_idx)
    
    expense_df = df[df['year_month'] == selected_month] if not df.empty else pd.DataFrame()
    
    total_expense = expense_df['amount'].sum() if not expense_df.empty else 0
    fixed_expense = expense_df[expense_df['is_fixed'] == 1]['amount'].sum() if not expense_df.empty else 0
    var_expense = expense_df[expense_df['is_fixed'] == 0]['amount'].sum() if not expense_df.empty else 0
    
    st.metric("총 지출", f"{total_expense:,} 원")
    
    if not expense_df.empty and total_expense > 0:
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
        st.write("#### ⚖️ 고정지출 vs 변동지출")
        fc1, fc2 = st.columns(2)
        fc1.metric("📌 고정지출", f"{fixed_expense:,} 원")
        fc2.metric("🛒 변동지출", f"{var_expense:,} 원")
        
        fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.45)
        fig.update_layout(margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)

        st.write("---")
        st.write("#### 🏷️ 전체 카테고리별 지출 비중")
        cat_sum = expense_df.groupby('category')['amount'].sum().reset_index()
        fig_cat = px.pie(cat_sum, values='amount', names='category', hole=0.35)
        fig_cat.update_layout(margin=dict(t=20, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3))
        st.plotly_chart(fig_cat, use_container_width=True)

        # ⭐️ 변동지출(고정비 제외) 비중 파이 차트 추가
        st.write("---")
        st.write("#### 🛒 변동지출 카테고리별 비중 (고정비 제외)")
        var_expense_df = expense_df[expense_df['is_fixed'] == 0]
        if not var_expense_df.empty and var_expense > 0:
            var_cat_sum = var_expense_df.groupby('category')['amount'].sum().reset_index()
            fig_var_cat = px.pie(var_cat_sum, values='amount', names='category', hole=0.35)
            fig_var_cat.update_layout(margin=dict(t=20, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3))
            st.plotly_chart(fig_var_cat, use_container_width=True)
        else:
            st.info("이번 달 변동지출 내역이 없습니다.")

    else:
        st.info("해당 월의 지출 데이터가 없습니다.")

# -------------------------------------------------------------
# 메뉴 3: 월별 지출 비교 (날짜 포맷 고정 및 변동지출 그래프 추가)
# -------------------------------------------------------------
elif menu == "📈 월별 지출 비교":
    st.subheader("📈 월별 지출 추이 및 전월 대비 비교")
    df = load_records()
    
    if df.empty:
        st.info("지출 내역이 없습니다.")
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        monthly_summary = df.groupby('year_month').agg(
            총지출=('amount', 'sum'),
            고정지출=('amount', lambda x: x[df.loc[x.index, 'is_fixed'] == 1].sum()),
            변동지출=('amount', lambda x: x[df.loc[x.index, 'is_fixed'] == 0].sum())
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
            text_auto=',.0f'
        )
        fig_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2), xaxis_title="")
        fig_trend.update_xaxes(type='category') # ⭐️ 영문 월별 표기를 막고 '2026-09' 숫자 형태로 강제 고정
        st.plotly_chart(fig_trend, use_container_width=True)
        
        st.write("---")
        st.write("#### 🏷️ 전체 카테고리별 월간 지출 변화")
        cat_monthly = df.groupby(['year_month', 'category'])['amount'].sum().reset_index()
        fig_cat_trend = px.bar(
            cat_monthly, x='year_month', y='amount', color='category',
            title="카테고리별 월별 비교", barmode='group', 
            text_auto=',.0f'
        )
        fig_cat_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3), xaxis_title="")
        fig_cat_trend.update_xaxes(type='category') # ⭐️ 영문 월별 표기 방지
        st.plotly_chart(fig_cat_trend, use_container_width=True)

        # ⭐️ 변동지출(고정비 제외) 카테고리별 비교 막대그래프 추가
        st.write("---")
        st.write("#### 🛒 변동지출 카테고리별 월간 변화 (고정비 제외)")
        var_df = df[df['is_fixed'] == 0]
        if not var_df.empty:
            var_cat_monthly = var_df.groupby(['year_month', 'category'])['amount'].sum().reset_index()
            fig_var_cat_trend = px.bar(
                var_cat_monthly, x='year_month', y='amount', color='category',
                title="변동지출 카테고리별 월별 비교", barmode='group', 
                text_auto=',.0f'
            )
            fig_var_cat_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3), xaxis_title="")
            fig_var_cat_trend.update_xaxes(type='category') # ⭐️ 영문 월별 표기 방지
            st.plotly_chart(fig_var_cat_trend, use_container_width=True)
        else:
            st.info("변동지출 내역이 없어 비교할 수 없습니다.")

# -------------------------------------------------------------
# 메뉴 4: 전체 내역 및 바로 수정
# -------------------------------------------------------------
elif menu == "📋 전체 내역 및 바로 수정":
    st.subheader("📋 전체 내역 관리 및 삭제·수정")
    df = load_records()
    
    tab1, tab2 = st.tabs(["⚡️ 표에서 바로 수정 및 삭제", "💾 엑셀 백업 & 복원(가져오기)"])
    
    with tab1:
        if df.empty:
            st.info("등록된 지출 내역이 없습니다.")
        else:
            current_ym = datetime.today().strftime('%Y-%m')
            df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
            all_months = sorted(list(set(df['year_month'].tolist() + [current_ym])), reverse=True)
            months = ["전체 월"] + all_months
            
            s_col1, s_col2 = st.columns([1, 2])
            with s_col1:
                default_idx = months.index(current_ym) if current_ym in months else 0
                sel_m = st.selectbox("조회할 월 선택", months, index=default_idx)
            with s_col2:
                kw = st.text_input("🔎 검색어 (사용처, 상세항목, 카테고리)", placeholder="예: 스타벅스, 신한카드")

            sort_c1, sort_c2 = st.columns(2)
            with sort_c1:
                sort_key = st.selectbox("🔽 정렬 기준", ["날짜", "금액", "카테고리", "상세 항목", "결제 수단"])
            with sort_c2:
                sort_dir = st.selectbox("↕️ 정렬 방식", ["내림차순 (최신/큰값 우선)", "오름차순 (과거/작은값 우선)"])
                
            filtered_df = df.copy()
            if sel_m != "전체 월":
                filtered_df = filtered_df[filtered_df['year_month'] == sel_m]
            if kw.strip():
                filtered_df = filtered_df[
                    filtered_df['memo'].str.contains(kw, na=False) |
                    filtered_df['sub_category'].str.contains(kw, na=False) |
                    filtered_df['category'].str.contains(kw, na=False)
                ]
                
            st.caption(f"💡 **수정:** 표의 칸을 클릭하여 내용을 변경하세요. 제목을 눌러도 정렬됩니다.<br>💡 **삭제:** 지우고 싶은 항목의 **[🗑️ 삭제]** 체크박스를 누른 후 <b>저장</b>을 누르세요.<br>(조회 항목: 총 {len(filtered_df)}건 / 합계: {filtered_df['amount'].sum():,}원)", unsafe_allow_html=True)
            
            df_edit = filtered_df.drop(columns=['year_month']).copy()
            if 'type' in df_edit.columns:
                df_edit = df_edit.drop(columns=['type'])
            df_edit.insert(0, '삭제', False)
            
            df_edit['id'] = pd.to_numeric(df_edit['id'], errors='coerce')
            df_edit['date'] = pd.to_datetime(df_edit['date'], errors='coerce')
            df_edit['category'] = df_edit['category'].fillna("").astype(str)
            df_edit['sub_category'] = df_edit['sub_category'].fillna("").astype(str)
            df_edit['amount'] = pd.to_numeric(df_edit['amount'], errors='coerce').fillna(0).astype(int)
            df_edit['payment_method'] = df_edit['payment_method'].fillna("").astype(str)
            df_edit['is_fixed'] = df_edit['is_fixed'].apply(lambda x: True if str(x).lower() in ['1', '1.0', 'true'] else False).astype(bool)
            df_edit['memo'] = df_edit['memo'].fillna("").astype(str)
            
            sort_col_map = {"날짜": "date", "금액": "amount", "카테고리": "category", "상세 항목": "sub_category", "결제 수단": "payment_method"}
            is_asc = True if "오름차순" in sort_dir else False
            df_edit = df_edit.sort_values(by=[sort_col_map[sort_key], 'id'], ascending=[is_asc, False])
            
            edited_data = st.data_editor(
                df_edit,
                column_config={
                    "삭제": st.column_config.CheckboxColumn("🗑️ 삭제", default=False),
                    "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "date": st.column_config.DateColumn("날짜", required=True, format="YYYY-MM-DD"),
                    "category": st.column_config.SelectboxColumn("카테고리", options=expense_categories, required=True),
                    "sub_category": st.column_config.TextColumn("상세 항목"),
                    "amount": st.column_config.NumberColumn("금액 (원)", min_value=0, step=1000, format="%d", required=True),
                    "payment_method": st.column_config.SelectboxColumn("결제 수단", options=payment_methods, required=True),
                    "is_fixed": st.column_config.CheckboxColumn("고정지출"),
                    "memo": st.column_config.TextColumn("메모 / 사용처"),
                },
                disabled=["id"], hide_index=True, use_container_width=True, num_rows="dynamic", key="ledger_table_editor"
            )
            
            st.write("")
            col_save1, col_save2 = st.columns([2, 1])
            with col_save1:
                if st.button("💾 체크된 항목 삭제 및 수정사항 전체 저장", type="primary", use_container_width=True):
                    upsert_edited_records(filtered_df, edited_data)
                    st.success("🎉 변경 사항이 구글 시트에 안전하게 동기화되었습니다!")
                    st.rerun()
            with col_save2:
                if st.button("🔄 원래대로 복구", use_container_width=True):
                    st.rerun()

    with tab2:
        st.write("#### 📥 1. 현재 가계부 내역 엑셀 다운로드")
        if not df.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='지출_내역')
            
            timestamp_str = datetime.today().strftime('%Y%m%d_%H%M')
            st.download_button(
                label="📥 가계부 전체 엑셀(XLSX) 다운로드 백업", data=output.getvalue(),
                file_name=f"지출내역_백업_{timestamp_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True
            )
        else:
            st.info("백업할 데이터가 없습니다.")
            
        st.write("---")
        st.write("#### 📤 2. 백업 엑셀 파일로 가계부 복원 (가져오기)")
        st.caption("기존에 다운로드해 둔 가계부 엑셀(.xlsx) 파일을 올리면 데이터를 안전하게 구글 시트로 복원합니다.")
        
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
    st.subheader("⚙️ 정기 고정비 일괄 등록 및 템플릿 관리")
    
    records_df = load_records()
    current_ym = datetime.today().strftime('%Y-%m')
    has_fixed_this_month = False
    
    if not records_df.empty:
        records_df['ym'] = pd.to_datetime(records_df['date'], errors='coerce').dt.strftime('%Y-%m')
        records_df['is_fixed_safe'] = pd.to_numeric(records_df['is_fixed'], errors='coerce').fillna(0).astype(int)
        fixed_this_month = records_df[(records_df['ym'] == current_ym) & (records_df['is_fixed_safe'] == 1)]
        if not fixed_this_month.empty:
            has_fixed_this_month = True
            st.warning(f"🚨 주의: 이번 달({current_ym})에 이미 등록된 고정 지출 이력이 {len(fixed_this_month)}건 있습니다. 이중 등록하지 않도록 주의하세요!")

    st.info("💡 **표 안에서 고정비 항목을 바로 추가/수정/삭제**할 수 있습니다. 가계부에 일괄 등록할 항목은 왼쪽 **'☑️ 이번달 등록'** 칸을 체크하세요.")
    
    df_fixed = load_fixed_templates()
    df_edit = df_fixed.copy()
    
    df_edit.insert(0, '이번달 등록', not has_fixed_this_month)
    df_edit.insert(1, '템플릿 삭제', False)
    
    df_edit['id'] = pd.to_numeric(df_edit['id'], errors='coerce')
    df_edit['category'] = df_edit['category'].fillna("").astype(str)
    df_edit['sub_category'] = df_edit['sub_category'].fillna("").astype(str)
    df_edit['default_amount'] = pd.to_numeric(df_edit['default_amount'], errors='coerce').fillna(0).astype(int)
    df_edit['default_payment'] = df_edit['default_payment'].fillna("").astype(str)
    df_edit['memo'] = df_edit['memo'].fillna("").astype(str)
    
    edited_data = st.data_editor(
        df_edit,
        column_config={
            "이번달 등록": st.column_config.CheckboxColumn("☑️ 이번달 등록"),
            "템플릿 삭제": st.column_config.CheckboxColumn("🗑️ 템플릿 삭제", default=False),
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "category": st.column_config.SelectboxColumn("카테고리", options=expense_categories, required=True),
            "sub_category": st.column_config.TextColumn("상세 항목", required=True),
            "default_amount": st.column_config.NumberColumn("기본 금액 (원)", min_value=0, step=1000, format="%d", required=True),
            "default_payment": st.column_config.SelectboxColumn("기본 결제수단", options=payment_methods, required=True),
            "memo": st.column_config.TextColumn("메모"),
        },
        hide_index=True, num_rows="dynamic", use_container_width=True
    )

    col_save, col_empty = st.columns([1, 1])
    with col_save:
        if st.button("💾 표의 수정사항(추가/삭제) 구글 시트에 영구 저장", use_container_width=True):
            save_edited_fixed_templates(df_fixed, edited_data)
            st.success("고정비 템플릿이 성공적으로 업데이트되었습니다!")
            st.rerun()

    st.write("---")
    st.write("#### 🚀 이번 달 가계부 일괄 등록 실행")
    target_date = st.date_input("등록 기준 일자", datetime.today())
    
    if st.button("🔍 체크된 항목 확인 및 일괄 등록 준비", use_container_width=True):
        save_edited_fixed_templates(df_fixed, edited_data)
        st.session_state.confirm_batch = True
        
    if st.session_state.get('confirm_batch', False):
        st.markdown("### 📋 일괄 등록 전 최종 확인")
        to_register = edited_data[(edited_data['이번달 등록'] == True) & (edited_data['템플릿 삭제'] == False)]
        
        if to_register.empty:
            st.warning("☑️ '이번달 등록' 칸에 체크된 항목이 없습니다. 표에서 등록할 항목을 체크한 후 다시 버튼을 눌러주세요.")
            st.session_state.confirm_batch = False
        else:
            st.dataframe(
                to_register[['category', 'sub_category', 'default_amount', 'default_payment', 'memo']],
                hide_index=True, use_container_width=True
            )
            total_amt = to_register['default_amount'].sum()
            st.info(f"✅ 총 **{len(to_register)}건**, 합계 **{total_amt:,}원**을 '{target_date.strftime('%Y-%m-%d')}' 날짜로 가계부에 일괄 등록합니다. 맞습니까?")
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🚀 네, 이대로 최종 등록 실행", type="primary", use_container_width=True):
                    df_records = load_records()
                    df_templates = load_fixed_templates()
                    
                    new_record_rows = []
                    count = 0
                    
                    for _, row in to_register.iterrows():
                        amt = int(pd.to_numeric(row['default_amount'], errors='coerce') or 0)
                        if amt > 0:
                            new_id = int(df_records['id'].max() + 1) if not df_records.empty and pd.notna(df_records['id'].max()) else 1
                            new_id += len(new_record_rows)
                            
                            new_record_rows.append({
                                'id': new_id, 
                                'date': target_date.strftime("%Y-%m-%d"), 
                                'category': str(row['category']), 
                                'sub_category': str(row['sub_category']), 
                                'amount': amt, 
                                'payment_method': str(row['default_payment']), 
                                'is_fixed': 1, 
                                'memo': str(row.get('memo', ''))
                            })
                            
                            t_id = row.get('id')
                            if pd.notna(t_id) and t_id in df_templates['id'].values:
                                idx = df_templates.index[df_templates['id'] == t_id][0]
                                df_templates.at[idx, 'default_amount'] = amt
                                df_templates.at[idx, 'default_payment'] = str(row['default_payment'])
                                
                            count += 1
                    
                    if new_record_rows:
                        df_records = pd.concat([df_records, pd.DataFrame(new_record_rows)], ignore_index=True) if not df_records.empty else pd.DataFrame(new_record_rows)
                        save_gsheet("records", df_records)
                        save_gsheet("fixed_templates", df_templates)
                        
                    st.session_state.confirm_batch = False
                    st.success(f"🎉 총 {count}건의 고정 지출이 구글 시트에 안전하게 일괄 등록되었습니다!")
                    st.rerun()

            with c2:
                if st.button("❌ 취소", use_container_width=True):
                    st.session_state.confirm_batch = False
                    st.rerun()

# -------------------------------------------------------------
# 메뉴 6: 분류 관리
# -------------------------------------------------------------
elif menu == "🏷️ 분류 및 결제수단 관리":
    st.subheader("🏷️ 카테고리 및 결제수단 순서·관리")
    st.info("💡 **텍스트 박스 안에서 줄바꿈으로 순서를 자유롭게 변경**할 수 있습니다.\n새로운 항목을 쓰면 '추가', 지우면 '삭제'가 되며 아래 저장 버튼을 눌러야 반영됩니다.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("##### 🛒 지출 카테고리")
        exp_text = st.text_area("항목 편집 (위에서 차례대로 표시)", value="\n".join(expense_categories), height=350)

    with col2:
        st.write("##### 💳 결제수단 / 카드")
        pay_text = st.text_area("항목 편집 (위에서 차례대로 표시)", value="\n".join(payment_methods), height=350)

    st.write("")
    if st.button("💾 변경된 순서 및 항목 전체 저장", type="primary", use_container_width=True):
        new_expenses = list(dict.fromkeys([x.strip() for x in exp_text.split('\n') if x.strip()]))
        new_payments = list(dict.fromkeys([x.strip() for x in pay_text.split('\n') if x.strip()]))
        
        new_settings = []
        for e in new_expenses:
            new_settings.append({'setting_type': 'expense', 'name': e})
        for p in new_payments:
            new_settings.append({'setting_type': 'payment', 'name': p})
            
        df_new_settings = pd.DataFrame(new_settings, columns=['setting_type', 'name'])
        save_gsheet("settings", df_new_settings)
        
        st.success("🎉 카테고리 및 결제수단이 성공적으로 업데이트되었습니다!")
        st.rerun()
