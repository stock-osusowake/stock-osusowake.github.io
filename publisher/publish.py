#!/usr/bin/env python3
"""Instagram リール予約投稿（Instagram API with Instagram Login）。標準ライブラリのみ。

使い方:
  python publisher/publish.py --mode select  --queue-dir queue-checkout
  python publisher/publish.py --mode publish --queue-dir queue-checkout --video-url https://.../m/xxxx.mp4

環境変数: IG_ACCESS_TOKEN, IG_USER_ID, VIDEO_URL, DRY_RUN=1,
          GITHUB_OUTPUT, GITHUB_STEP_SUMMARY
トークン類は絶対に出力しない。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone, time as dtime

API_VERSION = "v26.0"
GRAPH = f"https://graph.instagram.com/{API_VERSION}"
JST = timezone(timedelta(hours=9))
PUBLISH_AT = dtime(21, 0)
MAX_ATTEMPTS = 3
POLL_INTERVAL = 45          # 秒（30〜60秒）
POLL_TIMEOUT = 600          # 秒
URL_WAIT_TIMEOUT = 600
URL_WAIT_INTERVAL = 15


class PublishError(Exception):
    pass


def log(msg):
    print(msg, flush=True)


# ---------- 時刻 ----------

def now_jst():
    return datetime.now(JST)


def parse_meta_timestamp(s):
    s = s.replace("Z", "+00:00")
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    return datetime.fromisoformat(s)


# ---------- キュー ----------

def load_queue(queue_dir):
    with open(os.path.join(queue_dir, "queue.json"), encoding="utf-8") as f:
        return json.load(f)


def save_queue(queue_dir, queue):
    path = os.path.join(queue_dir, "queue.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def select_post(queue, today):
    """publish_date == today かつ status == approved の最初の1件。"""
    for p in queue.get("posts", []):
        if p.get("status") == "approved" and p.get("publish_date") == today.isoformat():
            return p
    return None


def stale_posts(queue, today):
    return [p for p in queue.get("posts", [])
            if p.get("status") == "approved" and p.get("publish_date", "") < today.isoformat()]


def mark_published(post, media_id, permalink, now):
    post["status"] = "published"
    post["published_at"] = now.isoformat(timespec="seconds")
    post["media_id"] = media_id
    post["permalink"] = permalink
    post["attempts"] = int(post.get("attempts") or 0) + 1
    post["last_error"] = None


def mark_failure(post, error):
    post["attempts"] = int(post.get("attempts") or 0) + 1
    post["last_error"] = str(error)[:300]
    if post["attempts"] >= MAX_ATTEMPTS:
        post["status"] = "failed"
    return post["status"]


# ---------- HTTP ----------

def http_request(method, url, headers=None, data=None, timeout=60):
    """(status, json本文(dict), ヘッダ(小文字dict)) を返す。"""
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, (b"" if method == "HEAD" else r.read())
            hdrs = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        status = e.code
        raw = b"" if method == "HEAD" else e.read()
        hdrs = {k.lower(): v for k, v in e.headers.items()}
    except urllib.error.URLError as e:
        raise PublishError(f"network error: {e.reason}")
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        parsed = {}
    return status, parsed, hdrs


class DryRunRequester:
    """DRY_RUN 用。Meta へは一切アクセスせず、応答を模擬する。"""

    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers=None, data=None, timeout=60):
        self.calls.append((method, url))
        if method == "POST" and url.endswith("/media_publish"):
            return 200, {"id": "dry-media-1"}, {}
        if method == "POST":
            return 200, {"id": "dry-container-1"}, {}
        if "dry-container-1" in url:
            return 200, {"status_code": "FINISHED"}, {}
        if "dry-media-1" in url:
            return 200, {"permalink": "https://www.instagram.com/reel/DRYRUN/",
                         "timestamp": now_jst().strftime("%Y-%m-%dT%H:%M:%S%z")}, {}
        return 200, {"data": []}, {}


# ---------- Meta クライアント ----------

class MetaClient:
    def __init__(self, token, user_id, requester=http_request, sleep=time.sleep, logger=log):
        self.token = token
        self.user_id = user_id
        self.requester = requester
        self.sleep = sleep
        self.log = logger

    def _clean(self, text):
        text = str(text)
        if self.token:
            text = text.replace(self.token, "***")
        return text[:200]

    def _call(self, method, path, params=None):
        url = f"{GRAPH}/{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if method == "GET" and params:
            url += "?" + urllib.parse.urlencode(params)
        elif method == "POST":
            data = params or {}
        status, body, _ = self.requester(method, url, headers, data)
        if status >= 400 or (isinstance(body, dict) and "error" in body):
            msg = ""
            if isinstance(body, dict):
                msg = (body.get("error") or {}).get("message", "")
            raise PublishError(self._clean(f"Meta API error {status}: {msg}"))
        return body

    def create_container(self, video_url, caption):
        body = self._call("POST", f"{self.user_id}/media", {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "is_ai_generated": "true",
        })
        return body["id"]

    def wait_container(self, container_id, interval=POLL_INTERVAL, timeout=POLL_TIMEOUT):
        waited = 0
        while True:
            body = self._call("GET", container_id, {"fields": "status_code"})
            code = body.get("status_code")
            self.log(f"container status: {code}")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED", "PUBLISHED"):
                raise PublishError(f"container status {code}")
            if waited >= timeout:
                raise PublishError("container processing timeout")
            self.sleep(interval)
            waited += interval

    def publish(self, container_id):
        return self._call("POST", f"{self.user_id}/media_publish", {"creation_id": container_id})["id"]

    def media_info(self, media_id):
        return self._call("GET", media_id, {"fields": "permalink,timestamp"})

    def recent_media(self):
        body = self._call("GET", f"{self.user_id}/media", {"fields": "id,caption,timestamp", "limit": "10"})
        return body.get("data", [])


def find_duplicate(recent, caption, today):
    """同一キャプションで、今日(JST)公開済みのメディアを探す。"""
    for m in recent:
        if m.get("caption") != caption or not m.get("timestamp"):
            continue
        try:
            ts = parse_meta_timestamp(m["timestamp"])
        except ValueError:
            continue
        if ts.astimezone(JST).date() == today:
            return m
    return None


def wait_for_public(url, size, requester=http_request, sleep=time.sleep,
                    timeout=URL_WAIT_TIMEOUT, interval=URL_WAIT_INTERVAL):
    """公開URLが200かつ Content-Length 一致になるまで待つ（認証ヘッダは送らない）。"""
    waited = 0
    while True:
        try:
            status, _, hdrs = requester("HEAD", url, {}, None)
        except PublishError:
            status, hdrs = 0, {}
        if status == 200 and str(hdrs.get("content-length")) == str(size):
            return
        if waited >= timeout:
            raise PublishError(f"public video url not ready (status {status})")
        sleep(interval)
        waited += interval


def wait_until(target, now_fn, sleep):
    while True:
        remaining = (target - now_fn()).total_seconds()
        if remaining <= 0:
            return
        sleep(min(30, remaining))


# ---------- git ----------

def git(queue_dir, *args, check=True):
    return subprocess.run(["git", "-C", queue_dir, *args], check=check,
                          capture_output=True, text=True)


def commit_and_push(queue_dir, message, push):
    git(queue_dir, "add", "-A", "queue.json", "videos")
    if git(queue_dir, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    git(queue_dir, "commit", "-q", "-m", message)
    if not push:
        return
    if git(queue_dir, "push", "-q", check=False).returncode != 0:
        git(queue_dir, "pull", "--rebase", "-q")
        git(queue_dir, "push", "-q")


def write_summary(env, lines):
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# ---------- モード ----------

def run_select(queue_dir, env, now_fn=now_jst):
    queue = load_queue(queue_dir)
    today = now_fn().date()
    for p in stale_posts(queue, today):
        log(f"WARNING: 日付が過ぎた承認済み投稿があります（{p['id']}）。再設定が必要です。")
    post = select_post(queue, today)
    out = {"has_post": "false"}
    if post is None:
        log("nothing to publish")
    else:
        video = post.get("video", "")
        path = os.path.join(queue_dir, video)
        if not os.path.isfile(path):
            log(f"ERROR: 動画ファイルがありません: {video}")
            return 1
        out = {"has_post": "true", "post_id": post["id"], "video": video,
               "video_size": str(os.path.getsize(path))}
        log(f"selected: {post['id']}")
    if env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            for k, v in out.items():
                f.write(f"{k}={v}\n")
    return 0


def run_publish(queue_dir, video_url, env, requester=None, sleep=time.sleep, now_fn=now_jst,
                push=None, poll_interval=POLL_INTERVAL):
    dry = env.get("DRY_RUN") in ("1", "true", "TRUE")
    if push is None:
        push = not dry
    if dry:
        requester = requester or DryRunRequester()
        sleep = lambda s: None  # noqa: E731
    requester = requester or http_request

    queue = load_queue(queue_dir)
    today = now_fn().date()
    post = select_post(queue, today)
    if post is None:
        log("nothing to publish")
        return 0

    token = env.get("IG_ACCESS_TOKEN", "")
    user_id = env.get("IG_USER_ID", "")
    client = MetaClient(token, user_id, requester, sleep)
    log(f"post: {post['id']} (dry_run={dry})")

    try:
        if not dry and (not token or not user_id):
            raise PublishError("IG_ACCESS_TOKEN / IG_USER_ID が未設定です")
        video_path = os.path.join(queue_dir, post["video"])
        if not os.path.isfile(video_path):
            raise PublishError("動画ファイルがありません")

        # 二重投稿ガード
        dup = client.recent_media() if (token or dry) else None
        dup = find_duplicate(dup or [], post["caption"], today)
        if dup:
            info = client.media_info(dup["id"])
            mark_published(post, dup["id"], info.get("permalink"), now_fn())
            post["attempts"] = max(0, post["attempts"] - 1)
            save_queue(queue_dir, queue)
            git_finish(queue_dir, post, push, "recovered")
            write_summary(env, [f"### 投稿（復旧）: {post['id']}", info.get("permalink") or ""])
            log("already published today; state recovered")
            return 0

        if not dry:
            if not video_url:
                raise PublishError("VIDEO_URL がありません")
            wait_for_public(video_url, os.path.getsize(video_path), requester, sleep)
        video_url = video_url or "https://example.invalid/dry-run.mp4"

        container = client.create_container(video_url, post["caption"])
        client.wait_container(container, interval=poll_interval)

        target = datetime.combine(today, PUBLISH_AT, tzinfo=JST)
        wait_until(target, now_fn, sleep)

        if now_fn().astimezone(JST).date() != today:
            log("WARNING: 日付が変わったため公開しません（approvedのまま残します）")
            return 0

        media_id = client.publish(container)
    except Exception as e:  # noqa: BLE001
        status = mark_failure(post, client._clean(e))
        save_queue(queue_dir, queue)
        try:
            commit_and_push(queue_dir, f"queue: {post['id']} failed ({post['attempts']})", push)
        except Exception as ge:  # noqa: BLE001
            log(f"git error: {client._clean(ge)}")
        write_summary(env, [f"### 失敗: {post['id']}", f"status={status} attempts={post['attempts']}",
                            post["last_error"] or ""])
        log(f"ERROR: {post['last_error']} (status={status})")
        return 1

    # ここから先は公開済み。失敗扱いにはしない（次の実行では二重投稿ガードが状態を直す）
    try:
        info = client.media_info(media_id)
    except Exception as e:  # noqa: BLE001
        log(f"WARNING: permalink を取得できませんでした: {client._clean(e)}")
        info = {}
    mark_published(post, media_id, info.get("permalink"), now_fn())
    save_queue(queue_dir, queue)
    try:
        git_finish(queue_dir, post, push, "published", delete_video=video_path)
    except Exception as ge:  # noqa: BLE001
        log(f"ERROR: 公開は成功しましたが、記録の保存に失敗しました: {client._clean(ge)}")
        return 1
    write_summary(env, [f"### 投稿しました: {post['id']}", info.get("permalink") or ""])
    log(f"published: {post['id']} {info.get('permalink')}")
    return 0


def git_finish(queue_dir, post, push, verb, delete_video=None):
    if delete_video and os.path.exists(delete_video):
        os.remove(delete_video)
    commit_and_push(queue_dir, f"queue: {post['id']} {verb}", push)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["select", "publish"], required=True)
    ap.add_argument("--queue-dir", required=True)
    ap.add_argument("--site-dir", default=".")  # 互換用（未使用）
    ap.add_argument("--video-url", default=None)
    args = ap.parse_args(argv)
    env = dict(os.environ)
    if args.mode == "select":
        return run_select(args.queue_dir, env)
    return run_publish(args.queue_dir, args.video_url or env.get("VIDEO_URL"), env)


if __name__ == "__main__":
    sys.exit(main())
