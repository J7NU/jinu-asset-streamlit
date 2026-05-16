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
        "인증 코드", max_chars=10, placeholder="12345678",
        help="이메일로 받은 숫자 코드 입력 (Supabase 프로젝트 설정에 따라 6-10자리)",
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
    with st.form("tx_form", clear_on_submit=True):
        asset_label = st.selectbox(
            "종목",
            options=holdings.apply(
                lambda r: f"{r['id']} — {r['asset_name']} ({r['account']})",
                axis=1,
            ).tolist(),
        )
        asset_id = asset_label.split(" — ")[0] if asset_label else None

        col1, col2 = st.columns(2)
        tx_type = col1.selectbox("종류", ["buy", "sell", "rebalance"])
        tx_date = col2.date_input("거래일", value=dt.date.today())

        col3, col4 = st.columns(2)
        quantity = col3.number_input("수량", min_value=0.0, step=0.0001, format="%.4f")
        price = col4.number_input("단가(원)", min_value=0.0, step=0.01, format="%.2f")

        memo = st.text_input("메모 (선택)", placeholder="예: 6월 1회차 매수")

        submitted = st.form_submit_button("등록", type="primary")
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
                    st.success(f"등록 완료: {tx_type} {asset_id} × {quantity} @ ₩{price:,.0f}")
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
            st.rerun()
        menu = st.radio("메뉴", ["Dashboard", "Transactions"], index=0)

    if menu == "Dashboard":
        dashboard_view(user)
    elif menu == "Transactions":
        transactions_view(user)


if __name__ == "__main__":
    main()
