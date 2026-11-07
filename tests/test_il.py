"""Tests for tools/il.py. Standard library only: python3 -m unittest discover -s tests"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import il  # noqa: E402

STARTER = "learning-how-to-learn"


def answer(q, grade, at, **extra):
    return {"at": at, "q": q, "grade": grade, **extra}


def card(qid, concept="a", purpose="recall", type_="short", **extra):
    return {"id": qid, "concept": concept, "type": type_, "purpose": purpose, "prompt": qid, **extra}


def deck_of(*questions, concepts=("a", "b", "c")):
    return {"format": 1, "id": "t", "title": "T", "source": {"kind": "topic", "title": "T"},
            "concepts": [{"id": c, "title": c.upper(), "summary": "s"} for c in concepts],
            "questions": list(questions)}


def run_cli(*argv, stdin=None):
    """Run il.py in-process. Returns (exit code, stdout + any error message)."""
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out):
        patch = mock.patch("sys.stdin", io.StringIO(stdin)) if stdin is not None else mock.patch("sys.argv", ["il.py"])
        with patch:
            try:
                code = il.main(list(argv))
            except SystemExit as ex:
                code = 1 if isinstance(ex.code, str) else (ex.code or 0)
                if isinstance(ex.code, str):
                    out.write(ex.code)
    return code, out.getvalue()


class Scheduling(unittest.TestCase):
    def test_each_good_day_moves_up_one_box_and_stretches_the_gap(self):
        log, day = [], "2026-01-01"
        for box, gap in [(1, 1), (2, 3), (3, 7), (4, 14), (5, 30), (6, 60)]:
            log.append(answer("x", "good", day + "T09:00:00"))
            c = il.replay(log)["x"]
            self.assertEqual(c["box"], box)
            self.assertEqual(c["due"], il.add_days(day, gap))
            day = c["due"]

    def test_top_box_is_the_ceiling(self):
        days = [il.add_days("2026-01-01", i) for i in range(10)]
        cards = il.replay([answer("x", "good", d + "T09:00:00") for d in days])
        self.assertEqual(cards["x"]["box"], il.MAX_BOX)

    def test_missed_goes_back_to_box_one_and_counts_a_lapse(self):
        c = il.replay([answer("x", "good", "2026-01-01T09:00:00"),
                       answer("x", "good", "2026-01-02T09:00:00"),
                       answer("x", "again", "2026-01-05T09:00:00")])["x"]
        self.assertEqual((c["box"], c["due"], c["lapses"]), (1, "2026-01-06", 1))

    def test_missing_a_card_in_box_one_is_not_a_lapse(self):
        c = il.replay([answer("x", "again", "2026-01-01T09:00:00"),
                       answer("x", "again", "2026-01-02T09:00:00")])["x"]
        self.assertEqual(c["lapses"], 0)

    def test_partly_stays_in_the_same_box(self):
        c = il.replay([answer("x", "good", "2026-01-01T09:00:00"),
                       answer("x", "good", "2026-01-02T09:00:00"),
                       answer("x", "partly", "2026-01-05T09:00:00")])["x"]
        self.assertEqual((c["box"], c["due"]), (2, "2026-01-08"))

    def test_partly_on_a_new_card_lands_in_box_one(self):
        self.assertEqual(il.replay([answer("x", "partly", "2026-01-01T09:00:00")])["x"]["box"], 1)

    def test_only_the_first_answer_of_the_day_can_move_a_card_up(self):
        c = il.replay([answer("x", "good", "2026-01-01T09:00:00"),
                       answer("x", "good", "2026-01-01T09:05:00"),
                       answer("x", "good", "2026-01-01T09:10:00")])["x"]
        self.assertEqual((c["box"], c["reps"]), (1, 3))

    def test_a_miss_then_a_retry_the_same_day_stays_in_box_one(self):
        c = il.replay([answer("x", "good", "2026-01-01T09:00:00"),
                       answer("x", "good", "2026-01-02T09:00:00"),
                       answer("x", "again", "2026-01-05T09:00:00"),
                       answer("x", "good", "2026-01-05T09:03:00")])["x"]
        self.assertEqual((c["box"], c["due"]), (1, "2026-01-06"))

    def test_a_pretest_starts_in_box_one_even_when_right(self):
        c = il.replay([answer("x", "good", "2026-01-01T09:00:00", pretest=True)])["x"]
        self.assertEqual(c["box"], 1)

    def test_state_depends_on_timestamps_not_log_order(self):
        log = [answer("x", "again", "2026-01-05T09:00:00"), answer("x", "good", "2026-01-01T09:00:00")]
        self.assertEqual(il.replay(log), il.replay(list(reversed(log))))

    def test_intervals_match_the_table_in_principles(self):
        text = (ROOT / "PRINCIPLES.md").read_text(encoding="utf-8")
        row = re.search(r"\*\*Next review in\*\*(.*)\|", text).group(1)
        unit_days = {"day": 1, "week": 7, "month": 30}
        table = []
        for n, unit in re.findall(r"(\d+) (day|week|month)s?", row):
            table.append(int(n) * unit_days[unit])
        self.assertEqual(table, [il.INTERVALS[b] for b in sorted(il.INTERVALS)])


class Entries(unittest.TestCase):
    def test_a_correct_guess_counts_as_partly_but_still_scores_as_right(self):
        e = il.make_entry(card("x"), {}, "good", conf="guess", at="2026-01-01T09:00:00")
        self.assertEqual((e["grade"], e["score"], e["conf"]), ("partly", 1.0, "guess"))

    def test_a_correct_answer_you_were_sure_of_stays_good(self):
        e = il.make_entry(card("x"), {}, "good", conf="know")
        self.assertEqual(e["grade"], "good")

    def test_pretest_flag_only_on_the_first_answer(self):
        q = card("x", purpose="pretest")
        self.assertTrue(il.make_entry(q, {}, "again")["pretest"])
        self.assertNotIn("pretest", il.make_entry(q, {"x": {"box": 1}}, "good"))

    def test_the_grade_decides_the_score(self):
        self.assertEqual(il.make_entry(card("x"), {}, "good", score=0.33)["score"], 1.0)
        self.assertEqual(il.make_entry(card("x"), {}, "again", score=1)["score"], 0.0)

    def test_a_score_refines_partly_and_is_rounded(self):
        self.assertEqual(il.make_entry(card("x"), {}, "partly", score=1 / 3)["score"], 0.33)
        for useless in (None, 0, 1, 7, -1):
            self.assertEqual(il.make_entry(card("x"), {}, "partly", score=useless)["score"], 0.5)

    def test_rejects_unknown_grade_and_confidence(self):
        with self.assertRaises(ValueError):
            il.make_entry(card("x"), {}, "great")
        with self.assertRaises(ValueError):
            il.make_entry(card("x"), {}, "good", conf="certain")


class Queue(unittest.TestCase):
    SETTINGS = {"new_per_day": 3}

    def test_due_reviews_come_before_new_cards(self):
        deck = deck_of(card("seen"), card("fresh"))
        items = il.queue_items(deck, [answer("seen", "good", "2026-01-01T09:00:00")], self.SETTINGS, "2026-01-02")
        self.assertEqual([i["q"] for i in items], ["seen", "fresh"])
        self.assertEqual([i["kind"] for i in items], ["review", "new"])

    def test_a_card_is_not_due_before_its_date(self):
        deck = deck_of(card("seen"))
        log = [answer("seen", "good", "2026-01-01T09:00:00")]
        self.assertEqual(il.queue_items(deck, log, self.SETTINGS, "2026-01-01"), [])

    def test_reviews_rotate_between_concepts(self):
        deck = deck_of(card("a1"), card("a2"), card("a3"), card("b1", "b"), card("b2", "b"), card("c1", "c"))
        log = [answer(q["id"], "good", "2026-01-01T09:00:00") for q in deck["questions"]]
        items = il.queue_items(deck, log, self.SETTINGS, "2026-01-02")
        self.assertEqual([i["q"] for i in items], ["a1", "b1", "c1", "a2", "b2", "a3"])

    def test_new_cards_run_pretest_first_and_teach_back_last(self):
        deck = deck_of(card("t", purpose="teach", type_="feynman"), card("r"), card("p", purpose="pretest"))
        self.assertEqual([i["q"] for i in il.queue_items(deck, [], self.SETTINGS, "2026-01-01")], ["p", "r", "t"])

    def test_new_card_budget_spans_concepts_and_counts_today(self):
        deck = deck_of(card("a1"), card("a2"), card("b1", "b"), card("b2", "b"))
        self.assertEqual([i["q"] for i in il.queue_items(deck, [], self.SETTINGS, "2026-01-01")], ["a1", "a2", "b1"])
        log = [answer("a1", "good", "2026-01-01T09:00:00")]
        self.assertEqual([i["q"] for i in il.queue_items(deck, log, self.SETTINGS, "2026-01-01")], ["a2", "b1"])

    def test_concept_intro_comes_after_the_pretest_and_only_once(self):
        deck = deck_of(card("p", purpose="pretest"), card("r1"), card("r2"))
        flags = {i["q"]: i["intro"] for i in il.queue_items(deck, [], self.SETTINGS, "2026-01-01")}
        self.assertEqual(flags, {"p": False, "r1": True, "r2": False})

    def test_no_intro_once_a_concept_has_been_studied(self):
        deck = deck_of(card("r1"), card("r2"))
        log = [answer("r1", "good", "2026-01-01T09:00:00")]
        items = il.queue_items(deck, log, self.SETTINGS, "2026-01-01")
        self.assertEqual([(i["q"], i["intro"]) for i in items], [("r2", False)])

    def test_answers_for_deleted_cards_are_ignored(self):
        deck = deck_of(card("kept"))
        log = [answer("deleted", "good", "2026-01-01T09:00:00")]
        self.assertEqual([i["q"] for i in il.queue_items(deck, log, self.SETTINGS, "2026-02-01")], ["kept"])


class Stats(unittest.TestCase):
    def test_mastery_caps_at_box_four(self):
        deck = deck_of(card("x"), concepts=("a",))
        self.assertEqual(il.mastery(deck, {"x": {"box": 6}})["a"], 1.0)
        self.assertEqual(il.mastery(deck, {"x": {"box": 2}})["a"], 0.5)
        self.assertEqual(il.mastery(deck, {})["a"], 0.0)

    def test_mastery_of_an_empty_concept_is_none(self):
        self.assertIsNone(il.mastery(deck_of(concepts=("a",)), {})["a"])

    def test_calibration_uses_scores_and_skips_pretests(self):
        deck = deck_of(card("x"), card("y"))
        log = [answer("x", "partly", "2026-01-01T09:00:00", conf="guess", score=1.0),
               answer("y", "again", "2026-01-01T09:00:01", conf="guess", score=0.0),
               answer("x", "good", "2026-01-01T09:00:02", conf="know", score=1.0, pretest=True)]
        cal = il.calibration(deck, log)
        self.assertEqual(cal["guess"], (2, 0.5))
        self.assertEqual(cal["know"], (0, None))


class ProgressFile(unittest.TestCase):
    def sample(self):
        return il.normalize_progress({
            "deck": "t",
            "log": [{"at": "2026-01-01T09:00:00", "via": "app", "q": "x", "grade": "good", "score": 1.0}],
            "feynman": {"a": [{"at": "2026-01-01T09:00:00", "q": "x", "text": "hi", "words": 1, "score": 1.0}]},
            "gaps": [{"at": "2026-01-01T09:00:00", "text": "why?"}],
        }, "t")

    def test_format_round_trips(self):
        p = self.sample()
        self.assertEqual(il.normalize_progress(json.loads(il.format_progress(p)), "t"), p)

    def test_each_answer_sits_on_its_own_line_in_a_fixed_key_order(self):
        p = self.sample()
        p["log"].append(answer("y", "again", "2026-01-02T09:00:00"))
        lines = il.format_progress(p).splitlines()
        self.assertIn('    {"at": "2026-01-01T09:00:00", "q": "x", "grade": "good", "score": 1.0, "via": "app"},', lines)
        self.assertIn('    {"at": "2026-01-02T09:00:00", "q": "y", "grade": "again"}', lines)

    def test_normalize_drops_malformed_rows(self):
        p = il.normalize_progress({"log": [{"at": "x"}, "junk"], "gaps": [{"text": "no time"}]}, "t")
        self.assertEqual((p["log"], p["gaps"]), ([], []))

    def test_a_row_that_would_break_scheduling_never_gets_in(self):
        ok = {"at": "2026-01-01T09:00:00", "q": "x", "grade": "good"}
        for bad in ({**ok, "at": "2026-13-45T00:00:00"}, {**ok, "at": "2026-02-30T09:00:00"},
                    {**ok, "at": "0000-01-01T09:00:00"}, {**ok, "at": "9999-12-31T09:00:00"},
                    {**ok, "at": "2026-01-01"}, {**ok, "at": 5}, {**ok, "q": 7}, {**ok, "q": []},
                    {**ok, "grade": "great"}, {**ok, "grade": []}, {**ok, "conf": "certain"},
                    {**ok, "conf": []}, {**ok, "score": "high"}, {**ok, "score": True}):
            with self.subTest(bad=bad):
                p = il.normalize_progress({"log": [bad, ok]}, "t")
                self.assertEqual(p["log"], [ok])
                il.replay(p["log"])
                il.calibration(deck_of(card("x")), p["log"])

    def test_normalize_survives_fields_of_the_wrong_type(self):
        for raw in ([], [1, 2], "x", 5, None,
                    {"settings": []}, {"settings": [1]}, {"settings": "x"},
                    {"feynman": [1]}, {"feynman": "x"}, {"feynman": {"c": "x"}}, {"feynman": {"c": [1, {"at": 5}]}},
                    {"log": {}}, {"log": "x"}, {"gaps": {}}, {"gaps": [1, {"at": 5, "text": "x"}]},
                    {"settings_at": 5}, {"settings_at": "soon"}):
            with self.subTest(raw=raw):
                p = il.normalize_progress(raw, "t")
                il.merge_progress(p, il.normalize_progress(raw, "t"))
                self.assertEqual(json.loads(il.format_progress(p))["settings"], p["settings"])

    def test_bad_settings_values_fall_back_to_the_defaults(self):
        s = il.normalize_progress({"settings": {"minimum": 0, "new_per_day": -1, "anchor": 5}}, "t")["settings"]
        self.assertEqual(s, il.DEFAULT_SETTINGS)
        s = il.normalize_progress({"settings": {"minimum": "3", "new_per_day": True, "other": 1}}, "t")["settings"]
        self.assertEqual(s, {**il.DEFAULT_SETTINGS, "other": 1})

    def test_merge_is_idempotent_and_sorted(self):
        a = il.normalize_progress({"log": [answer("x", "good", "2026-01-02T09:00:00")]}, "t")
        b = il.normalize_progress({"log": [answer("y", "good", "2026-01-01T09:00:00"),
                                           answer("x", "good", "2026-01-02T09:00:00")]}, "t")
        merged = il.merge_progress(a, b)
        self.assertEqual([e["q"] for e in merged["log"]], ["y", "x"])
        self.assertEqual(il.merge_progress(merged, b), merged)

    def test_the_most_recently_changed_settings_win(self):
        older = il.normalize_progress({"settings": {"anchor": "old", "minimum": 3}, "settings_at": "2026-01-01T09:00:00"}, "t")
        newer = il.normalize_progress({"settings": {"anchor": ""}, "settings_at": "2026-01-02T09:00:00"}, "t")
        for merged in (il.merge_progress(older, newer), il.merge_progress(newer, older)):
            self.assertEqual(merged["settings"], {**il.DEFAULT_SETTINGS, "anchor": ""})  # clearing sticks
            self.assertEqual(merged["settings_at"], "2026-01-02T09:00:00")

    def test_on_a_settings_tie_the_local_copy_stays(self):
        mine = il.normalize_progress({"settings": {"anchor": "mine"}, "settings_at": "2026-01-01T09:00:00"}, "t")
        theirs = il.normalize_progress({"settings": {"anchor": "theirs"}, "settings_at": "2026-01-01T09:00:00"}, "t")
        self.assertEqual(il.merge_progress(mine, theirs)["settings"]["anchor"], "mine")

    def test_settings_that_were_changed_beat_defaults_that_never_were(self):
        untouched = il.normalize_progress({}, "t")
        chosen = il.normalize_progress({"settings": {"anchor": "theirs"}, "settings_at": "2026-01-01T09:00:00"}, "t")
        self.assertEqual(il.merge_progress(untouched, chosen)["settings"]["anchor"], "theirs")

    def test_merge_unions_teachbacks_by_time(self):
        a = il.normalize_progress({"feynman": {"c": [{"at": "2026-01-02T00:00:00", "text": "b"}]}}, "t")
        b = il.normalize_progress({"feynman": {"c": [{"at": "2026-01-01T00:00:00", "text": "a"},
                                                     {"at": "2026-01-02T00:00:00", "text": "b"}],
                                               "d": [{"at": "2026-01-03T00:00:00", "text": "c"}]}}, "t")
        merged = il.merge_progress(a, b)["feynman"]
        self.assertEqual([e["text"] for e in merged["c"]], ["a", "b"])
        self.assertEqual(len(merged["d"]), 1)

    def test_a_gap_closed_on_either_side_stays_closed(self):
        gap = {"at": "2026-01-01T00:00:00", "text": "why?"}
        open_side = il.normalize_progress({"gaps": [dict(gap)]}, "t")
        closed = il.normalize_progress({"gaps": [{**gap, "closed": True, "card": "new"}]}, "t")
        for merged in (il.merge_progress(open_side, closed), il.merge_progress(closed, open_side)):
            self.assertEqual(len(merged["gaps"]), 1)
            self.assertTrue(merged["gaps"][0]["closed"])
            self.assertEqual(merged["gaps"][0]["card"], "new")


def good_deck():
    return {
        "format": 1, "id": "good-deck", "title": "T", "source": {"kind": "paper", "title": "P"},
        "concepts": [
            {"id": "one", "title": "One", "summary": "s", "read": "s1"},
            {"id": "two", "title": "Two", "summary": "s", "read": "s2", "prereqs": ["one"]},
        ],
        "questions": [
            {"id": "m", "concept": "one", "type": "mcq", "purpose": "pretest", "prompt": "p", "ref": "r",
             "options": [{"text": "a", "correct": True, "why": "w"}, {"text": "b", "why": "w"}]},
            {"id": "s", "concept": "two", "type": "short", "purpose": "pretest", "prompt": "p", "ref": "r",
             "answer": "a", "key_points": ["k"]},
            {"id": "f", "concept": "two", "type": "feynman", "purpose": "teach", "prompt": "p", "ref": "r",
             "rubric": ["a", "b"], "word_limit": 100},
        ],
    }


# (name, how to break the deck, text the error must contain)
BROKEN = [
    ("wrong format", lambda d: d.update(format=2), "format must be 1"),
    ("bad id", lambda d: d.update(id="Not Kebab"), "id must be lowercase"),
    ("no title", lambda d: d.pop("title"), "title is required"),
    ("no source", lambda d: d.pop("source"), "source is required"),
    ("bad source kind", lambda d: d["source"].update(kind="blog"), "source.kind"),
    ("concepts not a list", lambda d: d.update(concepts={}), "concepts must be a list"),
    ("questions not a list", lambda d: d.update(questions=5), "questions must be a list"),
    ("duplicate concept", lambda d: d["concepts"].append(dict(d["concepts"][0])), "duplicate id"),
    ("forward prereq", lambda d: d["concepts"][0].update(prereqs=["two"]), "listed earlier"),
    ("prereqs not a list", lambda d: d["concepts"][1].update(prereqs="one"), "prereqs must be a list"),
    ("duplicate question", lambda d: d["questions"].append(dict(d["questions"][0])), "duplicate id"),
    ("unknown concept", lambda d: d["questions"][0].update(concept="nope"), "does not exist"),
    ("concept is a list", lambda d: d["questions"][0].update(concept=["one"]), "does not exist"),
    ("unknown also", lambda d: d["questions"][0].update(also=["nope"]), "is not a concept"),
    ("also not a list", lambda d: d["questions"][0].update(also=[{}]), "also must be a list"),
    ("no prompt", lambda d: d["questions"][0].pop("prompt"), "prompt is required"),
    ("bad type", lambda d: d["questions"][0].update(type="essay"), "type must be one of"),
    ("bad purpose", lambda d: d["questions"][0].update(purpose="fun"), "purpose must be one of"),
    ("two correct", lambda d: d["questions"][0]["options"][1].update(correct=True), "exactly one"),
    ("none correct", lambda d: d["questions"][0]["options"][0].pop("correct"), "exactly one"),
    ("one option", lambda d: d["questions"][0].update(options=[{"text": "a", "correct": True}]), "2-6 options"),
    ("mcq teach", lambda d: d["questions"][0].update(purpose="teach"), "only for type 'feynman'"),
    ("short without answer", lambda d: d["questions"][1].pop("answer"), "needs an 'answer'"),
    ("empty key_points", lambda d: d["questions"][1].update(key_points=[]), "key_points must be"),
    ("feynman not teach", lambda d: d["questions"][2].update(purpose="recall"), "must have purpose 'teach'"),
    ("thin rubric", lambda d: d["questions"][2].update(rubric=["a"]), "rubric of at least 2"),
    ("bad word limit", lambda d: d["questions"][2].update(word_limit=0), "word_limit"),
    ("bad follow ups", lambda d: d["questions"][2].update(follow_ups="why?"), "follow_ups"),
]


class Validation(unittest.TestCase):
    def test_a_good_deck_is_clean(self):
        self.assertEqual(il.validate_deck(good_deck(), "good-deck"), ([], []))

    def test_each_mistake_is_reported(self):
        for name, breakit, expected in BROKEN:
            with self.subTest(name):
                d = good_deck()
                breakit(d)
                errors, _ = il.validate_deck(d, "good-deck")
                self.assertTrue(any(expected in e for e in errors), f"{expected!r} not in {errors}")

    def test_id_must_match_the_folder(self):
        errors, _ = il.validate_deck(good_deck(), "other-folder")
        self.assertTrue(any("must match its folder" in e for e in errors))

    def test_garbage_is_reported_rather_than_crashing(self):
        for junk in ([], "deck", 7, None, {}, {"concepts": [1, None], "questions": [[], "x"]}):
            with self.subTest(junk=junk):
                self.assertTrue(il.validate_deck(junk)[0])

    def test_typos_and_missing_grounding_are_warnings(self):
        d = good_deck()
        d["subtitel"] = "typo"
        d["concepts"][0]["sumary"] = "typo"
        d["questions"][0]["keypoints"] = ["typo"]
        d["questions"][0]["options"][0]["corect"] = True
        d["questions"][1].pop("ref")
        d["concepts"][0].pop("read")
        errors, warnings = il.validate_deck(d, "good-deck")
        self.assertEqual(errors, [])
        for expected in ("'subtitel'", "'sumary'", "'keypoints'", "'corect'", "no 'ref'", "no 'read'"):
            self.assertTrue(any(expected in w for w in warnings), expected)


class TempProjects(unittest.TestCase):
    """Runs the CLI against a throwaway projects/ folder, never the real one."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        for name, value in (("ROOT", self.root), ("PROJECTS", self.projects)):
            patcher = mock.patch.object(il, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.projects / "good-deck").mkdir()
        (self.projects / "good-deck" / "deck.json").write_text(json.dumps(good_deck()), encoding="utf-8")

    def progress(self, pid="good-deck"):
        return json.loads((self.projects / pid / "progress.json").read_text(encoding="utf-8"))


