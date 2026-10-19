---
name: tour
description: Explains the current plan (or a project topic) as an animated, narrated story in the browser, like an explainer video. Use ONLY when the user explicitly asks for a tour, a plan tour or an animated/narrated walkthrough of the plan (in any language, e.g. "plan tour", "explain the plan as a tour", "tour del plan"). Never use it for ordinary plans or explanations.
argument-hint: "[quick|standard|deep] [optional topic]"
allowed-tools: Bash(python *) Bash(py *) Bash(python3 *)
---

# Plan Tour

Turn the plan (or whatever the user wants to understand) into an **animated story**, like a YouTube explainer video: the screen starts empty, characters and components appear when the voice names them, the request travels between them as an envelope, and the camera follows the action. No slides, no bullet points. You publish scenes **one at a time** so the user starts watching right away, following an outline you write first. Questions and adjustments arrive through this chat.

**Arguments:** $ARGUMENTS

- If they start with `quick`, `standard` or `deep`, that is the depth: don't ask. The rest is the topic.
- Otherwise it's all topic. With no topic, explain the most recent plan in this conversation. With no plan and no topic, ask what they want to understand and don't start anything.

The engine is `${CLAUDE_SKILL_DIR}/scripts/tour.py`. Run every command from the project root. On Windows, if `python` doesn't exist, use `py`; elsewhere you may need `python3` (from here on, `python` means whichever works).

**Language.** This skill is written in English, but **everything the user sees or hears in the tour** (narration, scene titles, actor labels, notes, envelope labels, big statements, the outline and the questions you ask) is in **the user's language**: the language they write to you in. The written plan is published verbatim, in whatever language it was written.

**Permissions rule.** Never use Write, Edit or any file tool for the tour, and never write anything in the project or its `.claude` folder. Everything goes through `tour.py` commands with JSON on stdin (heredoc). This also works in plan mode.

## 1. Choose the depth

If the arguments don't set it, ask **a single question** with AskUserQuestion before anything else, in the user's language. In English it would be:

- Question: `How deep should the tour go?` (header: `Depth`)
- Options, in this order:
  1. `Standard (Recommended)`: 4–6 scenes: the story, where it breaks and the fix
  2. `Quick`: 3 scenes: just what changes and why
  3. `Deep`: 6–10 scenes: down to the code, edge cases and trade-offs

If they answer with free text, take the depth and focus from it. Don't ask anything else.

| Depth | Scenes | Content |
|---|---|---|
| **Quick** | 3 | The question, what changes, how it ends up. No code. |
| **Standard** | 4–6 | The question, the case's journey, the twist (where it breaks or what must change), the fix, the decisions that need their input. At most one code card. |
| **Deep** | 6–10 | Everything in Standard, plus code cards at the key points, edge cases and discarded alternatives. |

## 2. How to tell it: explainer-video style

How you tell the story is what makes it understandable. Always follow these rules:

1. **It's a story with a protagonist.** Pick a concrete, real case from the domain, with a person and a situation ("Ana, from support, opens Orders and picks Lola's Store"), and follow it from start to finish. Everything technical is explained through what happens to that case.
2. **Four beats.** The question (what happens to the protagonist, as a hook), the journey (where their request travels, step by step), the twist (the exact moment it breaks, or where the change goes) and the fix (the same journey, now working). For a plan that isn't a bug fix, the twist is "what changes and why".
3. **One thing per sentence, and the screen shows it.** Each narrated sentence carries its actions: if you say "the request reaches the gatekeeper", the envelope travels to the gatekeeper right then. If a sentence makes nothing happen on screen, merge it or cut it.
4. **The key moment is visible.** The important thing must happen visually: the envelope's label changes text and color, an actor turns red, a ✕ appears. Save a big statement (`big`) for the opening question and the central idea.
5. **Human words.** Short sentences (about 25 words max), conversational tone, no markdown, symbols, code or file paths in the narration. Give each technical piece an everyday nickname and always use the same one: the middleware is "the gatekeeper", the cache is "the notebook". The nickname goes in the actor's `sub`.
6. **Few things on screen.** 3 to 6 actors in total; notes of 2 to 6 words; envelope labels of 1 to 3 words.

Base everything on the project's real code. If you didn't verify something, say so in the narration.

**The written plan is the source of truth.** The tour tells the plan, not another version of it: don't claim anything the plan doesn't say, and name files, functions, steps and decisions exactly as the plan does. If you need a detail the plan doesn't have to explain something, present it as context ("to understand it, look at how it works today…"), never as part of the solution.

