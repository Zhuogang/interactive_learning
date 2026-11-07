"""The app and the CLI must schedule identically, because they share one progress file.

These tests run the scheduling code from app/index.html in Node (see core_driver.js)
and compare it with tools/il.py on the same inputs, including randomized histories.
"""
import datetime as dt
import json
import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import il  # noqa: E402

NODE = shutil.which("node")


def js(*calls):
    """Call Core functions from the app. Returns one result per call."""
    done = subprocess.run([NODE, str(ROOT / "tests" / "core_driver.js")], input=json.dumps(calls),
                          capture_output=True, text=True, encoding="utf-8", check=False)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def plain(value):
    """Tuples become lists, as they would in JSON."""
    return json.loads(json.dumps(value))


def random_history(rng, deck, days=90):
    """Answers built the way the app builds them, with gaps, retries and new-card budgets."""
    log, settings = [], {"minimum": 1, "new_per_day": rng.choice([0, 1, 3, 5, 12]), "anchor": ""}
    day = "2026-01-01"
    checkpoints = []
    for _ in range(days):
        day = il.add_days(day, rng.choice([1, 1, 1, 2, 3, 9]))
        items = il.queue_items(deck, log, settings, day)
        queue = [i["q"] for i in items[:rng.randint(0, 12)]]
        qmap = {q["id"]: q for q in deck["questions"]}
        second = 0
        while queue:
            qid = queue.pop(0)
            second += 7
            at = f"{day}T{9 + second // 3600:02d}:{(second % 3600) // 60:02d}:{second % 60:02d}"
            grade = rng.choices(il.GRADES, weights=[3, 2, 6])[0]
            conf = rng.choice([None, "guess", "think", "know"])
            score = rng.choice([None, None, 0.0, 1 / 3, 0.5, 2 / 3, 0.125, 0.625, 1.0])
            entry = il.make_entry(qmap[qid], il.replay(log), grade, conf, score, "app", at)
            log.append(entry)
            if grade == "again" and rng.random() < 0.5:
                queue.append(qid)
        checkpoints.append((il.add_days(day, rng.choice([0, 1, 8])), [dict(e) for e in log]))
    return settings, checkpoints


