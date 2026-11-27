# セットアップ手順

GitHub の組織 `stock-osusowake` に、次の2つのリポジトリを作ります。

- 公開: `stock-osusowake/stock-osusowake.github.io`（`site/` の中身をリポジトリ直下に置く）
- 非公開: `stock-osusowake/post-queue`（`queue/` の中身をリポジトリ直下に置く）

## 1. GitHub Pages

公開リポジトリの Settings > Pages > Build and deployment > Source を **GitHub Actions** にします。

## 2. Secrets（公開リポジトリ: Settings > Secrets and variables > Actions）

| 名前 | 内容 |
| --- | --- |
| `IG_ACCESS_TOKEN` | Instagram API with Unified Login のシステムユーザーアクセストークン（期限なし。Meta のアプリダッシュボード > ユースケース > Instagram API > API setup with Unified login の「トークンを生成」で発行） |
| `IG_USER_ID` | Instagram のプロアカウントID（数字。同じ画面のアカウント一覧に表示される） |
| `BOT_PAT` | Fine-grained personal access token（下記） |

### BOT_PAT の作り方

- Resource owner: `stock-osusowake`
- Repository access: 2つのリポジトリ（`stock-osusowake.github.io` と `post-queue`）
- Permissions（Repository）:
  - `post-queue`: Contents = Read and write、Issues = Read and write
  - `stock-osusowake.github.io`: Actions = Read and write（定期実行が60日で止まらないようにするため）

組織側で fine-grained PAT が制限されている場合は、組織の設定で許可してください。

## 3. Variables（公開リポジトリ: 同じ画面の Variables タブ）

| 名前 | 内容 |
| --- | --- |
| `OWNER_LOGIN` | 失敗通知を割り当てる GitHub ユーザー名（空なら割り当てなし） |

失敗通知のIssueは、非公開リポジトリ `post-queue` に作られます（担当者名が公開されないようにするため）。通知メールを受け取るには、`post-queue` を Watch するか、担当者として割り当てられる設定にしてください。

## 4. 動作確認

1. 公開リポジトリの Actions から `deploy` を実行し、ページが表示されることを確認します。
2. `publish` を `dry_run` を有効にして手動実行します（Meta には送信されません）。
3. 本番の投稿は、`queue.json` に承認済みの投稿がある日の 20:35 / 20:45（日本時間）から動きます。再試行は 21:10 / 21:40 / 22:30 / 23:20 です。

## 5. 注意

- 公開リポジトリには動画を置きません。投稿のたびに一時的な公開URLで動画を配信し、投稿後にページを動画なしで再デプロイします。
- トークンやPATをログやIssueに書かないでください。
