#!/usr/bin/env python3
"""Daily AI news collector from HackerNews, Zenn, and Qiita."""

import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KEYWORDS = [
    # Japanese
    "生成AI",
    "AIエージェント",
    "プロンプト",
    "ファインチューニング",
    "機械学習",
    # Brand / model names (matched case-insensitively)
    "LLM",
    "ChatGPT",
    "Claude",
    "Gemini",
    "RAG",
    "GPT",
    # English variants (for HackerNews titles)
    "generative ai",
    "large language model",
    "fine-tun",
    "machine learning",
    "ai agent",
    "prompt engineering",
]

HN_MAX_IDS = 100       # Total HN story IDs to consider (split evenly between top/new)
HN_CONCURRENCY = 10    # Parallel HTTP workers for HN item fetches
REQUEST_TIMEOUT = 10   # Seconds

ZENN_FEED_URLS = [
    "https://zenn.dev/topics/llm/feed",
    "https://zenn.dev/topics/chatgpt/feed",
    "https://zenn.dev/topics/generativeai/feed",
    "https://zenn.dev/topics/rag/feed",
    "https://zenn.dev/topics/ai/feed",
    "https://zenn.dev/topics/machinelearning/feed",
]

QIITA_TAGS = [
    "LLM", "ChatGPT", "生成AI", "RAG",
    "機械学習", "Claude", "Gemini", "プロンプト",
]
QIITA_PER_PAGE = 20
QIITA_RATE_LIMIT_SLEEP = 0.5   # Seconds between Qiita API calls (unauthenticated limit)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def matches_keywords(text: str) -> bool:
    """Return True if text contains at least one target keyword (case-insensitive)."""
    lower = text.lower()
    return any(kw.lower() in lower for kw in KEYWORDS)


def clean_html(html: str, max_length: int = 200) -> str:
    """Strip HTML tags and return plain text up to max_length."""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()[:max_length]


def strip_markdown(text: str, max_length: int = 200) -> str:
    """Lightly strip Markdown syntax for use as a plain-text summary."""
    text = re.sub(r"```[\s\S]*?```", "", text)          # fenced code blocks
    text = re.sub(r"`[^`]+`", "", text)                  # inline code
    text = re.sub(r"#+\s*", "", text)                    # headings
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  # links
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)  # bold/italic
    return text.strip()[:max_length]

# ---------------------------------------------------------------------------
# HackerNews
# ---------------------------------------------------------------------------

def _fetch_hn_item(story_id: int, session: requests.Session) -> Optional[dict]:
    """Fetch one HN story and return a normalised article dict, or None."""
    try:
        resp = session.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        item = resp.json()

        if not item or item.get("type") != "story":
            return None

        title = item.get("title", "")
        text  = item.get("text", "")
        url   = item.get("url") or f"https://news.ycombinator.com/item?id={story_id}"

        if not matches_keywords(title + " " + text):
            return None

        published_at = (
            datetime.fromtimestamp(item["time"], tz=timezone.utc).isoformat()
            if item.get("time") else ""
        )

        return {
            "title":        title,
            "url":          url,
            "source":       "HackerNews",
            "published_at": published_at,
            "summary":      clean_html(text) if text else "",
        }
    except Exception as e:
        print(f"  [HN] item {story_id}: {e}", file=sys.stderr)
        return None


