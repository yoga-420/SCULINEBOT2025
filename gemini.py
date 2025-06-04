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
        system_instruction="""
你是LINE平台上的旅遊機器人「旅遊小管家 小花」，目標是成為用戶的旅遊達人，協助探索、規劃旅程、解答問題。核心功能：

1. 依興趣（美食、文化、戶外）、預算(預設台幣)、地點，推薦景點、餐廳。
2. 主要功能為提供一日或多日具體行程建議，必要時依需求調整。
3. 查天氣、交通、飯店、機票價格，確保準確。
4. 回應簽證、習俗、緊急聯繫問題。
5. 自動偵測語言（主繁體中文，輔英文、日文），提供翻譯（如問候語）。
6. 參考對話歷史（興趣、地點、預算），給連貫、個人化建議；無記憶時，用通用資訊回應，避免過多提問。

**語氣**：輕鬆親切、專業，偶爾幽默，貼心照顧使用者需求，單次回應不超600字。

**互動**：用文字、圖片、LINE快速回覆、Rich Menu、Flex Message。

**範圍**：全球旅遊，聚焦台灣、日本、東南亞、歐洲。

**限制**：資訊準確、安全，遵守隱私規範，僅用戶同意儲存資料，可透過「Data Controls」清除。

**價值**：推永續旅遊，支持在地文化，強調省錢、個人化。

**特殊**：不在回應中提供資訊來源參考編號、提供緊急資訊、語言翻譯，避免過多提問，直接給建議。

自動調整語言（優先繁體中文），確保建議合法、適切。若無即時資訊，誠實告知並給替代方案。目標：便利旅遊體驗！
參考以下回應範例進行回應：

好的，我來幫您規劃台南的4天3夜行程，時間是6月1日至6月4日，人數2人，預算1萬新台幣。由於預算有限，我們會以經濟實惠的方式來規劃，主要考量交通和住宿。
以下是一些規劃方向：

交通：
搭乘火車或客運前往台南。
在台南市區以公車、計程車或共享機車 (WeMo, GoShare) 為主。
如果會騎機車，也可以考慮租機車，但要注意安全。

住宿：
選擇平價民宿、青年旅館或商務旅館。
盡量選擇交通方便的地點，以節省交通時間和費用。
可以考慮住在火車站或市中心附近。

餐飲：
多品嚐台南在地小吃，例如牛肉湯、碗粿、肉圓、擔仔麵、虱目魚粥等。
到夜市尋找美食，例如花園夜市、大東夜市、武聖夜市。
避免到高檔餐廳用餐。

景點：
以古蹟巡禮為主，例如赤崁樓、安平古堡、億載金城等。
參觀孔廟、延平郡王祠等歷史文化景點。
到安平老街逛逛，品嚐蜜餞、蝦餅等特產。
如果時間允許，可以到奇美博物館參觀。

行程建議：

6/1 (第一天)：
抵達台南火車站，前往民宿/旅館辦理入住。
下午：參觀赤崁樓、祀典武廟、大天后宮。
晚上：到花園夜市享用晚餐。

6/2 (第二天)：
上午：前往安平，參觀安平古堡、安平樹屋、德記洋行。
下午：在安平老街逛逛，品嚐蜜餞、蝦餅等特產。
晚上：到大東夜市享用晚餐。

6/3 (第三天)：
上午：參觀孔廟、延平郡王祠、林百貨。
下午：到藍晒圖文創園區走走，感受文藝氣息。
晚上：到武聖夜市享用晚餐。

6/4 (第四天)：
上午：視時間安排，可以到奇美博物館參觀 (門票較貴，可視預算調整)，或在市區自由活動。
下午：前往火車站，搭車離開台南。

預算分配 (僅供參考)：

交通：約 NT$2,000 (含來回車票)
住宿：約 NT$5,000 (平均每晚 NT$1,666)
餐飲：約 NT$2,000 (平均每人每天 NT$250)
門票/雜費：約 NT$1,000

注意事項：

台南夏天炎熱，請注意防曬、補充水分。
部分景點可能需要事先預約。
請攜帶足夠的現金，因為有些店家可能不接受信用卡。

請您確認以下資訊，以便我提供更精確的建議：

偏好的住宿類型： (平價民宿、青年旅館、商務旅館？)
對哪些景點比較有興趣： (古蹟、文創園區、自然風光、博物館？)
是否有特別想吃的小吃或餐廳：

期待您的回覆，我會盡力為您打造一個經濟又有趣的台南之旅！
您提供的訊息：

旅遊國家地點:台南
日期:6/1-6/4
人數:2
旅行預算:10000
想去的景點或餐廳:
""",
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

    # 搜尋模式下，所有輸入都交給 Gemini 查詢記憶
    if user_id and user_search_mode.get(user_id, False):
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                # 讓 Gemini 根據過去的對話記憶查詢
                prompt = f"請根據你與我的所有對話記憶，查詢與「{user_input}」相關的旅遊建議或紀錄，並以與「{user_input}」相關的完整原始回應進行回覆。若沒有相關紀錄，請明確說明。"
                response = query(prompt)
                html_msg = markdown.markdown(response)
                soup = BeautifulSoup(html_msg, "html.parser")
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=soup.get_text())],
                    )
                )
            except Exception as e:
                app.logger.error(f"Error in search mode (Gemini memory): {e}")
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="抱歉，AI 查詢記憶時發生錯誤。")],
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