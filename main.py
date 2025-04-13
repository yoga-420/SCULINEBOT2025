# 東吳大學資料系 2025 年 LINEBOT

import os
import tempfile
import logging
import requests
import markdown

from flask import Flask, request, abort, send_from_directory
from bs4 import BeautifulSoup
import google.generativeai as genai
import openai

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent
)

# === 初始化 Google Gemini ===
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# === 初始化OpenAI模型 ===
openai.api_key = os.getenv("OPENAI_API_KEY")


# === 初始設定 ===
static_tmp_path = "/tmp"
os.makedirs(static_tmp_path, exist_ok=True)
base_url = os.getenv("SPACE_HOST")  # e.g., "your-space-name.hf.space"

# === Flask 應用初始化 ===
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app.logger.setLevel(logging.INFO)

channel_secret = os.environ.get("YOUR_CHANNEL_SECRET")
channel_access_token = os.environ.get("YOUR_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# === AI Query 包裝 ===
def query(payload):
    response = model.generate_content(payload)
    return response.text

# === 靜態圖檔路由 ===
@app.route("/images/<filename>")
def serve_image(filename):
    return send_from_directory(static_tmp_path, filename)

@app.route("/static/<path:path>")
def send_static_content(path):
    return send_from_directory("static", path)

# === LINE Webhook 接收端點 ===
@app.route("/")
def home():
    return {"message": "Line Webhook Server"}

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

# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
        user_input = event.message.text.strip()
        if user_input.startswith("AI "):
            prompt = user_input[3:].strip()
            try:
                response = openai.Image.create(
                    prompt=prompt,
                    model="dall-e-3",
                    n=1,
                    size="1024x1024",
                    response_format="url"
                )
                image_url = response['data'][0]['url']
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                ImageMessage(
                                    original_content_url=image_url,
                                    preview_image_url=image_url
                                )
                            ]
                        )
                    )
            except Exception as e:
                app.logger.error(f"DALL·E 3 API error: {e}")
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="抱歉，生成圖像時發生錯誤。")]
                        )
                    )
        else:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                response = query(event.message.text)
                html_msg = markdown.markdown(response)
                soup = BeautifulSoup(html_msg, "html.parser")
    
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=soup.get_text())]
                    )
                )

# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    ext = "jpg"
    with ApiClient(configuration) as api_client:
        blob_api = MessagingApiBlob(api_client)
        content = blob_api.get_message_content(message_id=event.message.id)

    with tempfile.NamedTemporaryFile(dir=static_tmp_path, suffix=f".{ext}", delete=False) as tf:
        tf.write(content)
        filename = os.path.basename(tf.name)

    image_url = f"https://{base_url}/images/{filename}"
    app.logger.info(f"Image URL: {image_url}")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    ImageMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url
                    )
                ]
            )
        )
