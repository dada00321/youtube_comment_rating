# pip install google-api-python-client pandas tqdm regex

import re
import math
from collections import defaultdict, Counter
from urllib.parse import urlparse, parse_qs

import pandas as pd
from googleapiclient.discovery import build
from tqdm import tqdm

API_KEY = "PASTE_YOUR_API_KEY_HERE"

# 要分析的影片連結
VIDEO_URLS = [
    "https://www.youtube.com/watch?v=Hf4FGGKm9nM", # 泛式｜2025年10月新番完結吐槽
    "https://www.youtube.com/watch?v=AhHvImNYUAg", # 泛式｜2025年10月新番導視
    "https://www.youtube.com/watch?v=xU31H_C6hiQ" # 卡欸蝶｜【10月新番資訊】最快速帶你看這季所有新番
]

# 作品別名表：你之後可以越補越完整
# key = 標準作品名（繁中），value = 可能出現在留言的別名/簡稱/英文/日文
TITLE_ALIASES = {
    "我的英雄學院 最終季": [
        "我英", "MHA", "HeroAca", "My Hero Academia", "我的英雄學院", "最終季"
    ],
    "SPY×FAMILY 間諜家家酒 第三季": [
        "間諜家家酒", "SPY FAMILY", "Spy Family", "安妮亞", "黃昏", "約兒", "家家酒", "++9", "8+9"
    ],
    "賽馬娘 Pretty Derby 灰姑娘格雷 第二部": [
        "賽馬娘", "馬娘", "Cinderella Gray", "灰姑娘格雷", "小栗帽"
    ],
    "一拳超人 第三季": [
        "一拳", "一拳超人", "OPM", "One Punch Man", "埼玉", "光頭"
    ],
    "給不滅的你 第三季": [
        "不滅", "給不滅的你", "To Your Eternity", "Fushi", "不死"
    ],
    "GACHIAKUTA": [
        "Gachiakuta", "垃圾場少年", "塗鴉能力", "戰鬥垃圾"
    ],
    "這個怪物想吃掉我": [
        "怪物想吃我", "This Monster Wants to Eat Me", "病嬌怪物", "怪物"
    ],
    "WANDANCE": [
        "Wandance", "街舞番", "舞蹈番"
    ],
    "我朋友的妹妹只喜歡煩我": [
        "朋友的妹妹", "煩我妹妹", "ImoUza", "我妹只會煩我"
    ],
    "擁有超常技能的異世界流浪美食家 第二季": [
        "流浪美食家", "Campfire Cooking", "異世界料理", "穆寇達", "史伊"
    ],
    "拜託了，可以讓我問最後一個問題嗎？": [
        "最後一個問題", "May I Ask For One Final Thing", "拜託最後"
    ]
}

POS_WORDS = [
    "神", "神作", "頂", "封神", "好看", "超好看", "好讚", "推", "必追", "必看", "驚艷",
    "爽", "感動", "燃", "強", "最強", "上頭", "香", "高品質", "屌"
]
NEG_WORDS = [
    "爛", "難看", "失望", "糞", "崩", "作畫崩", "無聊", "拖", "尷尬", "勸退", "雷",
    "看不下去", "棄", "棄番", "浪費時間", "糞", "鳥"
]

def extract_video_id(url: str) -> str:
    u = urlparse(url)
    if u.hostname in ["youtu.be"]:
        return u.path.lstrip("/")
    if u.hostname and "youtube.com" in u.hostname:
        qs = parse_qs(u.query)
        if "v" in qs:
            return qs["v"][0]
        # shorts
        m = re.search(r"/shorts/([^/?]+)", u.path)
        if m:
            return m.group(1)
    raise ValueError(f"無法解析 videoId: {url}")

def fetch_comments(video_id: str, max_comments: int = 2000) -> list[str]:
    yt = build("youtube", "v3", developerKey=API_KEY)
    comments = []
    next_page = None

    while True:
        req = yt.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            pageToken=next_page,
            textFormat="plainText",
            order="relevance",  # 你也可以改 time
        )
        resp = req.execute()

        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(top)
            if len(comments) >= max_comments:
                return comments

        next_page = resp.get("nextPageToken")
        if not next_page:
            break
    return comments

def build_alias_regex(title_aliases: dict) -> dict[str, re.Pattern]:
    compiled = {}
    for std_title, aliases in title_aliases.items():
        # escape 並做 OR
        parts = [re.escape(a) for a in sorted(set([std_title] + aliases), key=len, reverse=True)]
        compiled[std_title] = re.compile(r"(" + "|".join(parts) + r")", re.IGNORECASE)
    return compiled

def sentiment_score(text: str) -> tuple[int, int]:
    # 回傳 (pos_hits, neg_hits)
    pos = sum(1 for w in POS_WORDS if w in text)
    neg = sum(1 for w in NEG_WORDS if w in text)
    return pos, neg

