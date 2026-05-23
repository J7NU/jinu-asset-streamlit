"""jinu-asset-streamlit — D-047 자산배분 Streamlit 앱 v1 (lean).

기능:
- Email OTP 코드 인증 (D-049 — 매직링크/PKCE 폐기 후 전환, Supabase 프로젝트 설정에 따라 6-10자리)
- Dashboard: 카테고리별 목표 vs 실제 비중 + 종목별 보유·평가액
- Transactions 입력 form (buy/sell/rebalance)
- (v2 후속) Dividends / Monthly Log / 시계열 차트
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import Client, create_client


# ---------------------------------------------------------------------------
# Supabase client (cached)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)


sb = get_supabase()


# ---------------------------------------------------------------------------
# Auth — Email OTP (6자리 코드)
# ---------------------------------------------------------------------------
# D-049 — 매직링크 + PKCE flow 폐기 사유:
# - Supabase 디폴트 implicit flow는 토큰을 URL hash(#)에 박는데 Streamlit이 못 읽음
# - PKCE flow 전환(PR #19)해도 code_verifier 영속성이 Streamlit cache_resource +
#   multi-session 구조와 본질적으로 충돌 (라이브 검증 시 동일 증상 재현)
# - Email OTP 6자리 코드는 redirect/hash 자체가 없어 위 구조적 문제 회피
# - Supabase 대시보드 Email Template에서 {{ .ConfirmationURL }} → {{ .Token }} 1줄 교체
def _current_user():
    try:
        resp = sb.auth.get_user()
        return resp.user if resp else None
    except Exception:  # noqa: BLE001
        return None


def login_view() -> None:
    st.title("jinu-asset — 자산배분 v1")
    st.caption("D-049 Email OTP 코드 인증")

    if "otp_email" not in st.session_state:
        st.session_state["otp_email"] = ""

    if not st.session_state["otp_email"]:
        email = st.text_input("이메일 입력", placeholder="you@example.com")
        if st.button("인증 코드 발송", type="primary", disabled=not email):
            try:
                sb.auth.sign_in_with_otp({"email": email})
                st.session_state["otp_email"] = email
                st.success(f"{email}로 인증 코드를 발송했습니다. 이메일 확인 후 입력하세요.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"발송 실패: {exc}")
        return

    st.info(f"코드 발송됨: {st.session_state['otp_email']}")
    token = st.text_input(
        "인증 코드", max_chars=10, placeholder="6-10자리 숫자",
        help="이메일로 받은 인증 코드 입력 (Supabase 프로젝트 설정에 따라 6-10자리)",
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("로그인", type="primary", disabled=not token or len(token) < 6):
            try:
                sb.auth.verify_otp(
                    {
                        "email": st.session_state["otp_email"],
                        "token": token,
                        "type": "email",
                    }
                )
                st.session_state["otp_email"] = ""
                st.cache_data.clear()
                st.success("로그인 성공")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"인증 실패: {exc}")
    with col2:
        if st.button("이메일 변경"):
            st.session_state["otp_email"] = ""
            st.rerun()


# ---------------------------------------------------------------------------
# Data fetchers (RLS 자동 적용 — 본인 데이터만)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60)
def fetch_categories() -> pd.DataFrame:
    rows = sb.table("categories").select("*").execute().data or []
    return pd.DataFrame(rows)


@st.cache_data(ttl=60)
def fetch_holdings() -> pd.DataFrame:
    rows = sb.table("holdings").select("*").execute().data or []
    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def fetch_transactions() -> pd.DataFrame:
    rows = (
        sb.table("transactions")
        .select("*")
        .order("date", desc=True)
        .execute()
        .data
        or []
    )
    return pd.DataFrame(rows)


@st.cache_data(ttl=60)
def fetch_latest_prices() -> pd.DataFrame:
    """asset_id별 최신 가격 1행씩."""
    rows = (
        sb.table("prices_snapshot")
        .select("asset_id, price, currency, fetched_at")
        .order("fetched_at", desc=True)
        .limit(500)
        .execute()
        .data
        or []
    )
    if not rows:
        return pd.DataFrame(columns=["asset_id", "price", "currency", "fetched_at"])
    df = pd.DataFrame(rows)
    return df.sort_values("fetched_at").drop_duplicates("asset_id", keep="last")


# ---------------------------------------------------------------------------
# Domain — 포트폴리오 KPI 계산
# ---------------------------------------------------------------------------
def calc_position_table(
    holdings: pd.DataFrame,
    transactions: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """asset_id별 보유수량·매수원가·평가액 집계.

    수량: buy - sell - rebalance(sell side는 별도 처리, 단순화)
    매수원가: buy의 quantity * price 합
    평가액: 보유수량 * latest price (manual_price fallback)
    """
    if holdings.empty:
        return pd.DataFrame()

    tx = transactions.copy() if not transactions.empty else pd.DataFrame()
    if not tx.empty:
        tx["signed_qty"] = tx.apply(
            lambda r: r["quantity"] if r["type"] == "buy" else -r["quantity"],
            axis=1,
        )
        tx["buy_cost"] = tx.apply(
            lambda r: r["quantity"] * r["price"] if r["type"] == "buy" else 0,
            axis=1,
        )
        agg = (
            tx.groupby("asset_id")
            .agg(quantity=("signed_qty", "sum"), buy_cost=("buy_cost", "sum"))
            .reset_index()
        )
    else:
        agg = pd.DataFrame(columns=["asset_id", "quantity", "buy_cost"])

    pos = holdings.rename(columns={"id": "asset_id"}).merge(
        agg, on="asset_id", how="left"
    )
    pos["quantity"] = pos["quantity"].fillna(0)
    pos["quantity"] = pos["quantity"].clip(lower=0)
    pos["buy_cost"] = pos["buy_cost"].fillna(0)

    if not prices.empty:
        pos = pos.merge(
            prices[["asset_id", "price"]].rename(columns={"price": "latest_price"}),
            on="asset_id",
            how="left",
        )
    else:
        pos["latest_price"] = pd.NA

    pos["effective_price"] = pos["latest_price"].fillna(pos["manual_price"])
    pos["market_value"] = pos["quantity"] * pos["effective_price"].fillna(0)
    pos["return_pct"] = (
        (pos["market_value"] - pos["buy_cost"]) / pos["buy_cost"].replace(0, pd.NA) * 100
    )
    return pos


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def dashboard_view(user) -> None:
    st.subheader("Dashboard")

    categories = fetch_categories()
    holdings = fetch_holdings()
    transactions = fetch_transactions()
    prices = fetch_latest_prices()

    pos = calc_position_table(holdings, transactions, prices)

    total_value = pos["market_value"].sum() if not pos.empty else 0
    total_cost = pos["buy_cost"].sum() if not pos.empty else 0
    total_return_pct = (
        (total_value - total_cost) / total_cost * 100 if total_cost else 0
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("총 평가액", f"₩{total_value:,.0f}")
    col2.metric("총 매수원가", f"₩{total_cost:,.0f}")
    col3.metric("총 수익률", f"{total_return_pct:+.2f}%")

    # M-3: 가격 데이터 누락 종목 경고 (조용한 -100% 표시 방어)
    if not pos.empty:
        missing_price = pos[pos["effective_price"].isna()]
        if not missing_price.empty:
            missing_names = missing_price["asset_name"].tolist()
            st.warning(
                f"⚠️ 가격 데이터 없는 종목 {len(missing_names)}개: {', '.join(missing_names)}. "
                f"평가액 0으로 계산됨. holdings.manual_price 또는 prices_snapshot fetch 확인 필요."
            )

    st.divider()

    # 카테고리별 비중 (account 분리)
    st.markdown("### 카테고리별 비중 (실제)")
    if not pos.empty and pos["market_value"].sum() > 0:
        by_cat = (
            pos.groupby(["account", "category_id"])["market_value"]
            .sum()
            .reset_index()
        )
        if not categories.empty:
            by_cat = by_cat.merge(
                categories[["id", "name"]].rename(
                    columns={"id": "category_id", "name": "category"}
                ),
                on="category_id",
                how="left",
            )
        fig = px.bar(
            by_cat,
            x="category",
            y="market_value",
            color="account",
            barmode="group",
            title="계좌별 카테고리 평가액",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("거래 내역이 없어 비중 차트를 그릴 데이터가 없습니다. Transactions 탭에서 매수 기록을 입력하세요.")

    # 종목별 보유 테이블
    st.markdown("### 종목별 보유")
    if not pos.empty:
        display_cols = [
            "asset_id",
            "asset_name",
            "account",
            "quantity",
            "effective_price",
            "market_value",
            "buy_cost",
            "return_pct",
        ]
        existing = [c for c in display_cols if c in pos.columns]
        st.dataframe(pos[existing], use_container_width=True, hide_index=True)
    else:
        st.info("종목 데이터가 없습니다. Phase 3 seed가 완료되었는지 확인하세요.")


def transactions_view(user) -> None:
    st.subheader("Transactions")

    holdings = fetch_holdings()
    if holdings.empty:
        st.warning("holdings 테이블이 비었습니다. seed.sql 실행을 먼저 확인하세요.")
        return

    st.markdown("### 신규 거래 입력")

    # 1) 계좌 토글 — form 밖에 둠. form 안 위젯은 submit 전 rerun을 안 일으켜서
    #    계좌를 form 안에 두면 종목 목록이 즉시 안 바뀜. 밖에 둬야 변경 즉시 필터.
    acct_label = st.radio("계좌", ["연금", "ISA"], horizontal=True, key="tx_acct")
    acct = "pension" if acct_label == "연금" else "isa"
    acct_holdings = holdings[holdings["account"] == acct]
    if acct_holdings.empty:
        st.info(f"{acct_label} 계좌에 등록된 종목이 없습니다.")
        return

    # 2) 종목 선택 + 입력 — Enter로 저장, clear_on_submit으로 폼 자동 초기화되어 다음 입력 연속.
    with st.form("tx_form", clear_on_submit=True):
        asset_label = st.selectbox(
            "종목",
            options=acct_holdings.apply(
                lambda r: f"{r['id']} — {r['asset_name']}",
                axis=1,
            ).tolist(),
        )
        asset_id = asset_label.split(" — ")[0] if asset_label else None

        col1, col2 = st.columns(2)
        tx_type = col1.selectbox("종류", ["buy", "sell"])
        tx_date = col2.date_input("거래일", value=dt.date.today())

        col3, col4 = st.columns(2)
        # 한국 ETF는 정수 주 단위 거래(소수점 매매 X) + 단가는 원 단위 → 둘 다 정수 표시.
        quantity = col3.number_input("수량(주)", min_value=0.0, step=1.0, format="%.0f")
        price = col4.number_input("단가(원)", min_value=0.0, step=1.0, format="%.0f")

        memo = st.text_input("메모 (선택)", placeholder="예: 5월 1회차 매수")

        st.caption(
            "💡 수량·단가 입력 후 **Enter** 또는 '등록' 클릭으로 저장 → 폼이 자동 초기화되어 "
            "같은 계좌의 다음 종목을 바로 입력할 수 있습니다. 계좌를 바꾸려면 위 토글을 변경하세요. "
            "buy = 매수(수량·원가 누적) / sell = 매도(수량 차감)."
        )
        submitted = st.form_submit_button("등록 (Enter)", type="primary")
        if submitted:
            if not asset_id or quantity <= 0 or price <= 0:
                st.error("종목·수량·단가를 모두 입력하세요.")
            else:
                try:
                    sb.table("transactions").insert(
                        {
                            "date": tx_date.isoformat(),
                            "type": tx_type,
                            "asset_id": asset_id,
                            "quantity": float(quantity),
                            "price": float(price),
                            "memo": memo or None,
                        }
                    ).execute()
                    st.success(
                        f"등록 완료: [{acct_label}] {tx_type} {asset_id} × {quantity:g} @ ₩{price:,.0f}"
                    )
                    fetch_transactions.clear()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"등록 실패: {exc}")

    st.markdown("### 최근 거래 내역")
    tx = fetch_transactions()
    if tx.empty:
        st.info("거래 내역이 없습니다.")
    else:
        st.dataframe(
            tx[["date", "type", "asset_id", "quantity", "price", "memo"]].head(50),
            use_container_width=True,
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def holdings_admin_view(user) -> None:
    st.subheader("종목 관리")

    categories = fetch_categories()
    holdings = fetch_holdings()
    transactions = fetch_transactions()

    if categories.empty:
        st.warning("categories 테이블이 비었습니다. seed 먼저 확인하세요.")
        return

    # 종목별 net 수량 (buy - sell) — 삭제 가능 판정용 (net 0만 삭제 허용)
    net_qty: dict[str, float] = {}
    if not transactions.empty:
        t = transactions.copy()
        t["signed"] = t.apply(
            lambda r: r["quantity"] if r["type"] == "buy" else -r["quantity"], axis=1
        )
        net_qty = t.groupby("asset_id")["signed"].sum().to_dict()

    cat_names = categories["name"].tolist()
    tab_add, tab_edit, tab_del = st.tabs(["➕ 추가", "✏️ 수정", "🗑️ 삭제"])

    # ---- 추가 ----
    with tab_add:
        with st.form("hold_add", clear_on_submit=True):
            c1, c2 = st.columns(2)
            acct_label = c1.radio("계좌", ["연금", "ISA"], horizontal=True, key="add_acct")
            acct = "pension" if acct_label == "연금" else "isa"
            ticker = c2.text_input("티커", placeholder="예: 379800")
            asset_name = st.text_input("종목명", placeholder="예: KODEX 미국S&P500")
            c3, c4 = st.columns(2)
            cat_name = c3.selectbox("카테고리", cat_names, key="add_cat")
            target_pct = c4.number_input(
                "목표비중(%)", min_value=0.0, max_value=100.0, step=0.5, format="%.1f"
            )
            notes = st.text_input("메모 (선택)")
            st.caption("💡 id는 `티커_계좌`로 자동 생성. 같은 티커+계좌 중복 시 등록 불가.")
            if st.form_submit_button("종목 추가", type="primary"):
                t_up = (ticker or "").strip().upper()
                if not t_up or not asset_name.strip():
                    st.error("티커·종목명을 입력하세요.")
                else:
                    new_id = f"{t_up}_{acct.upper()}"
                    cat_row = categories[categories["name"] == cat_name]
                    cat_id = int(cat_row.iloc[0]["id"]) if not cat_row.empty else None
                    try:
                        sb.table("holdings").insert(
                            {
                                "id": new_id,
                                "asset_name": asset_name.strip(),
                                "category_id": cat_id,
                                "account": acct,
                                "ticker": t_up,
                                "currency": "KRW",
                                "price_source": "naver",
                                "target_pct": float(target_pct),
                                "notes": notes or None,
                            }
                        ).execute()
                        st.success(f"추가 완료: {new_id} ({asset_name.strip()})")
                        fetch_holdings.clear()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"추가 실패 (중복 id 또는 제약 위반): {exc}")

    # ---- 수정 ----
    with tab_edit:
        if holdings.empty:
            st.info("수정할 종목이 없습니다.")
        else:
            opts = holdings.apply(
                lambda r: f"{r['id']} — {r['asset_name']}", axis=1
            ).tolist()
            sel = st.selectbox("종목 선택", opts, key="edit_sel")
            hid = sel.split(" — ")[0]
            row = holdings[holdings["id"] == hid].iloc[0]
            with st.form("hold_edit"):
                new_name = st.text_input("종목명", value=row["asset_name"])
                c1, c2 = st.columns(2)
                cur_cat = categories[categories["id"] == row.get("category_id")]
                cur_cat_name = (
                    cur_cat.iloc[0]["name"] if not cur_cat.empty else cat_names[0]
                )
                cat_idx = cat_names.index(cur_cat_name) if cur_cat_name in cat_names else 0
                cat_name = c1.selectbox(
                    "카테고리", cat_names, index=cat_idx, key="edit_cat"
                )
                cur_tp = float(row["target_pct"]) if pd.notna(row.get("target_pct")) else 0.0
                target_pct = c2.number_input(
                    "목표비중(%)",
                    min_value=0.0,
                    max_value=100.0,
                    value=cur_tp,
                    step=0.5,
                    format="%.1f",
                )
                notes = st.text_input("메모", value=row.get("notes") or "")
                st.caption(f"계좌·티커는 고정 (id `{hid}`). 변경하려면 삭제 후 재추가.")
                if st.form_submit_button("수정 저장", type="primary"):
                    cat_row = categories[categories["name"] == cat_name]
                    cat_id = int(cat_row.iloc[0]["id"]) if not cat_row.empty else None
                    try:
                        sb.table("holdings").update(
                            {
                                "asset_name": new_name.strip(),
                                "category_id": cat_id,
                                "target_pct": float(target_pct),
                                "notes": notes or None,
                            }
                        ).eq("id", hid).execute()
                        st.success(f"수정 완료: {hid}")
                        fetch_holdings.clear()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"수정 실패: {exc}")

    # ---- 삭제 (net 수량 0만 허용) ----
    with tab_del:
        if holdings.empty:
            st.info("삭제할 종목이 없습니다.")
        else:
            opts = holdings.apply(
                lambda r: f"{r['id']} — {r['asset_name']}", axis=1
            ).tolist()
            sel = st.selectbox("종목 선택", opts, key="del_sel")
            hid = sel.split(" — ")[0]
            qty = float(net_qty.get(hid, 0) or 0)
            st.metric("현재 보유 수량 (net)", f"{qty:g} 주")
            if abs(qty) > 1e-9:
                st.warning(
                    f"보유 수량이 {qty:g}주입니다. 전량 매도(수량 0) 후에만 삭제할 수 있습니다."
                )
            else:
                st.caption(
                    "보유 수량 0 → 삭제 가능. 해당 종목의 종료된 거래기록도 함께 제거됩니다."
                )
                confirm = st.checkbox(f"'{hid}' 삭제를 확인합니다", key="del_confirm")
                if st.button("종목 삭제", type="primary", disabled=not confirm):
                    try:
                        # net 0이라도 거래 행이 남아 있으면 FK 막힘 → 거래 먼저 제거
                        sb.table("transactions").delete().eq("asset_id", hid).execute()
                        sb.table("holdings").delete().eq("id", hid).execute()
                        st.success(f"삭제 완료: {hid}")
                        fetch_holdings.clear()
                        fetch_transactions.clear()
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"삭제 실패: {exc}")


def main() -> None:
    st.set_page_config(page_title="jinu-asset", page_icon="💰", layout="wide")

    user = _current_user()

    if not user:
        login_view()
        return

    with st.sidebar:
        st.markdown(f"**로그인:** {user.email}")
        if st.button("로그아웃"):
            sb.auth.sign_out()
            st.cache_data.clear()
            st.rerun()
        menu = st.radio("메뉴", ["Dashboard", "Transactions", "종목 관리"], index=0)

    if menu == "Dashboard":
        dashboard_view(user)
    elif menu == "Transactions":
        transactions_view(user)
    elif menu == "종목 관리":
        holdings_admin_view(user)


if __name__ == "__main__":
    main()
