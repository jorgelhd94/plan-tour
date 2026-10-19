#!/usr/bin/env python3
"""plan-tour engine: publishes animated, narrated scenes (voice via edge-tts) to a local player.

Commands:
  doctor                 Check Python, edge-tts and the player files.
  voices [--lang xx]     List the edge-tts voices for a language.
  allow                  Add (once) a permanent permission for this script to ~/.claude/settings.json.
  init [--lang xx]       Prepare a new tour in the system temp folder. --lang is the narration language
                         (e.g. es, en, pt, es-AR); it picks the voice. Defaults to en.
  where                  Print this project's tour folder.
  plan                   Read the written plan (markdown, verbatim) from stdin so it can be read in the player.
  outline                Read the outline (case, actors, scenes) from stdin.
  serve [--port P] [--open]
                         Serve the player at http://127.0.0.1:P (run it in the background).
  add [file|-]           Read a scene (JSON) from stdin or a file, validate it, synthesize audio and publish it.
  status                 Show published scenes, the scene the user is watching, the outline and the cast.
  rewind [N]             Drop scenes from N on (1 = first). Without N: keep up to the scene being watched.
  finish                 Mark the tour as finished.

Optional environment variables:
  PLAN_TOUR_VOICE  edge-tts voice; overrides the one picked from --lang (e.g. es-MX-JorgeNeural)
  PLAN_TOUR_RATE   speaking rate, e.g. +10% or -5% (default +0%)
  PLAN_TOUR_DIR    tour folder (default <system temp>/plan-tour/<project>-<hash>)
"""
import argparse
import asyncio
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import socketserver
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PLAYER = SKILL_DIR / "player" / "index.html"
RATE = os.environ.get("PLAN_TOUR_RATE", "+0%")

# Default neural voice per language (edge-tts). Region-specific codes fall back to the base language.
VOICES = {
    "en": "en-US-AriaNeural", "en-gb": "en-GB-SoniaNeural", "en-au": "en-AU-NatashaNeural",
    "es": "es-MX-DaliaNeural", "es-es": "es-ES-ElviraNeural", "es-ar": "es-AR-ElenaNeural",
    "es-co": "es-CO-SalomeNeural", "es-uy": "es-UY-ValentinaNeural", "es-cl": "es-CL-CatalinaNeural",
    "pt": "pt-BR-FranciscaNeural", "pt-pt": "pt-PT-RaquelNeural",
    "fr": "fr-FR-DeniseNeural", "de": "de-DE-KatjaNeural", "it": "it-IT-ElsaNeural",
    "nl": "nl-NL-ColetteNeural", "pl": "pl-PL-ZofiaNeural", "tr": "tr-TR-EmelNeural",
    "ru": "ru-RU-SvetlanaNeural", "uk": "uk-UA-PolinaNeural", "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural", "zh": "zh-CN-XiaoxiaoNeural", "hi": "hi-IN-SwaraNeural",
    "ar": "ar-SA-ZariyahNeural", "id": "id-ID-GadisNeural", "vi": "vi-VN-HoaiMyNeural",
}


def voice_for(lang: str) -> str:
    if os.environ.get("PLAN_TOUR_VOICE"):
        return os.environ["PLAN_TOUR_VOICE"]
    lang = (lang or "en").lower().replace("_", "-")
    return VOICES.get(lang) or VOICES.get(lang.split("-")[0]) or VOICES["en"]


def tour_dir() -> Path:
    """Tour folder in the system temp dir: nothing is ever written inside the project."""
    if os.environ.get("PLAN_TOUR_DIR"):
        return Path(os.environ["PLAN_TOUR_DIR"]).resolve()
    project = Path.cwd().resolve()
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in project.name)[:40] or "project"
    digest = hashlib.sha1(str(project).lower().encode()).hexdigest()[:8]
    return Path(tempfile.gettempdir()) / "plan-tour" / f"{slug}-{digest}"


def manifest_path() -> Path:
    return tour_dir() / "manifest.json"


def load_manifest() -> dict:
    p = manifest_path()
    if not p.exists():
        sys.exit("No tour started. Run first: tour.py init")
    return json.loads(p.read_text(encoding="utf-8"))


def save_manifest(m: dict) -> None:
    m["updated"] = time.time()
    p = manifest_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # atomic write: the player never reads half a JSON


def read_stdin_text() -> str:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    return sys.stdin.read()


def read_stdin_json(what: str):
    try:
        return json.loads(read_stdin_text())
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid {what} JSON: {e}")


