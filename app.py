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
# 2. 모바일 최적화 커스텀 스타일 (CSS)
# -------------------------------------------------------------
st.markdown("""
<style>
    /* 상단 우측 아이콘 및 하단 워터마크 강제 숨김 (메뉴 버튼 유지) */
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
# 3. 구글 시트 DB 헬퍼 함수
# -------------------------------------------------------------
def load_gsheet(worksheet_name, default_cols):
    try:
        df = conn.read(worksheet=worksheet_name, ttl=0)
        if df.empty and len(df.columns) == 0:
            return pd.DataFrame(columns=default_cols)
        return df.dropna(how='all')
    except Exception:
        return pd.DataFrame(columns=default_cols)

def save_gsheet(worksheet_name, df):
    conn.update(worksheet=worksheet_name, data=df)

def load_settings():
    df = load_gsheet("settings", ['setting_type', 'name'])
    if df.empty:
        # 최초 실행 시 기본 세팅 생성
        default_settings = pd.DataFrame([
            {'setting_type': 'expense', 'name': '식비'},
            {'setting_type': 'expense', 'name': '주거/통신'},
            {'setting_type': 'expense', 'name': '공과금'},
            {'setting_type': 'expense', 'name': '보험료'},
            {'setting_type': 'payment', 'name': '신한카드'},
            {'setting_type': 'payment', 'name': '계좌이체'}
        ])
        save_gsheet("settings", default_settings)
        df = default_settings
        
    expenses = df[df['setting_type'] == 'expense']['name'].dropna().tolist()
    payments = df[df['setting_type'] == 'payment']['name'].dropna().tolist()
    return expenses, payments

def add_setting(stype, name):
    df = load_gsheet("settings", ['setting_type', 'name'])
    if not ((df['setting_type'] == stype) & (df['name'] == name)).any():
        new_row = pd.DataFrame([{'setting_type': stype, 'name': name}])
        df = pd.concat([df, new_row], ignore_index=True)
        save_gsheet("settings", df)

def delete_setting(stype, name):
    df = load_gsheet("settings", ['setting_type', 'name'])
    df = df[~((df['setting_type'] == stype) & (df['name'] == name))]
    save_gsheet("settings", df)

def load_records():
    return load_gsheet("records", ['id', 'date', 'category', 'sub_category', 'amount', 'payment_method', 'is_fixed', 'memo'])

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
        d_val = row['date']
        d_str = pd.to_datetime(d_val, errors='coerce').strftime("%Y-%m-%d") if pd.notna(d_val) else datetime.today().strftime("%Y-%m-%d")
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
        return False, "엑셀 필수 열(date, category, amount, payment_method)이 누락되었습니다."
    
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
    return True, f"총 {len(new_rows)}건의 지출 내역을 성공적으로 복원했습니다."

def load_fixed_templates():
    return load_gsheet("fixed_templates", ['id', 'category', 'sub_category', 'default_amount', 'default_payment', 'memo'])

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

# -------------------------------------------------------------
# 4. 메인 UI & 메뉴
# -------------------------------------------------------------
expense_categories, payment_methods = load_settings()

st.title("💰 스마트 가계부")
menu = st.sidebar.radio("📌 바로가기 메뉴", [
    "📝 지출 내역 입력", 
    "📊 월별 지출 분석", 
    "📈 월별 지출 비교 (MoM)", 
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
            rec_date = st.date_input("날짜", datetime.today())
        with col2:
            amount = st.number_input("금액 (원)", min_value=0, step=1000, value=0)
            
        col3, col4 = st.columns(2)
        with col3:
            category = st.selectbox("지출 카테고리 (대분류)", expense_categories + ["➕ 새 카테고리 직접 입력"])
            custom_cat = st.text_input("새 지출 카테고리명", placeholder="직접 입력") if category == "➕ 새 카테고리 직접 입력" else None
        with col4:
            sub_category = st.text_input("상세 항목", placeholder="예: 점심식사, 주유비, 커피")
            
        col5, col6 = st.columns(2)
        with col5:
            payment_method = st.selectbox("결제 수단 / 카드", payment_methods + ["➕ 새 결제수단 직접 입력"])
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
                st.success("🎉 지출 내역이 성공적으로 저장되었습니다!")
                st.rerun()

# -------------------------------------------------------------
# 메뉴 2: 월별 지출 분석
# -------------------------------------------------------------
elif menu == "📊 월별 지출 분석":
    st.subheader("📊 월별 지출 심층 분석")
    df = load_records()
    
    if df.empty:
        st.info("기록된 데이터가 없습니다. 먼저 지출 내역을 입력해주세요.")
    else:
        df['year_month'] = df['date'].apply(lambda x: str(x)[:7])
        selected_month = st.selectbox("조회할 월 선택", sorted(df['year_month'].unique(), reverse=True))
        expense_df = df[df['year_month'] == selected_month]
        
        total_expense = expense_df['amount'].sum()
        fixed_expense = expense_df[expense_df['is_fixed'] == 1]['amount'].sum()
        var_expense = expense_df[expense_df['is_fixed'] == 0]['amount'].sum()
        
        st.metric("총 지출", f"{total_expense:,} 원")
        
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
            st.write("#### 🏷️ 카테고리별 지출 비중")
            cat_sum = expense_df.groupby('category')['amount'].sum().reset_index()
            fig_cat = px.pie(cat_sum, values='amount', names='category', hole=0.35)
            fig_cat.update_layout(margin=dict(t=20, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.3))
            st.plotly_chart(fig_cat, use_container_width=True)

            st.write("---")
            st.write("#### ⚖️ 고정지출 vs 변동지출")
            fc1, fc2 = st.columns(2)
            fc1.metric("📌 고정지출", f"{fixed_expense:,} 원")
            fc2.metric("🛒 변동지출", f"{var_expense:,} 원")
            
            fig = px.pie(values=[fixed_expense, var_expense], names=["고정지출", "변동지출"], hole=0.45)
            fig.update_layout(margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)

# -------------------------------------------------------------
# 메뉴 3: 월별 지출 비교 (MoM)
# -------------------------------------------------------------
elif menu == "📈 월별 지출 비교 (MoM)":
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
            monthly_summary, x='year_month', y=['고정지출', '변동지출'], 
            title="월별 지출 구조 추이", barmode='stack', text_auto=True
        )
        fig_trend.update_layout(margin=dict(t=30, b=20, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2), xaxis_title="")
        st.plotly_chart(fig_trend, use_container_width=True)
        
        st.write("---")
        st.write("#### 🏷️ 카테고리별 월간 지출 변화")
        cat_monthly = df.groupby(['year_month', 'category'])['amount'].sum().reset_index()
        fig_cat_trend = px.bar(
            cat_monthly, x='year_month', y='amount', color='category',
            title="카테고리별 월별 비교", barmode='group', text_auto=True
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
            st.info("등록된 지출 내역이 없습니다.")
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
                    "category": st.column_config.SelectboxColumn("카테고리", options=expense_categories, required=True),
                    "sub_category": st.column_config.TextColumn("상세 항목"),
                    "amount": st.column_config.NumberColumn("금액 (원)", min_value=0, step=1000, required=True),
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
                    st.success("🎉 수정한 내용과 삭제된 항목이 구글 시트에 안전하게 동기화되었습니다!")
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
            st.download_button(
                label="📥 가계부 전체 엑셀(XLSX) 다운로드 백업", data=output.getvalue(),
                file_name=f"지출내역_백업_{datetime.today().strftime('%Y%m%d')}.xlsx",
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
# 메뉴 5: 정기 고정비 일괄 등록 (통합됨)
# -------------------------------------------------------------
elif menu == "⚙️ 정기 고정비 일괄 등록":
    st.subheader("⚙️ 정기 고정비 일괄 등록 및 템플릿 관리")
    st.info("💡 **표 안에서 고정비 항목을 바로 추가/수정/삭제**할 수 있습니다. 가계부에 일괄 등록할 항목은 왼쪽 **'☑️ 이번달 등록'** 칸을 체크하세요.")
    
    df_fixed = load_fixed_templates()
    
    df_edit = df_fixed.copy()
    df_edit.insert(0, '이번달 등록', True)
    df_edit.insert(1, '템플릿 삭제', False)
    
    edited_data = st.data_editor(
        df_edit,
        column_config={
            "이번달 등록": st.column_config.CheckboxColumn("☑️ 이번달 등록", default=True),
            "템플릿 삭제": st.column_config.CheckboxColumn("🗑️ 템플릿 삭제", default=False),
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "category": st.column_config.SelectboxColumn("카테고리", options=expense_categories, required=True),
            "sub_category": st.column_config.TextColumn("상세 항목", required=True),
            "default_amount": st.column_config.NumberColumn("기본 금액 (원)", min_value=0, step=1000, required=True),
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
    
    if st.button("🚀 위 표에서 체크된 항목을 가계부에 일괄 등록", use_container_width=True, type="primary"):
        # 등록 전 템플릿 변경사항 먼저 안전하게 저장
        save_edited_fixed_templates(df_fixed, edited_data)

        to_register = edited_data[(edited_data['이번달 등록'] == True) & (edited_data['템플릿 삭제'] == False)]
        if to_register.empty:
            st.warning("등록할 항목이 선택되지 않았습니다.")
        else:
            count = 0
            for _, row in to_register.iterrows():
                amt = int(pd.to_numeric(row['default_amount'], errors='coerce') or 0)
                if amt > 0:
                    add_record(target_date, row['category'], row['sub_category'], amt, row['default_payment'], True, str(row.get('memo', '')))
                    count += 1
            st.success(f"🎉 총 {count}건의 고정 지출이 구글 시트에 안전하게 등록되었습니다!")

# -------------------------------------------------------------
# 메뉴 6: 분류 관리
# -------------------------------------------------------------
elif menu == "🏷️ 분류 및 결제수단 관리":
    st.subheader("🏷️ 카테고리 및 결제수단 관리")
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("##### 🛒 지출 카테고리")
        st.write(expense_categories)
        new_exp = st.text_input("새 지출 카테고리 추가")
        if st.button("지출 카테고리 추가", use_container_width=True) and new_exp:
            add_setting("expense", new_exp.strip())
            st.success(f"'{new_exp}' 추가 완료!")
            st.rerun()
                
        del_exp = st.selectbox("삭제할 지출 카테고리", ["선택 안 함"] + expense_categories)
        if st.button("지출 카테고리 삭제", use_container_width=True) and del_exp != "선택 안 함":
            delete_setting("expense", del_exp)
            st.warning(f"'{del_exp}' 삭제 완료!")
            st.rerun()

    with col2:
        st.write("##### 💳 결제수단 / 카드")
        st.write(payment_methods)
        new_pay = st.text_input("새 카드/결제수단 추가")
        if st.button("결제수단 추가", use_container_width=True) and new_pay:
            add_setting("payment", new_pay.strip())
            st.success(f"'{new_pay}' 추가 완료!")
            st.rerun()
                
        del_pay = st.selectbox("삭제할 결제수단", ["선택 안 함"] + payment_methods)
        if st.button("결제수단 삭제", use_container_width=True) and del_pay != "선택 안 함":
            delete_setting("payment", del_pay)
            st.warning(f"'{del_pay}' 삭제 완료!")
            st.rerun()
