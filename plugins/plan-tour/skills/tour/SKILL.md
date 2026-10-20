---
name: tour
description: Explains the current plan (or a project topic) as an animated, narrated story in the browser, like an explainer video. Use ONLY when the user explicitly asks for a tour, a plan tour or an animated/narrated walkthrough of the plan (in any language, e.g. "plan tour", "explain the plan as a tour", "tour del plan"). Never use it for ordinary plans or explanations.
argument-hint: "[quick|standard|deep] [optional topic]"
allowed-tools: Bash(python *) Bash(py *) Bash(python3 *)
---

# Plan Tour

Turn the plan (or whatever the user wants to understand) into an **animated story**, like a good YouTube explainer: a concrete case, step by step, where the screen always shows exactly what the voice is saying. You **design every scene yourself** (HTML/SVG on a 1600×900 canvas) choosing the visual form that best explains that idea, then **review what you designed** from a snapshot before moving on. The player handles the voice, captions, timing, transitions, navigation and the written plan. You publish scenes **one at a time** so the user starts watching right away. Questions and adjustments arrive through this chat.

**Arguments:** $ARGUMENTS

- If they start with `quick`, `standard` or `deep`, that is the depth: don't ask. The rest is the topic.
- Otherwise it's all topic. With no topic, explain the most recent plan in this conversation. With no plan and no topic, ask what they want to understand and don't start anything.

The engine is `${CLAUDE_SKILL_DIR}/scripts/tour.py`. Run every command from the project root. On Windows, if `python` doesn't exist, use `py`; elsewhere you may need `python3` (from here on, `python` means whichever works).

**Language.** This skill is written in English, but **everything the user sees or hears** (narration, scene text, labels, notes, the outline and your questions) is in **the user's language**: the language they write to you in. The written plan is published verbatim.

**Permissions rule.** Never use Write, Edit or any file tool for the tour, and never write anything in the project or its `.claude` folder. Everything goes through `tour.py` commands with JSON on stdin (heredoc). This also works in plan mode.

## 1. Choose the depth

If the arguments don't set it, ask **a single question** with AskUserQuestion before anything else, in the user's language. In English:

- Question: `How deep should the tour go?` (header: `Depth`)
- Options, in this order:
  1. `Standard (Recommended)`: 4–6 scenes: the story, where it breaks and the fix
  2. `Quick`: 3 scenes: just what changes and why
  3. `Deep`: 6–10 scenes: down to the code, edge cases and trade-offs

If they answer with free text, take the depth and focus from it. Don't ask anything else.

| Depth | Scenes | Content |
|---|---|---|
| **Quick** | 3 | The question, what changes, how it ends up. No code. |
| **Standard** | 4–6 | The question, the case's journey, the twist (where it breaks or what must change), the fix, decisions that need their input. At most one code view. |
| **Deep** | 6–10 | Everything in Standard, plus code at the key points, edge cases and discarded alternatives. |

## 2. How to tell it

1. **A story with a protagonist.** Pick a concrete, real case from the domain, with a person and a situation ("Ana, from support, opens Orders and picks Lola's Store"), and follow it from start to finish. Everything technical is explained through what happens to that case.
2. **Four beats.** The question (a hook), the journey (step by step), the twist (the exact moment it breaks, or what changes and why) and the fix (the same journey, now working).
3. **One idea per scene, one change per sentence.** Each narrated sentence makes something happen on screen at that moment: something appears, moves, changes, gets highlighted, or the camera goes to it. If a sentence changes nothing, merge it or cut it.
4. **The key moment is visible.** What matters must happen visually: a label changes, something turns red, a value is crossed out, a path stops.
5. **Human words.** Short sentences (about 25 words max), conversational, no markdown, symbols, code or file paths in the narration. Give each technical piece an everyday nickname and keep it ("the middleware is the gatekeeper").
6. **The written plan is the source of truth.** Don't claim anything the plan doesn't say; name files, functions, steps and decisions exactly as the plan does. Extra context is labeled as context ("to understand it, look at how it works today…").

Base everything on the project's real code. If you didn't verify something, say so in the narration.

## 3. Set up

1. `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" doctor`. If edge-tts is missing, tell the user to install it with `python -m pip install edge-tts` and stop. If Claude Code asks for approval on `tour.py` commands, suggest at the end that they run `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" allow` once.
2. Read what you need from the code to understand the real journey.
3. `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" init --lang <code>` with the user's language (`es`, `en`, `pt`…; `es-AR`, `en-GB` pick regional voices).
4. Start the server **in the background** (with `run_in_background`): `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" serve --open`.
5. **Publish the written plan, verbatim** (skip if you're explaining a topic that isn't a plan): the exact, complete text of the most recent plan, without summarizing, rewriting or translating it.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/tour.py" plan <<'PLAN_EOF'
...the full plan text, verbatim...
PLAN_EOF
```

   It prints the plan's section headings: use them in each scene's `plan` field.

6. **Write the outline**: the case and the scene titles (each mapped to a plan section).

```bash
python "${CLAUDE_SKILL_DIR}/scripts/tour.py" outline <<'OUTLINE'
{"case": "Ana, from support, can't see Lola's Store categories",
 "scenes": [{"title": "The question", "goal": "Ana gets an empty list"},
            {"title": "The request's journey", "goal": "From the panel to the gatekeeper"},
            {"title": "The fix", "goal": "The same journey, now working"}]}
