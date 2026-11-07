# Run a study session in chat

Use this when the learner says "session", "quiz me" or similar. The rules in [CLAUDE.md](../CLAUDE.md) apply throughout. The biggest one: **no answer appears until they've committed to one.**

## Start

1. **Pick the deck.** `projects/manifest.json` lists them. If there's only one, use it. If there are several, ask which, or use the one they've been studying.
2. **Get the queue.**
   ```bash
   python3 tools/il.py due ID --json
   ```
   This prints `answered_today`, `settings` and `items` in today's order: due reviews, then new cards. It includes prompts but no answers.
3. **Read `projects/ID/deck.json` quietly** for each card's options, answer and key points. Don't print it where the learner can see it.
4. **Open in one line.** For example: "3 due and 2 new. Your minimum is one card."
   - If `answered_today` already meets the minimum, say so: "Today already counts, so these are bonus reps."
   - If `settings.anchor` is empty, ask once: "Want to pick a habit? *After I ___, I will answer one card.*" An anchor is something they already do every day. Save it with `python3 tools/il.py settings ID --anchor "pour my coffee"`. If they'd rather not, move on.

If `items` is empty, say nothing is due and that the gap is part of how this works. Don't fill the time with rereading.

## Each card

Work through `items` in order. Ask one card per message.

**1. Introduce (only if `intro` is true).** Before the card, share the concept's `summary`, plus its `analogy`, `example` and `read` pointer if it has them. Ask them to say when they're ready. Keep it short.

**2. Ask.**

| Card | What to send |
|---|---|
| `mcq` | The prompt and the options as A, B, C, D, shuffled. Leave out every `why` and any hint about which is right. |
| `short` | The prompt. "Type it, or say it out loud and tell me how it went." |
| `feynman` | Switch to [feynman.md](feynman.md), then come back here. |
| First time on a `pretest` card | Same as its type, plus: "This is a guess. You haven't studied it yet, and wrong guesses help." |

A card in the queue with `"kind": "review"` isn't a first attempt, so treat a pretest card there like any other review.

**3. Commit.** Get their answer *and* their confidence before you reveal anything: **Guessing**, **I think so** or **I know it**. They can reply in one go ("B, think so"). First-time pretests don't need a rating, because they are guesses (`--conf guess`).

If they ask for the answer without trying, ask for any guess first. If they still want it, show it and record `again`.

**4. Reveal and grade.**

- **`mcq`:** right is `good`, wrong is `again`. Share the `why` for what they picked and for the correct option, and the `explanation` if there is one.
- **`short`:** compare with `key_points`. Grade the ideas, not the wording. All of them is `good`, some is `partly`, none is `again`. Show the `answer` and say which points they hit. For `partly`, use `--score` for the share (2 of 3 is `0.67`). If they make a good case that they had it, take their word and grade it that way.
- **If they were confident and wrong,** say so kindly: confident mistakes are the ones people fix best.

**5. Record.** Do this before moving on.

```bash
python3 tools/il.py record ID QID GRADE --conf guess|think|know [--score 0.67]
```

Tell them the result in a few words, using the command's output: "Up to box 2, back in 3 days." The tool applies the scheduling rules, including "a correct guess counts as partly", so pass the grade they actually earned.

**6. Bring misses back.** A card graded `again` returns after about three other cards. Ask it again and record it again, at most twice. First-time pretests don't come back, because the answer was just shown.

## The minimum

Count `answered_today` plus every answer this session. **The moment that count reaches `settings.minimum`, stop and celebrate**, even if it feels like you've only just started. This only happens once a day.

> That's today's card. Today is a full success. Celebrate now: a fist pump, a "Yes!", anything that feels good. That feeling is what wires in the habit.
>
> Stop here, or keep going? Both are good.

If they stop, end warmly and don't list what's left. If they keep going, those are bonus reps. Don't count them down.

If the queue runs out before the minimum, that's a full success too: they did everything there was to do. Celebrate the same way.

## Gaps

When something confuses them, answer briefly and note it:

```bash
python3 tools/il.py gaps ID --add "why does a gap help if you forget?" --q QID
```

Don't derail the session. At the end, offer to turn open gaps into cards (see "Adding a card" in [build.md](build.md)). Close each gap once a card covers it, using the timestamp from `python3 tools/il.py gaps ID`:

```bash
python3 tools/il.py gaps ID --close 2026-01-05T08:03:11 --card NEW-CARD-ID
```

Gaps the learner noted in the app arrive here after `python3 tools/il.py import`.

## Finish

End in a line or two: how many they answered and when the next review is. For the longer view, `python3 tools/il.py status ID` shows mastery, show-up days and calibration. Share it if they ask, or if the calibration says something useful ("when you say *I know it*, you're right 95% of the time").

Getting 60% right is normal and healthy, so never present it as a poor result.
