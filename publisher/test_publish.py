import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish as P  # noqa: E402

JST = P.JST
TODAY = date(2026, 11, 28)


def jst(h, m=0, d=28):
    return datetime(2026, 11, d, h, m, tzinfo=JST)


class Clock:
    def __init__(self, dt):
        self.t = dt

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)


class FakeMeta:
    """Meta API の偽物。requester として注入する。"""

    def __init__(self, clock, recent=None, fail_create=False, statuses=None):
        self.clock = clock
        self.recent = recent or []
        self.fail_create = fail_create
        self.statuses = list(statuses or ["FINISHED"])
        self.calls = []
        self.publish_time = None
        self.create_data = None

    def __call__(self, method, url, headers=None, data=None, timeout=60):
        self.calls.append((method, url))
        assert "Bearer " in (headers or {}).get("Authorization", "") or method == "HEAD"
        assert "access_token" not in url
        if method == "HEAD":
            return 200, {}, {"content-length": "3"}
        if method == "POST" and url.endswith("/media_publish"):
            self.publish_time = self.clock.now()
            return 200, {"id": "M1"}, {}
        if method == "POST":
            if self.fail_create:
                return 400, {"error": {"message": "bad video"}}, {}
            self.create_data = data
            return 200, {"id": "C1"}, {}
        if "/media?" in url:
            return 200, {"data": self.recent}, {}
        if "C1" in url:
            s = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return 200, {"status_code": s}, {}
        if "M1" in url or "M0" in url:
            return 200, {"permalink": "https://www.instagram.com/reel/ABC/",
                         "timestamp": "2026-11-28T12:00:00+0000"}, {}
        return 404, {}, {}


def make_queue(tmp, status="approved", date_str="2026-11-28", attempts=0, caption="cap #a"):
    qd = os.path.join(tmp, "q")
    os.makedirs(os.path.join(qd, "videos"))
    with open(os.path.join(qd, "videos", "a.mp4"), "wb") as f:
        f.write(b"abc")
    post = {"id": "2026-11-28-x", "publish_date": date_str, "caption": caption,
            "video": "videos/a.mp4", "status": status, "approved_at": "2026-11-27T10:00:00+09:00",
            "published_at": None, "media_id": None, "permalink": None, "last_error": None,
            "attempts": attempts}
    P.save_queue(qd, {"posts": [post]})
    for args in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.com"],
                 ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", qd, *args], check=True, capture_output=True)
    return qd


ENV = {"IG_ACCESS_TOKEN": "SECRET_TOKEN", "IG_USER_ID": "123"}
URL = "https://stock-osusowake.github.io/m/abc.mp4"


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = self._t.name

    def tearDown(self):
        self._t.cleanup()

    def run_pub(self, qd, clock, meta, env=None):
        return P.run_publish(qd, URL, ENV if env is None else env, requester=meta, sleep=clock.sleep,
                             now_fn=clock.now, push=False)

    def post(self, qd):
        return P.load_queue(qd)["posts"][0]


class TestSelect(Base):
    def test_jst_date_selection(self):
        q = {"posts": [{"status": "approved", "publish_date": "2026-11-28"}]}
        # UTC 2026-11-27 20:00 は JST では 11/28
        utc = datetime(2026, 11, 27, 20, 0, tzinfo=P.timezone.utc)
        self.assertEqual(utc.astimezone(JST).date(), TODAY)
        self.assertIsNotNone(P.select_post(q, utc.astimezone(JST).date()))

    def test_only_approved(self):
        for st in ("published", "failed", "skipped"):
            q = {"posts": [{"status": st, "publish_date": "2026-11-28"}]}
            self.assertIsNone(P.select_post(q, TODAY))

    def test_no_post(self):
        qd = make_queue(self.tmp, date_str="2026-11-29")
        clock = Clock(jst(20, 40))
        meta = FakeMeta(clock)
        self.assertEqual(self.run_pub(qd, clock, meta), 0)
        self.assertEqual(meta.calls, [])

    def test_select_mode_output(self):
        qd = make_queue(self.tmp)
        out = os.path.join(self.tmp, "out.txt")
        env = {"GITHUB_OUTPUT": out}
        self.assertEqual(P.run_select(qd, env, now_fn=lambda: jst(10)), 0)
        text = open(out).read()
        self.assertIn("has_post=true", text)
        self.assertIn("video=videos/a.mp4", text)
        open(out, "w").close()
        P.run_select(qd, env, now_fn=lambda: jst(10, d=29))
        self.assertIn("has_post=false", open(out).read())