OUTLINE
```

7. In the chat, one line in the user's language: the URL, that they should press **Start**, that **Plan** (or P) shows the written plan, and that they can write `more detail`, `faster`, `skip` or any question.

## 4. Design each scene

### Choose the visual form first

Before writing markup, decide what picture explains this idea best. Don't default to boxes and arrows. Some options:

- **A flow**: components the request passes through, with something travelling between them.
- **A mock of the real screen**: a simplified window of the app the user knows (a table, a form, a notification), to show the symptom.
- **Before / after**: two columns, the same journey today and with the plan.
- **A timeline**: events in order (retries, jobs, expirations).
- **A table or list that fills in**: rules, states, permissions, data that changes.
- **A state machine**: states and the transitions the plan adds or changes.
- **A zoom into code**: a short real snippet with the key lines lit, only when the exact line matters.
- **A metaphor**: a ticket, a queue at a counter, a gatekeeper, when it makes an abstract idea click.

Mix them across scenes so the tour doesn't feel repetitive.

### The scene JSON

```bash
python "${CLAUDE_SKILL_DIR}/scripts/tour.py" draft <<'SCENE'
{
  "title": "The trap",
  "plan": "Root cause",
  "css": ".road { stroke-dasharray: 10 10; }",
  "html": "<svg class='layer'><path id='road' class='arrow' d='M300 560 C 560 360, 1040 360, 1300 560' data-step='1'/></svg><div class='box at' id='mw' style='left:800px;top:600px' data-step='2'><div class='icon' data-icon='filter'></div><div class='label'>Middleware</div><div class='sub'>The gatekeeper</div></div><div class='pill at' id='env' style='left:300px;top:450px' data-step='1'><span data-icon='envelope'></span><span class='t'>Lola's Store</span></div><div class='note bad at' id='n1' style='left:800px;top:790px' data-step='3'>Merchant swapped</div>",
  "steps": [
    {"text": "Ana's request leaves the panel with a label: Lola's Store."},
    {"text": "First it reaches the middleware, a kind of gatekeeper.", "move": {"sel": "#env", "to": "#mw", "dy": -150}, "focus": ["#mw", "#env"]},
    {"text": "And here's the trap: the gatekeeper swaps the label.", "set": [{"sel": "#env", "text": "Acme Pay Inc", "add": "bad"}, {"sel": "#mw", "add": "bad"}], "focus": ["#mw", "#env", "#n1"]}
  ]
}
SCENE
```

- **`html`**: your markup for a **1600×900 canvas** (it's scaled to fit the screen). Position things absolutely. The class `at` puts an element's **center** at its `left`/`top`. Draw lines and arrows inside `<svg class="layer">`, which covers the canvas with the same coordinates. No `<script>` tags and nothing loaded from the internet: everything inline.
- **`css`**: optional styles for this scene. Each tour runs isolated, so short class names are fine.
- **`steps`**: one per narrated sentence, in order. Step *n* is when the voice says sentence *n*.
- `title` (short), `plan` (the plan heading this scene tells, as printed by `tour.py plan`), and optionally `kind` (`question`, `correction`, `detail`, `summary`) and `continue: true` (see below).

### What happens at each step

- **Reveal by markup:** an element with `data-step="n"` is hidden until step *n*, then animates in. `data-anim` picks the entrance: `up` (default for HTML), `fade`, `pop`, `left`, `right`, `down`, `grow` (bars, from the left), `draw` (default for SVG paths: the line draws itself). `data-hide="n"` removes it at step *n*. Elements without `data-step` are visible from the start.
- **Step fields** (all optional; selectors are CSS selectors within the canvas):

| Field | What it does |
|---|---|
| `"show": ["#a", ".b"]` / `"hide": [...]` | Reveal or remove elements at this step. |
| `"set": {"sel": "#env", "text": "Acme Pay Inc", "add": "bad", "remove": "flow", "attr": {...}, "style": {...}}` | Change text (with a swap animation), classes, attributes or inline styles. A list applies several. |
| `"move": {"sel": "#env", "to": "#mw", "dx": 0, "dy": -150, "arc": -60, "ms": 1400}` | Move an element to another element's center (plus offset) along an arc. `"path": "#road"` follows an SVG path instead; `"x"`/`"y"` go to a canvas point. Moves accumulate. A list moves several at once. |
| `"focus": ["#mw", "#env"]` | Highlights those elements and dims everything else, whatever your markup. `[]` clears it. |
| `"camera": ["#mw", "#n1"]` | Zooms smoothly to frame those elements. `"all"` goes back to the whole canvas. |
| `"lines": [130, "132-133"]` | Lights those lines in the code block (others dim). |
| `"run": "root.querySelector('#x').classList.add('y')"` | Escape hatch: JavaScript with `root` (the canvas) and `ctx` (`ctx.animate` is false while rebuilding instantly). Prefer the fields above. |
| `"pause": 600` | Extra milliseconds after the sentence. |

### Kit (optional)

Use it when it fits, ignore it when your own design is better. Colors are CSS variables: `--flow` (cyan), `--bad` (red), `--good` (green), `--warn`, `--text`, `--text-2`, `--muted`, `--card`, `--card-2`, `--line`.

- `.box` with `.icon` (`data-icon="name"` fills it), `.label`, `.sub`; `.box.round` for people. Tones: add `flow`, `bad` or `good` to the box.
- `.pill` (a travelling label: `<span data-icon='envelope'></span><span class='t'>text</span>`), `.note` (a short callout), `.card` (`h3` + `p`), `.chip`, `.tag` (monospace), `.big` (a full-canvas statement), `.title`, `.text`, `.row`, `.col`, `.t-bad`/`.t-good`/`.t-flow`.
- SVG: `class="arrow"` gets an arrowhead (add `flow`, `bad`, `good` or `dashed`).
- Code: `<div class='code'><div class='path'>file.go</div><pre data-start='129' data-hl='130'>…real code…</pre></div>` numbers the lines with the real line numbers and lights `data-hl`.
- Icons for `data-icon`: person, people, screen, phone, table, server, filter, gear, search, db, list, lock, key, store, cloud, box, envelope, clock, bell, queue, money, card, shield, doc, code, globe, check, x, warn, bolt, chart.

### Visual quality bar

- Text at least 20px (labels 24–30px, statements 60–80px): it's watched from a distance.
- 3 to 7 visible elements per step; generous empty space; align things on a clear grid.
- Nothing overlapping, nothing cut at the edges, arrows routed around elements (curve them), labels of 1–3 words, notes of 2–6 words.
- No identifiers in labels unless the identifier is the point; prefer the nickname.

### Review before publishing

1. Send the scene with **`tour.py draft`** (as above). It renders every step in a headless browser and prints **detected layout issues** (overlaps, text that doesn't fit, elements cut at the edge, arrows crossing elements, tiny text) plus the **path of a snapshot** with the state after each step.
2. **Read the snapshot image** and judge it like a designer: is the idea clear at a glance? Does each step show what its sentence says? Is it balanced, readable, uncluttered? Fix and `draft` again (at most two rounds per scene).
3. Publish with **`tour.py add`** (same JSON). It synthesizes the voice and runs the automatic checks again.

To save time, you may skip the snapshot reading for very simple scenes when `draft` reports 0 issues, but always read it for the first scene, for any scene with movement or more than four elements, and whenever issues were reported. If you spot a problem in an already published scene, fix it with **`tour.py replace N`**.

### Continuity between scenes

Each scene starts from an empty canvas, unless it has `"continue": true`: then it's added on top of the previous scene's final state, and its steps can reference the previous scene's elements (move the same envelope, light the same box). Use it to keep the same picture across consecutive scenes; start a fresh scene when the idea changes.

After each `add`, move on. In the chat, at most one line per scene ("Scene 3 ready"); never paste the narration or the markup.

## 5. Adjustments during the tour

Any message from the user stops your turn. First run `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" status` to see which scene they're watching, which ones you published, the outline and the plan sections.