class CliNew(TempProjects):
    def test_new_scaffolds_a_valid_deck_and_updates_the_manifest(self):
        code, out = run_cli("new", "my-paper", "--title", "My Paper", "--url", "https://x.test", "--source-title", "The Paper")
        self.assertEqual(code, 0, out)
        deck = json.loads((self.projects / "my-paper" / "deck.json").read_text(encoding="utf-8"))
        self.assertEqual((deck["id"], deck["source"]["title"], deck["source"]["url"]), ("my-paper", "The Paper", "https://x.test"))
        self.assertEqual(il.validate_deck(deck, "my-paper")[0], [])
        self.assertIn("my-paper", (self.projects / "manifest.json").read_text(encoding="utf-8"))
        readme = (self.projects / "my-paper" / "README.md").read_text(encoding="utf-8")
        self.assertIn("# My Paper", readme)
        self.assertNotIn("{{", readme + json.dumps(deck))

    def test_quotes_in_a_title_dont_break_the_json(self):
        title = 'Why "attention" matters \\ a lot'
        self.assertEqual(run_cli("new", "quoted", "--title", title)[0], 0)
        deck = json.loads((self.projects / "quoted" / "deck.json").read_text(encoding="utf-8"))
        self.assertEqual(deck["title"], title)
        self.assertIn(title, (self.projects / "quoted" / "README.md").read_text(encoding="utf-8"))

    def test_new_refuses_bad_ids_kinds_and_existing_projects(self):
        self.assertIn("kebab", run_cli("new", "Bad Id", "--title", "T")[1])
        self.assertIn("--kind", run_cli("new", "ok-id", "--title", "T", "--kind", "blog")[1])
        code, out = run_cli("new", "good-deck", "--title", "T")
        self.assertEqual(code, 1)
        self.assertIn("already exists", out)

    def test_new_says_so_when_templates_are_missing(self):
        with mock.patch.object(il, "TEMPLATES", self.root / "nowhere"):
            code, out = run_cli("new", "no-templates", "--title", "T")
        self.assertEqual(code, 1)
        self.assertIn("no templates", out)
        self.assertFalse((self.projects / "no-templates").exists())


