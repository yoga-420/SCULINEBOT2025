# 東吳大學資料系2025年LINEBOT

from flask import Flask, request, abort, send_from_directory

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
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

import os
import requests
import logging

import google.generativeai as genai

# HF_TOKEN = os.environ.get('HF_TOKEN')
# headers = {"Authorization": f"Bearer {HF_TOKEN}"}

GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

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

@app.route('/static/<path:path>')
def send_static_content(path):
    return send_from_directory('static', path)