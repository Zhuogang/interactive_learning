# Interactive Learning

> **Pull ideas out of your head, a little every day, in your own words.**

A small toolkit for actually learning papers, books and courses. Turn a source into a deck of questions, then answer one card a day, in a browser or in a chat with an AI tutor.

It's built on three ideas, explained with their evidence in [PRINCIPLES.md](PRINCIPLES.md):

- **Learning science:** retrieve instead of rereading, space it out, mix it up, guess first, check yourself.
- **Tiny Habits and Mini Habits:** attach it to something you already do, keep the minimum too small to fail, and celebrate.
- **The Feynman technique:** explain it simply, and let your gaps tell you what to study next.

## Try it

You need Python 3.9+ and a browser. There's nothing to install.

```bash
git clone https://github.com/zhuogang/interactive_learning.git
cd interactive_learning
python3 -m http.server 8000
```

Open <http://localhost:8000/app/>. The [starter deck](projects/learning-how-to-learn/) quizzes you on the method itself, so you learn it by using it.

**One card is a full day.** The app stops and celebrates after your first card. Keep going if you feel like it.

## Study with an AI tutor

Open this repo in [Claude Code](https://claude.com/claude-code). [CLAUDE.md](CLAUDE.md) tells it how to tutor you. With other assistants, point them at that file and the [prompts](prompts/).

| Say | What happens |
|---|---|
| `session` | One question at a time, graded and scheduled. It stops at your minimum. ([prompt](prompts/session.md)) |
| `build a deck from <paper or link>` | Reads the source, proposes concepts for your OK, then writes the cards. ([prompt](prompts/build.md)) |
| `check my explanation` | A coach who asks questions instead of rewriting your words. ([prompt](prompts/feynman.md)) |
| `I'm confused about ___` | A short answer, and the gap can become a new card. |
| `how am I doing?` | Mastery, show-up days, and how well your confidence matches your results. |

## Make your own deck

Ask your tutor (above), or write one yourself:

```bash
python3 tools/il.py new 2024-depth-pro --title "Depth Pro" --kind paper --url "https://example.com/paper"
# edit projects/2024-depth-pro/deck.json
python3 tools/il.py validate 2024-depth-pro
python3 tools/il.py manifest
```

[prompts/build.md](prompts/build.md) covers how to write good cards, and [the schema](schema/deck.schema.json) documents every field. The [starter deck](projects/learning-how-to-learn/deck.json) is a full example.

**AI-built decks can contain mistakes.** Every card carries a `ref` back into the source. If a card looks wrong, check the source and fix the card.

## How a card works

1. **Guess.** Each new concept starts with a guess, and wrong guesses don't count against you.
2. **Read.** A short summary, and a pointer into the source.
3. **Answer, then rate yourself.** Pick *Guessing*, *I think so* or *I know it*. The answer stays hidden until you do.
4. **Space it out.** Cards move through six boxes, from 1 day up to 2 months. A miss goes back to box 1. A correct guess counts as partly.

## Your progress

Answers are stored as a plain log, and each card's schedule is worked out from it.

| Where you study | Where it's saved |
|---|---|
| In the app | This browser's storage. Use **Settings and your data → Export progress** to keep a copy. |
| In chat or the CLI | `projects/<id>/progress.json` |

They connect like this:

- **Chat to app:** automatic. The app reads `progress.json` whenever you open a deck or come back to its tab.
- **App to chat:** export from the app, then run `python3 tools/il.py import <id> progress-<id>.json`.

**Git ignores `progress.json`,** because this repo is public and the file includes your teach-back explanations. That also means git isn't backing it up. To keep your history in a private fork, remove the `projects/*/progress.json` line from `.gitignore`. The file has one answer per line, so the diffs stay readable.

## Command reference

```bash
python3 tools/il.py validate [ID ...]      # check decks
python3 tools/il.py manifest [--check]     # rebuild the deck list the app reads
python3 tools/il.py new ID --title T [--kind paper] [--url U] [--source-title S]
python3 tools/il.py due ID [--json]        # today's queue
python3 tools/il.py record ID QID GRADE [--conf guess|think|know] [--score 0..1] [--text TEXT|-]
python3 tools/il.py status ID              # mastery, show-up days, calibration
python3 tools/il.py settings ID [--anchor TEXT] [--minimum N] [--new-per-day N]
python3 tools/il.py gaps ID [--json]       # things that confused you
python3 tools/il.py gaps ID --add TEXT [--q QID]
python3 tools/il.py gaps ID --close AT [--card QID]
python3 tools/il.py import ID FILE         # merge a progress export from the app
```

`GRADE` is `again` (missed), `partly` or `good`.

## What's here

```
PRINCIPLES.md        the method and its evidence
CLAUDE.md            the tutor contract
app/index.html       the browser app: one file, no build, no dependencies
tools/il.py          the CLI: Python standard library only
prompts/             how to run a session, build a deck, coach an explanation
schema/              JSON Schema for deck.json
templates/project/   what `il.py new` copies
projects/            one folder per deck
tests/               unit tests, and app-vs-CLI parity tests
```

The app works on any static host, since it only reads files from `projects/`. It needs to be served over HTTP: browsers block loading decks from a page opened as a `file://`. If you open it that way, it explains this and lets you pick a `deck.json` by hand.

## Development

```bash
python3 -m unittest discover -s tests
```

The parity tests need Node, and the schema tests need `pip install jsonschema`. Each group skips itself if its tool is missing.

`tests/e2e.js` drives the app in a real browser, along with the real CLI, against a throwaway copy of the repo:

```bash
npm install --no-save playwright && npx playwright install chromium
node tests/e2e.js
```

The scheduling rules live in both `tools/il.py` and `app/index.html`. The parity tests run the app's code against the CLI on randomized histories, so the two can't quietly drift apart. See "Working on the toolkit itself" in [CLAUDE.md](CLAUDE.md).

## License

[GPL-3.0](LICENSE)