@unittest.skipIf(NODE is None, "needs node to run the app's code")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deck = il.load_deck("learning-how-to-learn")

    def assertClose(self, a, b, path="$"):
        """Equal, allowing rounding noise in floats: Python 3.12's sum() is more exact than +."""
        if isinstance(a, float) or isinstance(b, float):
            self.assertAlmostEqual(a, b, places=9, msg=path)
        elif isinstance(a, dict):
            self.assertEqual(set(a), set(b), path)
            for k in a:
                self.assertClose(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, list):
            self.assertEqual(len(a), len(b), path)
            for i, (x, y) in enumerate(zip(a, b)):
                self.assertClose(x, y, f"{path}[{i}]")
        else:
            self.assertEqual(a, b, path)

    def test_randomized_histories_schedule_identically(self):
        compared = 0
        for seed in range(12):
            rng = random.Random(seed)
            # Decks list cards in any order, so sort rules can't lean on the starter deck's order.
            deck = {**self.deck, "questions": rng.sample(self.deck["questions"], len(self.deck["questions"]))}
            settings, checkpoints = random_history(rng, deck)
            calls = []
            expected = []
            for day, log in checkpoints:
                calls += [["replay", log],
                          ["buildQueue", deck, log, settings, day],
                          ["queueItems", deck, log, settings, day],
                          ["answeredOn", log, day],
                          ["mastery", deck, plain(il.replay(log))],
                          ["calibration", deck, log]]
                expected += [il.replay(log), il.build_queue(deck, log, settings, day),
                             il.queue_items(deck, log, settings, day), il.answered_on(log, day),
                             il.mastery(deck, il.replay(log)), il.calibration(deck, log)]
            self.assertClose(js(*calls), plain(expected))
            compared += len(calls)
        self.assertGreater(compared, 4000)  # guard against the loop silently doing nothing

    def test_new_entries_match(self):
        pretest = next(q for q in self.deck["questions"] if q["purpose"] == "pretest")
        recall = next(q for q in self.deck["questions"] if q["purpose"] == "recall")
        seen = {pretest["id"]: {"box": 1}}
        cases = []
        for q in (pretest, recall):
            for cards in ({}, seen):
                for grade in il.GRADES:
                    for conf in (None, *il.CONFIDENCE):
                        for score in (None, 0, 0.5, 1, 3, -1):
                            cases.append((q, cards, grade, conf, score))
        calls = [["makeEntry", q, c, g, cf, s, "app", "2026-01-01T09:00:00"] for q, c, g, cf, s in cases]
        expected = [il.make_entry(q, c, g, cf, s, "app", "2026-01-01T09:00:00") for q, c, g, cf, s in cases]
        self.assertEqual(js(*calls), expected)

    def test_score_rounding_matches_python_including_exact_ties(self):
        q = self.deck["questions"][0]
        ratios = sorted({k / n for n in range(1, 41) for k in range(1, n)})
        calls = [["makeEntry", q, {}, "partly", None, r, "app", "2026-01-01T09:00:00"] for r in ratios]
        got = [e["score"] for e in js(*calls)]
        self.assertEqual(got, [round(r, 2) for r in ratios])

    def test_teachbacks_match(self):
        q = next(q for q in self.deck["questions"] if q["type"] == "feynman")
        entry = {"at": "2026-01-01T09:00:00", "score": 0.67}
        texts = ["one", "  two words  ", "line one\nline two\n\ttabbed", "naïve café 日本語 text"]
        got = js(*[["makeTeachback", q, t, entry] for t in texts])
        self.assertEqual(got, [il.make_teachback(q, t, entry) for t in texts])

    def progress_samples(self):
        tricky = 'quotes " and \\ back\nnew\ttab \u00e9 日本語 \U0001f331 \x01 \x7f /slash'
        return [
            il.normalize_progress({}, "d"),
            il.normalize_progress({"deck": "d", "settings": {"minimum": 3, "new_per_day": 0, "anchor": tricky},
                                   "settings_at": "2026-01-01T09:00:00"}, "d"),
            il.normalize_progress({
                "deck": "d",
                "log": [
                    {"via": "app", "score": 1.0, "grade": "good", "q": "x", "at": "2026-01-01T09:00:00", "conf": "know"},
                    {"at": "2026-01-02T09:00:00", "q": "y", "grade": "partly", "conf": "guess", "score": 0.33, "pretest": True, "via": "chat"},
                    {"at": "2026-01-03T09:00:00", "q": "z", "grade": "again", "score": 0.0, "extra": {"k": [1, "a"]}},
                ],
                "feynman": {"concept-a": [{"at": "2026-01-01T09:00:00", "q": "x", "text": tricky, "words": 9, "score": 0.5},
                                          {"at": "2026-01-02T09:00:00", "q": "x", "text": "plain", "words": 1, "score": 1.0}],
                            "concept-b": []},
                "gaps": [{"text": tricky, "q": "x", "at": "2026-01-01T09:00:00"},
                         {"at": "2026-01-02T09:00:00", "text": "done", "closed": True, "card": "y"}],
            }, "d"),
        ]

    def test_the_exported_file_is_byte_identical(self):
        samples = self.progress_samples()
        got = js(*[["formatProgress", p] for p in samples])
        for ours, theirs in zip(got, samples):
            self.assertEqual(ours, il.format_progress(theirs))

    def test_a_file_written_by_one_side_loads_on_the_other(self):
        for p in self.progress_samples():
            text = il.format_progress(p)
            normal, again = js(["normalizeProgress", json.loads(text), "d"],
                               ["formatProgress", il.normalize_progress(json.loads(text), "d")])
            self.assertEqual(normal, plain(p))
            self.assertEqual(again, text)

    def test_normalize_drops_the_same_malformed_rows(self):
        ok = {"at": "2026-01-01T09:00:00", "q": "x", "grade": "good"}
        bad_rows = [{"at": "x"}, "junk", 5, None, {**ok, "at": "2026-13-45T00:00:00"}, {**ok, "at": "2026-02-30T09:00:00"},
                    {**ok, "at": "0000-01-01T09:00:00"}, {**ok, "at": "9999-12-31T09:00:00"}, {**ok, "at": "2026-01-01"},
                    {**ok, "at": "2026-01-01T09:00:00\n"}, {**ok, "at": "٢٠٢٦-01-01T09:00:00"}, {**ok, "at": 5},
                    {**ok, "q": 7}, {**ok, "grade": "great"}, {**ok, "grade": []}, {**ok, "conf": "certain"},
                    {**ok, "conf": None}, {**ok, "score": "high"}, {**ok, "score": True}, {**ok, "score": None}]
        good_rows = [ok, {**ok, "at": "2028-02-29T09:00:00"}, {**ok, "conf": "think", "score": 0.5}, {**ok, "score": 1}]
        raws = [{"log": bad_rows + good_rows},
                {"gaps": [{"text": "no time"}, {"at": "a", "text": "ok"}, {"at": ok["at"], "text": 5}, 5, {"at": ok["at"], "text": "ok"}]},
                {"settings": {"anchor": "x", "extra": 1}},
                {"settings": {"minimum": 0, "new_per_day": -1, "anchor": 5}},
                {"settings": {"minimum": "3", "new_per_day": True}},
                {"settings": {"minimum": 4, "new_per_day": 0, "anchor": ""}},
                {"settings": [1]}, {"settings": "x"}, {"feynman": [1]}, {"feynman": "x"},
                {"feynman": {"c": "x", "d": [1, {"at": 5, "text": "x"}, {"at": ok["at"]}, {"at": ok["at"], "text": "y"}]}},
                {"log": {}}, {"gaps": "x"}, {"settings_at": 5}, {"settings_at": "soon"},
                {"settings_at": ok["at"]}, {"deck": "other"}, [], [1], "x", 5, None, {}]
        got = js(*[["normalizeProgress", raw, "d"] for raw in raws])
        self.assertEqual(got, [il.normalize_progress(raw, "d") for raw in raws])
        self.assertEqual(len(got[0]["log"]), len(good_rows))

    def test_merges_match_in_both_directions(self):
        a, b, c = self.progress_samples()
        b = {**b, "log": [{"at": "2026-01-01T09:00:00", "q": "x", "grade": "again", "score": 0.0}],
             "feynman": {"concept-a": [{"at": "2025-12-31T09:00:00", "q": "x", "text": "first", "words": 1, "score": 0.5}]},
             "gaps": [{"at": "2026-01-02T09:00:00", "text": "done"}, {"at": "2025-01-01T09:00:00", "text": "older"}]}
        newer = {**a, "settings": {"minimum": 1, "new_per_day": 5, "anchor": ""}, "settings_at": "2030-01-01T09:00:00"}
        tied = {**a, "settings": {"minimum": 9, "new_per_day": 9, "anchor": "tied"}, "settings_at": newer["settings_at"]}
        pairs = [(a, b), (b, a), (a, c), (c, a), (b, c), (c, b), (c, c), (b, newer), (newer, b), (a, newer), (newer, a),
                 (newer, tied), (tied, newer)]
        got = js(*[["mergeProgress", x, y] for x, y in pairs])
        self.assertEqual(got, [il.merge_progress(x, y) for x, y in pairs])

    def test_date_arithmetic_crosses_months_years_and_leap_days(self):
        cases = [("2026-01-31", 1), ("2026-12-31", 1), ("2028-02-28", 1), ("2027-02-28", 1),
                 ("2026-03-08", 1), ("2026-11-01", 60), ("2026-01-15", -27), ("2026-03-01", -1)]
        self.assertEqual(js(*[["addDays", d, n] for d, n in cases]), [il.add_days(d, n) for d, n in cases])

    def test_timestamps_use_the_local_clock_and_day(self):
        """Entries are local time with no zone, in the same layout as il.now()."""
        noon_utc = int(dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        late_utc = int(dt.datetime(2026, 1, 1, 3, 5, 9, tzinfo=dt.timezone.utc).timestamp() * 1000)
        cases = [("UTC", noon_utc, "2026-01-01T12:00:00"),
                 ("Pacific/Auckland", noon_utc, "2026-01-02T01:00:00"),
                 ("America/Los_Angeles", late_utc, "2025-12-31T19:05:09")]
        for zone, millis, expected in cases:
            done = subprocess.run(
                [NODE, str(ROOT / "tests" / "core_driver.js")],
                input=json.dumps([["now", {"$date": millis}], ["today", {"$date": millis}]]),
                capture_output=True, text=True, check=True, env={"TZ": zone, "PATH": str(Path(NODE).parent)})
            self.assertEqual(json.loads(done.stdout), [expected, expected[:10]], zone)


if __name__ == "__main__":
    unittest.main()
