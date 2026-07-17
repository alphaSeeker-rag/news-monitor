#!/usr/bin/env python3
"""
ニュース監視スクリプト
RSS フィードを定期チェックし、指定キーワードが含まれる記事を通知する
英語記事は Claude AI で日本語に翻訳・要約する
"""

import json
import re
import time
import hashlib
import logging
import argparse
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path

import feedparser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "keywords": ["AI", "人工知能", "ChatGPT", "Python"],
    "feeds": [
        "https://www3.nhk.or.jp/rss/news/cat0.xml",
        "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
        "https://www.asahi.com/rss/asahi/newsheadlines.rdf",
        "https://gigazine.net/news/rss_2.0/",
        "https://techcrunch.com/feed/",
        "https://zenn.dev/feed",
    ],
    "interval_seconds": 300,
    "notify_desktop": True,
    "notify_email": False,
    "summarize_english": True,
    "anthropic_api_key": "",
    "email": {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "username": "",
        "password": "",
        "to": ""
    }
}

SEEN_FILE = Path("seen_articles.json")
CONFIG_FILE = Path("config.json")
REPORT_FILE = Path("report.html")
LOG_FILE = Path("articles.json")

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>DC × SEMICON INTEL — ニュース監視レポート</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Share+Tech+Mono&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #030818;
    --cyan: #5fd8ff;
    --blue: #2e7bff;
    --ink: #d7e9ff;
    --dim: #7fa0cc;
    --line: rgba(95, 178, 255, .30);
    --panel: rgba(10, 24, 56, .58);
    --glow: 0 0 8px rgba(95, 216, 255, .55);
    --mono: "Share Tech Mono", Consolas, monospace;
    --disp: "Orbitron", "Share Tech Mono", sans-serif;
    --sans: "Noto Sans JP", -apple-system, "Segoe UI", sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: var(--sans); color: var(--ink); line-height: 1.6;
    background:
      radial-gradient(ellipse at 20% -10%, rgba(46,123,255,.28), transparent 55%),
      radial-gradient(ellipse at 85% 110%, rgba(46,123,255,.22), transparent 55%),
      linear-gradient(160deg, #050c24 0%, #030818 45%, #071230 100%);
    background-attachment: fixed; min-height: 100vh;
  }}
  /* HUD grid overlay */
  body::before {{
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background:
      linear-gradient(rgba(95,178,255,.05) 1px, transparent 1px),
      linear-gradient(90deg, rgba(95,178,255,.05) 1px, transparent 1px);
    background-size: 44px 44px;
  }}
  /* scanline sweep */
  body::after {{
    content: ""; position: fixed; left: 0; right: 0; height: 120px; z-index: 0;
    background: linear-gradient(180deg, transparent, rgba(95,216,255,.05), transparent);
    animation: sweep 9s linear infinite; pointer-events: none;
  }}
  @keyframes sweep {{ 0% {{ top: -120px; }} 100% {{ top: 100vh; }} }}
  header, .filters, main, footer {{ position: relative; z-index: 1; }}

  /* ===== HUD Masthead ===== */
  header {{ padding: 30px 32px 20px; border-bottom: 1px solid var(--line);
            background: linear-gradient(180deg, rgba(10,24,56,.85), rgba(10,24,56,.2)); }}
  .mast {{ max-width: 1000px; margin: 0 auto; }}
  .sysline {{ font-family: var(--mono); font-size: .68rem; letter-spacing: .3em;
              color: var(--cyan); text-transform: uppercase;
              display: flex; align-items: center; gap: 12px; }}
  .sysline::before {{ content: ""; width: 9px; height: 9px; background: var(--cyan);
              box-shadow: var(--glow); border-radius: 50%; flex-shrink: 0;
              animation: blink 2s infinite; }}
  @keyframes blink {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: .25; }} }}
  header h1 {{ font-family: var(--disp); font-size: 2.1rem; font-weight: 900;
               letter-spacing: .12em; color: #fff; margin-top: 12px;
               text-shadow: 0 0 14px rgba(95,216,255,.65), 0 0 40px rgba(46,123,255,.35); }}
  header h1 .jp {{ display: block; font-family: var(--sans); font-size: .82rem; font-weight: 500;
               letter-spacing: .28em; color: var(--dim); margin-top: 8px; text-shadow: none; }}
  .hud-meta {{ margin-top: 14px; font-family: var(--mono); font-size: .7rem; color: var(--dim);
               display: flex; gap: 22px; flex-wrap: wrap; letter-spacing: .1em; }}
  .hud-meta b {{ color: var(--cyan); font-weight: 400; }}

  /* ===== Filters ===== */
  .filters {{ position: sticky; top: 0; z-index: 5; padding: 12px 32px;
              display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
              background: rgba(4, 10, 30, .88); backdrop-filter: blur(8px);
              border-bottom: 1px solid var(--line); }}
  .filters span {{ font-family: var(--mono); font-size: .68rem; letter-spacing: .22em;
              text-transform: uppercase; color: var(--cyan); margin-right: 6px; }}
  .btn {{ font-family: var(--mono); font-size: .74rem; padding: 4px 13px;
          background: transparent; color: var(--dim); border: 1px solid var(--line);
          cursor: pointer; transition: all .15s;
          clip-path: polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%, 0 8px); }}
  .btn:hover {{ color: var(--cyan); border-color: var(--cyan); box-shadow: var(--glow); }}
  .btn.active {{ background: rgba(95,216,255,.14); color: var(--cyan); border-color: var(--cyan);
                 box-shadow: var(--glow), inset 0 0 12px rgba(95,216,255,.12); }}

  /* ===== Layout ===== */
  main {{ max-width: 960px; margin: 34px auto 70px; padding: 0 20px; }}
  .section-label {{ font-family: var(--disp); font-size: .95rem; letter-spacing: .28em;
      color: var(--cyan); margin: 36px 0 14px; display: flex; align-items: center; gap: 14px;
      text-shadow: var(--glow); }}
  .section-label::before {{ content: "◆"; font-size: .7rem; }}
  .section-label::after {{ content: ""; flex: 1; height: 1px;
      background: linear-gradient(90deg, var(--line), transparent); }}

  /* ===== Article panel ===== */
  .card {{ position: relative; background: var(--panel); border: 1px solid var(--line);
           padding: 18px 22px; margin-bottom: 14px; backdrop-filter: blur(3px);
           transition: border-color .15s, box-shadow .15s; }}
  .card::before, .card::after {{ content: ""; position: absolute; width: 14px; height: 14px;
           border: 1.5px solid var(--cyan); pointer-events: none; opacity: .8; }}
  .card::before {{ top: -1px; left: -1px; border-right: none; border-bottom: none; }}
  .card::after {{ bottom: -1px; right: -1px; border-left: none; border-top: none; }}
  .card:hover {{ border-color: rgba(95,216,255,.7); box-shadow: 0 0 18px rgba(46,123,255,.25); }}
  .card-title a {{ color: #eaf4ff; font-size: 1.04rem; font-weight: 700;
                   text-decoration: none; line-height: 1.55; transition: color .15s; }}
  .card-title a:hover {{ color: var(--cyan); text-shadow: var(--glow); }}
  .card-meta {{ display: flex; gap: 12px; margin-top: 10px; flex-wrap: wrap; align-items: center; }}
  .kw {{ font-family: var(--mono); font-size: .66rem; letter-spacing: .06em; padding: 2px 9px;
         color: var(--cyan); border: 1px solid rgba(95,216,255,.5);
         background: rgba(95,216,255,.07); text-transform: uppercase; }}
  .source {{ font-family: var(--mono); font-size: .7rem; color: var(--ink); }}
  .date {{ font-family: var(--mono); font-size: .68rem; color: var(--dim); }}

  /* ===== AI summary panel ===== */
  .ai-box {{ margin-top: 14px; border: 1px solid rgba(95,178,255,.25);
             border-left: 3px solid var(--cyan); background: rgba(5,14,38,.6); padding: 14px 18px; }}
  .ai-label {{ font-family: var(--mono); font-size: .62rem; letter-spacing: .26em;
             color: var(--cyan); text-transform: uppercase; margin-bottom: 8px; }}
  .ai-title-ja {{ font-size: .98rem; font-weight: 700; color: #eaf4ff; margin-bottom: 8px; }}
  .ai-summary {{ font-size: .86rem; color: var(--ink); line-height: 1.8; margin-bottom: 8px; }}
  .ai-insights {{ list-style: none; padding: 0; }}
  .ai-insights li {{ font-size: .84rem; color: var(--dim); padding-left: 20px;
                     position: relative; margin-bottom: 5px; line-height: 1.65; }}
  .ai-insights li::before {{ content: "▸"; position: absolute; left: 0; color: var(--cyan); }}

  .empty {{ text-align: center; padding: 70px 0; color: var(--dim); font-family: var(--mono); }}
  footer {{ text-align: center; padding: 26px; border-top: 1px solid var(--line);
            font-family: var(--mono); font-size: .66rem; letter-spacing: .22em;
            color: var(--dim); text-transform: uppercase; }}
  @media (max-width: 640px) {{
    header h1 {{ font-size: 1.3rem; letter-spacing: .08em; }}
    header h1 .jp {{ letter-spacing: .14em; }}
    main {{ padding: 0 14px; }}
  }}
</style>
</head>
<body>
<header>
  <div class="mast">
    <div class="sysline">System Online // Datacenter · Semiconductor · AI Policy</div>
    <h1>DC × SEMICON INTEL
      <span class="jp">データセンター・半導体・AI政策 監視レポート</span>
    </h1>
    <div class="hud-meta">
      <span>UPDATED <b>{updated}</b></span>
      <span>ARTICLES <b>{total}</b></span>
      <span>AUTO-REFRESH <b>60S</b></span>
    </div>
  </div>
</header>
<div class="filters">
  <span>Filter</span>
  <button class="btn active" onclick="filter(this,'')">ALL</button>
  {kw_buttons}
</div>
<main id="main">
{cards}
</main>
<footer>
  Self-Adaptive Monitoring System // Updated {updated}
</footer>
<script>
  function filter(btn, kw) {{
    document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.card').forEach(c => {{
      c.style.display = (!kw || c.dataset.kw.includes(kw)) ? '' : 'none';
    }});
    document.querySelectorAll('.section-label').forEach(s => {{
      let n = s.nextElementSibling, vis = 0;
      while (n && n.classList.contains('card')) {{
        if (n.style.display !== 'none') vis++;
        n = n.nextElementSibling;
      }}
      s.style.display = vis ? '' : 'none';
    }});
  }}
