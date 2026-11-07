#!/usr/bin/env python3
"""il.py: command-line helper for the interactive_learning toolkit.

Standard library only (Python 3.9+). Run from the repo root:

    python3 tools/il.py validate [ID ...]      check deck.json files (all if none given)
    python3 tools/il.py manifest [--check]     rebuild projects/manifest.json
    python3 tools/il.py new ID --title T [--kind paper] [--url U] [--source-title S]
    python3 tools/il.py due ID [--json]        today's queue (reviews, then new cards)
    python3 tools/il.py record ID QID GRADE [--conf guess|think|know] [--score 0..1]
                        [--text TEXT|-]        add a teach-back (feynman cards; - reads stdin)
    python3 tools/il.py status ID              mastery, show-up days, calibration
    python3 tools/il.py settings ID [--anchor TEXT] [--minimum N] [--new-per-day N]
    python3 tools/il.py gaps ID [--json]       list open gaps (things that confused you)
    python3 tools/il.py gaps ID --add TEXT [--q QID]
    python3 tools/il.py gaps ID --close AT [--card QID]
    python3 tools/il.py import ID FILE         merge a progress export from the app

GRADE is one of: again (missed), partly, good.

The scheduling rules below are mirrored in app/index.html (<script id="core">).
Change both together, plus the table in PRINCIPLES.md section 2. tests/test_parity.py
fails if the two ever disagree.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
TEMPLATES = ROOT / "templates" / "project"

FORMAT = 1
# Leitner box -> days until next review.
INTERVALS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30, 6: 60}
MAX_BOX = 6
GRADES = ("again", "partly", "good")
CONFIDENCE = ("guess", "think", "know")
SCORE = {"again": 0.0, "partly": 0.5, "good": 1.0}
TYPES = ("mcq", "short", "feynman")
PURPOSES = ("pretest", "recall", "explain", "apply", "compare", "teach")
KINDS = ("paper", "book", "chapter", "article", "course", "lecture", "video",
         "topic", "concept", "other")
DEFAULT_SETTINGS = {"minimum": 1, "new_per_day": 5, "anchor": ""}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AT_RE = re.compile(r"[12][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
ENTRY_KEYS = ("at", "q", "grade", "conf", "score", "pretest", "via")
GAP_KEYS = ("at", "q", "text", "closed", "card")

# Every key a deck may use. Anything else is probably a typo, so validate warns.
# schema/deck.schema.json lists the same keys (tests/test_il.py checks they match).
DECK_KEYS = {"$schema", "format", "id", "title", "subtitle", "source", "goal",
             "audience", "habit", "concepts", "questions"}
SOURCE_KEYS = {"kind", "title", "authors", "year", "url", "notes"}
HABIT_KEYS = {"suggested_anchor"}
CONCEPT_KEYS = {"id", "title", "summary", "analogy", "example", "read", "read_url",
                "prereqs", "jargon"}
QUESTION_KEYS = {"id", "concept", "also", "type", "purpose", "prompt", "ref", "explanation",
                 "options", "answer", "key_points", "audience", "word_limit", "rubric",
                 "follow_ups"}
OPTION_KEYS = {"text", "correct", "why"}


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

def today() -> str:
    return dt.date.today().isoformat()


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def add_days(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


# --------------------------------------------------------------------------
# Scheduling (mirror of app/index.html)
# --------------------------------------------------------------------------

def replay(log: list) -> dict:
    """Card state is a pure function of the answer log.

    Rules:
      pretest (first answer of a pretest card) -> box 1
      again  -> box 1
      partly -> stay (at least box 1)
      good   -> up one box, but only the first answer of a day can promote
    next due = answer day + INTERVALS[box]
    """
    cards: dict = {}
    for e in sorted(log, key=lambda e: e["at"]):
        day = e["at"][:10]
        c = cards.get(e["q"]) or {"box": 0, "due": None, "reps": 0, "lapses": 0, "last": None}
        box, lapses = c["box"], c["lapses"]
        grade = e["grade"]
        if e.get("pretest"):
            new = 1
        elif grade == "again":
            new = 1
            if box >= 2:
                lapses += 1
        elif grade == "partly" or c["last"] == day:
            new = max(1, box)
        else:
            new = min(MAX_BOX, box + 1)
        cards[e["q"]] = {"box": new, "due": add_days(day, INTERVALS[new]),
                         "reps": c["reps"] + 1, "lapses": lapses, "last": day}
    return cards


def _rank(q: dict) -> int:
    """Order of unseen cards inside a concept: pretest, then the rest, teach-back last."""
    if q.get("purpose") == "pretest":
        return 0
    if q.get("type") == "feynman":
        return 2
    return 1


def interleave(items: list) -> list:
    """Round-robin across concepts, keeping each concept's internal order."""
    groups: dict = {}
    for q in items:
        groups.setdefault(q["concept"], []).append(q)
    out = []
    while groups:
        for k in list(groups):
            out.append(groups[k].pop(0))
            if not groups[k]:
                del groups[k]
    return out


