# {{title}}

- **Source:** {{source_title}} {{url}}
- **Started:** {{date}}
- **Why I'm learning this:** _one sentence. What will you be able to do?_

## My habit

> **After I** _[something you already do every day]_, **I will** answer one card. Then I'll _[celebrate]_.

## Files

- `deck.json`: the concepts and cards. Build it with `prompts/build.md`, or by hand.
- `progress.json`: your answer history. It appears after your first recorded answer, and git ignores it.

## Commands

```bash
python3 tools/il.py validate {{id}}   # check the deck
python3 tools/il.py due {{id}}        # what's up today
python3 tools/il.py status {{id}}     # how it's going
python3 tools/il.py gaps {{id}}       # things that confused you
```
