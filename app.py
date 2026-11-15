
import streamlit as st
import pandas
import pickle

# 저장된 로보어드바이저 데이터 불러오기
with open("robo_advisor_data.pkl", "rb") as file:
    app_data = pickle.load(file)

ETF_expected_returns = app_data["ETF_expected_returns"]
investor_portfolios = app_data["investor_portfolios"]
portfolio_evaluation = app_data["portfolio_evaluation"]
rebalancing_results = app_data["rebalancing_results"]
comparison_table = app_data["comparison_table"]

# 페이지 기본 설정
st.set_page_config(
    page_title="Robo Advisor",
    page_icon="📊",
    layout="wide"
)

# 제목
st.title("ROBO ADVISOR")
st.caption("투자 성향 기반 포트폴리오 관리 시뮬레이터")

st.divider()

# 투자자 정보 입력
if "profile" not in st.session_state:
    st.session_state.profile = None

if st.session_state.profile is None:

    st.subheader("투자자 프로필 설정")
    st.write("개인 정보를 입력하고 나에게 맞는 포트폴리오를 확인하세요.")

    with st.form("investor_profile"):

        name = st.text_input("이름", placeholder="이름을 입력하세요")

        reason = st.text_area(
            "투자 목적 및 이유",
            placeholder="투자를 시작하려는 이유와 목표를 입력하세요."
        )

        initial_amount = st.number_input(
            "초기 투자 금액 (원)",
            min_value=10000,
            value=10000000,
            step=100000
        )

        investor_type = st.radio(
            "투자 유형 선택",
            ["안정추구형", "위험중립형", "적극투자형"],
            captions=[
                "투자 위험 최소화",
                "위험 대비 수익 효율 추구",
                "기대수익률 최대화"
            ]
        )

        submitted = st.form_submit_button(
            "포트폴리오 생성하기",
            use_container_width=True
        )

        if submitted:

            if not name.strip():
                st.error("이름을 입력해 주세요.")

            elif not reason.strip():
                st.error("투자 목적 및 이유를 입력해 주세요.")

            else:
                st.session_state.profile = {
                    "name": name,
                    "reason": reason,
                    "initial_amount": initial_amount,
                    "investor_type": investor_type
                }

                st.rerun()


# 포트폴리오 화면
else:

    profile = st.session_state.profile

    name = profile["name"]
    reason = profile["reason"]
    initial_amount = profile["initial_amount"]
    investor_type = profile["investor_type"]

    weights = investor_portfolios[investor_type]

    # 투자자 정보
    st.subheader(f"{name}님의 투자 포트폴리오")

    st.write(f"**투자 목적:** {reason}")
    st.write(f"**투자 유형:** {investor_type}")

    st.metric(
        "초기 투자 금액",
        f"{initial_amount:,.0f}원"
    )

    st.divider()

    # ETF별 투자 비중과 투자 금액 계산
    portfolio = pandas.DataFrame({
        "ETF": ETF_expected_returns.index,
        "투자 비중(%)": weights * 100,
        "배분 금액(원)": [
            round(initial_amount * weight)
            for weight in weights
        ]
    })

    st.subheader("ETF별 자산 배분")

    st.bar_chart(
        portfolio.set_index("ETF")["투자 비중(%)"],
        horizontal=True
    )

    display_portfolio = portfolio.copy()
    display_portfolio["투자 비중(%)"] = (
        display_portfolio["투자 비중(%)"].round(2)
    )
    display_portfolio["배분 금액(원)"] = (
        display_portfolio["배분 금액(원)"].map(
            lambda amount: f"{amount:,.0f}원"
        )
    )

    st.dataframe(
        display_portfolio,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # 포트폴리오 구성 단계의 추정 성과
    st.subheader("포트폴리오 예상 지표")

    evaluation = portfolio_evaluation.loc[investor_type]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "연간 기대수익률",
        f"{evaluation['연간 기대수익률']:.2f}%"
    )

    col2.metric(
        "연간 위험",
        f"{evaluation['연간 위험']:.2f}%"
    )

    col3.metric(
        "샤프지수",
        f"{evaluation['샤프지수']:.2f}"
    )

    col4.metric(
        "일간 VaR (95%)",
        f"{evaluation['일간 VaR (95%)']:.2f}%"
    )

    st.caption(
        "위 지표는 포트폴리오 설정 기간의 과거 데이터로 추정한 값이며, "
        "미래 수익을 보장하지 않습니다."
    )

    st.divider()

    # 처음 화면으로 돌아가기
    if st.button("투자자 정보 다시 입력하기"):
        st.session_state.profile = None
        st.rerun()
