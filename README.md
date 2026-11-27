# ストックのおすそわけ屋さん（リンクページ）

プロフィールのリンク先ページです。GitHub Pages（GitHub Actions デプロイ）で公開します。ビルド作業はありません。

## 商品の編集

`public/products.json` を編集して main に push すると、自動で公開されます。

- 表示順は配列の順です。No. は各商品の `no`（固定番号）で、一度使った番号は変えず、新しい商品には次の番号を付けます。期限切れで消えても他の番号はずれません。
- `active: false` にすると非表示になります。
- `until` に日付（YYYY-MM-DD）を入れると、その日の翌日から自動で非表示になります（日本時間）。
- `label` は「期間限定」などの小さな表示です（なければ `null`）。
- URL は `https://www.amazon.co.jp/...` で、`tag=stockosusowak-22` を必ず含めます。
- 価格・星評価・レビュー・商品画像は載せません（Amazonアソシエイトの規約）。

デプロイ前に `scripts/check_products.py` が自動で検証します。手元でも `python3 scripts/check_products.py` で確認できます。

## 予約投稿

`publisher/` と `.github/workflows/publish.yml` は Instagram への予約投稿用です。設定は `SETUP.md` を参照してください。

テスト: `cd publisher && python3 -m unittest`
