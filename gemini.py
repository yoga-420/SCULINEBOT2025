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

**特殊**：不在回應中提供資訊來源參考編號、提供緊急資訊、語言翻譯，避免過多提問，直接給建議，當使用者提供資訊不足時先回應一份完整行程，再向使用者提問獲得更多資訊。

自動調整語言（優先繁體中文），確保建議合法、適切。若無即時資訊，誠實告知並給替代方案。目標：便利旅遊體驗！
參考以下回應範例進行回應：

好的，我來幫您規劃台南的4天3夜行程，時間是6月1日至6月4日，人數2人，預算1萬新台幣。由於預算有限，我們會以經濟實惠的方式來規劃，主要考量交通和住宿。
以下是一些規劃方向：

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

希望我有為您打造一個經濟又有趣的台南之旅！
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
    logging.info(f"[query] Gemini input: {payload}")
    try:
        response = chat.send_message(message=payload)
        logging.info(f"[query] Gemini raw response: {response}")
        # 防呆：response 可能不是物件或沒有 .text
        if hasattr(response, "text"):
            logging.info(f"[query] Gemini response.text: {response.text}")
            return response.text
        elif isinstance(response, str):
            logging.info(f"[query] Gemini response(str): {response}")
            return response
        else:
            logging.warning("[query] Gemini response is empty or unknown format.")
            return "抱歉，AI 沒有回應內容。"
    except Exception as e:
        logging.error(f"[query] Gemini API error in query(): {e}")
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
    app.logger.info(f"[callback] Request body: {body}")
    app.logger.info(f"[callback] Signature: {signature}")

    try:
        handler.handle(body, signature)
        app.logger.info("[callback] Handler.handle() success")
    except InvalidSignatureError:
        app.logger.warning("[callback] Invalid signature. Please check channel credentials.")
        abort(400)
    except Exception as e:
        app.logger.error(f"[callback] Exception in handler.handle: {e}")
        abort(500)

    return "OK"


# 用戶歷史查詢記錄（user_id: List[Tuple[地點, 建議]]）
user_history = {}

# 新增：用戶搜尋模式狀態（user_id: bool）
user_search_mode = {}

# 新增：用戶搜尋結果暫存（user_id: List[dict]）
user_search_results = {}

# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_input = event.message.text.strip()
    user_id = event.source.user_id if hasattr(event.source, "user_id") else None
    logging.info(f"[handle_text_message] user_id: {user_id}, user_input: {user_input}")

    # 進入歷史紀錄搜尋模式
    if user_input == "我要瀏覽歷史紀錄":
        if user_id:
            user_search_mode[user_id] = True
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            ask_msg = (
                "請直接輸入您想查詢的國家地點或關鍵字（多次查詢皆可），"
                "記得按下「結束搜尋」選單按紐來結束搜尋模式。"
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
            # 清除舊的查詢標號
            if user_id in user_search_results:
                del user_search_results[user_id]
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
                logging.info(f"[search_mode] user_id: {user_id}, input: {user_input}, search_results: {user_search_results.get(user_id)}")
                # 若前次已查詢且輸入為數字或"全部顯示"，則回傳對應內容
                if user_id in user_search_results and user_search_results[user_id]:
                    if user_input.isdigit():
                        idx = int(user_input) - 1
                        results = user_search_results[user_id]
                        if 0 <= idx < len(results):
                            # 若已經有完整內容則直接回傳，否則即時查詢
                            if results[idx]["full"]:
                                detail = results[idx]["full"]
                            else:
                                # 重新查詢該筆完整內容
                                # 只取掉前面的編號，避免 prompt 再帶入 1. 2. 3.
                                summary = results[idx]["summary"]
                                # 移除前面的數字與點
                                import re
                                summary_no_num = re.sub(r"^\d+\.\s*", "", summary)
                                prompt = (
                                    f"請根據你與我的所有對話記憶，針對以下摘要內容，"
                                    f"詳細列出該旅遊行程的完整內容，請分早上、下午、晚上，"
                                    f"並以繁體中文回覆：\n{summary_no_num}"
                                )
                                detail = query(prompt)
                                user_search_results[user_id][idx]["full"] = detail
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    reply_token=event.reply_token,
                                    messages=[TextMessage(text=detail)],
                                )
                            )
                        else:
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    reply_token=event.reply_token,
                                    messages=[TextMessage(text="查無此編號，請重新輸入。")],
                                )
                            )
                        return
                    elif user_input == "全部顯示":
                        details = "\n\n".join(
                            f"{i+1}.\n{item['full'] or item['summary']}" for i, item in enumerate(user_search_results[user_id])
                        )
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[TextMessage(text=details)],
                            )
                        )
                        return
                # 否則進行新查詢
                # 進行新查詢，請 Gemini 只給與關鍵字有關的紀錄摘要，並分早上/下午/晚上
                prompt = (
                    f"請根據你與我的所有對話記憶，查詢與「{user_input}」相關的所有旅遊行程紀錄，"
                    "只顯示與該關鍵字有關的紀錄。\n"
                    "如果有多筆，請依下列格式編號並摘要列出，內容請簡短：\n"
                    "1. 🗓️ [日期] - [行程標題]\n"
                    "   - 早上：[簡要說明]\n"
                    "   - 下午：[簡要說明]\n"
                    "   - 晚上：[簡要說明]\n"
                    "2. ...\n"
                    "請勿給完整內容，只給每筆紀錄的簡短摘要，並在每筆前**加上代號（1、2、3...）**。\n"
                    "最後請附註：請輸入想查看的代號（例如：1），來查看完整內容。\n"
                    "如果只有一筆，請直接顯示完整內容，並請分早上、下午、晚上。\n"
                    "如果沒有相關紀錄，請明確說明。\n"
                    "請以繁體中文回覆。"
                )
                response = query(prompt)
                logging.info(f"[search_mode] Gemini summary response: {response}")
                html_msg = markdown.markdown(response)
                soup = BeautifulSoup(html_msg, "html.parser")
                # 將多餘空行去除，並用單一換行分隔，縮小間距
                text = '\n'.join([line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()])

                # 解析每一筆摘要，存入 user_search_results 以便後續查詢完整內容
                import re
                results = []
                # 修正：若 Gemini 回傳只有「請輸入想查看的代號」而沒有任何摘要，代表沒有找到紀錄
                if "請輸入想查看的代號" in text and re.search(r"\d+\.\s", text):
                    # 解析 1. 2. 3. 開頭的段落
                    matches = re.findall(r"(\d+)\.\s(.*?)(?=\n\d+\.\s|\Z)", text, re.DOTALL)
                    for idx, (num, content) in enumerate(matches):
                        # 嘗試從內容中抓取日期與地點資訊
                        # 預設格式：🗓️ [日期] - [行程標題]
                        date_place_match = re.search(r"🗓️\s*([^\s-]+(?:-[^\s-]+)*)\s*-\s*(.+)", content)
                        if date_place_match:
                            date_str = date_place_match.group(1).strip()
                            place_str = date_place_match.group(2).strip()
                            # 只取第一行作為標題
                            first_line = f"{idx+1}. {date_str}-{place_str}"
                            # 其餘內容（去掉第一行）
                            rest = content.split('\n', 1)[1].strip() if '\n' in content else ""
                            summary = f"{first_line}\n{rest}" if rest else first_line
                        else:
                            # 若無法解析則維持原本內容
                            summary = f"{idx+1}. {content.strip()}"
                        results.append({"summary": summary, "full": None})
                    user_search_results[user_id] = results
                    # 重新組合摘要訊息，前面加上 [編號1] [編號2] ...
                    summary_text = ""
                    for i, item in enumerate(results):
                        lines = item["summary"].split('\n', 1)
                        summary_text += f"[編號{i+1}] {lines[0]}\n"
                        if len(lines) > 1:
                            summary_text += f"{lines[1]}\n"
                        summary_text += "\n"
                    summary_text = summary_text.strip() + "\n\n請輸入想查看的代號（例如：1），來查看完整內容。"
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=summary_text)],
                        )
                    )
                else:
                    # 若沒有任何摘要，直接回傳 Gemini 的訊息
                    user_search_results[user_id] = []
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=text)],
                        )
                    )
                logging.info("[search_mode] reply_message_with_http_info sent")
            except Exception as e:
                app.logger.error(f"[search_mode] Error in search mode (Gemini memory): {e}")
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="抱歉，AI 查詢記憶時發生錯誤。")],
                    )
                )
        return

    # 若用戶在搜尋模式下選擇摘要後，查詢完整內容
    if user_id and user_id in user_search_results and user_search_results[user_id]:
        # 若前面已處理，這裡可略過
        pass

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
                "5.住宿類型選擇:\n"
                "6.交通方式:\n"
                "7.想去的景點或餐廳:\n"
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
                logging.info(f"[handle_text_message] Querying Gemini with: {event.message.text}")
                response = query(event.message.text)
                logging.info(f"[handle_text_message] Gemini response: {response}")
                html_msg = markdown.markdown(response)
                soup = BeautifulSoup(html_msg, "html.parser")
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=soup.get_text())],
                    )
                )
                logging.info("[handle_text_message] reply_message_with_http_info sent")
            except Exception as e:
                app.logger.error(f"[handle_text_message] Error in handle_text_message: {e}")
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


# base_url 檢查
if not base_url:
    logging.warning("SPACE_HOST (base_url) 未設置，圖片/影片網址將無法正確顯示。")