- **`more detail`** (or the same in their language): `tour.py rewind` (keeps up to the scene being watched), then 1 or 2 `detail` scenes that zoom into that part (often `continue: true` with a close `camera`, or a code view). Then continue with the outline.
- **`faster`**: `tour.py rewind`, rewrite the rest of the outline at Quick depth, continue.
- **`skip`**: `tour.py rewind` and continue from the next outline scene.
- **A question:** `tour.py rewind`, publish a `question` scene that answers it with the same case and the same visual language, then continue.
- **A correction that changes the plan:** `tour.py rewind N` from the obsolete scene, publish the updated plan again with `tour.py plan` (complete, verbatim), update the outline, and regenerate starting with a `correction` scene that shows what changed. Say it in the chat in one line.
- **`stop`**: don't publish anything else; wait for instructions.

## 6. Wrap up

The last scene (`summary`) shows the whole journey working, or the central idea as a `.big` statement, and ends by asking in the narration whether they approve the plan, want to change something or review a part. Then `python "${CLAUDE_SKILL_DIR}/scripts/tour.py" finish`, and ask the same question in the chat in one line.

## Rules

- Don't modify anything in the project during the tour.
- If an audio clip fails, the player uses the browser voice for that sentence; don't retry.
- `PLAN_TOUR_VOICE` overrides the voice (`tour.py voices --lang es` lists them), `PLAN_TOUR_RATE` sets the speed, `PLAN_TOUR_BROWSER` points the review at a specific Edge/Chrome/Chromium if auto-detection fails.
