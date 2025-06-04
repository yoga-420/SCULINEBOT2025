# ===東吳大學資料系 2025 年 LINEBOT ===
import logging
import os
import tempfile
import uuid
from io import BytesIO

import markdown
from bs4 import BeautifulSoup
from flask import Flask, abort, request, send_from_directory

from google import genai
from google.genai import types
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    ImageMessage,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    FollowEvent,
    ImageMessageContent,
    MessageEvent,
    TextMessageContent,
)

from PIL import Image
from linebot.v3.webhooks import VideoMessageContent

# === 初始化 Google Gemini ===
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

google_search_tool = Tool(
    google_search=GoogleSearch()
)

chat = client.chats.create(
    model="gemini-2.0-flash",
    config=GenerateContentConfig(
        # 修改為旅遊規劃專家
        system_instruction="你是一個專門規劃旅遊的AI助手，請用繁體中文根據使用者需求，提供旅遊建議、行程規劃、景點推薦、交通與住宿建議等，並主動詢問使用者旅遊地點、天數、預算、興趣等資訊以協助規劃。",
        tools=[google_search_tool],
        response_modalities=["TEXT"],
    )
)

# === 初始設定 ===
static_tmp_path = tempfile.gettempdir()
os.makedirs(static_tmp_path, exist_ok=True)
base_url = os.getenv("SPACE_HOST")  # e.g., "your-space-name.hf.space"

# === Flask 應用初始化 ===
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
app.logger.setLevel(logging.INFO)

channel_secret = os.environ.get("YOUR_CHANNEL_SECRET")
channel_access_token = os.environ.get("YOUR_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)


# === AI Query 包裝 ===
def query(payload):
    try:
        response = chat.send_message(message=payload)
        # 防呆：response 可能不是物件或沒有 .text
        if hasattr(response, "text"):
            return response.text
        elif isinstance(response, str):
            return response
        else:
            return "抱歉，AI 沒有回應內容。"
    except Exception as e:
        logging.error(f"Gemini API error in query(): {e}")
        return "抱歉，AI 回應時發生錯誤。"


# === 靜態圖檔路由 ===
@app.route("/images/<filename>")
def serve_image(filename):
    return send_from_directory(static_tmp_path, filename)


# === LINE Webhook 接收端點 ===
@app.route("/")
def home():
    return "Line Webhook Server"  # 修正回傳格式


@app.route("/", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.warning("Invalid signature. Please check channel credentials.")
        abort(400)

    return "OK"


# 用戶歷史查詢記錄（user_id: List[Tuple[地點, 建議]]）
user_history = {}

# 新增：用戶搜尋模式狀態（user_id: bool）
user_search_mode = {}

# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_input = event.message.text.strip()
    user_id = event.source.user_id if hasattr(event.source, "user_id") else None

    # 進入歷史紀錄搜尋模式
    if user_input == "我要瀏覽歷史紀錄":
        if user_id:
            user_search_mode[user_id] = True
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            ask_msg = (
                "請直接輸入您想查詢的國家地點或關鍵字（多次查詢皆可），\n"
                "若要結束搜尋，請輸入：結束搜尋"
            )
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=ask_msg)],
                )
            )
        return

    # 結束歷史紀錄搜尋模式
    if user_input == "結束搜尋":
        if user_id and user_id in user_search_mode:
            user_search_mode[user_id] = False
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            msg = "已結束歷史紀錄查詢，請繼續使用其他功能。"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=msg)],
                )
            )
        return

    # 搜尋模式下，所有輸入都視為關鍵字查詢
    if user_id and user_search_mode.get(user_id, False):
        # 只要 user_id 有歷史紀錄
        if user_id in user_history and user_history[user_id]:
            # 遍歷歷史紀錄，找出地點或建議中包含 user_input 的紀錄
            filtered = [
                (place, advice)
                for place, advice in user_history[user_id]
                if user_input in place or user_input in advice
            ]
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                if filtered:
                    # 有找到符合的紀錄，組成回應訊息
                    history_list = "\n\n".join(
                        f"{idx+1}. {place}\n建議：{advice}"
                        for idx, (place, advice) in enumerate(filtered)
                    )
                    msg = f"查詢「{user_input}」的歷史紀錄：\n{history_list}"
                else:
                    # 沒有找到符合的紀錄
                    msg = f"沒有查詢過包含「{user_input}」的國家地點或建議。"
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=msg)],
                    )
                )
        else:
            # 沒有任何歷史紀錄
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                msg = "您尚未查詢過任何旅遊資訊。"
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=msg)],
                    )
                )
        return

    if user_input == "我要新增規劃":
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            plan_msg = (
                "請告訴我以下資訊:\n"
                "\n"
                "1.旅遊國家地點:\n"
                "2.日期:\n"
                "3.人數:\n"
                "4.旅行預算:\n"
                "5.想去的景點或餐廳:\n"
                "\n"
                "請幫我複製此對話框的訊息來回覆問題！"
            )
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=plan_msg)],
                )
            )
        return

    else:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                response = query(event.message.text)
                html_msg = markdown.markdown(response)
                soup = BeautifulSoup(html_msg, "html.parser")
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=soup.get_text())],
                    )
                )
            except Exception as e:
                app.logger.error(f"Error in handle_text_message: {e}")
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="抱歉，AI 回應時發生錯誤。")],
                    )
                )

# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    # === 以下是處理圖片回傳部分 === #
    with ApiClient(configuration) as api_client:
        blob_api = MessagingApiBlob(api_client)
        content = blob_api.get_message_content(message_id=event.message.id)

    # Step 4：將圖片存到本地端
    with tempfile.NamedTemporaryFile(
        dir=static_tmp_path, suffix=".jpg", delete=False
    ) as tf:
        tf.write(content)
        filename = os.path.basename(tf.name)

    image_url = f"https://{base_url}/images/{filename}"

    app.logger.info(f"Image URL: {image_url}")

    # === 以下是解釋圖片 === #
    image = Image.open(tf.name)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        config=types.GenerateContentConfig(
            system_instruction="你是一個資深的面相命理師，如果有人上手掌的照片，就幫他解釋手相，如果上傳正面臉部的照片，就幫他解釋面相，照片要先去背，如果是一般的照片，就正常說明照片不用算命，請用繁體中文回答",
            response_modalities=["TEXT"],
            tools=[google_search_tool],
        ),
        contents=[image, "用繁體中文描述這張圖片"],
    )
    app.logger.info(response.text)

    # === 以下是回傳圖片部分 === #
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    ImageMessage(
                        original_content_url=image_url, preview_image_url=image_url
                    ),
                    TextMessage(text=response.text),
                ],
            )
        )

# === 處理影片訊息 ===

@handler.add(MessageEvent, message=VideoMessageContent)
def handle_video_message(event):
    # 下載影片內容
    with ApiClient(configuration) as api_client:
        blob_api = MessagingApiBlob(api_client)
        video_data = blob_api.get_message_content(message_id=event.message.id)

    # 儲存影片到本地
    if video_data is None:
        err_msg = "抱歉，無法取得影片內容。"
        app.logger.error(err_msg)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=err_msg)]
                )
            )
        return

    with tempfile.NamedTemporaryFile(
        dir=static_tmp_path, suffix=".mp4", delete=False
    ) as tf:
        tf.write(video_data)
        filename = os.path.basename(tf.name)

    video_url = f"https://{base_url}/images/{filename}"
    app.logger.info(f"Video URL: {video_url}")

    # 影片說明
    try:
        from io import BytesIO
        video_bytes = BytesIO(video_data)
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            config=types.GenerateContentConfig(
                system_instruction="你是一個專業的影片解說員，請用繁體中文簡要說明這段影片的內容。",
                response_modalities=["TEXT"],
                tools=[google_search_tool],
            ),
            contents=[video_bytes, "用繁體中文描述這段影片"],
        )
        description = response.text
    except Exception as e:
        app.logger.error(f"Gemini API error (video): {e}")
        description = "抱歉，無法解釋這段影片內容。"

    # 回傳影片連結與說明
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=f"影片連結：{video_url}"),
                    TextMessage(text=description),
                ],
            )
        )

# === 處理使用者加入聊天室（加好友/進入聊天室）===
@handler.add(FollowEvent)
def handle_follow(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        intro_msg = (
            "您好！我是您的旅遊小管家小花。\n"
            "請問：\n"
            "1. 想去的旅遊地點？\n"
            "2. 預算金額？\n"
            "3. 旅遊天數？\n"
            "4. 旅遊人數？\n"
            "請一次告訴我這四個資訊，讓我幫您規劃行程！"
        )
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=intro_msg)],
            )
        )

# base_url 檢查
if not base_url:
    logging.warning("SPACE_HOST (base_url) 未設置，圖片/影片網址將無法正確顯示。")