class CliValidate(TempProjects):
    def test_exit_code_reflects_errors(self):
        self.assertEqual(run_cli("validate")[0], 0)
        (self.projects / "broken").mkdir()
        (self.projects / "broken" / "deck.json").write_text("{not json", encoding="utf-8")
        code, out = run_cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("invalid JSON", out)

    def test_a_deck_that_is_not_an_object_does_not_crash_validate_or_manifest(self):
        (self.projects / "listy").mkdir()
        (self.projects / "listy" / "deck.json").write_text("[]", encoding="utf-8")
        code, out = run_cli("validate", "listy")
        self.assertEqual(code, 1)
        self.assertIn("must be a JSON object", out)
        self.assertEqual(run_cli("manifest")[0], 0)

    def test_manifest_check_notices_drift(self):
        run_cli("manifest")
        self.assertEqual(run_cli("manifest", "--check")[0], 0)
        (self.projects / "manifest.json").write_text("{}", encoding="utf-8")
        self.assertEqual(run_cli("manifest", "--check")[0], 1)


class CliStudy(TempProjects):
    def test_record_writes_the_answer_and_reports_the_schedule(self):
        code, out = run_cli("record", "good-deck", "s", "good", "--conf", "know", "--at", "2026-01-01T09:00:00")
        self.assertEqual(code, 0, out)
        self.assertIn("next review 2026-01-02", out)
        self.assertIn("pretest", out)
        entry = self.progress()["log"][0]
        self.assertEqual((entry["q"], entry["grade"], entry["via"], entry["pretest"]), ("s", "good", "chat", True))

    def test_record_notes_when_a_guess_is_downgraded(self):
        _, out = run_cli("record", "good-deck", "m", "good", "--conf", "guess")
        self.assertIn("a correct guess counts as partly", out)
        self.assertEqual(self.progress()["log"][0]["grade"], "partly")

    def test_record_rejects_unknown_questions_without_touching_the_file(self):
        code, out = run_cli("record", "good-deck", "nope", "good")
        self.assertEqual(code, 1)
        self.assertIn("no question", out)
        self.assertFalse((self.projects / "good-deck" / "progress.json").exists())

    def test_record_saves_a_teachback(self):
        run_cli("record", "good-deck", "f", "partly", "--score", "0.6", "--text", "  plain words here  ", "--at", "2026-01-01T09:00:00")
        saved = self.progress()["feynman"]["two"][0]
        self.assertEqual(saved, {"at": "2026-01-01T09:00:00", "q": "f", "text": "plain words here", "words": 3, "score": 0.6})

    def test_record_reads_a_teachback_from_stdin(self):
        run_cli("record", "good-deck", "f", "good", "--text", "-", stdin='it\'s "quoted"\nand multiline\n')
        self.assertEqual(self.progress()["feynman"]["two"][0]["text"], 'it\'s "quoted"\nand multiline')

    def test_text_is_only_for_teach_it_cards(self):
        code, out = run_cli("record", "good-deck", "s", "good", "--text", "hello")
        self.assertEqual(code, 1)
        self.assertIn("teach-it", out)
        self.assertFalse((self.projects / "good-deck" / "progress.json").exists())

    def test_blank_text_records_the_answer_but_no_teachback(self):
        run_cli("record", "good-deck", "f", "good", "--text", "   ")
        self.assertEqual(self.progress()["feynman"], {})
        self.assertEqual(len(self.progress()["log"]), 1)

    def test_due_json_reports_how_much_was_answered_today(self):
        _, out = run_cli("due", "good-deck", "--json", "--today", "2026-01-01")
        before = json.loads(out)
        self.assertEqual(before["answered_today"], 0)
        self.assertEqual([i["q"] for i in before["items"]], ["m", "s", "f"])
        run_cli("record", "good-deck", "m", "good", "--at", "2026-01-01T09:00:00")
        after = json.loads(run_cli("due", "good-deck", "--json", "--today", "2026-01-01")[1])
        self.assertEqual(after["answered_today"], 1)

    def test_due_and_status_handle_a_deck_with_no_progress(self):
        self.assertEqual(run_cli("due", "good-deck")[0], 0)
        code, out = run_cli("status", "good-deck")
        self.assertEqual(code, 0)
        self.assertIn("0/3 cards started", out)

    def test_status_counts_show_up_days_not_streaks(self):
        run_cli("record", "good-deck", "m", "good", "--at", "2026-01-01T09:00:00")
        run_cli("record", "good-deck", "s", "good", "--at", "2026-01-05T09:00:00")
        _, out = run_cli("status", "good-deck", "--today", "2026-01-10")
        self.assertIn("show-up days: 2 of the last 28", out)

    def test_status_mentions_calibration_only_with_enough_answers(self):
        for i, qid in enumerate(["s", "s", "s"], 2):
            run_cli("record", "good-deck", qid, "good", "--conf", "know", "--at", f"2026-01-0{i}T09:00:00")
        _, out = run_cli("status", "good-deck", "--today", "2026-01-05")
        self.assertNotIn("calibration", out)  # the first answer was a pretest, so n=2
        run_cli("record", "good-deck", "s", "good", "--conf", "know", "--at", "2026-01-05T09:00:00")
        _, out = run_cli("status", "good-deck", "--today", "2026-01-05")
        self.assertIn("know 100% (n=3)", out)

    def test_unknown_deck_is_a_friendly_error(self):
        code, out = run_cli("due", "no-such-deck")
        self.assertEqual(code, 1)
        self.assertIn("no deck at", out)


