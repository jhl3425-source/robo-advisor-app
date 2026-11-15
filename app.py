import streamlit as st
import pandas
import numpy
import pickle
import json
import io
import math
from datetime import datetime
from supabase import create_client
from PIL import Image, ImageDraw, ImageFont


# =========================================================
# 1. 기본 설정 및 데이터 불러오기
# =========================================================

st.set_page_config(
    page_title="ROBO ADVISOR",
    page_icon="📈",
    layout="wide"
)

st.markdown("""
<style>
    .stApp {
        background-color: #F7F8FA;
    }
    h1, h2, h3 {
        color: #172B4D;
    }
    div.stButton > button {
        border-radius: 10px;
        min-height: 45px;
        font-weight: 600;
    }
    div[data-testid="stMetric"] {
        background: white;
        padding: 18px;
        border-radius: 12px;
        border: 1px solid #E7EAF0;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def load_app_data():
    with open("robo_advisor_data.pkl", "rb") as file:
        return pickle.load(file)


try:
    app_data = load_app_data()

    ETF_analysis = app_data["ETF_analysis"]
    ETF_expected_returns = app_data["ETF_expected_returns"]
    investor_portfolios = app_data["investor_portfolios"]
    portfolio_evaluation = app_data["portfolio_evaluation"]
    ETF_returns = app_data["ETF_returns_for_rebalancing_period"]

    ETF_returns.index = pandas.to_datetime(ETF_returns.index)
    ETF_returns = ETF_returns.sort_index()

    ETF_names = list(ETF_expected_returns.index)
    ETF_returns = ETF_returns[ETF_names]

    REBALANCING_THRESHOLD = float(
        app_data.get("rebalancing_threshold", 0.05)
    )

except Exception as error:
    st.error("데이터 파일을 불러오지 못했어")
    st.code(str(error))
    st.stop()


# =========================================================
# 2. Supabase 연결
# =========================================================

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

except Exception:
    st.error("Supabase 연결 정보를 확인해줘")
    st.info("Streamlit Cloud의 Settings → Secrets에 SUPABASE_URL과 SUPABASE_KEY가 있어야 해")
    st.stop()


# =========================================================
# 3. 세션 상태 초기화
# =========================================================

default_values = {
    "page": "home",
    "access_token": None,
    "refresh_token": None,
    "user_id": None,
    "selected_portfolio_id": None,
    "wizard_step": 0,

    # 실제 저장할 값
    "wizard_investor_name": "",
    "wizard_reason": "",
    "wizard_amount": 10000000,
    "wizard_investor_type": "위험중립형",
    "wizard_portfolio_name": "",
    "wizard_rebalance_mode": "자동"
}

for key, value in default_values.items():
    if key not in st.session_state:
        st.session_state[key] = value


def sync_wizard_value(input_key, saved_key):
    """화면 입력값을 유지할 세션 상태에 복사"""
    st.session_state[saved_key] = st.session_state[input_key]


def prepare_wizard_widget(input_key, saved_key):
    """화면에 다시 나타난 입력 위젯의 값을 복구"""
    if input_key not in st.session_state:
        st.session_state[input_key] = st.session_state[saved_key]
        
# =========================================================
# 4. 로그인 세션 복구
# =========================================================

if st.session_state.access_token and st.session_state.refresh_token:
    try:
        supabase.auth.set_session(
            st.session_state.access_token,
            st.session_state.refresh_token
        )
    except Exception:
        st.session_state.access_token = None
        st.session_state.refresh_token = None
        st.session_state.user_id = None


# =========================================================
# 5. 공통 함수
# =========================================================

def get_weights(investor_type):
    """투자자 유형에 맞는 최적화 포트폴리오 비중을 가져오는 함수"""

    raw_weights = investor_portfolios.get(investor_type)

    if raw_weights is None:
        if "안정" in investor_type:
            search_words = ["안정", "stable"]
        elif "위험중립" in investor_type:
            search_words = ["중립", "neutral"]
        else:
            search_words = ["적극", "공격", "aggressive"]

        for key in investor_portfolios:
            if any(word in str(key).lower() for word in search_words):
                raw_weights = investor_portfolios[key]
                break

    if raw_weights is None:
        raise ValueError("투자자 유형에 맞는 포트폴리오를 찾지 못했어")

    if isinstance(raw_weights, pandas.Series):
        weights = {
            str(key): float(value)
            for key, value in raw_weights.items()
        }

    elif isinstance(raw_weights, dict):
        weights = {
            str(key): float(value)
            for key, value in raw_weights.items()
        }

    else:
        weights = {
            ETF_names[index]: float(raw_weights[index])
            for index in range(len(ETF_names))
        }

    weights = {
        name: max(0.0, value)
        for name, value in weights.items()
        if name in ETF_names
    }

    total_weight = sum(weights.values())

    if total_weight <= 0:
        raise ValueError("포트폴리오 비중을 계산할 수 없어")

    for name in ETF_names:
        weights.setdefault(name, 0.0)

    weights = {
        name: value / total_weight
        for name, value in weights.items()
    }

    return weights


def to_json_value(value):
    """Supabase에 저장할 수 있도록 숫자 자료형 변환"""

    if isinstance(value, dict):
        return {
            str(key): to_json_value(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [to_json_value(item) for item in value]

    if isinstance(value, (numpy.integer,)):
        return int(value)

    if isinstance(value, (numpy.floating,)):
        return float(value)

    return value


def get_user_portfolios():
    response = (
        supabase.table("portfolios")
        .select("*")
        .eq("owner_id", st.session_state.user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def get_selected_portfolio():
    response = (
        supabase.table("portfolios")
        .select("*")
        .eq("id", st.session_state.selected_portfolio_id)
        .eq("owner_id", st.session_state.user_id)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def save_portfolio_update(portfolio_id, update_data):
    supabase.table("portfolios").update(
        to_json_value(update_data)
    ).eq(
        "id", portfolio_id
    ).eq(
        "owner_id", st.session_state.user_id
    ).execute()


def calculate_metrics(daily_returns, initial_amount, current_amount):
    """실제 시뮬레이션 수익률을 이용해 성과 지표 계산"""

    if len(daily_returns) == 0:
        return {
            "누적 수익률": 0.0,
            "연환산 위험": 0.0,
            "샤프지수": 0.0,
            "일간 VaR 95%": 0.0
        }

    returns = pandas.Series(daily_returns, dtype=float)

    cumulative_return = (
        current_amount / initial_amount - 1
    )

    annual_risk = (
        returns.std(ddof=1) * math.sqrt(252)
        if len(returns) > 1 else 0.0
    )

    sharpe_ratio = (
        returns.mean() / returns.std(ddof=1) * math.sqrt(252)
        if len(returns) > 1 and returns.std(ddof=1) != 0
        else 0.0
    )

    daily_var = max(0.0, -returns.quantile(0.05))

    return {
        "누적 수익률": cumulative_return,
        "연환산 위험": annual_risk,
        "샤프지수": sharpe_ratio,
        "일간 VaR 95%": daily_var
    }


def calculate_no_rebalance(initial_amount, target_weights, number_of_days):
    """리밸런싱을 하지 않았을 때의 성과를 별도로 계산"""

    holdings = {
        name: initial_amount * target_weights[name]
        for name in ETF_names
    }

    daily_returns = []

    for day in range(number_of_days):
        previous_total = sum(holdings.values())

        for name in ETF_names:
            daily_change = float(
                ETF_returns.iloc[day][name]
            )
            holdings[name] *= (1 + daily_change)

        current_total = sum(holdings.values())

        if previous_total > 0:
            daily_returns.append(
                current_total / previous_total - 1
            )

    final_amount = sum(holdings.values())

    metrics = calculate_metrics(
        daily_returns,
        initial_amount,
        final_amount
    )

    return final_amount, metrics


def create_certificate(portfolio, metrics, rebalance_count):

    from PIL import Image, ImageDraw, ImageFont
    import io

    width, height = 2000, 1400
    image = Image.new("RGB", (width, height), "#101C35")
    draw = ImageDraw.Draw(image)

    #폰트

    import os
    import urllib.request

    # 공식 Noto Sans KR 폰트 자동 다운로드
    font_path = "/tmp/NotoSansKR-VF.ttf"

    if not os.path.exists(font_path):
        font_url = (
            "https://raw.githubusercontent.com/notofonts/noto-cjk/"
            "main/Sans/Variable/TTF/Subset/NotoSansKR-VF.ttf"
        )

        urllib.request.urlretrieve(font_url, font_path)

    # 큰 글씨 설정
    logo = ImageFont.truetype(font_path, 55)
    title = ImageFont.truetype(font_path, 120)
    name = ImageFont.truetype(font_path, 85)
    return_font = ImageFont.truetype(font_path, 220)
    heading = ImageFont.truetype(font_path, 48)
    metric = ImageFont.truetype(font_path, 90)
    body = ImageFont.truetype(font_path, 55)
    small = ImageFont.truetype(font_path, 38)
    
    # 색상 설정
    white = "#FFFFFF"
    mint = "#6DD6C1"
    muted = "#AAB8CC"
    card = "#1C2C49"

    # 배경
    draw.ellipse((1400, -400, 2200, 400), fill="#172A49")
    draw.ellipse((-350, 1050, 450, 1850), fill="#172A49")

    # 테두리
    draw.rounded_rectangle(
        (55, 55, 1945, 1345),
        radius=45,
        outline="#42516A",
        width=4
    )

    # 상단
    draw.text((130, 110), "ROBO / ADVISOR", font=logo, fill=white)
    draw.text((1300, 125), "PORTFOLIO PERFORMANCE", font=small, fill=mint)

    draw.line((130, 210, 1870, 210), fill="#42516A", width=3)

    # 제목
    draw.text((130, 270), "YOUR MONEY.", font=title, fill=white)
    draw.text((130, 385), "YOUR STRATEGY.", font=title, fill=mint)

    # 포트폴리오 이름과 투자자
    draw.text((140, 555), str(portfolio["portfolio_name"]), font=name, fill=white)
    draw.text(
        (140, 650),
        "INVESTOR  /  " + str(portfolio["investor_name"]),
        font=body,
        fill=muted
    )

    # 수익률 카드
    draw.rounded_rectangle(
        (130, 760, 1870, 1060),
        radius=35,
        fill=card
    )

    draw.text((190, 805), "CUMULATIVE RETURN", font=heading, fill=muted)

    return_rate = metrics["누적 수익률"] * 100

    draw.text(
        (180, 860),
        f"{return_rate:+.2f}%",
        font=return_font,
        fill=mint if return_rate >= 0 else "#FF8B8B"
    )

    # 지표 카드
    items = [
        ("ANNUAL RISK", f'{metrics["연환산 위험"] * 100:.2f}%'),
        ("SHARPE RATIO", f'{metrics["샤프지수"]:.2f}'),
        ("DAILY VaR 95%", f'{metrics["일간 VaR 95%"] * 100:.2f}%'),
        ("REBALANCING", f"{rebalance_count} TIMES")
    ]

    card_width = 400
    gap = 46
    start_x = 130

    for index, item in enumerate(items):
        x = start_x + index * (card_width + gap)

        draw.rounded_rectangle(
            (x, 1100, x + card_width, 1260),
            radius=25,
            fill=card
        )

        draw.text(
            (x + 30, 1120),
            item[0],
            font=small,
            fill=muted
        )

        draw.text(
            (x + 30, 1170),
            item[1],
            font=metric,
            fill=white
        )

    # 하단
    draw.text(
        (130, 1290),
        "ROBO ADVISOR LAB",
        font=small,
        fill=mint
    )

    output = io.BytesIO()
    image.save(output, format="PNG")

    return output.getvalue()

# =========================================================
# 6. 로그인하지 않은 경우
# =========================================================

if not st.session_state.user_id:

    st.markdown("# ROBO ADVISOR")
    st.caption("데이터 기반 포트폴리오 설계 및 리밸런싱 시뮬레이션")

    login_tab, signup_tab = st.tabs(["로그인", "회원가입"])

    with login_tab:
        st.subheader("로그인")

        with st.form("login_form"):
            email = st.text_input("이메일")
            password = st.text_input("비밀번호", type="password")
            login_button = st.form_submit_button(
                "로그인",
                use_container_width=True
            )

        if login_button:
            try:
                response = supabase.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })

                st.session_state.access_token = response.session.access_token
                st.session_state.refresh_token = response.session.refresh_token
                st.session_state.user_id = response.user.id

                st.success("로그인 성공")
                st.rerun()

            except Exception as error:
                st.error("로그인에 실패했어. 이메일과 비밀번호를 확인해줘")
                st.caption(str(error))

    with signup_tab:
        st.subheader("회원가입")

        with st.form("signup_form"):
            new_email = st.text_input("이메일 주소")
            new_password = st.text_input(
                "비밀번호",
                type="password"
            )
            confirm_password = st.text_input(
                "비밀번호 확인",
                type="password"
            )

            signup_button = st.form_submit_button(
                "회원가입",
                use_container_width=True
            )

        if signup_button:
            if new_password != confirm_password:
                st.error("비밀번호가 서로 달라")

            elif len(new_password) < 6:
                st.error("비밀번호는 6자 이상으로 입력해줘")

            else:
                try:
                    response = supabase.auth.sign_up({
                        "email": new_email,
                        "password": new_password
                    })

                    if response.session is not None:
                        st.session_state.access_token = response.session.access_token
                        st.session_state.refresh_token = response.session.refresh_token
                        st.session_state.user_id = response.user.id

                        st.success("회원가입 및 로그인 성공")
                        st.rerun()

                    else:
                        st.success(
                            "회원가입 요청이 완료됐어. 이메일 인증을 마친 뒤 로그인해줘"
                        )

                except Exception as error:
                    st.error("회원가입에 실패했어")
                    st.caption(str(error))

    st.stop()


# =========================================================
# 7. 로그인 이후 공통 화면
# =========================================================

with st.sidebar:
    st.markdown("## ROBO ADVISOR")
    st.caption("나만의 투자 포트폴리오")

    if st.button("홈으로", use_container_width=True):
        st.session_state.page = "home"
        st.rerun()

    if st.button("내 포트폴리오", use_container_width=True):
        st.session_state.page = "portfolio_list"
        st.rerun()

    st.divider()

    if st.button("로그아웃", use_container_width=True):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass

        st.session_state.access_token = None
        st.session_state.refresh_token = None
        st.session_state.user_id = None
        st.session_state.selected_portfolio_id = None
        st.session_state.page = "home"
        st.rerun()


# =========================================================
# 8. 홈 화면
# =========================================================

if st.session_state.page == "home":

    st.markdown("# 나의 투자, 데이터로 설계하다")
    st.markdown(
        "투자 성향에 맞는 포트폴리오를 구성하고 "
        "과거 시장 데이터를 활용해 리밸런싱을 경험해보세요"
    )

    st.divider()

    left, right = st.columns(2)

    with left:
        st.markdown("### 새로운 포트폴리오")
        st.write("투자 목적과 성향을 바탕으로 나만의 포트폴리오를 설계해")
        if st.button(
            "새 포트폴리오 만들기",
            use_container_width=True
        ):
            st.session_state.page = "products"
            st.rerun()

    with right:
        st.markdown("### 기존 포트폴리오 관리")
        st.write("저장된 포트폴리오의 성과를 확인하고 리밸런싱을 진행해")
        if st.button(
            "내 포트폴리오 리밸런싱하기",
            use_container_width=True
        ):
            st.session_state.page = "portfolio_list"
            st.rerun()

    st.divider()

    st.info(
        "본 서비스는 과거 ETF 가격 데이터를 이용한 교육용 시뮬레이션이며 "
        "실제 금융상품 매매를 수행하지 않아"
    )


# =========================================================
# 9. ETF 상품 소개
# =========================================================

elif st.session_state.page == "products":

    st.markdown("# ROBO ADVISOR ETF")
    st.subheader("포트폴리오를 구성하는 5가지 ETF")

    st.write(
        "각 ETF는 서로 다른 투자 요인을 반영해. "
        "로보어드바이저는 이들의 특성과 상관관계를 고려해 비중을 구성해"
    )

    products = [
        (
            "KODEX 가치주",
            "275290",
            "가치(Value)",
            "기업의 내재가치에 비해 상대적으로 저평가된 종목에 주목하는 투자 요인"
        ),
        (
            "TIGER 우량가치",
            "227570",
            "우량·가치 특성",
            "기업의 우량성과 가치 특성을 함께 고려하는 ETF로, 순수한 퀄리티 팩터 상품과는 구분돼"
        ),
        (
            "TIGER 모멘텀",
            "147970",
            "모멘텀(Momentum)",
            "최근 상대적으로 양호한 가격 흐름을 보인 종목의 추세 지속 특성에 주목하는 투자 요인"
        ),
        (
            "KODEX 200중소형",
            "226980",
            "규모(Size) 관련 대리 지표",
            "중소형주 비중을 통해 기업 규모와 관련된 특성을 반영하는 상품이야. 순수한 규모 팩터 ETF와 동일하지는 않아"
        ),
        (
            "TIGER 로우볼",
            "174350",
            "저변동성(Low Volatility)",
            "상대적으로 가격 변동성이 낮은 종목에 주목하는 투자 요인"
        )
    ]

    for index, product in enumerate(products):
        with st.container(border=True):
            st.markdown(f"### {product[0]}")
            st.caption(f"종목코드 {product[1]} · {product[2]}")
            st.write(product[3])

    st.divider()

    if st.button(
        "상품 확인 완료 · 포트폴리오 만들기",
        use_container_width=True
    ):
        st.session_state.wizard_step = 0
        st.session_state.page = "wizard"
        st.rerun()

# =========================================================
# 10. 포트폴리오 생성 마법사
# =========================================================

elif st.session_state.page == "wizard":

    st.markdown("# 나만의 포트폴리오 만들기")

    steps = [
        "투자자 이름",
        "투자 목적",
        "초기 투자금",
        "투자 성향",
        "포트폴리오 이름",
        "리밸런싱 방식"
    ]

    step = st.session_state.wizard_step

    st.progress((step + 1) / len(steps))
    st.caption(f"{step + 1} / {len(steps)} 단계")

    if step == 0:
        st.subheader("투자자 이름을 알려줘")
        st.write("포트폴리오에 표시할 이름이야")

        prepare_wizard_widget(
            "wizard_investor_name_input",
            "wizard_investor_name"
        )

        st.text_input(
            "이름",
            key="wizard_investor_name_input",
            placeholder="이름을 입력해줘",
            on_change=sync_wizard_value,
            args=("wizard_investor_name_input", "wizard_investor_name")
        )

    elif step == 1:
        st.subheader("투자 목적은 무엇이야?")
        st.write("어떤 이유로 포트폴리오를 구성하려고 해?")

        prepare_wizard_widget(
            "wizard_reason_input",
            "wizard_reason"
        )

        st.text_area(
            "투자 목적",
            key="wizard_reason_input",
            placeholder="예: 장기적인 자산 형성과 분산투자 경험",
            on_change=sync_wizard_value,
            args=("wizard_reason_input", "wizard_reason")
        )

    elif step == 2:
        st.subheader("초기 투자 금액을 정해줘")
        st.write("이 금액을 기준으로 ETF별 투자 금액이 계산돼")

        prepare_wizard_widget(
            "wizard_amount_input",
            "wizard_amount"
        )

        st.number_input(
            "초기 투자금 (원)",
            min_value=100000,
            max_value=1000000000,
            step=1000000,
            key="wizard_amount_input",
            on_change=sync_wizard_value,
            args=("wizard_amount_input", "wizard_amount")
        )

    elif step == 3:
        st.subheader("투자 성향을 선택해줘")

        prepare_wizard_widget(
            "wizard_investor_type_input",
            "wizard_investor_type"
        )

        st.radio(
            "나의 투자 성향",
            [
                "안정추구형",
                "위험중립형",
                "적극투자형"
            ],
            key="wizard_investor_type_input",
            on_change=sync_wizard_value,
            args=("wizard_investor_type_input", "wizard_investor_type")
        )

        st.caption(
            "안정추구형은 위험 최소화, 위험중립형은 위험 대비 수익, "
            "적극투자형은 기대수익 극대화를 기준으로 구성돼"
        )

    elif step == 4:
        st.subheader("포트폴리오 이름을 정해줘")

        prepare_wizard_widget(
            "wizard_portfolio_name_input",
            "wizard_portfolio_name"
        )

        st.text_input(
            "포트폴리오 이름",
            key="wizard_portfolio_name_input",
            placeholder="예: 나의 첫 번째 투자",
            on_change=sync_wizard_value,
            args=("wizard_portfolio_name_input", "wizard_portfolio_name")
        )

    elif step == 5:
        st.subheader("리밸런싱 방식을 선택해줘")

        prepare_wizard_widget(
            "wizard_rebalance_mode_input",
            "wizard_rebalance_mode"
        )

        st.radio(
            "리밸런싱 방식",
            ["자동", "수동"],
            key="wizard_rebalance_mode_input",
            format_func=lambda value: (
                "자동 리밸런싱" if value == "자동"
                else "수동 리밸런싱"
            ),
            on_change=sync_wizard_value,
            args=("wizard_rebalance_mode_input", "wizard_rebalance_mode")
        )

        st.write("**자동:** 기준 비중과의 차이가 5%p를 초과하면 자동으로 비중을 조정해")
        st.write("**수동:** 기준 비중과의 차이가 5%p를 초과하면 알림을 표시하고 직접 실행해야 해")

    st.divider()

    back_col, next_col = st.columns(2)

    with back_col:
        if st.button(
            "이전",
            disabled=(step == 0),
            use_container_width=True
        ):
            st.session_state.wizard_step -= 1
            st.rerun()

    with next_col:

        if step < 5:

            if st.button("다음", use_container_width=True):

                # 현재 화면의 입력값을 다시 한번 저장
                input_keys = {
                    0: ("wizard_investor_name_input", "wizard_investor_name"),
                    1: ("wizard_reason_input", "wizard_reason"),
                    2: ("wizard_amount_input", "wizard_amount"),
                    3: ("wizard_investor_type_input", "wizard_investor_type"),
                    4: ("wizard_portfolio_name_input", "wizard_portfolio_name")
                }

                if step in input_keys:
                    input_key, saved_key = input_keys[step]

                    if input_key in st.session_state:
                        st.session_state[saved_key] = (
                            st.session_state[input_key]
                        )

                required_keys = {
                    0: "wizard_investor_name",
                    1: "wizard_reason",
                    4: "wizard_portfolio_name"
                }

                if step in required_keys:
                    key = required_keys[step]

                    if not str(st.session_state[key]).strip():
                        st.error("내용을 입력해줘")
                        st.stop()

                st.session_state.wizard_step += 1
                st.rerun()

        else:

            if st.button(
                "포트폴리오 생성하기",
                type="primary",
                use_container_width=True
            ):

                try:
                    # 마지막 화면의 리밸런싱 방식도 저장
                    if "wizard_rebalance_mode_input" in st.session_state:
                        st.session_state.wizard_rebalance_mode = (
                            st.session_state.wizard_rebalance_mode_input
                        )

                    # 필수 정보 확인
                    if not st.session_state.wizard_investor_name.strip():
                        st.error("투자자 이름을 확인해줘")
                        st.stop()

                    if not st.session_state.wizard_portfolio_name.strip():
                        st.error("포트폴리오 이름을 확인해줘")
                        st.stop()

                    selected_type = st.session_state.wizard_investor_type

                    if selected_type not in [
                        "안정추구형",
                        "위험중립형",
                        "적극투자형"
                    ]:
                        st.error("투자 성향을 다시 선택해줘")
                        st.stop()

                    weights = get_weights(selected_type)

                    initial_amount = float(
                        st.session_state.wizard_amount
                    )

                    holdings = {
                        name: initial_amount * weights[name]
                        for name in ETF_names
                    }

                    new_portfolio = {
                        "owner_id": st.session_state.user_id,
                        "portfolio_name": st.session_state.wizard_portfolio_name.strip(),
                        "investor_name": st.session_state.wizard_investor_name.strip(),
                        "investment_reason": st.session_state.wizard_reason.strip(),
                        "initial_amount": initial_amount,
                        "investor_type": selected_type,
                        "rebalance_mode": st.session_state.wizard_rebalance_mode,
                        "simulation_day": 0,
                        "holdings": holdings,
                        "daily_returns": [],
                        "rebalance_history": [],
                        "status": "active"
                    }

                    response = (
                        supabase.table("portfolios")
                        .insert(new_portfolio)
                        .execute()
                    )

                    if not response.data:
                        raise ValueError("저장된 포트폴리오 정보를 확인할 수 없어")

                    created = response.data[0]

                    st.session_state.selected_portfolio_id = created["id"]
                    st.session_state.page = "portfolio_detail"

                    st.success("포트폴리오가 생성됐어")
                    st.rerun()

                except Exception as error:
                    st.error("포트폴리오 생성 중 문제가 발생했어")
                    st.code(str(error))



# =========================================================
# 11. 저장된 포트폴리오 목록
# =========================================================

elif st.session_state.page == "portfolio_list":

    st.markdown("# 내 포트폴리오")

    try:
        portfolios = get_user_portfolios()

        if not portfolios:
            st.info("아직 생성한 포트폴리오가 없어")
            if st.button("새 포트폴리오 만들기"):
                st.session_state.page = "products"
                st.rerun()

        else:
            for portfolio in portfolios:
                with st.container(border=True):
                    st.markdown(
                        f"### {portfolio.get('portfolio_name') or '이름 미입력'}"
                    )

                    st.caption(
                        f"{portfolio['investor_type']} · "
                        f"{portfolio['rebalance_mode']} 리밸런싱"
                    )

                    progress = int(
                        portfolio.get("simulation_day", 0)
                    )

                    st.write(
                        f"시뮬레이션 진행: {progress} / {len(ETF_returns)} 거래일"
                    )

                    if st.button(
                        "포트폴리오 열기",
                        key=f"open_{portfolio['id']}",
                        use_container_width=True
                    ):
                        st.session_state.selected_portfolio_id = portfolio["id"]
                        st.session_state.page = "portfolio_detail"
                        st.rerun()

    except Exception as error:
        st.error("포트폴리오 목록을 불러오지 못했어")
        st.code(str(error))


# =========================================================
# 12. 포트폴리오 상세 및 시뮬레이션
# =========================================================

elif st.session_state.page == "portfolio_detail":

    portfolio = get_selected_portfolio()

    if portfolio is None:
        st.error("포트폴리오를 찾을 수 없어")
        st.session_state.page = "portfolio_list"
        st.rerun()

    portfolio_id = portfolio["id"]
    st.write("이름 확인용")
    st.write("포트폴리오 이름:", repr(portfolio.get("portfolio_name")))
    st.write("투자자 이름:", repr(portfolio.get("investor_name")))
    
    initial_amount = float(portfolio["initial_amount"])
    holdings = portfolio.get("holdings") or {}
    daily_returns = portfolio.get("daily_returns") or []
    rebalance_history = portfolio.get("rebalance_history") or []

    simulation_day = int(
        portfolio.get("simulation_day", 0)
    )

    target_weights = get_weights(
        portfolio["investor_type"]
    )

    current_total = sum(
        float(holdings.get(name, 0))
        for name in ETF_names
    )

    current_weights = {
        name: (
            float(holdings.get(name, 0)) / current_total
            if current_total > 0 else 0
        )
        for name in ETF_names
    }

st.markdown(
    f"# {portfolio.get('portfolio_name') or '이름 미입력'}"
)

st.caption(
    f"{portfolio.get('investor_name') or '투자자 이름 미입력'} · "
    f"{portfolio['investor_type']} · "
    f"{portfolio['rebalance_mode']} 리밸런싱"
)

st.info(
        "이 화면은 과거 ETF 가격 데이터를 활용한 가상 시뮬레이션이야. "
        "실제 거래나 미래 수익을 보장하지 않아"
    )

st.divider()

    metric1, metric2, metric3 = st.columns(3)

    metric1.metric(
        "초기 투자금",
        f"{initial_amount:,.0f}원"
    )

    metric2.metric(
        "현재 평가금액",
        f"{current_total:,.0f}원",
        f"{(current_total / initial_amount - 1) * 100:.2f}%"
    )

    metric3.metric(
        "진행 거래일",
        f"{simulation_day} / {len(ETF_returns)}일"
    )

st.subheader("현재 자산 배분")

    allocation_table = pandas.DataFrame({
        "ETF": ETF_names,
        "현재 비중": [
            current_weights[name] * 100
            for name in ETF_names
        ],
        "목표 비중": [
            target_weights[name] * 100
            for name in ETF_names
        ],
        "현재 평가금액": [
            float(holdings.get(name, 0))
            for name in ETF_names
        ]
    })

st.dataframe(
        allocation_table.style.format({
            "현재 비중": "{:.2f}%",
            "목표 비중": "{:.2f}%",
            "현재 평가금액": "{:,.0f}원"
        }),
        use_container_width=True,
        hide_index=True
    )

    chart_table = allocation_table.set_index("ETF")[
        ["현재 비중", "목표 비중"]
    ]

st.bar_chart(chart_table)

st.divider()

# -----------------------------------------------------
    # 리밸런싱 대기 상태 확인
 # -----------------------------------------------------

    pending_event = None

    for event in reversed(rebalance_history):
        if event.get("pending") is True:
            pending_event = event
            break

    if pending_event is not None:

        st.error(
            "리밸런싱 기준을 초과했어. "
            "현재 포트폴리오의 비중을 확인하고 리밸런싱을 실행해줘"
        )

        st.write(
            f"발생 날짜: {pending_event.get('date', '날짜 정보 없음')}"
        )

        st.write(
            f"최대 비중 차이: {pending_event.get('deviation', 0) * 100:.2f}%p"
        )

        if st.button(
            "리밸런싱 실행",
            type="primary",
            use_container_width=True
        ):

            total_value = sum(
                float(holdings.get(name, 0))
                for name in ETF_names
            )

            new_holdings = {
                name: total_value * target_weights[name]
                for name in ETF_names
            }

            pending_event["pending"] = False
            pending_event["executed"] = True
            pending_event["after_weights"] = target_weights

            save_portfolio_update(
                portfolio_id,
                {
                    "holdings": new_holdings,
                    "rebalance_history": rebalance_history
                }
            )

            st.success("리밸런싱이 완료됐어")
            st.rerun()

    # -----------------------------------------------------
    # 시뮬레이션 진행
    # -----------------------------------------------------

    if simulation_day < len(ETF_returns):

        st.subheader("시뮬레이션 진행")

        st.write(
            "1일, 30일, 90일 단위로 과거 거래일을 진행할 수 있어"
        )

        step_col1, step_col2, step_col3 = st.columns(3)

        advance_amount = None

        with step_col1:
            if st.button(
                "1 거래일 진행",
                use_container_width=True,
                disabled=(pending_event is not None)
            ):
                advance_amount = 1

        with step_col2:
            if st.button(
                "30 거래일 진행",
                use_container_width=True,
                disabled=(pending_event is not None)
            ):
                advance_amount = 30

        with step_col3:
            if st.button(
                "90 거래일 진행",
                use_container_width=True,
                disabled=(pending_event is not None)
            ):
                advance_amount = 90

        if advance_amount is not None:

            new_holdings = {
                name: float(holdings.get(name, 0))
                for name in ETF_names
            }

            new_daily_returns = list(daily_returns)
            new_history = list(rebalance_history)
            new_day = simulation_day

            for day in range(
                simulation_day,
                min(
                    simulation_day + advance_amount,
                    len(ETF_returns)
                )
            ):

                previous_total = sum(new_holdings.values())

                for name in ETF_names:
                    daily_change = float(
                        ETF_returns.iloc[day][name]
                    )

                    new_holdings[name] *= (
                        1 + daily_change
                    )

                new_total = sum(new_holdings.values())

                if previous_total > 0:
                    portfolio_return = (
                        new_total / previous_total - 1
                    )
                else:
                    portfolio_return = 0.0

                new_daily_returns.append(
                    float(portfolio_return)
                )

                new_day = day + 1

                actual_weights = {
                    name: (
                        new_holdings[name] / new_total
                        if new_total > 0 else 0
                    )
                    for name in ETF_names
                }

                deviations = {
                    name: abs(
                        actual_weights[name] - target_weights[name]
                    )
                    for name in ETF_names
                }

                maximum_deviation = max(
                    deviations.values()
                )

                if maximum_deviation > REBALANCING_THRESHOLD:

                    event = {
                        "date": str(ETF_returns.index[day].date()),
                        "deviation": float(maximum_deviation),
                        "before_weights": actual_weights,
                        "pending": False,
                        "executed": False
                    }

                    if portfolio["rebalance_mode"] == "자동":

                        new_holdings = {
                            name: new_total * target_weights[name]
                            for name in ETF_names
                        }

                        event["pending"] = False
                        event["executed"] = True
                        event["after_weights"] = target_weights

                        new_history.append(event)

                    else:

                        event["pending"] = True
                        event["executed"] = False

                        new_history.append(event)

                        # 수동 모드는 알림이 발생하면 진행을 멈춤
                        break

            save_portfolio_update(
                portfolio_id,
                {
                    "simulation_day": new_day,
                    "holdings": new_holdings,
                    "daily_returns": new_daily_returns,
                    "rebalance_history": new_history,
                    "status": (
                        "completed"
                        if new_day >= len(ETF_returns)
                        else "active"
                    )
                }
            )

            st.rerun()

    else:
        st.success("1년 시뮬레이션이 완료됐어")

    st.divider()

    # -----------------------------------------------------
    # 성과 분석
    # -----------------------------------------------------

    if len(daily_returns) > 0:

        st.subheader("현재까지의 성과")

        actual_metrics = calculate_metrics(
            daily_returns,
            initial_amount,
            current_total
        )

        result1, result2 = st.columns(2)

        with result1:
            st.metric(
                "누적 수익률",
                f'{actual_metrics["누적 수익률"] * 100:.2f}%'
            )

            st.metric(
                "연환산 위험",
                f'{actual_metrics["연환산 위험"] * 100:.2f}%'
            )

        with result2:
            st.metric(
                "샤프지수",
                f'{actual_metrics["샤프지수"]:.2f}'
            )

            st.metric(
                "일간 VaR 95%",
                f'{actual_metrics["일간 VaR 95%"] * 100:.2f}%'
            )

        st.caption(
            "연환산 위험은 일간 수익률의 표준편차를 연환산한 값이며, "
            "일간 VaR 95%는 일간 수익률의 5% 분위수를 이용한 손실 추정치야"
        )

    # -----------------------------------------------------
    # 1년 완료 시 최종 비교
    # -----------------------------------------------------

    if simulation_day >= len(ETF_returns):

        st.divider()
        st.markdown("# 1년 시뮬레이션 최종 결과")

        final_metrics = calculate_metrics(
            daily_returns,
            initial_amount,
            current_total
        )

        no_rebalance_amount, no_rebalance_metrics = (
            calculate_no_rebalance(
                initial_amount,
                target_weights,
                simulation_day
            )
        )

        st.subheader("리밸런싱 유무에 따른 성과 비교")

        comparison = pandas.DataFrame({
            "리밸런싱 적용": [
                final_metrics["누적 수익률"] * 100,
                final_metrics["연환산 위험"] * 100,
                final_metrics["샤프지수"],
                final_metrics["일간 VaR 95%"] * 100
            ],
            "리밸런싱 미적용": [
                no_rebalance_metrics["누적 수익률"] * 100,
                no_rebalance_metrics["연환산 위험"] * 100,
                no_rebalance_metrics["샤프지수"],
                no_rebalance_metrics["일간 VaR 95%"] * 100
            ]
        }, index=[
            "누적 수익률 (%)",
            "연환산 위험 (%)",
            "샤프지수",
            "일간 VaR 95% (%)"
        ])

        st.dataframe(
            comparison.style.format("{:.2f}"),
            use_container_width=True
        )

        st.bar_chart(comparison)

        st.write(
            f"리밸런싱 실행 횟수: "
            f"{sum(1 for event in rebalance_history if event.get('executed'))}회"
        )

        st.divider()

        st.subheader("나의 포트폴리오 성과 인증서")

        st.write(
            "실제 시뮬레이션 결과를 바탕으로 인증서 이미지를 만들 수 있어"
        )

        rebalance_count = sum(
            1 for event in rebalance_history
            if event.get("executed")
        )

        certificate = create_certificate(
            portfolio,
            final_metrics,
            rebalance_count
        )

        st.image(
            certificate,
            caption="ROBO ADVISOR · PORTFOLIO REPORT",
            use_container_width=True
        )

        st.download_button(
            "성과 인증서 PNG 다운로드",
            data=certificate,
            file_name="robo_advisor_certificate.png",
            mime="image/png",
            use_container_width=True
        )

    # -----------------------------------------------------
    # 리밸런싱 이력
    # -----------------------------------------------------

    st.divider()
    st.subheader("리밸런싱 이력")

    if rebalance_history:

        history_rows = []

        for event in rebalance_history:
            history_rows.append({
                "발생 날짜": event.get("date", ""),
                "최대 비중 차이": (
                    float(event.get("deviation", 0)) * 100
                ),
                "상태": (
                    "실행 대기"
                    if event.get("pending")
                    else "실행 완료"
                    if event.get("executed")
                    else "미실행"
                )
            })

        history_table = pandas.DataFrame(history_rows)

        st.dataframe(
            history_table.style.format({
                "최대 비중 차이": "{:.2f}%"
            }),
            use_container_width=True,
            hide_index=True
        )

    else:
        st.caption("아직 리밸런싱 이력이 없어")

    st.divider()

    if st.button("포트폴리오 목록으로 돌아가기"):
        st.session_state.page = "portfolio_list"
        st.rerun()