</script>
</body>
</html>
"""


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    CONFIG_FILE.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.info("config.json を生成しました。編集してから再実行してください。")
    return DEFAULT_CONFIG


def load_seen() -> set:
    if SEEN_FILE.exists():
        with SEEN_FILE.open(encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set) -> None:
    with SEEN_FILE.open("w", encoding="utf-8") as f:
        json.dump(list(seen), f)


def load_log() -> list:
    if LOG_FILE.exists():
        with LOG_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    return []


def save_log(articles: list) -> None:
    with LOG_FILE.open("w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def article_id(entry) -> str:
    key = getattr(entry, "id", None) or getattr(entry, "link", "") or entry.title
    return hashlib.sha1(key.encode()).hexdigest()


def matches_keywords(entry, keywords: list[str]) -> list[str]:
    text = " ".join([
        getattr(entry, "title", ""),
        getattr(entry, "summary", ""),
    ]).lower()
    return [kw for kw in keywords if kw.lower() in text]


def is_english(text: str) -> bool:
    if not text:
        return False
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    all_letters = sum(1 for c in text if c.isalpha())
    return all_letters > 5 and ascii_letters / all_letters > 0.75


def get_anthropic_client(config: dict):
    import os
    api_key = config.get("anthropic_api_key", "").strip() or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        log.warning("anthropic パッケージ未インストール: py -3 -m pip install anthropic")
        return None


def ai_summarize(title: str, body: str, client) -> dict | None:
    content = f"Title: {title}"
    if body:
        content += f"\n\nExcerpt: {body[:800]}"
    prompt = (
        "以下の英語記事を日本語に翻訳・要約し、重要インサイトを箇条書きでまとめてください。\n\n"
        f"{content}\n\n"
        "次のJSON形式のみで回答してください（前後に余分なテキスト不要）:\n"
        '{"title_ja": "日本語タイトル", "summary": "3文以内の日本語要約", '
        '"insights": ["インサイト1", "インサイト2", "インサイト3"]}'
    )
    try:
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in resp.content if hasattr(b, "text")), "")
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        log.debug("AI要約エラー: %s", e)
    return None


def build_report(articles: list, keywords: list[str]) -> None:
    if not articles:
        cards_html = '<p class="empty">まだ記事がありません。</p>'
        kw_buttons = ""
    else:
        kw_buttons = " ".join(
            f'<button class="btn" onclick="filter(this,\'{escape(kw)}\')">{escape(kw)}</button>'
            for kw in keywords
        )
        grouped: dict[str, list] = {}
        for a in articles:
            day = a.get("detected_at", "")[:10] or "不明"
            grouped.setdefault(day, []).append(a)

        sections = []
        for day in sorted(grouped.keys(), reverse=True):
            sections.append(f'<div class="section-label">{escape(day)}</div>')
            for a in grouped[day]:
                kws_data = "|".join(a["keywords"])
                kws_html = " ".join(
                    f'<span class="kw">{escape(k)}</span>' for k in a["keywords"]
                )
                ai = a.get("ai_summary")
                if ai:
                    insights_html = "".join(
                        f'<li>{escape(ins)}</li>' for ins in ai.get("insights", [])
                    )
                    ai_block = (
                        f'<div class="ai-box">'
                        f'<div class="ai-label">AI 日本語要約</div>'
                        f'<div class="ai-title-ja">{escape(ai.get("title_ja",""))}</div>'
                        f'<p class="ai-summary">{escape(ai.get("summary",""))}</p>'
                        f'<ul class="ai-insights">{insights_html}</ul>'
                        f'</div>'
                    )
                else:
                    ai_block = ""

                sections.append(
                    f'<div class="card" data-kw="{escape(kws_data)}">'
                    f'<div class="card-title"><a href="{escape(a["link"])}" target="_blank">{escape(a["title"])}</a></div>'
                    f'<div class="card-meta">'
                    f'{kws_html}'
                    f'<span class="source">{escape(a["source"])}</span>'
                    f'<span class="date">{escape(a.get("published",""))}</span>'
                    f'</div>'
                    f'{ai_block}'
                    f'</div>'
                )
        cards_html = "\n".join(sections)

    html = HTML_TEMPLATE.format(
        updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total=len(articles),
        kw_buttons=kw_buttons,
        cards=cards_html,
    )
    REPORT_FILE.write_text(html, encoding="utf-8")


def notify_desktop(title: str, message: str, url: str = "") -> None:
    try:
        from winotify import Notification
        toast = Notification(
            app_id="ニュース監視",
            title=title,
            msg=message[:200],
            duration="short",
            launch=url,
        )
        toast.show()
        return
    except ImportError:
        pass
    except Exception as e:
        log.debug("winotify 通知エラー: %s", e)

    try:
        from plyer import notification
        notification.notify(title=title, message=message[:200], timeout=10)
    except Exception:
        pass


def notify_email(subject: str, body: str, cfg: dict) -> None:
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["username"]
    msg["To"] = cfg["to"]
    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as s:
        s.starttls()
        s.login(cfg["username"], cfg["password"])
        s.send_message(msg)


def check_feed(url: str, keywords: list[str], seen: set, config: dict,
               ai_client=None) -> list[dict]:
    found = []
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "news-monitor/1.0"})
        for entry in feed.entries:
            aid = article_id(entry)
            if aid in seen:
                continue
            seen.add(aid)
            hit_kws = matches_keywords(entry, keywords)
            if not hit_kws:
                continue

            title = getattr(entry, "title", "(タイトルなし)")
            body = getattr(entry, "summary", "")
            article = {
                "title": title,
                "link": getattr(entry, "link", ""),
                "published": getattr(entry, "published", ""),
                "keywords": hit_kws,
                "source": feed.feed.get("title", url),
                "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ai_summary": None,
            }

            if ai_client and config.get("summarize_english") and is_english(title):
                log.info("AI要約中: %s", title[:60])
                ai = ai_summarize(title, body, ai_client)
                if ai:
                    article["ai_summary"] = ai
                    log.info("  → %s", ai.get("title_ja", ""))

            found.append(article)
            log.info("【ヒット】%s | キーワード: %s", title, ", ".join(hit_kws))

            if config.get("notify_desktop"):
                display_title = article.get("ai_summary", {}) and article["ai_summary"].get("title_ja") or title
                notify_desktop(
                    f"[{', '.join(hit_kws)}] {article['source']}",
                    display_title,
                    article["link"],
                )
            if config.get("notify_email") and config.get("email", {}).get("to"):
                try:
                    notify_email(
                        f"ニュースアラート: {', '.join(hit_kws)}",
                        f"{title}\n{article['link']}",
                        config["email"]
                    )
                except Exception as e:
                    log.warning("メール送信失敗: %s", e)

    except Exception as e:
        log.warning("フィード取得エラー (%s): %s", url, e)
    return found


def run(config: dict, open_browser: bool = False) -> None:
    keywords = config["keywords"]
    feeds = config["feeds"]
    interval = config.get("interval_seconds", 300)
    ai_client = get_anthropic_client(config)

    if ai_client:
        log.info("Claude AI 要約: 有効")
    elif config.get("summarize_english"):
        log.info("Claude AI 要約: anthropic_api_key が未設定のため無効")

    log.info("監視開始 | キーワード: %s | フィード数: %d | 間隔: %ds",
             ", ".join(keywords), len(feeds), interval)

    seen = load_seen()
    all_articles = load_log()
    cycle = 0

    while True:
        cycle += 1
        log.info("チェック #%d (%s)", cycle, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        new_articles = []
        for url in feeds:
            new_articles.extend(check_feed(url, keywords, seen, config, ai_client))

        if new_articles:
            all_articles = new_articles + all_articles
            save_log(all_articles)
            build_report(all_articles, keywords)
            log.info("%d件の新着記事 → report.html を更新しました", len(new_articles))
            if open_browser or cycle == 1:
                webbrowser.open(REPORT_FILE.resolve().as_uri())
                open_browser = False
        else:
            log.info("新着ヒットなし")

        save_seen(seen)
        log.info("%d秒後に次回チェック...", interval)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="ニュース監視スクリプト")
    parser.add_argument("--config", help="設定ファイルのパス (デフォルト: config.json)")
    parser.add_argument("--once", action="store_true", help="1回だけ実行して終了")
    parser.add_argument("--keywords", nargs="+", help="監視キーワード (設定ファイルを上書き)")
    parser.add_argument("--report", action="store_true", help="レポートだけ開く")
    args = parser.parse_args()

    global CONFIG_FILE
    if args.config:
        CONFIG_FILE = Path(args.config)

    config = load_config()
    if args.keywords:
        config["keywords"] = args.keywords

    if args.report:
        all_articles = load_log()
        build_report(all_articles, config["keywords"])
        webbrowser.open(REPORT_FILE.resolve().as_uri())
        return

    ai_client = get_anthropic_client(config)

    if args.once:
        seen = load_seen()
        all_articles = load_log()
        new_articles = []
        for url in config["feeds"]:
            new_articles.extend(check_feed(url, config["keywords"], seen, config, ai_client))
        if new_articles:
            all_articles = new_articles + all_articles
            save_log(all_articles)
        build_report(all_articles, config["keywords"])
        save_seen(seen)
        log.info("report.html を生成しました (%d件)", len(all_articles))
        webbrowser.open(REPORT_FILE.resolve().as_uri())
    else:
        run(config, open_browser=True)


if __name__ == "__main__":
    main()