class CliSettings(TempProjects):
    def test_shows_defaults_without_creating_a_file(self):
        code, out = run_cli("settings", "good-deck")
        self.assertEqual(code, 0)
        self.assertIn("minimum 1", out)
        self.assertIn("(none yet)", out)
        self.assertFalse((self.projects / "good-deck" / "progress.json").exists())

    def test_changes_only_what_you_ask_for(self):
        run_cli("settings", "good-deck", "--anchor", " pour my coffee ")
        run_cli("settings", "good-deck", "--new-per-day", "0")
        self.assertEqual(self.progress()["settings"], {"minimum": 1, "new_per_day": 0, "anchor": "pour my coffee"})
        self.assertEqual(run_cli("due", "good-deck", "--json")[1].count('"kind": "new"'), 0)

    def test_a_change_is_timestamped_and_showing_is_not(self):
        run_cli("settings", "good-deck", "--anchor", "x")
        stamped = self.progress()["settings_at"]
        self.assertTrue(il.valid_at(stamped))
        run_cli("settings", "good-deck")
        self.assertEqual(self.progress()["settings_at"], stamped)

    def test_refuses_a_minimum_below_one(self):
        code, out = run_cli("settings", "good-deck", "--minimum", "0")
        self.assertEqual(code, 1)
        self.assertIn("at least 1", out)
        self.assertFalse((self.projects / "good-deck" / "progress.json").exists())


