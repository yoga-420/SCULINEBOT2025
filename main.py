# 東吳大學資料系2025年LINEBOT

from flask import Flask, request, abort, send_from_directory
import pyimgur

import markdown
from bs4 import BeautifulSoup

from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent
)

import os
import requests
import logging

import google.generativeai as genai

# HF_TOKEN = os.environ.get('HF_TOKEN')
# headers = {"Authorization": f"Bearer {HF_TOKEN}"}

imgur_client_id = os.environ.get('IMGUR_CLIENT_ID')
imgur_client = pyimgur.Imgur(imgur_client_id)

GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# API_URL = "https://api-inference.huggingface.co/models/mistralai/Mixtral-8x7B-Instruct-v0.1"
def query(payload):
    # response = requests.post(API_URL, headers=headers, json=payload)
    response = model.generate_content(payload)
    return response.text

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

channel_secret = os.environ.get('YOUR_CHANNEL_SECRET')
channel_access_token = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

@app.route("/")
def home():
    return {"message": "Line Webhook Server"}

@app.route("/", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        response = query(event.message.text)
        html_msg = markdown.markdown(response)
        soup = BeautifulSoup(html_msg, 'html.parser')
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=soup.get_text())]
            )
        )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        # 取得圖片內容
        message_content = line_bot_api.get_message_content(event.message.id)
        # 儲存圖片至暫存檔案
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
            for chunk in message_content.iter_content():
                tf.write(chunk)
            temp_file_path = tf.name
        try:
            # 上傳圖片至 Imgur
            uploaded_image = imgur_client.upload_image(temp_file_path, title="Uploaded via LINE Bot")
            image_url = uploaded_image.link
            # 回傳圖片給使用者
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
        finally:
            # 刪除暫存檔案
            os.remove(temp_file_path)

@app.route('/static/<path:path>')
def send_static_content(path):
    return send_from_directory('static', path)