# ---------- doctor / voices / allow ----------

def cmd_doctor(_args) -> None:
    print(f"Python {sys.version.split()[0]}")
    try:
        import edge_tts  # noqa: F401
        print("edge-tts installed")
    except ImportError:
        sys.exit("edge-tts is missing. Install it with: python -m pip install edge-tts")
    for f in (PLAYER, PLAYER.parent / "fonts", PLAYER.parent / "marked.umd.js"):
        if not f.exists():
            sys.exit(f"Player file missing: {f}")
    print("Player OK. Ready.")


def cmd_voices(args) -> None:
    import edge_tts
    prefix = (args.lang or "").lower()

    async def run():
        for v in await edge_tts.list_voices():
            if not prefix or v["Locale"].lower().startswith(prefix):
                print(f'{v["ShortName"]:32} {v["Gender"]:7} {v["Locale"]}')

    try:
        asyncio.run(run())
    except Exception as e:
        sys.exit(f"Could not list edge-tts voices (offline?): {e}")


ALLOW_RULES = ["Bash(py *plan-tour*tour.py*)", "Bash(python *plan-tour*tour.py*)", "Bash(python3 *plan-tour*tour.py*)"]


def cmd_allow(_args) -> None:
    """Add a permanent permission for this script to ~/.claude/settings.json (one time)."""
    settings = Path.home() / ".claude" / "settings.json"
    data = {}
    if settings.exists():
        raw = settings.read_text(encoding="utf-8")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            sys.exit(f"{settings} is not valid JSON; leaving it alone. Add these to permissions.allow by hand: {ALLOW_RULES}")
        shutil.copyfile(settings, settings.with_suffix(".json.bak"))
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    added = [r for r in ALLOW_RULES if r not in allow]
    allow.extend(added)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Permission added to {settings}: {added}" if added else "Permission was already set.")


# ---------- init ----------

def cmd_init(args) -> None:
    d = tour_dir()
    if d.exists():
        for child in ("audio", "scenes", "position.json", "plan.md"):
            p = d / child
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    (d / "audio").mkdir(parents=True, exist_ok=True)
    (d / "scenes").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLAYER, d / "index.html")
    shutil.copyfile(PLAYER.parent / "marked.umd.js", d / "marked.umd.js")
    shutil.copytree(PLAYER.parent / "fonts", d / "fonts", dirs_exist_ok=True)
    lang = (args.lang or "en").lower().replace("_", "-")
    save_manifest({
        "tour": int(time.time()), "revision": 0, "resumeAt": 0, "total": None, "done": False,
        "lang": lang, "voice": voice_for(lang), "actors": {}, "outline": None, "plan": None, "scenes": [],
    })
    print(f"Tour ready in {d} (language: {lang}, voice: {voice_for(lang)})")


# ---------- serve ----------

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # The player reports which scene it is showing: /position?i=N
        if self.path.startswith("/position"):
            from urllib.parse import parse_qs, urlparse
            try:
                i = int(parse_qs(urlparse(self.path).query)["i"][0])
                (Path(self.directory) / "position.json").write_text(json.dumps({"index": i}), encoding="utf-8")
                self.send_response(204)
            except (KeyError, ValueError):
                self.send_response(400)
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_):
        pass  # quiet: the player polls the manifest every second


def free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    sys.exit("No free port found")