def main():
    # 1) 抓留言
    all_rows = []
    for url in VIDEO_URLS:
        vid = extract_video_id(url)
        print("Fetching:", url, "->", vid)
        comments = fetch_comments(vid, max_comments=3000)
        for c in comments:
            all_rows.append({"video_url": url, "comment": c})

    df = pd.DataFrame(all_rows)
    if df.empty:
        raise SystemExit("沒有抓到留言（檢查 API_KEY / 影片網址 / 是否關閉留言）")

    # 2) 命中作品
    alias_re = build_alias_regex(TITLE_ALIASES)
    stats = defaultdict(lambda: {"mentions": 0, "pos": 0, "neg": 0, "comments": []})

    for c in tqdm(df["comment"].tolist(), desc="Scoring"):
        pos, neg = sentiment_score(c)
        for std_title, rx in alias_re.items():
            if rx.search(c):
                stats[std_title]["mentions"] += 1
                stats[std_title]["pos"] += pos
                stats[std_title]["neg"] += neg
                
                #if len(stats[std_title]["comments"]) < 3: # 特定作品的相關留言, 最多只取 3 則
                stats[std_title]["comments"].append(c)

    # 3) 算分（熱度 * 評價）
    rows = []
    mentioned_titles = set()

    for title, s in stats.items():
        if s["mentions"] == 0:
            continue
        mentioned_titles.add(title)
        pos_ratio = s["pos"] / max(1, (s["pos"] + s["neg"]))
        neg_ratio = s["neg"] / max(1, (s["pos"] + s["neg"]))
        score = s["mentions"] * (1 + pos_ratio - neg_ratio)
        '''
        rows.append({
            "title": title,
            "mentions": s["mentions"],
            "pos": s["pos"],
            "neg": s["neg"],
            "score": round(score, 3),
            "sample_comments": " / ".join(s["samples"])
        })
        '''
        rows.append({
            "title": title,
            "mentions": s["mentions"],
            "pos": s["pos"],
            "neg": s["neg"],
            "score": round(score, 3),
        })

    out = pd.DataFrame(rows).sort_values(["score", "mentions"], ascending=False)

    '''
    out_path = "ranking_2025_fall_from_comments.txt"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("2025 秋番｜YT 留言評價排行（熱度×評價）\n")
        f.write("="*60 + "\n\n")

        # ===== 有資料可排序區 =====
        if not out.empty:
            f.write("【有留言作品排行】\n\n")
            for i, r in enumerate(out.to_dict("records"), 1):
                f.write(f"{i:02d}. {r['title']}  |  score={r['score']}  |  mentions={r['mentions']}  |  pos={r['pos']}  |  neg={r['neg']}\n")
                f.write(f"    代表留言: {r['sample_comments']}\n\n")
        else:
            f.write("⚠️ 尚無作品被留言命中\n\n")

        # ===== 分隔線 =====
        f.write("\n" + "~"*70 + "\n")
        f.write("【完全沒有被留言提及（無法排序）】\n\n")

        # ===== 沒被提及區 =====
        all_titles = set(TITLE_ALIASES.keys())
        no_data_titles = sorted(all_titles - mentioned_titles)

        if no_data_titles:
            for t in no_data_titles:
                f.write(f"- {t}\n")
        else:
            f.write("（所有作品都有留言）\n")

    print("Saved:", out_path)
    '''
    out_path = "ranking_2025_fall_from_comments.txt"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("2025 秋番｜YT 留言評價排行（熱度×評價）\n")
        f.write("="*60 + "\n\n")

        # ===== 有資料可排序區 =====
        if not out.empty:
            f.write("【有留言作品排行】\n\n")
            for i, r in enumerate(out.to_dict("records"), 1):
                title = r["title"]
                s = stats[title]
                f.write(f"{i:02d}. {title}  |  score={r['score']}  |  mentions={r['mentions']}  |  pos={r['pos']}  |  neg={r['neg']}\n")
                f.write("    全部留言:\n")
                for j, c in enumerate(s["comments"], 1):
                    # 避免換行把排版弄爆：把留言中的換行縮成空白
                    c1 = " ".join(str(c).splitlines()).strip()
                    f.write(f"      ({j:04d}) {c1}\n")
                f.write("\n")
        else:
            f.write("⚠️ 尚無作品被留言命中\n\n")

        # ===== 分隔線 =====
        f.write("\n" + "~"*70 + "\n")
        f.write("【完全沒有被留言提及（無法排序）】\n\n")

        all_titles = set(TITLE_ALIASES.keys())
        no_data_titles = sorted(all_titles - set(out["title"].tolist()) if not out.empty else all_titles)

        if no_data_titles:
            for t in no_data_titles:
                f.write(f"- {t}\n")
        else:
            f.write("（所有作品都有留言）\n")
            
if __name__ == "__main__":
    main()
