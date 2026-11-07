# Build a deck from a source

Use this when the learner says "build a deck from ___" or "I want to learn ___". The rules in [CLAUDE.md](../CLAUDE.md) apply throughout.

A deck is only as trustworthy as its grounding. **Build from the source itself, not from what you remember about it.**

## 1. Agree on the scope

Ask only what you can't work out, in one message:

- **What's the source?** A file, a link, or a chapter of a book. If you can't read it (paywall, unreadable PDF), say so and ask for the text. Don't build from memory.
- **What do you want to be able to do with it?** This becomes `goal`.
- **What do you already know?** This becomes `audience`, and it decides which ideas need prerequisites.

**Start small.** Cover one chapter, one section or a handful of concepts. A 300-card deck on day one is an anti-pattern. Decks grow just in time, as the learner gets there.

## 2. Scaffold

```bash
python3 tools/il.py new 2024-depth-pro --title "Depth Pro" --kind paper \
  --url "https://example.com/paper" --source-title "Depth Pro: Sharp Monocular Metric Depth"
```

This creates `projects/ID/deck.json` and `README.md` and updates the manifest. Kinds: `paper`, `book`, `chapter`, `article`, `course`, `lecture`, `video`, `topic`, `concept`, `other`.

## 3. Read the whole source first

Finish reading before you write a card. Note the section or page for each idea as you go, because every card has to point back to where it came from.

## 4. Propose the concepts, then stop

Send a short list: 5 to 10 concepts, each with a title and one line, in the order they should be learned. Choose the ideas someone would need in order to explain the source to a friend, not whatever is easiest to quiz. Skip trivia such as dates, author names and dataset names, unless they're the point.

**Wait for the learner's OK before writing cards.** This is the cheapest moment to fix the scope.

## 5. Write each concept

```json
{
  "id": "spacing",
  "title": "Spacing",
  "summary": "Two short paragraphs at most, in plain words. Supports **bold**, *italic*, `code`, links and blank-line paragraphs.",
  "analogy": "Optional: only if it clarifies rather than decorates.",
  "example": "A concrete case.",
  "read": "Section 2, pages 3-5",
  "read_url": "https://example.com/paper#section-2",
  "prereqs": ["retrieval"],
  "jargon": ["spacing effect", "distributed practice"]
}
```

Prereqs must be concepts listed earlier. `jargon` lists the terms the app flags while the learner writes a teach-it card, so use real terms of art and leave out everyday words.

## 6. Write the cards, climbing the ladder

Each concept gets about 4 to 6 cards. The scheduler handles the order: pretest first, teach-it last.

| `purpose` | Which concepts | What it tests |
|---|---|---|
| `pretest` | Every concept, one card | A guess before studying. Must be guessable from common sense, and about the big idea. |
| `recall` | Every concept | The core idea, pulled from memory. |
| `explain` | Every concept | Why or how it works, in their own words. |
| `apply` | Every concept | The idea used in a new situation, not one from the source. |
| `compare` | Where there's a confusable neighbor | Telling two concepts apart. List the other concept in `also`. |
| `teach` | Key concepts only, about half | A plain-words explanation for a novice. |

### Every card

```json
{ "id": "spacing-why", "concept": "spacing", "type": "short", "purpose": "explain",
  "prompt": "...", "ref": "Section 2, p. 4" }
```

`ref` is required in practice: it's how a learner checks a card that looks wrong. Be specific, with a section, page, figure or timestamp. IDs are lowercase-kebab-case and usually start with the concept.

### Multiple choice (`"type": "mcq"`)

```json
"options": [
  { "text": "Plausible but wrong", "why": "Why it's tempting, and why it's wrong." },
  { "text": "The right answer", "correct": true, "why": "Why it's right." }
],
"explanation": "Optional: the wider point, with its citation."
```

- 3 or 4 options, exactly one correct, and a `why` on every one. The feedback on wrong answers is where much of the teaching happens.
- Wrong options should be real misconceptions, not filler.
- Keep the options similar in length and style, so the longest one isn't always correct.
- Avoid "all of the above" and trick wording.

### Short answer (`"type": "short"`)

```json
"answer": "A model answer in two or three sentences.",
"key_points": ["An idea a good answer must contain", "Another one"]
```

Use 2 to 4 key points. They're how the learner grades themselves, so each should name an idea, and be checkable as yes or no.

### Teach it (`"type": "feynman"`, `"purpose": "teach"`)

```json
"prompt": "Explain to a curious 12-year-old why ...",
"audience": "a curious 12-year-old",
"word_limit": 100,
"rubric": ["Says X", "Explains why Y", "Uses an example or analogy", "No unexplained jargon"],
"follow_ups": ["But if I ..., why isn't that enough?", "What if ...?"]
```

Write `follow_ups` in the audience's voice, aimed at the part people tend to hand-wave.

### What makes a good card

Adapted from Matuschak (2020) and Wozniak (1999):

- **Focused.** One idea per card. If an answer needs "and", consider two cards.
- **Precise.** The question has one clear reading, and the learner can tell whether they got it.
- **Effortful.** The answer must come from memory, not from the wording of the question.
- **Consistent.** Asked again next month, it should have the same answer. Avoid "name an example" unless any example will do.
- **Understood first.** Cards reinforce understanding but can't replace it. If an idea doesn't make sense yet, it needs a better summary, not more cards.
- **Not a yes/no.** Ask why, how or which.

The app doesn't render math, so write equations in plain text or Unicode (`loss = (y - ŷ)²`), or in `code`.

## 7. Check it

```bash
python3 tools/il.py validate ID
python3 tools/il.py manifest
```

Fix every error, and every warning you can. Then **audit the deck against the source**: go through the cards one at a time, reopen each `ref`, and confirm the card says what the source says. AI-built decks can contain mistakes, and this is where you catch them. Tell the learner about anything you couldn't verify.

## 8. Hand it over

Say what you built in a line or two: how many concepts and cards, and which part of the source they cover. Then offer the first step: "Say *session* to start, or open the app. Your minimum is one card."

## Adding a card

When a gap or a new question comes up, add a card to the existing deck:

1. Check the source first. If the source doesn't answer it, say so instead of inventing a card.
2. Add it to `questions`, with a new ID and a `ref`. New cards are safe to add at any time, since progress is keyed by card ID.
3. Run `python3 tools/il.py validate ID && python3 tools/il.py manifest`.
4. If it came from a gap, close that gap: `python3 tools/il.py gaps ID --close AT --card NEW-CARD-ID`.

**Don't rename a card's ID:** its history would be orphaned. Fixing a typo in the wording is fine. If you change what a card asks, give it a new ID.
