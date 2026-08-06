import os
import re
import time
import random
import requests
from google import genai

# ── 環境變數 ──────────────────────────────────────────
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
THREADS_USER_ID    = os.environ["THREADS_USER_ID"]
THREADS_TOKEN      = os.environ["IG_ACCESS_TOKEN"]

EXAMPLE_POST = """
以下是真實的發文範例，請完全學習這個風格、語氣、句子長度和換行方式：

【範例一】
叫小姐介紹小姐，表面上看起來很合理。

但我做了七年，從來不這樣做。

原因很簡單：

朋友做得不好，介紹人要負責。

朋友做得好，介紹人反而有壓力。

萬一朋友出了什麼事，姐妹情就這樣沒了。

錢可以再賺，但朋友之間的信任，賠掉就很難回來。

所以我的規矩是，每個人自己來，自己決定。

【範例二】
關於八大合約，有幾件事妳要知道：

第一，簽了合約，換經紀要付五萬以上違約金。

第二，就算有人說幫妳付，那錢最後還是從妳薪水扣回來。

第三，簽約之後衍生最多的問題就是壓薪水。

第四，妳有領經紀的底薪嗎？沒有。那憑什麼有競業條款？

我從不要求小姐簽合約。

因為她上班我才有錢賺，她想走是她的權利。
"""

def send_telegram(message):
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=30
    )

def get_pending_topics():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {"filter": {"property": "狀態", "status": {"equals": "待發"}}}
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    data = res.json()
    results = data.get("results", [])
    print(f"待發筆數：{len(results)}")
    return results

def update_status(page_id, status="已發"):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    requests.patch(url, headers=headers, json={"properties": {"狀態": {"status": {"name": status}}}}, timeout=30)

def clean_text(text):
    text = re.sub(r'\n?-{2,}\n?', '\n', text)
    text = re.sub(r'\*{2,}', '', text)
    text = re.sub(r'(?<!\*)\*(?!\*)', '', text)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [line.strip() for line in text.split('\n')]
    return '\n'.join(lines).strip()

def generate_post(custom_topic):
    prompt = f"""
你是一位在八大行業做了7年的男性經紀人，現在在 Threads 上發文。

【主題】
本次主題已指定為：「{custom_topic}」

{EXAMPLE_POST}

【風格：條列型】
清楚、資訊型、易讀。
用「第一、第二、第三」或「有幾件事妳要知道」這類開頭帶出重點。
每個重點獨立一行，簡短有力。
結尾用一句話收尾。

【字數規則】
整篇 150-300 字。
一行不超過 20 個字。
同一概念不空行，只有概念切換才空一行。

【語言風格】
台灣口語，每句獨立一行，句號後換行。
用「妳」稱呼讀者，用「她」稱呼案例中的人。

【寫作規則】
1. 禁止使用任何人名，一律用「有個小姐」「有個女生」「她」代替
2. 禁止 emoji、粗體、斜體
3. 標點符號全部使用全形（，。？！：）
4. 禁止「不是⋯而是⋯」句型
5. 問題來源只能是「黑心經紀」或「經紀人」
6. 禁止「姐妹們」「姊妹們」「妹子」「進場」
7. 直接輸出文章內容，不要輸出主題標題、不要有任何說明文字
"""

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
    ]

    for model in models_to_try:
        print(f"🤖 使用模型：{model}")
        for attempt in range(3):
            try:
                print(f"  第 {attempt+1} 次呼叫 Gemini...")
                client = genai.Client(
                    api_key=GEMINI_API_KEY,
                    http_options={"timeout": 300000}
                )
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                if not response.text:
                    print(f"  回應為空，重試...")
                    continue
                cleaned = clean_text(response.text.strip())
                print(f"📋 前100字：{repr(cleaned[:100])}")
                return cleaned

            except Exception as e:
                err = str(e)
                print(f"  第 {attempt+1} 次失敗：{err}")
                if "503" in err:
                    wait = 2 ** attempt * 10
                    print(f"  503 過載，等 {wait} 秒...")
                    time.sleep(wait)
                elif "429" in err:
                    print(f"  429 額度已滿，換下一個模型")
                    break
                else:
                    raise

        print(f"  {model} 全部失敗，換下一個模型...")

    raise Exception("所有模型都失敗，放棄")

def post_to_threads(text):
    text = clean_text(text)
    if len(text) > 500:
        text = text[:500]

    print(f"🚀 建立發文（{len(text)} 字元）| 預覽：{repr(text[:60])}")

    create_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    data = {"media_type": "TEXT", "text": text, "access_token": THREADS_TOKEN}
    res = requests.post(create_url, data=data, timeout=30).json()
    creation_id = res.get("id")
    if not creation_id:
        raise Exception(f"建立 container 失敗：{res}")

    time.sleep(8)

    for attempt in range(3):
        print(f"📤 發布（第 {attempt+1} 次）...")
        pub_res = requests.post(
            f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish",
            data={"creation_id": creation_id, "access_token": THREADS_TOKEN},
            timeout=30
        ).json()
        if pub_res.get("id"):
            print(f"✅ 發布成功：{pub_res['id']}")
            return
        elif pub_res.get("error", {}).get("is_transient"):
            print(f"暫時性錯誤，等待 15 秒...")
            time.sleep(15)
        else:
            raise Exception(f"發布失敗：{pub_res}")

    raise Exception("發布失敗超過重試次數")

if __name__ == "__main__":
    print("=== Gray 3 條列型 ===")
    pages = get_pending_topics()
    if not pages:
        print("沒有待發主題，結束。")
        send_telegram("⚠️ Gray 3 今日無待發主題")
        exit(0)

    page = random.choice(pages)
    page_id = page["id"]
    props = page.get("properties", {})
    topic_list = props.get("主題", {}).get("title", [])
    custom_topic = topic_list[0]["plain_text"] if topic_list else ""

    if not custom_topic.strip():
        print("主題為空，結束。")
        update_status(page_id, "已發")
        exit(0)

    try:
        print(f"📌 主題：{custom_topic}")
        post_text = generate_post(custom_topic)
        print("貼文內容：\n", post_text)
        post_to_threads(post_text)
        update_status(page_id, "已發")
        print("✅ 完成！")
        send_telegram(f"✅ Gray 3 發文成功！\n主題：{custom_topic}")
    except Exception as e:
        error_msg = f"❌ Gray 3 發文失敗！\n錯誤原因：{str(e)}"
        print(error_msg)
        update_status(page_id, "失敗")
        send_telegram(error_msg)
        raise
