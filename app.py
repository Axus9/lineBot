import os, random, shlex, logging
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv("LINE_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

HELP_MSG = (
    "支援指令：\n"
    "!yesno  → 回 Yes/No\n"
    '!trun a b c  → 從選項挑一個（可用引號包起含空白的選項，如 "!trun 咖哩飯 \\"牛丼 大碗\\""）\n'
    "!pick a b c  → 同 !trun\n"
    "!help   → 顯示本訊息"
)

# 接受 GET（給 Verify）與 POST（正式事件）
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

# --------- 文字訊息處理 ----------
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    text = (event.message.text or "").strip()
    lower = text.lower()

    # 只回覆以 "!" 開頭的指令
    if not lower.startswith("!"):
        return

    try:
        if lower.startswith("!help"):
            reply = HELP_MSG

        elif lower.startswith("!yesno"):
            reply = random.choice(["Yes", "No"])

        elif lower.startswith(("!trun", "!pick")):
            tokens = shlex.split(text)   # 支援引號內有空白
            options = tokens[1:]         # 拿掉指令本身
            if not options:
                reply = '用法：!trun 選項1 選項2 ... 例：!trun "咖哩飯" 牛丼 麵'
            else:
                reply = random.choice(options)

        else:
            reply = "看不懂這個指令，輸入 !help 取得說明。"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))

    except LineBotApiError:
        logging.exception("Line API error while replying")
    except Exception:
        logging.exception("Unexpected error in handle_text")
# ----------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