def collect_hackernews() -> list[dict]:
    articles: list[dict] = []
    try:
        session = requests.Session()
        session.headers["User-Agent"] = "AI-News-Collector/1.0"

        story_ids: list[int] = []
        half = HN_MAX_IDS // 2
        for endpoint in ("topstories", "newstories"):
            resp = session.get(
                f"https://hacker-news.firebaseio.com/v0/{endpoint}.json",
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            story_ids.extend(resp.json()[:half])

        # Deduplicate while preserving order
        seen: set[int] = set()
        unique_ids = [x for x in story_ids if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]

        with ThreadPoolExecutor(max_workers=HN_CONCURRENCY) as pool:
            futures = {pool.submit(_fetch_hn_item, sid, session): sid for sid in unique_ids}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    articles.append(result)

    except Exception as e:
        print(f"[HackerNews] collection failed: {e}", file=sys.stderr)

    return articles

# ---------------------------------------------------------------------------
# Zenn
# ---------------------------------------------------------------------------

def collect_zenn() -> list[dict]:
    articles: list[dict] = []
    seen_urls: set[str] = set()

    for feed_url in ZENN_FEED_URLS:
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                print(f"  [Zenn] bad feed {feed_url}: {feed.bozo_exception}", file=sys.stderr)
                continue

            for entry in feed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue

                title = entry.get("title", "")
                raw   = entry.get("summary", entry.get("description", ""))

                if not matches_keywords(title + " " + raw):
                    continue

                seen_urls.add(url)

                published_at = ""
                if entry.get("published_parsed"):
                    published_at = datetime(
                        *entry.published_parsed[:6], tzinfo=timezone.utc
                    ).isoformat()

                articles.append({
                    "title":        title,
                    "url":          url,
                    "source":       "Zenn",
                    "published_at": published_at,
                    "summary":      clean_html(raw),
                })

        except Exception as e:
            print(f"  [Zenn] {feed_url}: {e}", file=sys.stderr)

    return articles

# ---------------------------------------------------------------------------
# Qiita
# ---------------------------------------------------------------------------

def collect_qiita() -> list[dict]:
    articles: list[dict] = []
    seen_urls: set[str] = set()
    session = requests.Session()
    session.headers["User-Agent"] = "AI-News-Collector/1.0"

    for tag in QIITA_TAGS:
        try:
            resp = session.get(
                "https://qiita.com/api/v2/items",
                params={"query": f"tag:{tag}", "per_page": QIITA_PER_PAGE, "sort": "created"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            items = resp.json()
            if not isinstance(items, list):
                continue

            for item in items:
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue

                title = item.get("title", "")
                body  = item.get("body", "")

                if not matches_keywords(title + " " + body):
                    continue

                seen_urls.add(url)
                articles.append({
                    "title":        title,
                    "url":          url,
                    "source":       "Qiita",
                    "published_at": item.get("created_at", ""),
                    "summary":      strip_markdown(body),
                })

            time.sleep(QIITA_RATE_LIMIT_SLEEP)

        except Exception as e:
            print(f"  [Qiita] tag '{tag}': {e}", file=sys.stderr)

    return articles

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_results(articles: list[dict], date_str: str) -> Path:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    output_path = data_dir / f"{date_str}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    return output_path

# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def git_push(file_path: Path, date_str: str) -> None:
    """Stage → commit → push the collected JSON. Logs errors but never raises."""
    result = _run_git(["add", str(file_path)])
    if result.returncode != 0:
        print(f"[Git] add failed:\n{result.stderr.strip()}", file=sys.stderr)
        return

    result = _run_git(["commit", "-m", f"Add daily AI news collection: {date_str}"])
    if result.returncode != 0:
        # "nothing to commit" is not a fatal error
        msg = (result.stderr or result.stdout).strip()
        print(f"[Git] commit skipped or failed: {msg}", file=sys.stderr)
        return

    result = _run_git(["push"])
    if result.returncode != 0:
        print(
            f"[Git] push failed (conflict or no remote?): {result.stderr.strip()}",
            file=sys.stderr,
        )
    else:
        print(f"[Git] Pushed {file_path}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"=== AI News Collection: {date_str} ===\n")

    all_articles: list[dict] = []

    print("[1/3] HackerNews ...")
    hn = collect_hackernews()
    print(f"      {len(hn)} articles\n")
    all_articles.extend(hn)

    print("[2/3] Zenn ...")
    zenn = collect_zenn()
    print(f"      {len(zenn)} articles\n")
    all_articles.extend(zenn)

    print("[3/3] Qiita ...")
    qiita = collect_qiita()
    print(f"      {len(qiita)} articles\n")
    all_articles.extend(qiita)

    # Cross-source deduplication by URL, preserving first occurrence
    seen: set[str] = set()
    unique: list[dict] = []
    for a in all_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)

    # Sort newest-first (empty published_at goes to the end)
    unique.sort(key=lambda a: a["published_at"] or "0", reverse=True)

    print(f"Total after dedup: {len(unique)} articles")

    output_path = save_results(unique, date_str)
    print(f"Saved → {output_path}\n")

    git_push(output_path, date_str)
    print("\nDone.")


if __name__ == "__main__":
    main()
