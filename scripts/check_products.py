#!/usr/bin/env python3
"""public/products.json の検証（標準ライブラリのみ）。

失敗条件:
  - url が https://www.amazon.co.jp/ で始まらない / tag=stockosusowak-22 が無い
  - 必須項目の欠落・型の誤り
  - id の重複
  - 価格らしい文言（円, ¥, $ など）や禁止文字列を含む
"""
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TAG = "stockosusowak-22"
REQUIRED = ["no", "id", "name", "description", "url", "label", "until", "active"]
# 禁止文字列（自己検出を避けるため分割して記述）
FORBIDDEN = ["na" + "keno", "なけ" + "の"]
PRICE_PATTERNS = [r"円", r"[¥￥$＄]", r"税込", r"\byen\b", r"\bJPY\b", r"[★☆]", r"レビュー", r"最安"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def check(data):
    errors = []
    if not isinstance(data, dict):
        return ["トップレベルはオブジェクトにしてください"]
    if not valid_date(data.get("updated")):
        errors.append("updated は YYYY-MM-DD 形式")
    products = data.get("products")
    if not isinstance(products, list):
        return errors + ["products は配列にしてください"]

    seen = set()
    seen_no = set()
    for i, p in enumerate(products, 1):
        where = f"products[{i}]"
        if not isinstance(p, dict):
            errors.append(f"{where}: オブジェクトではありません")
            continue
        for k in REQUIRED:
            if k not in p:
                errors.append(f"{where}: 必須項目 {k} がありません")
        for k in ("id", "name", "description", "url"):
            if k in p and (not isinstance(p[k], str) or not p[k].strip()):
                errors.append(f"{where}: {k} は空でない文字列")
        if "active" in p and not isinstance(p["active"], bool):
            errors.append(f"{where}: active は true/false")
        if p.get("label") is not None and not isinstance(p.get("label"), str):
            errors.append(f"{where}: label は文字列か null")
        if p.get("until") is not None and not valid_date(p.get("until")):
            errors.append(f"{where}: until は YYYY-MM-DD か null")
        no = p.get("no")
        if not isinstance(no, int) or isinstance(no, bool) or no < 1:
            errors.append(f"{where}: no は1以上の整数（一度使った番号は変えない）")
        elif no in seen_no:
            errors.append(f"{where}: no が重複しています ({no})")
        else:
            seen_no.add(no)
        pid = p.get("id")
        if isinstance(pid, str):
            if pid in seen:
                errors.append(f"{where}: id が重複しています ({pid})")
            seen.add(pid)
        desc = p.get("description")
        if isinstance(desc, str) and len(desc) > 60:
            errors.append(f"{where}: description が長すぎます（60文字まで）")

        url = p.get("url")
        if isinstance(url, str):
            if not url.startswith("https://www.amazon.co.jp/"):
                errors.append(f"{where}: url は https://www.amazon.co.jp/ で始めてください")
            elif TAG not in parse_qs(urlparse(url).query).get("tag", []):
                errors.append(f"{where}: url に tag={TAG} がありません")

        for k, v in p.items():
            if k == "url" or not isinstance(v, str):
                continue
            for pat in PRICE_PATTERNS:
                if re.search(pat, v, re.IGNORECASE):
                    errors.append(f"{where}: {k} に価格・評価らしい文言があります ({pat})")
        blob = json.dumps(p, ensure_ascii=False).lower()
        for bad in FORBIDDEN:
            if bad.lower() in blob:
                errors.append(f"{where}: 禁止文字列を含んでいます")
    return errors


def main(argv):
    default = Path(__file__).resolve().parent.parent / "public" / "products.json"
    path = Path(argv[1]) if len(argv) > 1 else default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"NG: 読み込めません: {e}")
        return 1
    errors = check(data)
    if errors:
        print("NG: products.json に問題があります")
        for e in errors:
            print(" -", e)
        return 1
    print(f"OK: {len(data['products'])} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