class CliGaps(TempProjects):
    def test_add_list_close(self):
        self.assertEqual(run_cli("gaps", "good-deck")[1].strip(), "No open gaps.")
        code, out = run_cli("gaps", "good-deck", "--add", "why does it fade?", "--q", "s")
        self.assertEqual(code, 0, out)
        listed = json.loads(run_cli("gaps", "good-deck", "--json")[1])
        self.assertEqual((listed[0]["text"], listed[0]["q"]), ("why does it fade?", "s"))
        self.assertIn("open gaps: 1", run_cli("status", "good-deck")[1])

        code, out = run_cli("gaps", "good-deck", "--close", listed[0]["at"], "--card", "m")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(run_cli("gaps", "good-deck", "--json")[1]), [])
        self.assertEqual(self.progress()["gaps"][0]["card"], "m")
        self.assertNotIn("open gaps", run_cli("status", "good-deck")[1])

    def test_gaps_added_in_the_same_second_can_be_closed_separately(self):
        with mock.patch.object(il, "now", return_value="2026-01-01T23:59:59"):
            run_cli("gaps", "good-deck", "--add", "first")
            run_cli("gaps", "good-deck", "--add", "second")
            run_cli("gaps", "good-deck", "--add", "third")
        ats = [g["at"] for g in self.progress()["gaps"]]
        self.assertEqual(ats, ["2026-01-01T23:59:59", "2026-01-02T00:00:00", "2026-01-02T00:00:01"])
        run_cli("gaps", "good-deck", "--close", ats[1])
        self.assertEqual([g["text"] for g in json.loads(run_cli("gaps", "good-deck", "--json")[1])], ["first", "third"])

    def test_bad_input_is_refused(self):
        self.assertIn("no question", run_cli("gaps", "good-deck", "--add", "x", "--q", "nope")[1])
        self.assertIn("needs some text", run_cli("gaps", "good-deck", "--add", "  ")[1])
        self.assertIn("no gap at", run_cli("gaps", "good-deck", "--close", "2020-01-01T00:00:00")[1])