def cmd_serve(args) -> None:
    d = tour_dir()
    if not (d / "index.html").exists():
        sys.exit("No tour started. Run first: tour.py init")
    info = d / "server.json"
    if info.exists():
        old = json.loads(info.read_text(encoding="utf-8"))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", old["port"])) == 0:
                print(f"A server is already running: {old['url']}", flush=True)
                if args.open:
                    webbrowser.open(old["url"])
                return
    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    info.write_text(json.dumps({"port": port, "url": url}), encoding="utf-8")
    handler = lambda *a, **kw: NoCacheHandler(*a, directory=str(d), **kw)  # noqa: E731
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Player at {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        finally:
            info.unlink(missing_ok=True)


# ---------- plan, outline, scenes and validation ----------

WORLD_W, WORLD_H = 1600, 900
ICONS = {"person", "screen", "table", "server", "filter", "gear", "search", "db", "list", "lock",
         "store", "cloud", "box", "envelope", "key", "clock"}
ACTIONS = {"enter", "exit", "link", "unlink", "send", "change", "drop", "note", "clearNotes", "mark",
           "tone", "focus", "camera", "big", "code", "lines", "delay", "wait"}
TONES = {"flow", "bad", "good", "none", None}


def expand_lines(spec) -> list:
    """[43, "45-48"] -> [43, 45, 46, 47, 48]"""
    out = []
    for item in spec:
        if isinstance(item, str) and "-" in item:
            a, b = (int(x) for x in item.split("-", 1))
            out.extend(range(a, b + 1))
        else:
            out.append(int(item))
    return out


def plan_headings(md: str) -> list:
    """Plan headings (outside code fences) with their level."""
    out, fence = [], False
    for line in md.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        mt = None if fence else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if mt:
            out.append({"level": len(mt.group(1)), "text": mt.group(2).strip()})
    return out


def match_heading(ref: str, headings: list):
    def norm(t):
        return re.sub(r"[`*_]", "", t).strip().lower()
    r = norm(ref)
    exact = [h for h in headings if norm(h) == r]
    if exact:
        return exact[0]
    partial = [h for h in headings if r in norm(h)]
    return partial[0] if partial else None


def cmd_plan(_args) -> None:
    """Store the written plan, verbatim, so it can be read in the player."""
    md = read_stdin_text().strip("\n")
    if not md.strip():
        sys.exit("The plan is empty. Pass the full text on stdin.")
    (tour_dir() / "plan.md").write_text(md + "\n", encoding="utf-8")
    heads = plan_headings(md)
    m = load_manifest()
    m["plan"] = {"updated": time.time(), "headings": [h["text"] for h in heads]}
    save_manifest(m)
    print(f"Plan saved: {len(md.splitlines())} lines, {len(heads)} sections")
    for h in heads:
        print("  " * (h["level"] - 1) + "- " + h["text"])


def auto_layout(actors: dict) -> None:
    """Place actors without a position in one row (up to 5) or two rows (6 to 10)."""
    free = [k for k, a in actors.items() if "x" not in a or "y" not in a]
    if not free:
        return
    rows = [free] if len(free) <= 5 else [free[: (len(free) + 1) // 2], free[(len(free) + 1) // 2:]]
    ys = [470] if len(rows) == 1 else [300, 660]
    for row, y in zip(rows, ys):
        n = len(row)
        for i, k in enumerate(row):
            actors[k]["x"] = round(170 + (WORLD_W - 340) * (i / (n - 1) if n > 1 else 0.5))
            actors[k]["y"] = y


def check_actors(actors: dict) -> list:
    """Validate actor definitions; return overlap warnings."""
    warns = []
    for k, a in actors.items():
        if not re.fullmatch(r"[A-Za-z][\w-]*", k):
            sys.exit(f"Invalid actor id: {k!r} (use letters, digits and underscores)")
        if not a.get("label"):
            sys.exit(f"Actor {k!r} needs a 'label'")
        if a.get("icon", "box") not in ICONS:
            sys.exit(f"Actor {k!r} uses icon {a.get('icon')!r}; available: {sorted(ICONS)}")
        if not (100 <= a["x"] <= WORLD_W - 100 and 150 <= a["y"] <= WORLD_H - 150):
            sys.exit(f"Actor {k!r} is off stage (x 100-1500, y 150-750): ({a['x']}, {a['y']})")
    keys = list(actors)
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            a, b = actors[k1], actors[k2]
            if abs(a["x"] - b["x"]) < 250 and abs(a["y"] - b["y"]) < 300:
                warns.append(f"actors {k1!r} and {k2!r} are too close and will overlap")
    return warns


def cmd_outline(_args) -> None:
    """Store the outline: the case, the cast (actors) and the scene titles."""
    data = read_stdin_json("outline")
    scenes = data.get("scenes") or []
    if not scenes or not all(s.get("title") for s in scenes):
        sys.exit('The outline needs "scenes": [{"title": ..., "goal": ...}, ...]')
    actors = data.get("actors") or {}
    if not actors:
        sys.exit('The outline needs "actors": the cast of the story with label, sub and icon')
    m = load_manifest()
    merged = {**m.get("actors", {}), **actors}
    auto_layout(merged)
    for w in check_actors(merged):
        print(f"Warning: {w}", file=sys.stderr)
    m["actors"] = merged
    m["outline"] = {"case": data.get("case", ""), "scenes": scenes}
    m["total"] = max(len(scenes), len(m["scenes"]))
    save_manifest(m)
    print(f"Outline saved: {len(scenes)} scenes, {len(merged)} actors")
    print("Positions: " + ", ".join(f"{k}=({a['x']},{a['y']})" for k, a in merged.items()))


def as_list(v):
    return [v] if isinstance(v, dict) else (v or [])


def validate_scene(scene: dict, m: dict) -> tuple:
    if not scene.get("title"):
        sys.exit("The scene needs a 'title'")
    steps = scene.get("steps") or []
    if not steps:
        sys.exit("The scene needs 'steps' (narrated sentences with their actions)")
    extra = scene.get("actors") or {}
    actors = {**m.get("actors", {}), **extra}
    auto_layout(actors)
    warns = check_actors({k: actors[k] for k in extra}) if extra else []
    known = set(actors)

    def need(ids, where):
        for i in [ids] if isinstance(ids, str) else ids:
            if i not in known:
                sys.exit(f"{where}: actor {i!r} does not exist. Define it in the outline or in the scene's 'actors'.")

    heads = (m.get("plan") or {}).get("headings", [])
    if scene.get("plan"):
        if not heads:
            warns.append("the scene points to a plan section, but no plan was published (tour.py plan)")
        else:
            found = match_heading(scene["plan"], heads)
            if not found:
                warns.append(f"plan section {scene['plan']!r} not found; use the text of one of its headings")
            else:
                scene["plan"] = found
    elif heads:
        warns.append("the scene has no 'plan' (the plan section it tells)")

    code_lines = set()
    for si, st in enumerate(steps):
        where = f"Step {si + 1}"
        text = (st.get("text") or "").strip()
        if not text:
            sys.exit(f"{where}: missing 'text' (the narrated sentence)")
        if len(text.split()) > 45:
            warns.append(f"{where}: the sentence has {len(text.split())} words; split it (max ~35)")
        for a in st.get("do") or []:
            unknown = set(a) - ACTIONS
            if unknown:
                sys.exit(f"{where}: unknown action {sorted(unknown)}; valid: {sorted(ACTIONS)}")
            if "enter" in a:
                need(a["enter"], where)
            if "exit" in a:
                need(a["exit"], where)
            for lk in as_list(a.get("link")):
                need([lk.get("from"), lk.get("to")], where)
                if lk.get("tone") not in TONES:
                    sys.exit(f"{where}: invalid tone {lk.get('tone')!r}")
            if "send" in a:
                s = a["send"]
                need(s.get("to"), where)
                if s.get("from"):
                    need(s["from"], where)
                if s.get("label") and len(s["label"]) > 28:
                    warns.append(f"{where}: long envelope label ({s['label']!r}); use 1-3 words")
            for n in as_list(a.get("note")):
                need(n.get("at"), where)
                if len(n.get("text", "")) > 48:
                    warns.append(f"{where}: long note ({n['text']!r}); use ~6 words max")
            for mk in as_list(a.get("mark")):
                need(mk.get("at"), where)
            for t in as_list(a.get("tone")):
                need(t.get("at"), where)
            if a.get("focus"):
                need(a["focus"], where)
            if isinstance(a.get("camera"), list):
                need(a["camera"], where)
            if a.get("big"):
                txt = a["big"] if isinstance(a["big"], str) else a["big"].get("text", "")
                if len(txt) > 70:
                    warns.append(f"{where}: the big statement is long; use ~10 words max")
            if a.get("code"):
                c = a["code"]
                snippet = c.get("snippet", "")
                if not snippet.strip():
                    sys.exit(f"{where}: 'code' needs a 'snippet'")
                if len(snippet.splitlines()) > 18:
                    sys.exit(f"{where}: code snippets are limited to 18 lines")
                start = int(c.get("start", 1))
                code_lines = set(range(start, start + len(snippet.splitlines())))
                c["highlight"] = expand_lines(c.get("highlight", []))
                if set(c["highlight"]) - code_lines:
                    sys.exit(f"{where}: 'highlight' is outside the snippet ({start}-{max(code_lines)})")
            if a.get("lines"):
                a["lines"] = expand_lines(a["lines"])
                if set(a["lines"]) - code_lines:
                    sys.exit(f"{where}: 'lines' is outside the open code snippet")
    return extra, warns


async def synthesize(steps, prefix: str, audio_dir: Path, voice: str) -> None:
    import edge_tts

    async def one(i, st):
        name = f"{prefix}-{i}.mp3"
        try:
            await edge_tts.Communicate(st["text"], voice, rate=RATE).save(str(audio_dir / name))
            st["src"] = f"audio/{name}"
        except Exception as e:  # offline or service down: the player falls back to the browser voice
            print(f"Warning: edge-tts failed on step {i + 1} ({e}); the browser voice will be used", file=sys.stderr)
            st["src"] = None

    await asyncio.gather(*(one(i, s) for i, s in enumerate(steps)))


def cmd_add(args) -> None:
    # The scene arrives on stdin (heredoc) so Claude never needs to write files
    if args.file in (None, "-"):
        scene = read_stdin_json("scene")
    else:
        try:
            scene = json.loads(Path(args.file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"Invalid scene JSON: {e}")
    m = load_manifest()
    extra, warns = validate_scene(scene, m)
    for w in warns:
        print(f"Warning: {w}", file=sys.stderr)
    index = len(m["scenes"])
    prefix = f"r{m['revision']}-{index + 1:02d}"
    (tour_dir() / "scenes" / f"{prefix}.json").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    steps = [dict(st) for st in scene["steps"]]
    asyncio.run(synthesize(steps, prefix, tour_dir() / "audio", m.get("voice") or voice_for(m.get("lang"))))
    m = load_manifest()  # re-read in case a rewind happened while synthesizing
    if extra:
        merged = {**m.get("actors", {}), **extra}
        auto_layout(merged)
        m["actors"] = merged
    m["scenes"].append({"title": scene["title"], "clear": bool(scene.get("clear")),
                        "kind": scene.get("kind", "normal"), "plan": scene.get("plan"), "steps": steps})
    m["total"] = max(m.get("total") or 0, len(m["scenes"]))
    save_manifest(m)
    ok = sum(1 for s in steps if s.get("src"))
    print(f"Scene {len(m['scenes'])} published ({ok}/{len(steps)} audio clips from edge-tts)")


# ---------- status / rewind / finish ----------

def current_position() -> int:
    """0-based index of the scene the user is watching."""
    try:
        return int(json.loads((tour_dir() / "position.json").read_text(encoding="utf-8"))["index"])
    except (OSError, ValueError, KeyError):
        return len(load_manifest()["scenes"]) - 1


def cmd_status(_args) -> None:
    m = load_manifest()
    outline = m.get("outline") or {}
    print(json.dumps({
        "published": len(m["scenes"]),
        "watching": current_position() + 1,
        "planned_total": m.get("total"),
        "language": m.get("lang"),
        "titles": [s["title"] for s in m["scenes"]],
        "outline": [s["title"] for s in outline.get("scenes", [])],
        "case": outline.get("case", ""),
        "plan_sections": (m.get("plan") or {}).get("headings", []),
        "actors": {k: f"{a['label']} ({a['x']},{a['y']})" for k, a in m.get("actors", {}).items()},
    }, ensure_ascii=False, indent=2))


def cmd_rewind(args) -> None:
    m = load_manifest()
    n = current_position() + 2 if args.n is None else args.n
    n = max(1, min(n, len(m["scenes"]) + 1))
    m["scenes"] = m["scenes"][: n - 1]
    m["revision"] += 1
    m["resumeAt"] = n - 1
    m["done"] = False
    save_manifest(m)
    print(f"Tour rewound: the next scene will be scene {n}")


def cmd_finish(_args) -> None:
    m = load_manifest()
    m["done"] = True
    m["total"] = len(m["scenes"])
    save_manifest(m)
    print("Tour finished")


def main() -> None:
    p = argparse.ArgumentParser(prog="tour.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("voices")
    s.add_argument("--lang", default=None)
    s.set_defaults(fn=cmd_voices)
    sub.add_parser("allow").set_defaults(fn=cmd_allow)
    s = sub.add_parser("init")
    s.add_argument("--lang", default="en")
    s.set_defaults(fn=cmd_init)
    sub.add_parser("where").set_defaults(fn=lambda _a: print(tour_dir()))
    sub.add_parser("plan").set_defaults(fn=cmd_plan)
    sub.add_parser("outline").set_defaults(fn=cmd_outline)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("add")
    s.add_argument("file", nargs="?", default="-")
    s.set_defaults(fn=cmd_add)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    s = sub.add_parser("rewind")
    s.add_argument("n", type=int, nargs="?", default=None)
    s.set_defaults(fn=cmd_rewind)
    sub.add_parser("finish").set_defaults(fn=cmd_finish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console with accents
        sys.stderr.reconfigure(encoding="utf-8")
    main()
