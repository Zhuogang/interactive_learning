#!/usr/bin/env python3
"""il.py: command-line helper for the interactive_learning toolkit.

Standard library only (Python 3.8+). Run from the repo root:

    python3 tools/il.py validate [ID ...]      check deck.json files (all if none given)
    python3 tools/il.py manifest [--check]     rebuild projects/manifest.json
    python3 tools/il.py new ID --title T [--kind paper] [--url U] [--source-title S]
    python3 tools/il.py due ID [--json]        today's queue (reviews, then new cards)
    python3 tools/il.py record ID QID GRADE [--conf guess|think|know] [--score 0..1]
    python3 tools/il.py status ID              mastery, show-up days, calibration
    python3 tools/il.py import ID FILE         merge a progress export from the app

GRADE is one of: again (missed), partly, good.

The scheduling rules below are mirrored in app/index.html. Change both together
(and the table in PRINCIPLES.md section 2).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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
ENTRY_KEYS = ("at", "q", "grade", "conf", "score", "pretest", "via")


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
    entry["score"] = round(SCORE[grade] if score is None else max(0.0, min(1.0, float(score))), 2)
    if q.get("purpose") == "pretest" and q["id"] not in cards:
        entry["pretest"] = True
    entry["via"] = via
    return entry


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


def normalize_progress(p: dict | None, pid: str) -> dict:
    p = dict(p or {})
    out = {"format": FORMAT, "deck": p.get("deck", pid),
           "settings": {**DEFAULT_SETTINGS, **(p.get("settings") or {})},
           "log": [e for e in (p.get("log") or []) if isinstance(e, dict) and "at" in e and "q" in e and "grade" in e],
           "feynman": p.get("feynman") or {}}
    return out


def load_progress(pid: str) -> dict:
    p = progress_path(pid)
    return normalize_progress(load_json(p) if p.exists() else None, pid)


def _flat(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def format_progress(p: dict) -> str:
    """One log entry per line, so git diffs stay readable (same layout as the app's export)."""
    lines = ["{", f'  "format": {p["format"]},', f'  "deck": {json.dumps(p["deck"])},',
             f'  "settings": {_flat(p["settings"])},', '  "log": [']
    for i, e in enumerate(p["log"]):
        ordered = {k: e[k] for k in ENTRY_KEYS if k in e}
        ordered.update({k: v for k, v in e.items() if k not in ordered})
        lines.append("    " + _flat(ordered) + ("," if i < len(p["log"]) - 1 else ""))
    lines.append("  ],")
    feyn = json.dumps(p["feynman"], ensure_ascii=False, indent=2).replace("\n", "\n  ")
    lines.append(f'  "feynman": {feyn}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def save_progress(pid: str, p: dict) -> None:
    progress_path(pid).write_text(format_progress(p), encoding="utf-8")


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
    settings = dict(local["settings"])
    if not settings.get("anchor") and incoming["settings"].get("anchor"):
        settings["anchor"] = incoming["settings"]["anchor"]
    return {**local, "settings": settings, "log": log, "feynman": feynman}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _nonempty_str(x) -> bool:
    return isinstance(x, str) and x.strip() != ""


def validate_deck(deck, folder: str | None = None):
    """Return (errors, warnings) as lists of strings."""
    E, W = [], []
    if not isinstance(deck, dict):
        return ["deck must be a JSON object"], []
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
        if cid in cids:
            E.append(f"{where}: duplicate id")
        for f in ("title", "summary"):
            if not _nonempty_str(c.get(f)):
                E.append(f"{where}: {f} is required")
        for p in c.get("prereqs", []) or []:
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
        if qid in qids:
            E.append(f"{where}: duplicate id")
        qids.add(qid)
        if q.get("concept") not in per_concept:
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
        for a in q.get("also", []) or []:
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
                    elif not _nonempty_str(o.get("why")):
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
            if wl is not None and not (isinstance(wl, int) and wl > 0):
                E.append(f"{where}: word_limit must be a positive integer")
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
        n_c, n_q = len(deck.get("concepts") or []), len(deck.get("questions") or [])
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
        src = d.get("source") or {}
        decks.append({"id": d.get("id", pid), "title": d.get("title", pid),
                      "subtitle": d.get("subtitle", ""), "kind": src.get("kind", "other"),
                      "source": src.get("title", ""), "path": f"{pid}/deck.json",
                      "concepts": len(d.get("concepts") or []),
                      "questions": len(d.get("questions") or [])})
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
            text = text.replace("{{" + k + "}}", v)
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
    due, new = build_queue(deck, prog["log"], prog["settings"], day)
    cards = replay(prog["log"])
    introduced = {q["concept"] for q in deck["questions"]
                  if q["id"] in cards and q.get("purpose") != "pretest"}
    concepts = {c["id"]: c for c in deck["concepts"]}
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
    if args.json:
        print(json.dumps({"day": day, "settings": prog["settings"], "items": items},
                         ensure_ascii=False, indent=2))
        return 0
    s = prog["settings"]
    anchor = f" · anchor: after I {s['anchor']}" if s.get("anchor") else ""
    print(f"{deck['title']}: {day} · minimum {s['minimum']} · {len(due)} due · {len(new)} new{anchor}")
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
    prog = load_progress(args.id)
    cards = replay(prog["log"])
    entry = make_entry(qmap[args.qid], cards, args.grade, args.conf, args.score, args.via, args.at)
    prog["log"].append(entry)
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
    return 0


def cmd_import(args) -> int:
    load_deck(args.id)
    incoming = normalize_progress(load_json(Path(args.file)), args.id)
    if incoming["deck"] != args.id:
        sys.exit(f"error: file is progress for '{incoming['deck']}', not '{args.id}'")
    local = load_progress(args.id)
    merged = merge_progress(local, incoming)
    added = len(merged["log"]) - len(local["log"])
    save_progress(args.id, merged)
    print(f"merged {added} new answers into projects/{args.id}/progress.json")
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
    p.add_argument("--score", type=float, help="0..1, e.g. share of key points hit")
    p.add_argument("--via", default="chat")
    p.add_argument("--at", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("status", help="progress summary")
    p.add_argument("id")
    p.add_argument("--today", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("import", help="merge a progress.json exported from the app")
    p.add_argument("id")
    p.add_argument("file")
    p.set_defaults(fn=cmd_import)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