class TestPublish(Base):
    def test_waits_until_21(self):
        qd = make_queue(self.tmp)
        clock = Clock(jst(20, 45))
        meta = FakeMeta(clock, statuses=["IN_PROGRESS", "FINISHED"])
        self.assertEqual(self.run_pub(qd, clock, meta), 0)
        self.assertGreaterEqual(meta.publish_time, jst(21, 0))
        p = self.post(qd)
        self.assertEqual(p["status"], "published")
        self.assertEqual(p["media_id"], "M1")
        self.assertEqual(p["attempts"], 1)
        self.assertFalse(os.path.exists(os.path.join(qd, "videos", "a.mp4")))
        self.assertEqual(meta.create_data["is_ai_generated"], "true")
        self.assertEqual(meta.create_data["media_type"], "REELS")

    def test_late_same_day_publishes_immediately(self):
        qd = make_queue(self.tmp)
        clock = Clock(jst(22, 10))
        meta = FakeMeta(clock)
        self.assertEqual(self.run_pub(qd, clock, meta), 0)
        self.assertEqual(meta.publish_time, jst(22, 10))

    def test_next_day_is_noop(self):
        qd = make_queue(self.tmp)
        clock = Clock(jst(0, 5, d=29))
        meta = FakeMeta(clock)
        self.assertEqual(self.run_pub(qd, clock, meta), 0)
        self.assertEqual(meta.calls, [])
        self.assertEqual(self.post(qd)["status"], "approved")

    def test_double_post_guard(self):
        qd = make_queue(self.tmp, caption="cap #a")
        clock = Clock(jst(20, 45))
        recent = [{"id": "M0", "caption": "cap #a", "timestamp": "2026-11-28T09:00:00+0000"}]
        meta = FakeMeta(clock, recent=recent)
        self.assertEqual(self.run_pub(qd, clock, meta), 0)
        self.assertIsNone(meta.create_data)
        self.assertIsNone(meta.publish_time)
        p = self.post(qd)
        self.assertEqual(p["status"], "published")
        self.assertEqual(p["media_id"], "M0")

    def test_guard_ignores_other_day_or_caption(self):
        qd = make_queue(self.tmp, caption="cap #a")
        clock = Clock(jst(21, 5))
        recent = [{"id": "M0", "caption": "cap #a", "timestamp": "2026-11-27T09:00:00+0000"},
                  {"id": "M9", "caption": "other", "timestamp": "2026-11-28T09:00:00+0000"}]
        meta = FakeMeta(clock, recent=recent)
        self.assertEqual(self.run_pub(qd, clock, meta), 0)
        self.assertEqual(self.post(qd)["media_id"], "M1")


class TestErrors(Base):
    def test_error_increments_and_keeps_approved(self):
        qd = make_queue(self.tmp)
        clock = Clock(jst(21, 5))
        meta = FakeMeta(clock, fail_create=True)
        self.assertEqual(self.run_pub(qd, clock, meta), 1)
        p = self.post(qd)
        self.assertEqual((p["status"], p["attempts"]), ("approved", 1))
        self.assertIn("bad video", p["last_error"])
        self.assertNotIn("SECRET_TOKEN", json.dumps(p))
        self.assertTrue(os.path.exists(os.path.join(qd, "videos", "a.mp4")))

    def test_third_failure_sets_failed(self):
        qd = make_queue(self.tmp, attempts=2)
        clock = Clock(jst(21, 5))
        meta = FakeMeta(clock, fail_create=True)
        self.assertEqual(self.run_pub(qd, clock, meta), 1)
        self.assertEqual(self.post(qd)["status"], "failed")

    def test_container_error_status(self):
        qd = make_queue(self.tmp)
        clock = Clock(jst(21, 5))
        meta = FakeMeta(clock, statuses=["ERROR"])
        self.assertEqual(self.run_pub(qd, clock, meta), 1)
        self.assertEqual(self.post(qd)["attempts"], 1)

    def test_missing_token(self):
        qd = make_queue(self.tmp)
        clock = Clock(jst(21, 5))
        self.assertEqual(self.run_pub(qd, clock, FakeMeta(clock), env={}), 1)


class TestDryRun(Base):
    def test_dry_run_end_to_end(self):
        qd = make_queue(self.tmp)
        today = P.now_jst().date().isoformat()
        q = P.load_queue(qd)
        q["posts"][0]["publish_date"] = today
        P.save_queue(qd, q)
        summary = os.path.join(self.tmp, "sum.md")
        env = {"DRY_RUN": "1", "GITHUB_STEP_SUMMARY": summary}
        rc = P.run_publish(qd, None, env)
        self.assertEqual(rc, 0)
        p = self.post(qd)
        self.assertEqual(p["status"], "published")
        self.assertEqual(p["media_id"], "dry-media-1")
        self.assertFalse(os.path.exists(os.path.join(qd, "videos", "a.mp4")))
        log = subprocess.run(["git", "-C", qd, "log", "--oneline"], capture_output=True, text=True).stdout
        self.assertIn("published", log)
        self.assertIn("DRYRUN", open(summary).read())


if __name__ == "__main__":
    unittest.main()