## 3. Set up

1. `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" doctor`. If edge-tts is missing, tell the user to install it with `python -m pip install edge-tts` and stop. If Claude Code asks for approval on `tour.py` commands, suggest at the end that they run `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" allow` once.
2. Read what you need from the code to understand the real journey.
3. `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" init --lang <code>` with the user's language (`es`, `en`, `pt`, `fr`…; a regional code such as `es-AR` or `en-GB` picks a regional voice when one is available).
4. Start the server **in the background** (with `run_in_background`): `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" serve --open`.
5. **Publish the written plan, verbatim.** If you're explaining a plan, pass the exact text of the most recent plan (the one the user saw, or the plan file's content if there is one), complete, without summarizing, rewriting or translating it. The user reads it in the player with the **Plan** button. If you're explaining a topic that isn't a plan, skip this step.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/tour.py" plan <<'PLAN_EOF'
# Plan: show categories to system users
## Context
...the full plan text, verbatim...
PLAN_EOF
```

   The command prints the plan's section headings: use them in each scene's `plan` field.

6. **Write the outline**: the case, the cast and the scene titles. Each outline scene should map to a plan section.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/tour.py" outline <<'OUTLINE'
{
  "case": "Ana, from support, can't see Lola's Store categories",
  "actors": {
    "ana":     {"label": "Ana", "sub": "Support", "icon": "person"},
    "orders":  {"label": "Orders", "sub": "Support panel", "icon": "table"},
    "mw":      {"label": "Middleware", "sub": "The gatekeeper", "icon": "filter"},
    "handler": {"label": "Handler", "sub": "for categories", "icon": "server"},
    "finder":  {"label": "Finder", "sub": "for merchants", "icon": "search"}
  },
  "scenes": [
    {"title": "The question", "goal": "Ana gets an empty list"},
    {"title": "The request's journey", "goal": "From the panel to the gatekeeper"},
    {"title": "The trap", "goal": "The gatekeeper swaps the merchant"},
    {"title": "Where it gets lost", "goal": "The finder hides Acme Pay"},
    {"title": "The fix", "goal": "The same journey, now working"}
  ]
}
OUTLINE
```

   - Order actors along the journey (left to right). Without `x`/`y`, the engine places them: up to 5 in one row, 6 to 10 in two rows. If you give positions, the stage is 1600×900 (x from 170 to 1430, y from 200 to 700) and actors need at least 280 px between them.
   - Available icons: `person`, `screen`, `table`, `server`, `filter`, `gear`, `search`, `db`, `list`, `lock`, `store`, `cloud`, `box`, `envelope`, `key`, `clock`.

7. In the chat, one line in the user's language: the URL, that they should press **Start**, that **Plan** (or the P key) shows the written plan, and that they can write `more detail`, `faster`, `skip` or any question.

## 4. Publish each scene

Follow the outline in order, one scene per command. Each step is **one narrated sentence** (`text`) plus what happens on screen while it's said (`do`):

```bash
python "${CLAUDE_SKILL_DIR}/scripts/tour.py" add <<'SCENE'
{
  "title": "The trap",
  "plan": "Root cause",
  "steps": [
    {"text": "And here's the trap. Since Ana is a system user, the gatekeeper changes the label.",
     "do": [{"clearNotes": true}, {"camera": ["mw"]}, {"focus": ["mw"]}]},
    {"text": "Now the request no longer says Lola's Store. It says Acme Pay Inc, the company's own merchant.",
     "do": [{"change": {"label": "Acme Pay Inc", "tone": "bad"}}, {"tone": {"at": "mw", "tone": "bad"}}]},
    {"text": "Ana asked for one thing, but the request keeps going saying another.",
     "do": [{"focus": []}, {"camera": "all"}, {"note": {"at": "mw", "text": "Merchant swapped", "tone": "bad"}}]}
  ]
}
SCENE
```

### Actions

A step's actions run in order while its sentence plays. Actions that move something (`send`) wait until they arrive before the next action. Any action accepts `"delay": ms` to wait before running.

