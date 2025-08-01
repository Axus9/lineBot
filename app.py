import os, random, shlex              # ← 加入 shlex
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

load_dotenv()

app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv("LINE_ACCESS_TOKEN"))
handler       = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# --------- 文字訊息處理 ----------
@handler.add(MessageEvent, message=TextMessage)   # ← 必須加這行
def handle_text(event):
    text = event.message.text.strip()

    # !yesno
    if text.lower().startswith("!yesno"):
        answer = random.choice(["Yes", "No"])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(answer)
        )
        return

    # !trun
    if text.lower().startswith("!trun"):
        tokens = shlex.split(text)      # 支援引號內有空白
        options = tokens[1:]            # 拿掉指令本身
        if not options:
            msg = '請在 !trun 後面加至少一個選項，例如：!trun 1 2 3'
            line_bot_api.reply_message(event.reply_token,
                                       TextSendMessage(msg))
            return
        choice = random.choice(options)
        line_bot_api.reply_message(event.reply_token,
                                   TextSendMessage(choice))
        return
# ----------------------------------

if __name__ == "__main__":
    app.run(port=8080)