class CliImport(TempProjects):
    def export(self, **fields):
        path = self.root / "export.json"
        path.write_text(json.dumps({"format": 1, "deck": "good-deck", "log": [], **fields}), encoding="utf-8")
        return str(path)

    def test_import_merges_and_a_second_import_adds_nothing(self):
        run_cli("record", "good-deck", "s", "good", "--at", "2026-01-02T09:00:00")
        path = self.export(log=[answer("m", "good", "2026-01-01T09:00:00", via="app")])
        self.assertIn("merged 1 new", run_cli("import", "good-deck", path)[1])
        self.assertEqual([e["q"] for e in self.progress()["log"]], ["m", "s"])
        self.assertIn("merged 0 new", run_cli("import", "good-deck", path)[1])

    def test_settings_changed_in_the_app_arrive_with_the_import(self):
        settings = {"minimum": 2, "new_per_day": 9, "anchor": "pour coffee"}
        run_cli("import", "good-deck", self.export(settings=settings, settings_at="2026-01-01T09:00:00"))
        self.assertEqual(self.progress()["settings"], settings)

    def test_an_older_export_doesnt_undo_a_newer_settings_change(self):
        run_cli("settings", "good-deck", "--minimum", "3")
        run_cli("import", "good-deck", self.export(settings={"minimum": 9}, settings_at="2020-01-01T09:00:00"))
        self.assertEqual(self.progress()["settings"]["minimum"], 3)

    def test_bad_rows_are_skipped_and_reported_and_the_deck_keeps_working(self):
        good = answer("m", "good", "2026-01-01T09:00:00")
        bad = answer("s", "good", "2026-13-45T00:00:00")
        code, out = run_cli("import", "good-deck", self.export(log=[bad, good, "junk"]))
        self.assertEqual(code, 0, out)
        self.assertIn("merged 1 new", out)
        self.assertIn("skipped 2 malformed", out)
        self.assertEqual([e["q"] for e in self.progress()["log"]], ["m"])
        for cmd in (("due", "good-deck"), ("status", "good-deck"), ("record", "good-deck", "s", "good")):
            self.assertEqual(run_cli(*cmd)[0], 0)

    def test_fields_of_the_wrong_type_dont_crash_the_import(self):
        code, out = run_cli("import", "good-deck", self.export(settings=[1], feynman=[1], gaps={}))
        self.assertEqual(code, 0, out)

    def test_a_corrupt_progress_file_stops_with_a_message_and_is_left_alone(self):
        path = self.projects / "good-deck" / "progress.json"
        conflict = '{"log": [\n<<<<<<< HEAD\n]}'
        path.write_text(conflict, encoding="utf-8")
        for cmd in (("record", "good-deck", "s", "good"), ("status", "good-deck"), ("settings", "good-deck", "--minimum", "2")):
            code, out = run_cli(*cmd)
            self.assertEqual(code, 1)
            self.assertIn("isn't valid JSON", out)
        self.assertEqual(path.read_text(encoding="utf-8"), conflict)

    def test_refuses_progress_for_another_deck(self):
        path = self.root / "other.json"
        path.write_text(json.dumps({"deck": "other", "log": []}), encoding="utf-8")
        code, out = run_cli("import", "good-deck", str(path))
        self.assertEqual(code, 1)
        self.assertIn("not 'good-deck'", out)

    def test_missing_bad_and_wrong_files_are_friendly_errors(self):
        self.assertIn("can't read", run_cli("import", "good-deck", str(self.root / "nope.json"))[1])
        bad = self.root / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        self.assertIn("not valid JSON", run_cli("import", "good-deck", str(bad))[1])
        bad.write_text("[1, 2]", encoding="utf-8")
        self.assertIn("progress export", run_cli("import", "good-deck", str(bad))[1])
        self.assertFalse((self.projects / "good-deck" / "progress.json").exists())