def first_seen(log: list) -> dict:
    seen: dict = {}
    for e in sorted(log, key=lambda e: e["at"]):
        seen.setdefault(e["q"], e["at"][:10])
    return seen


def build_queue(deck: dict, log: list, settings: dict, day: str):
    """Return (due_reviews, new_cards) for `day`."""
    cards = replay(log)
    qs = deck.get("questions", [])
    order = {c["id"]: i for i, c in enumerate(deck.get("concepts", []))}
    due = [q for q in qs if q["id"] in cards and cards[q["id"]]["due"] <= day]
    due.sort(key=lambda q: (cards[q["id"]]["due"], cards[q["id"]]["box"], order.get(q["concept"], 0)))
    due = interleave(due)

    new_today = sum(1 for d in first_seen(log).values() if d == day)
    budget = max(0, int(settings.get("new_per_day", 5)) - new_today)
    new = []
    for concept in deck.get("concepts", []):
        if budget <= 0:
            break
        unseen = [q for q in qs if q["concept"] == concept["id"] and q["id"] not in cards]
        unseen.sort(key=_rank)  # stable: keeps deck order within a rank
        take = unseen[:budget]
        new += take
        budget -= len(take)
    return due, new


def queue_items(deck: dict, log: list, settings: dict, day: str) -> list:
    """Today's queue as flat items: due reviews first, then new cards.

    A new card gets intro=True when it is the first non-pretest card of its
    concept: that is the moment to show the concept summary (step 2 of the ladder).
    """
    due, new = build_queue(deck, log, settings, day)
    cards = replay(log)
    introduced = {q["concept"] for q in deck.get("questions", [])
                  if q["id"] in cards and q.get("purpose") != "pretest"}
    items = []
    for q in due:
        items.append({"q": q["id"], "concept": q["concept"], "kind": "review",
                      "box": cards[q["id"]]["box"], "type": q["type"], "purpose": q["purpose"],
                      "prompt": q["prompt"]})
    for q in new:
        intro = q.get("purpose") != "pretest" and q["concept"] not in introduced
        if intro:
            introduced.add(q["concept"])
        items.append({"q": q["id"], "concept": q["concept"], "kind": "new", "intro": intro,
                      "type": q["type"], "purpose": q["purpose"], "prompt": q["prompt"]})
    return items


def answered_on(log: list, day: str) -> int:
    return sum(1 for e in log if e["at"][:10] == day)


def make_entry(q: dict, cards: dict, grade: str, conf: str | None = None,
               score: float | None = None, via: str = "chat", at: str | None = None) -> dict:
    """Build a log entry, applying the 'a correct guess counts as partly' rule."""
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}")
    if conf is not None and conf not in CONFIDENCE:
        raise ValueError(f"confidence must be one of {CONFIDENCE}")
    entry = {"at": at or now(), "q": q["id"],
             "grade": "partly" if (grade == "good" and conf == "guess") else grade}
    if conf:
        entry["conf"] = conf
    # The grade is the decision, and calibration reads the score, so they can't disagree.
    # A score only adds detail to "partly": how much of it you had.
    refined = grade == "partly" and score is not None and 0 < float(score) < 1
    entry["score"] = round(float(score) if refined else SCORE[grade], 2)
    if q.get("purpose") == "pretest" and q["id"] not in cards:
        entry["pretest"] = True
    entry["via"] = via
    return entry


def make_teachback(q: dict, text: str, entry: dict) -> dict:
    text = text.strip()
    return {"at": entry["at"], "q": q["id"], "text": text, "words": len(text.split()),
            "score": entry["score"]}


def mastery(deck: dict, cards: dict) -> dict:
    out = {}
    for c in deck.get("concepts", []):
        qs = [q for q in deck.get("questions", []) if q["concept"] == c["id"]]
        if not qs:
            out[c["id"]] = None
            continue
        out[c["id"]] = sum(min(cards.get(q["id"], {}).get("box", 0), 4) / 4 for q in qs) / len(qs)
    return out


