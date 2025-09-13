import os, random, shlex, logging, json
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv("LINE_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# 只允許這些群組（留空=不限制）
ALLOWED_GROUPS = set(filter(None, os.getenv("ALLOWED_GROUPS", "").split(",")))

HELP_MSG = (
    "器材租借指令：\n"
    "!additem 物品 總數量 [備註]\n"
    "!borrow  物品 數量   [備註]\n"
    "!return  物品 數量   [備註]\n"
    "!status [物品]  → 顯示庫存\n"
    "!mine       → 看自己未歸還\n"
    "其他：!help"
)

# ---------- Google Sheets storage ----------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_CREDS"]), scopes=SCOPES
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(os.environ["SHEET_ID"])

def _get_ws(name: str, header: list[str]):
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=1000, cols=len(header))
        ws.append_row(header)
        return ws
    # 確保有表頭
    vals = ws.row_values(1)
    if vals != header:
        if len(vals) == 0:
            ws.append_row(header)
        else:
            ws.update(f"A1:{chr(64+len(header))}1", [header])
    return ws

ws_items = _get_ws("items", ["item", "total", "note"])
ws_tx    = _get_ws("transactions", ["ts","group_id","user_id","user_name","item","delta","note"])

def upsert_item(item: str, total: int, note: str = ""):
    items = ws_items.col_values(1)  # item 欄
    try:
        idx = items.index(item) + 1  # 1-based row
        ws_items.update(f"B{idx}:C{idx}", [[total, note]])
    except ValueError:
        ws_items.append_row([item, total, note])

def add_tx(group_id, user_id, user_name, item, delta, note=""):
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    ws_tx.append_row([ts, group_id, user_id, user_name, item, int(delta), note])

def sum_borrowed(item: str) -> int:
    rows = ws_tx.get_all_values()
    s = 0
    for r in rows[1:]:
        if len(r) >= 6 and r[4] == item:
            try: s += int(r[5])
            except: pass
    return s

def user_borrowed(user_id: str, item: str) -> int:
    rows = ws_tx.get_all_values()
    s = 0
    for r in rows[1:]:
        if len(r) >= 6 and r[2] == user_id and r[4] == item:
            try: s += int(r[5])
            except: pass
    return s

def get_item(item: str):
    rows = ws_items.get_all_records()  # [{item,total,note}]
    for r in rows:
        if str(r.get("item")) == item:
            return {"item": item, "total": int(r.get("total", 0)), "note": r.get("note")}
    return None

def status_all():
    rows = ws_items.get_all_records()
    info = []
    for r in rows:
        item = str(r.get("item"))
        total = int(r.get("total", 0))
        borrowed = sum_borrowed(item)
        avail = total - borrowed
        info.append((item, total, borrowed, avail))
    return info
# ------------------------------------------

def _display_name(event):
    try:
        uid = event.source.user_id
        gid = getattr(event.source, "group_id", None)
        prof = line_bot_api.get_group_member_profile(gid, uid) if gid else line_bot_api.get_profile(uid)
        return prof.display_name
    except Exception:
        return None