class TheRepo(unittest.TestCase):
    """Checks on the files that ship in this repo."""

    def test_every_deck_validates_without_errors(self):
        for pid in il.project_ids():
            with self.subTest(pid):
                self.assertEqual(il.validate_deck(il.load_deck(pid), pid)[0], [])

    def test_the_starter_deck_has_no_warnings_either(self):
        self.assertEqual(il.validate_deck(il.load_deck(STARTER), STARTER)[1], [])

    def test_the_starter_deck_uses_every_rung_of_the_ladder(self):
        deck = il.load_deck(STARTER)
        self.assertEqual({q["purpose"] for q in deck["questions"]}, set(il.PURPOSES))
        for concept in deck["concepts"]:
            purposes = {q["purpose"] for q in deck["questions"] if q["concept"] == concept["id"]}
            self.assertIn("pretest", purposes, concept["id"])

    def test_the_manifest_is_up_to_date(self):
        text = json.dumps(il.build_manifest(), ensure_ascii=False, indent=2) + "\n"
        self.assertEqual((il.PROJECTS / "manifest.json").read_text(encoding="utf-8"), text)

    def test_relative_links_in_the_docs_point_at_real_files(self):
        skip = {".git", "templates", "node_modules"}
        docs = [p for p in ROOT.rglob("*.md") if not skip.intersection(p.parts)]
        self.assertGreater(len(docs), 3)
        for doc in docs:
            for target in re.findall(r"\]\((?!https?:|#)([^)#\s]+)", doc.read_text(encoding="utf-8")):
                with self.subTest(doc=doc.name, target=target):
                    self.assertTrue((doc.parent / target).exists())