def calibration(deck: dict, log: list) -> dict:
    """Mean score per confidence level, excluding pretests."""
    known = {q["id"] for q in deck.get("questions", [])}
    stats = {k: [0, 0.0] for k in CONFIDENCE}
    for e in log:
        if e.get("pretest") or e.get("conf") not in stats or e["q"] not in known:
            continue
        stats[e["conf"]][0] += 1
        stats[e["conf"]][1] += float(e.get("score", SCORE.get(e["grade"], 0)))
    return {k: (n, (s / n if n else None)) for k, (n, s) in stats.items()}


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def deck_path(pid: str) -> Path:
    return PROJECTS / pid / "deck.json"


def progress_path(pid: str) -> Path:
    return PROJECTS / pid / "progress.json"


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_deck(pid: str) -> dict:
    p = deck_path(pid)
    if not p.exists():
        sys.exit(f"error: no deck at {p.relative_to(ROOT)}")
    return load_json(p)


def valid_at(x) -> bool:
    """A real date in the one layout both tools write. Scheduling does date math on these."""
    if not (isinstance(x, str) and AT_RE.fullmatch(x)):
        return False
    try:
        dt.date.fromisoformat(x[:10])
    except ValueError:
        return False
    return True


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _valid_entry(e) -> bool:
    return (isinstance(e, dict) and valid_at(e.get("at")) and isinstance(e.get("q"), str)
            and e.get("grade") in GRADES
            and ("conf" not in e or e["conf"] in CONFIDENCE)
            and ("score" not in e or _is_int(e["score"]) or isinstance(e["score"], float)))


def _clean_settings(x) -> dict:
    out = dict(DEFAULT_SETTINGS)
    if isinstance(x, dict):
        for k, v in x.items():
            if ((k == "anchor" and not isinstance(v, str))
                    or (k == "minimum" and not (_is_int(v) and v >= 1))
                    or (k == "new_per_day" and not (_is_int(v) and v >= 0))):
                continue
            out[k] = v
    return out


def _clean_feynman(x) -> dict:
    if not isinstance(x, dict):
        return {}
    return {c: [e for e in entries if isinstance(e, dict) and valid_at(e.get("at")) and isinstance(e.get("text"), str)]
            for c, entries in x.items() if isinstance(entries, list)}


def normalize_progress(p, pid: str) -> dict:
    """Everything read from a file passes through here, so a bad row can't break scheduling."""
    p = p if isinstance(p, dict) else {}
    log = p.get("log") if isinstance(p.get("log"), list) else []
    gaps = p.get("gaps") if isinstance(p.get("gaps"), list) else []
    return {"format": FORMAT, "deck": p.get("deck", pid),
            "settings": _clean_settings(p.get("settings")),
            "settings_at": p["settings_at"] if valid_at(p.get("settings_at")) else "",
            "log": [e for e in log if _valid_entry(e)],
            "feynman": _clean_feynman(p.get("feynman")),
            "gaps": [g for g in gaps if isinstance(g, dict) and valid_at(g.get("at")) and isinstance(g.get("text"), str)]}


def load_progress(pid: str) -> dict:
    p = progress_path(pid)
    if not p.exists():
        return normalize_progress(None, pid)
    try:
        return normalize_progress(load_json(p), pid)
    except json.JSONDecodeError as ex:
        # Say so and stop: carrying on would overwrite the learner's history.
        sys.exit(f"error: {p.relative_to(ROOT)} isn't valid JSON ({ex}). Fix it by hand; a git merge conflict is a common cause.")