@app.route("/callback", methods=["GET", "POST"])
def callback():
    if request.method == "GET":
        return "OK", 200
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):

    # src = event.source
    # if hasattr(src, "group_id") and src.group_id:
    #     gid = src.group_id
    #     if ALLOWED_GROUPS and gid not in ALLOWED_GROUPS:
    #        return
    # elif hasattr(src, "user_id") and src.user_id:
    #     uid = src.user_id
    #     if uid != os.getenv("OWNER_USER_ID"):  
    #         return
    # else:
    #     return
    text = (event.message.text or "").strip()
    lower = text.lower()

    # 可選：限制白名單群組
    gid = getattr(event.source, "group_id", None)
    if ALLOWED_GROUPS and gid not in ALLOWED_GROUPS:
        return

    # 輕量指令
    if lower.startswith("!yesno"):
        return line_bot_api.reply_message(event.reply_token, TextSendMessage(random.choice(["Yes","No"])))
    if lower.startswith(("!trun","!pick")):
        tokens = shlex.split(text); opts = tokens[1:]
        msg = random.choice(opts) if opts else '用法：!trun 選項1 選項2 ...'
        return line_bot_api.reply_message(event.reply_token, TextSendMessage(msg))
    

    try:
        if lower.startswith("!help"):
            reply = HELP_MSG

        elif lower.startswith("!gid"):
            reply = f"groupId: {gid or '（非群組）'}"

        elif lower.startswith("!uid"):
            uid = getattr(event.source, "user_id", "unknown")
            reply = f"userId: {uid}"

        elif lower.startswith("!additem"):
            tokens = shlex.split(text)
            if len(tokens) < 3 or not tokens[2].lstrip("-").isdigit():
                reply = '用法：!additem 物品 總數量 [備註]'
            else:
                item = tokens[1]; total = int(tokens[2]); note = " ".join(tokens[3:]) if len(tokens)>3 else ""
                upsert_item(item, total, note)
                reply = f"設定完成：{item} 總數量 = {total}"

        elif lower.startswith("!status"):
            tokens = shlex.split(text)
            if len(tokens) >= 2:
                item = tokens[1]
                r = get_item(item)
                if not r: reply = f"尚未建立物品：{item}（用 !additem 建立）"
                else:
                    borrowed = sum_borrowed(item); avail = r["total"] - borrowed
                    reply = f"{item}：總量 {r['total']}、已借 {borrowed}、可借 {avail}"
            else:
                lines = [f"{i}：{t} / 借{b} / 可{a}" for i,t,b,a in status_all()]
                reply = "目前庫存：\n" + ("\n".join(lines) if lines else "（尚無物品）")

        elif lower.startswith(("!borrow","!return")):
            tokens = shlex.split(text)
            if len(tokens) < 3 or not tokens[2].lstrip("-").isdigit():
                reply = '用法：!borrow 物品 數量 [備註]；!return 同上'
            else:
                item = tokens[1]; qty = int(tokens[2]); note = " ".join(tokens[3:]) if len(tokens)>3 else ""
                r = get_item(item)
                if not r:
                    reply = f"尚未建立物品：{item}（先用 !additem）"
                else:
                    uid = getattr(event.source, "user_id", "unknown")
                    name = _display_name(event) or uid
                    if lower.startswith("!borrow"):
                        borrowed = sum_borrowed(item); avail = r["total"] - borrowed
                        if qty <= 0: reply = "數量需為正整數。"
                        elif avail < qty: reply = f"可借不足：{item} 剩 {avail}，你要 {qty}"
                        else:
                            add_tx(gid, uid, name, item, +qty, note)
                            reply = f"借出成功：{item} x {qty}（{name}）"
                    else:
                        have = user_borrowed(uid, item)
                        if qty <= 0: reply = "數量需為正整數。"
                        elif have <= 0: reply = f"你目前沒有借 {item}。"
                        else:
                            real = min(qty, have)
                            add_tx(gid, uid, name, item, -real, note)
                            extra = "" if real == qty else f"（你手上只有 {have}，已自動調整）"
                            reply = f"歸還成功：{item} x {real}（{name}）{extra}"

        elif lower.startswith("!mine"):
            uid = getattr(event.source, "user_id", "unknown")
            rows = ws_tx.get_all_values()
            tally = {}
            for r in rows[1:]:
                if len(r) >= 6 and r[2] == uid:
                    try: delta = int(r[5])
                    except: delta = 0
                    tally[r[4]] = tally.get(r[4], 0) + delta
            lines = [f"{k} x {v}" for k,v in tally.items() if v > 0]
            reply = "你未歸還：\n" + ("\n".join(lines) if lines else "（無）")
        
        else:
            return  # 非指令不回覆

        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))

    except LineBotApiError:
        logging.exception("Line API error while replying")
    except Exception:
        logging.exception("Unexpected error in handle_text")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
