# AI News Daily Collector

生成AI・LLM関連のニュース記事を毎日自動収集するスクリプトです。

## 収集元

| ソース | 取得方法 | APIキー |
|--------|----------|---------|
| Hacker News | 公式 Firebase API | 不要 |
| Zenn | トピック別 RSS フィード | 不要 |
| Qiita | REST API v2（タグ検索） | 不要（レート制限あり） |

## セットアップ

```bash
pip install -r requirements.txt
```

Python 3.9 以上を推奨します。

## 実行方法

```bash
python daily_collect.py
```

実行すると以下が行われます。

1. HackerNews のトップ／新着ストーリー最大 100 件を並列取得
2. Zenn の AI 関連トピックフィードを取得
3. Qiita の AI 関連タグ記事を取得
4. キーワードフィルタリングと URL 重複排除
5. `data/YYYY-MM-DD.json` として保存
6. `git add → commit → push` を自動実行

## フィルタリングキーワード

```
生成AI / LLM / ChatGPT / Claude / Gemini / RAG /
AIエージェント / プロンプト / ファインチューニング / GPT / 機械学習
(英語バリアントも含む: generative ai / large language model / fine-tun / ...)
```

## 出力フォーマット

`data/YYYY-MM-DD.json` に記事リストを保存します（新しい順）。

```json
[
  {
    "title": "記事タイトル",
    "url": "https://example.com/article",
    "source": "HackerNews",
    "published_at": "2025-01-01T09:00:00+00:00",
    "summary": "本文冒頭の要約（最大200文字）"
  }
]
```

| フィールド | 説明 |
|-----------|------|
| `title` | 記事タイトル |
| `url` | 記事 URL |
| `source` | 取得元（`HackerNews` / `Zenn` / `Qiita`） |
| `published_at` | 公開日時（ISO 8601、UTC）。取得できない場合は空文字 |
| `summary` | HTML・Markdown を除去した本文冒頭（最大 200 文字）。取得元によっては空の場合あり |

## git push の挙動

スクリプト末尾で以下の git 操作を自動実行します。

```
git add data/YYYY-MM-DD.json
git commit -m "Add daily AI news collection: YYYY-MM-DD"
git push
```

- **ユーザー名・メール**はリポジトリの既存設定（`git config user.name` / `user.email`）を使用します。スクリプト内にハードコードしていません。
- **push 失敗時**（コンフリクト・リモート未設定など）はエラーを標準エラー出力に出力しますが、スクリプト自体は正常終了（exit 0）します。収集済みの JSON ファイルはローカルに残ります。
- **「nothing to commit」**（当日分がすでに存在する場合など）も同様にログ出力のみで継続します。

## 自動実行（Routines / cron）

ローカル環境や CI で毎日実行する場合は以下のいずれかを利用してください。

### Windows タスクスケジューラ

```
プログラム: python
引数: C:\path\to\test-project\daily_collect.py
作業フォルダー: C:\path\to\test-project
```

### cron（Linux / macOS）

```cron
0 8 * * * cd /path/to/test-project && python daily_collect.py >> logs/collect.log 2>&1
```

## エラーハンドリング

各収集元の処理は独立した `try-except` で囲んでいます。  
1 つの収集元が失敗しても他の結果は保存されます。  
エラーは `stderr` に `[HackerNews]` / `[Zenn]` / `[Qiita]` プレフィックス付きで出力されます。