def _flat(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def _rows(entries: list, keys: tuple) -> list:
    """One flat JSON object per line, in a fixed key order."""
    out = []
    for i, e in enumerate(entries):
        ordered = {k: e[k] for k in keys if k in e}
        ordered.update({k: v for k, v in e.items() if k not in ordered})
        out.append("    " + _flat(ordered) + ("," if i < len(entries) - 1 else ""))
    return out


def format_progress(p: dict) -> str:
    """One log entry per line, so git diffs stay readable (byte-identical to the app's export)."""
    lines = ["{", f'  "format": {p["format"]},', f'  "deck": {json.dumps(p["deck"])},',
             f'  "settings": {_flat(p["settings"])},',
             f'  "settings_at": {json.dumps(p.get("settings_at", ""))},', '  "log": [']
    lines += _rows(p["log"], ENTRY_KEYS)
    lines.append("  ],")
    feyn = json.dumps(p["feynman"], ensure_ascii=False, indent=2).replace("\n", "\n  ")
    lines.append(f'  "feynman": {feyn},')
    lines.append('  "gaps": [')
    lines += _rows(p.get("gaps", []), GAP_KEYS)
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def save_progress(pid: str, p: dict) -> None:
    """Write via a temp file: the log is the only copy of your history, so never half-write it."""
    path = progress_path(pid)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(format_progress(p), encoding="utf-8")
    os.replace(tmp, path)


def merge_progress(local: dict, incoming: dict) -> dict:
    key = lambda e: (e["at"], e["q"])  # noqa: E731
    seen = {key(e) for e in local["log"]}
    log = list(local["log"]) + [e for e in incoming["log"] if key(e) not in seen]
    log.sort(key=lambda e: e["at"])
    feynman = {c: list(v) for c, v in local["feynman"].items()}
    for c, entries in incoming["feynman"].items():
        have = {e.get("at") for e in feynman.get(c, [])}
        feynman.setdefault(c, []).extend(e for e in entries if e.get("at") not in have)
        feynman[c].sort(key=lambda e: e.get("at", ""))
    # Settings: whichever side changed them most recently wins. A tie keeps the local copy.
    newer = incoming.get("settings_at", "") > local.get("settings_at", "")
    winner = incoming if newer else local
    gap_key = lambda g: (g["at"], g["text"])  # noqa: E731
    gaps = {gap_key(g): dict(g) for g in local.get("gaps", [])}
    for g in incoming.get("gaps", []):
        have = gaps.get(gap_key(g))
        if have is None:
            gaps[gap_key(g)] = dict(g)
        else:  # closed on either side stays closed
            if g.get("closed"):
                have["closed"] = True
            if g.get("card") and not have.get("card"):
                have["card"] = g["card"]
    return {**local, "settings": dict(winner["settings"]), "settings_at": winner.get("settings_at", ""),
            "log": log, "feynman": feynman, "gaps": sorted(gaps.values(), key=lambda g: g["at"])}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _nonempty_str(x) -> bool:
    return isinstance(x, str) and x.strip() != ""


def _list_of_str(x) -> bool:
    return isinstance(x, list) and all(isinstance(i, str) for i in x)


def _unknown(obj: dict, allowed: set, where: str) -> list:
    return [f"{where}: unknown key '{k}' (typo?)" for k in obj if k not in allowed]


def validate_deck(deck, folder: str | None = None):
    """Return (errors, warnings) as lists of strings."""
    E, W = [], []
    if not isinstance(deck, dict):
        return ["deck must be a JSON object"], []
    W += _unknown(deck, DECK_KEYS, "deck")
    if deck.get("format") != FORMAT:
        E.append(f"format must be {FORMAT}")
    did = deck.get("id")
    if not (isinstance(did, str) and ID_RE.match(did)):
        E.append("id must be lowercase-kebab-case, e.g. 2024-depth-pro")
    elif folder and did != folder:
        E.append(f"id '{did}' must match its folder name '{folder}'")
    if not _nonempty_str(deck.get("title")):
        E.append("title is required")
    src = deck.get("source")
    if not isinstance(src, dict):
        E.append("source is required (object with kind and title)")
    else:
        if src.get("kind") not in KINDS:
            E.append(f"source.kind must be one of {', '.join(KINDS)}")
        if not _nonempty_str(src.get("title")):
            E.append("source.title is required")
        W += _unknown(src, SOURCE_KEYS, "source")
    if "habit" in deck:
        if isinstance(deck["habit"], dict):
            W += _unknown(deck["habit"], HABIT_KEYS, "habit")
        else:
            E.append("habit must be an object")
    concepts = deck.get("concepts")
    questions = deck.get("questions")
    if not isinstance(concepts, list):
        E.append("concepts must be a list")
        concepts = []
    if not isinstance(questions, list):
        E.append("questions must be a list")
        questions = []
    if not concepts:
        W.append("deck has no concepts yet")

    cids: list = []
    for i, c in enumerate(concepts):
        where = f"concepts[{i}]"
        if not isinstance(c, dict):
            E.append(f"{where} must be an object")
            continue
        cid = c.get("id")
        if not (isinstance(cid, str) and ID_RE.match(cid)):
            E.append(f"{where}.id must be lowercase-kebab-case")
            continue
        where = f"concept '{cid}'"
        W += _unknown(c, CONCEPT_KEYS, where)
        if cid in cids:
            E.append(f"{where}: duplicate id")
        for f in ("title", "summary"):
            if not _nonempty_str(c.get(f)):
                E.append(f"{where}: {f} is required")
        prereqs = c.get("prereqs", []) or []
        if not _list_of_str(prereqs):
            E.append(f"{where}: prereqs must be a list of concept ids")
            prereqs = []
        for p in prereqs:
            if p not in cids:
                E.append(f"{where}: prereq '{p}' must be a concept listed earlier")
        if "jargon" in c and not (isinstance(c["jargon"], list) and all(_nonempty_str(j) for j in c["jargon"])):
            E.append(f"{where}: jargon must be a list of strings")
        if not _nonempty_str(c.get("read")):
            W.append(f"{where}: no 'read' pointer into the source")
        cids.append(cid)

    qids: set = set()
    per_concept: dict = {cid: [] for cid in cids}
    for i, q in enumerate(questions):
        where = f"questions[{i}]"
        if not isinstance(q, dict):
            E.append(f"{where} must be an object")
            continue
        qid = q.get("id")
        if not (isinstance(qid, str) and ID_RE.match(qid)):
            E.append(f"{where}.id must be lowercase-kebab-case")
            continue
        where = f"question '{qid}'"
        W += _unknown(q, QUESTION_KEYS, where)
        if qid in qids:
            E.append(f"{where}: duplicate id")
        qids.add(qid)
        if not (isinstance(q.get("concept"), str) and q["concept"] in per_concept):
            E.append(f"{where}: concept '{q.get('concept')}' does not exist")
        else:
            per_concept[q["concept"]].append(q)
        t, purpose = q.get("type"), q.get("purpose")
        if t not in TYPES:
            E.append(f"{where}: type must be one of {', '.join(TYPES)}")
        if purpose not in PURPOSES:
            E.append(f"{where}: purpose must be one of {', '.join(PURPOSES)}")
        if not _nonempty_str(q.get("prompt")):
            E.append(f"{where}: prompt is required")
        if not _nonempty_str(q.get("ref")):
            W.append(f"{where}: no 'ref' (where in the source this is grounded)")
        also = q.get("also", []) or []
        if not _list_of_str(also):
            E.append(f"{where}: also must be a list of concept ids")
            also = []
        for a in also:
            if a not in per_concept:
                E.append(f"{where}: also '{a}' is not a concept")
        if t == "mcq":
            opts = q.get("options")
            if not (isinstance(opts, list) and 2 <= len(opts) <= 6):
                E.append(f"{where}: mcq needs 2-6 options")
            else:
                if sum(1 for o in opts if isinstance(o, dict) and o.get("correct") is True) != 1:
                    E.append(f"{where}: mcq needs exactly one option with \"correct\": true")
                for j, o in enumerate(opts):
                    if not (isinstance(o, dict) and _nonempty_str(o.get("text"))):
                        E.append(f"{where}: options[{j}].text is required")
                        continue
                    W += _unknown(o, OPTION_KEYS, f"{where}: options[{j}]")
                    if not _nonempty_str(o.get("why")):
                        W.append(f"{where}: options[{j}] has no 'why' (feedback for that choice)")
            if purpose == "teach":
                E.append(f"{where}: purpose 'teach' is only for type 'feynman'")
        elif t == "short":
            if not _nonempty_str(q.get("answer")):
                E.append(f"{where}: short needs an 'answer'")
            kp = q.get("key_points")
            if kp is None:
                W.append(f"{where}: no key_points (used for self-grading)")
            elif not (isinstance(kp, list) and kp and all(_nonempty_str(k) for k in kp)):
                E.append(f"{where}: key_points must be a non-empty list of strings")
            if purpose == "teach":
                E.append(f"{where}: purpose 'teach' is only for type 'feynman'")
        elif t == "feynman":
            if purpose != "teach":
                E.append(f"{where}: feynman questions must have purpose 'teach'")
            rub = q.get("rubric")
            if not (isinstance(rub, list) and len(rub) >= 2 and all(_nonempty_str(r) for r in rub)):
                E.append(f"{where}: feynman needs a rubric of at least 2 items")
            wl = q.get("word_limit")
            if wl is not None and not (isinstance(wl, int) and not isinstance(wl, bool) and wl > 0):
                E.append(f"{where}: word_limit must be a positive integer")
            fu = q.get("follow_ups")
            if fu is not None and not (_list_of_str(fu) and all(_nonempty_str(f) for f in fu)):
                E.append(f"{where}: follow_ups must be a list of strings")
        if purpose == "compare" and not q.get("also"):
            W.append(f"{where}: compare question should list the other concept(s) in 'also'")

    for cid, qs in per_concept.items():
        if not qs:
            W.append(f"concept '{cid}': no questions yet")
        elif not any(q.get("purpose") == "pretest" for q in qs):
            W.append(f"concept '{cid}': no pretest question")
    return E, W


def project_ids() -> list:
    return sorted(p.parent.name for p in PROJECTS.glob("*/deck.json"))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def _count(deck, key: str) -> int:
    items = deck.get(key) if isinstance(deck, dict) else None
    return len(items) if isinstance(items, list) else 0


def cmd_validate(args) -> int:
    ids = args.ids or project_ids()
    if not ids:
        print("no projects found")
        return 0
    bad = 0
    for pid in ids:
        p = deck_path(pid)
        if not p.exists():
            print(f"✗ {pid}: no deck.json")
            bad += 1
            continue
        try:
            deck = load_json(p)
        except json.JSONDecodeError as ex:
            print(f"✗ {pid}: invalid JSON: {ex}")
            bad += 1
            continue
        errors, warnings = validate_deck(deck, pid)
        n_c, n_q = (_count(deck, "concepts"), _count(deck, "questions"))
        mark = "✗" if errors else "✓"
        print(f"{mark} {pid}: {n_c} concepts, {n_q} questions"
              f"{f', {len(errors)} errors' if errors else ''}{f', {len(warnings)} warnings' if warnings else ''}")
        for e in errors:
            print(f"    error: {e}")
        if not args.quiet:
            for w in warnings:
                print(f"    warn:  {w}")
        bad += bool(errors)
    return 1 if bad else 0


def build_manifest() -> dict:
    decks = []
    for pid in project_ids():
        try:
            d = load_json(deck_path(pid))
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        src = d.get("source") if isinstance(d.get("source"), dict) else {}
        decks.append({"id": d.get("id", pid), "title": d.get("title", pid),
                      "subtitle": d.get("subtitle", ""), "kind": src.get("kind", "other"),
                      "source": src.get("title", ""), "path": f"{pid}/deck.json",
                      "concepts": _count(d, "concepts"),
                      "questions": _count(d, "questions")})
    return {"format": FORMAT, "decks": decks}


def cmd_manifest(args) -> int:
    text = json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n"
    path = PROJECTS / "manifest.json"
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != text:
            print("projects/manifest.json is out of date; run: python3 tools/il.py manifest")
            return 1
        print("manifest up to date")
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"wrote projects/manifest.json ({len(build_manifest()['decks'])} decks)")
    return 0


