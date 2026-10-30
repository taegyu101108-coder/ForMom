"""장보기 알림메모 | 실행: streamlit run app.py
GitHub에 app.py와 requirements.txt를 올리고 Streamlit Community Cloud에서 배포하세요.
SQLite는 실행 서버의 로컬 파일입니다. Cloud 재시작/재배포 시 유실될 수 있어
'설정·백업'에서 JSON 백업을 권장합니다. 지속 보관이 필요하면 외부 DB로 교체하세요.
QR/주소를 아는 사람은 같은 목록을 읽고 수정할 수 있습니다. 개인정보를 적지 마세요.
"""
import io
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import qrcode
import streamlit as st

st.set_page_config(page_title="장보기 알림메모", page_icon="🛒", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container{max-width:520px;padding:0.65rem 0.8rem 1rem!important}
header[data-testid="stHeader"]{display:none}
[data-testid="stVerticalBlock"]{gap:0.38rem}
h1{font-size:1.45rem!important;padding:0!important}
p{margin-bottom:.25rem}div[data-testid="stMetric"]{background:#f0f7f3;border-radius:12px;padding:.35rem .7rem}
[data-testid="stMetricValue"]{font-size:1.65rem}
div[data-testid="stButton"] button{min-height:2.25rem;padding:.2rem .5rem}
[data-testid="stHorizontalBlock"]{gap:.4rem}
[data-testid="stCaptionContainer"]{font-size:.74rem}
@media(max-width:600px){[data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important}
[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:0!important}}
</style>""", unsafe_allow_html=True)

DB = os.environ.get("SHOPPING_DB_PATH", "shopping_memo.sqlite3")
CATEGORIES = ["🥬 야채", "🍎 과일", "🥩 고기·생선", "🥛 유제품·달걀", "🍚 쌀·면·곡물", "🥫 가공·냉동", "🧻 생활용품", "📦 기타"]
PRIORITIES = {1: "1 · 꼭 필요", 2: "2 · 가격 보고", 3: "3 · 여유 있을 때"}
PAGE_SIZE = 2


def connect():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


with connect() as conn:
    conn.execute("""CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY, book TEXT NOT NULL, name TEXT NOT NULL,
    category TEXT NOT NULL, priority INTEGER NOT NULL,
    target INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
    qty REAL NOT NULL DEFAULT 0, price INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL)""")

raw_book = st.query_params.get("memo", "")
try:
    BOOK = str(uuid.UUID(str(raw_book)))
except (ValueError, TypeError, AttributeError):
    BOOK = str(uuid.uuid4())
    st.query_params["memo"] = BOOK


def rows():
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM items WHERE book=? ORDER BY priority, created, id", (BOOK,))]


def money(price, qty):
    return int((Decimal(str(price)) * Decimal(str(qty))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def change_status(item_id, status):
    with connect() as conn:
        conn.execute("UPDATE items SET status=?, qty=0, price=0 WHERE id=? AND book=?", (status, item_id, BOOK))


@st.dialog("📝 살 것 추가")
def add_item():
    with st.form("add_form", clear_on_submit=True):
        category = st.selectbox("카테고리", CATEGORIES)
        name = st.text_input("상품명", placeholder="예: 사과 3개, 두부 1모", max_chars=60)
        priority = st.selectbox("중요도", [1, 2, 3], format_func=lambda x: PRIORITIES[x], index=1)
        target = st.number_input("단가 상한(원) · 0이면 미설정", min_value=0, max_value=100000000, step=100, value=0)
        st.caption("상한 초과 시 카트에서 안내합니다. 비싸면 보류해 두세요.")
        submitted = st.form_submit_button("목록에 추가", use_container_width=True, type="primary")
    if submitted:
        if not name.strip():
            st.warning("상품명을 적어 주세요.")
            return
        with connect() as conn:
            conn.execute("INSERT INTO items (id,book,name,category,priority,target,created) VALUES (?,?,?,?,?,?,?)",
                         (str(uuid.uuid4()), BOOK, name.strip(), category, priority, int(target), datetime.now(timezone.utc).isoformat()))
        st.rerun()


@st.dialog("🛒 카트에 담기")
def purchase(item):
    st.write(f"**{item['name']}** · {PRIORITIES[item['priority']]}")
    if item["target"]:
        st.caption(f"단가 상한 {item['target']:,}원")
    price = st.number_input("개당·단위당 가격(원)", min_value=0, max_value=100000000, step=100, value=int(item["target"]), key="buy_price_" + item["id"])
    qty = st.number_input("수량 (무게 구매는 소수 가능)", min_value=0.01, max_value=100000.0, value=1.0, step=1.0, format="%.2f", key="buy_qty_" + item["id"])
    st.info(f"이번 상품 합계: {money(price, qty):,}원")
    if item["target"] and price > item["target"]:
        st.warning("설정한 단가 상한보다 비쌉니다. 오늘은 보류해도 괜찮아요.")
    elif item["priority"] != 1:
        st.caption("꼭 필요한 물건이 아니라면 가격을 보고 보류하세요.")
    c1, c2 = st.columns(2)
    if c1.button("담기 확정", type="primary", use_container_width=True):
        with connect() as conn:
            conn.execute("UPDATE items SET status='cart',price=?,qty=? WHERE id=? AND book=? AND status IN ('pending','deferred')",
                         (int(price), float(qty), item["id"], BOOK))
        st.rerun()
    if c2.button("비싸요 · 보류", use_container_width=True):
        change_status(item["id"], "deferred")
        st.rerun()


def valid_backup(data):
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("지원하지 않는 백업 형식입니다.")
    if len(data["items"]) > 1000:
        raise ValueError("최대 1,000개까지 가져올 수 있습니다.")
    cleaned = []
    for x in data["items"]:
        if not isinstance(x, dict):
            raise ValueError("상품 형식 오류")
        name = str(x.get("name", "")).strip()
        priority, target = int(x.get("priority", 2)), int(x.get("target", 0))
        status = x.get("status", "pending")
        qty, price = float(x.get("qty", 0)), int(x.get("price", 0))
        if not name or len(name) > 60 or priority not in PRIORITIES or status not in ("pending", "deferred", "cart"):
            raise ValueError("상품명·중요도·상태를 확인해 주세요.")
        if not (0 <= target <= 100000000 and 0 <= price <= 100000000 and 0 <= qty <= 100000):
            raise ValueError("가격·수량 범위 오류")
        if status == "cart" and qty <= 0:
            raise ValueError("카트 상품에는 수량이 필요합니다.")
        category = x.get("category") if x.get("category") in CATEGORIES else CATEGORIES[-1]
        cleaned.append((str(uuid.uuid4()), BOOK, name, category, priority, target, status,
                        qty if status == "cart" else 0, price if status == "cart" else 0,
                        datetime.now(timezone.utc).isoformat()))
    return cleaned


st.title("🛒 장보기 알림메모")
all_items = rows()
cart = [x for x in all_items if x["status"] == "cart"]
total = sum(money(x["price"], x["qty"]) for x in cart)
pending_count = sum(x["status"] == "pending" for x in all_items)
st.metric("현재 카트 총액", f"{total:,}원", help="각 상품의 단가 × 수량을 원 단위 반올림하여 합산합니다.")
st.caption(f"살 것 {pending_count}종 · 카트 {len(cart)}종  |  ① 꼭 필요  ② 가격 보고  ③ 여유 있을 때")

left, middle, right = st.columns([1.2, 1, 1.2])
if left.button("＋ 추가", type="primary", use_container_width=True):
    add_item()
with middle.popover("QR 공유", use_container_width=True):
    st.caption("QR/주소를 아는 사람은 같은 목록을 수정할 수 있습니다.")
    try:
        current_url = st.context.url
    except Exception:
        current_url = ""
    from urllib.parse import urlsplit, urlunsplit, urlencode
    try:
        base = st.secrets.get("APP_URL", "") or current_url
    except Exception:
        base = current_url
    base = st.text_input("배포한 앱 주소", value=base, placeholder="https://your-app.streamlit.app")
    parsed = urlsplit(base.strip())
    if parsed.scheme in ("https", "http") and parsed.netloc:
        share_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode({"memo": BOOK}), ""))
        image = qrcode.make(share_url)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        st.image(buf.getvalue(), width=190)
        st.code(share_url, language=None)
        st.download_button("QR 저장", buf.getvalue(), "shopping_qr.png", "image/png", use_container_width=True)
    else:
        st.info("배포 후 실제 앱 주소를 입력하면 QR이 생성됩니다.")
with right.popover("설정·백업", use_container_width=True):
    st.warning("서버 재시작·재배포 시 목록이 사라질 수 있습니다. 중요한 기록은 백업하세요.")
    backup = json.dumps({"version": 1, "items": all_items}, ensure_ascii=False, indent=2)
    st.download_button("JSON 백업", backup, "shopping_backup.json", "application/json", use_container_width=True)
    uploaded = st.file_uploader("JSON 복원 (기존 목록에 추가)", type=["json"])
    if st.button("백업 가져오기", disabled=uploaded is None, use_container_width=True):
        try:
            if uploaded.size > 2000000:
                raise ValueError("2MB 이하의 백업만 지원합니다.")
            imported = valid_backup(json.loads(uploaded.getvalue().decode("utf-8")))
            with connect() as conn:
                conn.executemany("INSERT INTO items (id,book,name,category,priority,target,status,qty,price,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)", imported)
            st.rerun()
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            st.error(f"가져오기 실패: {exc}")
    st.caption("알림은 앱 내부 표시이며 푸시 알림은 아닙니다. 같은 QR로 열면 새로고침 후 변경사항이 보입니다.")

view = st.radio("목록", ["살 것", "카트", "보류"], horizontal=True, label_visibility="collapsed")
status = {"살 것": "pending", "카트": "cart", "보류": "deferred"}[view]
visible = [x for x in all_items if x["status"] == status]
page_key = "page_" + status
pages = max(1, (len(visible) + PAGE_SIZE - 1) // PAGE_SIZE)
st.session_state[page_key] = min(max(st.session_state.get(page_key, 0), 0), pages - 1)
page = st.session_state[page_key]

if not visible:
    st.info({"pending": "살 것을 추가해 보세요 📝", "cart": "물건을 담으면 여기에 금액이 쌓여요 🛒", "deferred": "비싼 물건은 무리하지 말고 보류해요 🌿"}[status])

for item in visible[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
    with st.container(border=True):
        # Render user-supplied names as plain text, not HTML/Markdown.
        st.text(f"{item['priority']} · {item['name']}")
        if status == "cart":
            st.caption(f"{item['price']:,}원 × {item['qty']:g} = {money(item['price'], item['qty']):,}원")
            a, b = st.columns(2)
            if a.button("↩ 담기 취소", key="undo_" + item["id"], use_container_width=True):
                change_status(item["id"], "pending")
                st.rerun()
            b.caption("취소 시 합계에서도 제외")
        else:
            target_text = f" · 상한 {item['target']:,}원" if item["target"] else ""
            st.caption(item["category"] + target_text)
            a, b, c = st.columns([1.2, 1, .7])
            if a.button("🛒 담기", key="buy_" + item["id"], use_container_width=True):
                purchase(item)
            if b.button("보류" if status == "pending" else "다시 살 것", key="hold_" + item["id"], use_container_width=True):
                change_status(item["id"], "deferred" if status == "pending" else "pending")
                st.rerun()
            if c.button("삭제", key="delete_" + item["id"], use_container_width=True):
                # Only non-cart memo entries can be deleted directly; cart records retain price/quantity.
                with connect() as conn:
                    conn.execute("DELETE FROM items WHERE id=? AND book=? AND status!='cart'", (item["id"], BOOK))
                st.rerun()

if pages > 1:
    a, b, c = st.columns([1, 2, 1])
    if a.button("◀", disabled=page == 0, use_container_width=True):
        st.session_state[page_key] = page - 1
        st.rerun()
    b.caption(f"{page + 1} / {pages} 페이지 · 총 {len(visible)}종")
    if c.button("▶", disabled=page >= pages - 1, use_container_width=True):
        st.session_state[page_key] = page + 1
        st.rerun()
st.caption("QR은 간직하고, 장보기는 가볍게 🌿")