try:
    import jsonschema
except ImportError:
    jsonschema = None


@unittest.skipIf(jsonschema is None, "pip install jsonschema to run the schema tests")
class Schema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((ROOT / "schema" / "deck.schema.json").read_text(encoding="utf-8"))
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    def errors(self, deck):
        return list(self.validator.iter_errors(deck))

    def test_the_schema_itself_is_valid(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_decks_and_the_template_pass(self):
        for pid in il.project_ids():
            with self.subTest(pid):
                self.assertEqual(self.errors(il.load_deck(pid)), [])
        self.assertEqual(self.errors(good_deck()), [])
        text = (il.TEMPLATES / "deck.json").read_text(encoding="utf-8")
        for key, value in {"id": "x", "title": "X", "kind": "paper", "url": "", "source_title": "S"}.items():
            text = text.replace("{{" + key + "}}", value)
        self.assertEqual(self.errors(json.loads(text)), [])

    def test_structural_mistakes_fail_the_schema_too(self):
        # Rules a schema can't express, such as "prereq listed earlier", stay in il.py only.
        semantic_only = {"forward prereq", "duplicate concept", "duplicate question", "unknown concept",
                         "unknown also"}
        for name, breakit, _ in BROKEN:
            if name in semantic_only:
                continue
            with self.subTest(name):
                d = good_deck()
                breakit(d)
                self.assertTrue(self.errors(d), "schema accepted it")

    def test_the_schema_and_validator_allow_the_same_keys(self):
        props = lambda d: set(d["properties"])  # noqa: E731
        defs = self.schema["$defs"]
        self.assertEqual(props(self.schema), il.DECK_KEYS)
        self.assertEqual(props(defs["source"]), il.SOURCE_KEYS)
        self.assertEqual(props(self.schema["properties"]["habit"]), il.HABIT_KEYS)
        self.assertEqual(props(defs["concept"]), il.CONCEPT_KEYS)
        self.assertEqual(props(defs["question"]), il.QUESTION_KEYS)
        self.assertEqual(props(defs["option"]), il.OPTION_KEYS)

    def test_the_schema_and_validator_allow_the_same_values(self):
        defs = self.schema["$defs"]
        question = defs["question"]["properties"]
        self.assertEqual(set(question["type"]["enum"]), set(il.TYPES))
        self.assertEqual(set(question["purpose"]["enum"]), set(il.PURPOSES))
        self.assertEqual(set(defs["source"]["properties"]["kind"]["enum"]), set(il.KINDS))
        self.assertEqual(defs["id"]["pattern"], il.ID_RE.pattern)


if __name__ == "__main__":
    unittest.main()