def cmd_new(args) -> int:
    pid = args.id
    if not ID_RE.match(pid):
        sys.exit("error: id must be lowercase-kebab-case, e.g. 2024-depth-pro")
    if args.kind not in KINDS:
        sys.exit(f"error: --kind must be one of {', '.join(KINDS)}")
    dest = PROJECTS / pid
    if dest.exists():
        sys.exit(f"error: projects/{pid} already exists")
    if not any(p.is_file() for p in TEMPLATES.rglob("*")):
        sys.exit(f"error: no templates in {TEMPLATES}")
    values = {"id": pid, "title": args.title, "kind": args.kind, "url": args.url or "",
              "source_title": args.source_title or args.title, "date": today()}
    for src in sorted(TEMPLATES.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(TEMPLATES)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8")
        for k, v in values.items():
            # In JSON files a value lands inside a string, so it needs escaping ("A "quoted" title").
            filled = json.dumps(v, ensure_ascii=False)[1:-1] if src.suffix == ".json" else v
            text = text.replace("{{" + k + "}}", filled)
        out.write_text(text, encoding="utf-8")
    print(f"created projects/{pid}/ ({', '.join(str(p.relative_to(dest)) for p in sorted(dest.rglob('*')) if p.is_file())})")
    cmd_manifest(argparse.Namespace(check=False))
    return 0


def _preview(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def cmd_due(args) -> int:
    deck = load_deck(args.id)
    prog = load_progress(args.id)
    day = args.today or today()
    items = queue_items(deck, prog["log"], prog["settings"], day)
    answered = answered_on(prog["log"], day)
    concepts = {c["id"]: c for c in deck["concepts"]}
    if args.json:
        print(json.dumps({"day": day, "settings": prog["settings"], "answered_today": answered,
                          "items": items}, ensure_ascii=False, indent=2))
        return 0
    s = prog["settings"]
    anchor = f" · anchor: after I {s['anchor']}" if s.get("anchor") else ""
    n_due = sum(1 for it in items if it["kind"] == "review")
    print(f"{deck['title']}: {day} · minimum {s['minimum']} · answered today {answered}"
          f" · {n_due} due · {len(items) - n_due} new{anchor}")
    if not items:
        print("All caught up. Nothing due today.")
    for i, it in enumerate(items, 1):
        tag = f"review·box{it['box']}" if it["kind"] == "review" else "new"
        if it.get("intro"):
            print(f"   ↳ introduce concept: {concepts[it['concept']]['title']}")
        print(f"{i:>3}. [{tag}·{it['purpose']}] {it['q']}: {_preview(it['prompt'])}")
    return 0


def cmd_record(args) -> int:
    deck = load_deck(args.id)
    qmap = {q["id"]: q for q in deck["questions"]}
    if args.qid not in qmap:
        sys.exit(f"error: no question '{args.qid}' in {args.id}")
    q = qmap[args.qid]
    text = None
    if args.text is not None:
        if q.get("type") != "feynman":
            sys.exit(f"error: --text is for teach-it cards, and '{args.qid}' is type '{q.get('type')}'")
        text = sys.stdin.read() if args.text == "-" else args.text
    prog = load_progress(args.id)
    cards = replay(prog["log"])
    entry = make_entry(q, cards, args.grade, args.conf, args.score, args.via, args.at)
    prog["log"].append(entry)
    if text and text.strip():
        prog["feynman"].setdefault(q["concept"], []).append(make_teachback(q, text, entry))
    save_progress(args.id, prog)
    c = replay(prog["log"])[args.qid]
    note = " (a correct guess counts as partly)" if entry["grade"] != args.grade else ""
    note += " (pretest → box 1)" if entry.get("pretest") else ""
    print(f"recorded {args.qid}: {entry['grade']}{note} → box {c['box']}, next review {c['due']}")
    return 0


def cmd_status(args) -> int:
    deck = load_deck(args.id)
    prog = load_progress(args.id)
    cards = replay(prog["log"])
    day = args.today or today()
    due, new = build_queue(deck, prog["log"], prog["settings"], day)
    qids = {q["id"] for q in deck["questions"]}
    started = sum(1 for q in qids if q in cards)
    days = {e["at"][:10] for e in prog["log"]}
    last28 = sum(1 for i in range(28) if add_days(day, -i) in days)
    print(f"{deck['title']}")
    print(f"  {started}/{len(qids)} cards started · {len(due)} due today · {len(new)} new available")
    print(f"  show-up days: {last28} of the last 28 · {len(days)} total")
    m = mastery(deck, cards)
    width = max((len(c["title"]) for c in deck["concepts"]), default=10)
    for c in deck["concepts"]:
        v = m[c["id"]]
        if v is None:
            print(f"  {c['title']:<{width}}  (no questions)")
            continue
        bar = "█" * round(v * 10) + "░" * (10 - round(v * 10))
        boxes = [cards.get(q["id"], {}).get("box", 0) for q in deck["questions"] if q["concept"] == c["id"]]
        print(f"  {c['title']:<{width}}  {bar} {v:>4.0%}  boxes {''.join(str(b) for b in boxes)}")
    cal = calibration(deck, prog["log"])
    parts = [f"{k} {s:.0%} (n={n})" for k, (n, s) in cal.items() if n >= 3]
    if parts:
        print("  calibration (how often you're right at each confidence): " + " · ".join(parts))
    if prog["feynman"]:
        print(f"  teach-backs saved: {sum(len(v) for v in prog['feynman'].values())}")
    open_gaps = sum(1 for g in prog["gaps"] if not g.get("closed"))
    if open_gaps:
        print(f"  open gaps: {open_gaps} (see: python3 tools/il.py gaps {args.id})")
    return 0


def cmd_settings(args) -> int:
    load_deck(args.id)
    prog = load_progress(args.id)
    s = prog["settings"]
    changed = False
    if args.anchor is not None:
        s["anchor"] = args.anchor.strip()
        changed = True
    if args.minimum is not None:
        if args.minimum < 1:
            sys.exit("error: --minimum must be at least 1")
        s["minimum"] = args.minimum
        changed = True
    if args.new_per_day is not None:
        if args.new_per_day < 0:
            sys.exit("error: --new-per-day can't be negative")
        s["new_per_day"] = args.new_per_day
        changed = True
    if changed:
        prog["settings_at"] = now()
        save_progress(args.id, prog)
    print(f"minimum {s['minimum']} · new per day {s['new_per_day']} · anchor: {s['anchor'] or '(none yet)'}")
    return 0


def cmd_gaps(args) -> int:
    deck = load_deck(args.id)
    prog = load_progress(args.id)
    qids = {q["id"] for q in deck["questions"]}
    for qid, flag in ((args.q, "--q"), (args.card, "--card")):
        if qid and qid not in qids:
            sys.exit(f"error: {flag}: no question '{qid}' in {args.id}")
    if args.add is not None:
        if not args.add.strip():
            sys.exit("error: --add needs some text")
        at = now()
        taken = {g["at"] for g in prog["gaps"]}
        while at in taken:  # timestamps identify gaps, and these have one-second resolution
            at = (dt.datetime.fromisoformat(at) + dt.timedelta(seconds=1)).isoformat()
        gap = {"at": at, "text": args.add.strip()}
        if args.q:
            gap["q"] = args.q
        prog["gaps"].append(gap)
        save_progress(args.id, prog)
        print(f"noted gap {gap['at']}: {_preview(gap['text'])}")
        return 0
    if args.close is not None:
        hits = [g for g in prog["gaps"] if g["at"] == args.close]
        if not hits:
            sys.exit(f"error: no gap at '{args.close}'; list them with: python3 tools/il.py gaps {args.id}")
        for g in hits:
            g["closed"] = True
            if args.card:
                g["card"] = args.card
        save_progress(args.id, prog)
        print(f"closed gap {args.close}{f' → card {args.card}' if args.card else ''}")
        return 0
    gaps = [g for g in prog["gaps"] if not g.get("closed")]
    if args.json:
        print(json.dumps(gaps, ensure_ascii=False, indent=2))
        return 0
    if not gaps:
        print("No open gaps.")
    for g in gaps:
        about = f" [{g['q']}]" if g.get("q") else ""
        print(f"{g['at']}{about}: {g['text']}")
    return 0


def cmd_import(args) -> int:
    load_deck(args.id)
    try:
        raw = load_json(Path(args.file))
    except OSError as ex:
        sys.exit(f"error: can't read {args.file}: {ex.strerror}")
    except json.JSONDecodeError as ex:
        sys.exit(f"error: {args.file} is not valid JSON: {ex}")
    if not (isinstance(raw, dict) and isinstance(raw.get("log"), list)):
        sys.exit(f"error: {args.file} doesn't look like a progress export (no 'log' list)")
    incoming = normalize_progress(raw, args.id)
    if incoming["deck"] != args.id:
        sys.exit(f"error: file is progress for '{incoming['deck']}', not '{args.id}'")
    local = load_progress(args.id)
    merged = merge_progress(local, incoming)
    added = len(merged["log"]) - len(local["log"])
    save_progress(args.id, merged)
    skipped = len(raw["log"]) - len(incoming["log"])
    note = f" (skipped {skipped} malformed)" if skipped else ""
    print(f"merged {added} new answers into projects/{args.id}/progress.json{note}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="il.py", description="interactive_learning toolkit helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="check deck.json files")
    p.add_argument("ids", nargs="*")
    p.add_argument("-q", "--quiet", action="store_true", help="hide warnings")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("manifest", help="rebuild projects/manifest.json")
    p.add_argument("--check", action="store_true", help="fail if the manifest is out of date")
    p.set_defaults(fn=cmd_manifest)

    p = sub.add_parser("new", help="scaffold a project from templates/project")
    p.add_argument("id")
    p.add_argument("--title", required=True)
    p.add_argument("--kind", default="paper")
    p.add_argument("--url")
    p.add_argument("--source-title")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("due", help="today's queue")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--today", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_due)

    p = sub.add_parser("record", help="log one answer")
    p.add_argument("id")
    p.add_argument("qid")
    p.add_argument("grade", choices=GRADES)
    p.add_argument("--conf", choices=CONFIDENCE)
    p.add_argument("--score", type=float, help="with partly: how much you had, e.g. 0.67 for 2 of 3 key points")
    p.add_argument("--via", default="chat")
    p.add_argument("--text", help="teach-back text for a feynman card; - reads it from stdin")
    p.add_argument("--at", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("status", help="progress summary")
    p.add_argument("id")
    p.add_argument("--today", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("settings", help="show or change the anchor, minimum and new cards per day")
    p.add_argument("id")
    p.add_argument("--anchor", metavar="TEXT", help="the routine in 'After I ___, I will answer one card'")
    p.add_argument("--minimum", type=int, metavar="N")
    p.add_argument("--new-per-day", type=int, metavar="N")
    p.set_defaults(fn=cmd_settings)

    p = sub.add_parser("gaps", help="list, add or close gaps (things that confused you)")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--add", metavar="TEXT", help="note a new gap")
    p.add_argument("--q", metavar="QID", help="with --add: the card it came up on")
    p.add_argument("--close", metavar="AT", help="close the gap with this timestamp")
    p.add_argument("--card", metavar="QID", help="with --close: the card that now covers it")
    p.set_defaults(fn=cmd_gaps)

    p = sub.add_parser("import", help="merge a progress.json exported from the app")
    p.add_argument("id")
    p.add_argument("file")
    p.set_defaults(fn=cmd_import)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