| Action | What it does |
|---|---|
| `{"enter": "id"}` or `["a","b"]` | The actor appears (with a small animation). The camera frames it automatically. |
| `{"exit": "id"}` | The actor leaves (with its arrows). |
| `{"link": {"from": "a", "to": "b", "label": "text", "tone": "flow"}}` | Draws an arrow that traces itself. `label` and `tone` are optional. |
| `{"unlink": "a>b"}` | Removes an arrow. |
| `{"send": {"from": "a", "to": "b", "label": "Lola's Store", "tone": "flow", "token": "t", "icon": "envelope", "ms": 1500}}` | An envelope travels from `a` to `b`. Without `from`, it leaves from wherever envelope `token` (default `t`) is. Omitted `label` or `tone` keep their previous values. Use another `token` for a second envelope at the same time. |
| `{"change": {"label": "Acme Pay Inc", "tone": "bad", "token": "t"}}` | Changes the envelope's label with an animation. Use it for the key moment. |
| `{"drop": "t"}` | The envelope disappears. |
| `{"note": {"at": "id", "text": "Empty list", "tone": "bad", "pos": "above"}}` | A short note next to the actor (below, or above with `pos: above`). |
| `{"clearNotes": true}` | Removes the notes. Use it when a new moment starts. |
| `{"mark": {"at": "id", "icon": "x"}}` | A ✕ (`x`) or ✓ (`ok`) mark on the actor. |
| `{"tone": {"at": "id", "tone": "bad"}}` | Colors the actor: `bad` (red), `good` (green) or `none`. |
| `{"focus": ["a","b"]}` | Highlights those actors and dims the rest. `[]` clears it. |
| `{"camera": ["a"]}` | Moves the camera close to those actors. `"all"` goes back to the wide shot. Without `camera`, it frames whatever enters or travels. |
| `{"big": "Why can't Ana see the categories?"}` or `{"big": {"text": "...", "tone": "bad"}}` | A big full-screen statement, with the scene dimmed behind it. It clears itself on the next step. |
| `{"code": {"file": "...", "start": 129, "snippet": "...", "highlight": [130]}}` | A real code card (18 lines max; `start` = real number of the first line). `{"code": null}` closes it. |
| `{"lines": [130, "132-133"]}` | Highlights other lines of the open card. |

Scene fields: `title` (short, shown at the top), `steps`, `plan` (the heading of the plan section this scene tells, as printed by `tour.py plan`; with the panel open, that section is highlighted and scrolled into view), and optionally `kind` (`question`, `correction`, `detail` or `summary`), `clear: true` to start with an empty stage, and `actors` to add actors that weren't in the outline.

The stage **persists across scenes**: actors, arrows and envelopes stay where they were, and that's what gives continuity. Notes, focus, the big statement and the code card are cleared at the end of each scene.

After each `add`, move to the next scene without waiting. In the chat, at most one line per scene ("Scene 3 ready"); never paste the narration. If `tour.py` prints a warning (long sentences, long notes, overlapping actors, missing plan section), fix it in the following scenes.

## 5. Adjustments during the tour

Any message from the user stops your turn. First run `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" status` to see which scene they're watching, which ones you published, the outline, the plan sections and the cast.

- **`more detail`** (or the same in their language): `tour.py rewind` (without a number it keeps up to the scene being watched). Publish 1 or 2 `detail` scenes that go one level deeper on that same part, with a close `camera` and, if it helps, a code card. Then continue with the outline.
- **`faster`**: `tour.py rewind`, rewrite the rest of the outline with `outline` at Quick depth, and continue.
- **`skip`**: `tour.py rewind` and continue from the next outline scene.
- **A question:** `tour.py rewind`, publish a `question` scene that answers it with the same actors and the same case (open with a `big` that restates the question in a few words), then continue with the outline.
- **A correction that changes the plan:** `tour.py rewind N` from the scene that became obsolete, publish the updated plan again with `tour.py plan` (complete, verbatim), update the outline with `outline`, and regenerate starting with a `correction` scene that shows what changed. Also say it in the chat in one line.
- **`stop`**: don't publish anything else; wait for instructions.

The player detects the rewind, rebuilds the stage up to that point and waits for the new scene.

## 6. Wrap up

The last scene (`summary`) replays the whole journey working, or sums up the central idea with a `big`, and ends by asking in the narration whether they approve the plan, want to change something or review a part. Then run `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" finish`, and ask the same question in the chat in one line.

## Rules

- Don't modify anything in the project during the tour.
- If an audio clip fails, the player uses the browser voice for that sentence; don't retry.
- Voice and speed: `PLAN_TOUR_VOICE` overrides the voice picked from `--lang` (any edge-tts voice; `tour.py voices --lang es` lists them) and `PLAN_TOUR_RATE` sets the rate (e.g. `+10%`).
