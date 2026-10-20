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
  outline                Read the outline (case, scenes) from stdin.
  serve [--port P] [--open]
                         Serve the player at http://127.0.0.1:P (run it in the background).
  draft [file|-]         Validate and visually review a scene WITHOUT publishing it (snapshot + layout issues).
  add [file|-]           Validate, synthesize audio, publish the scene, then review it (--no-review to skip).
  replace N [file|-]     Replace published scene N (same checks and review).
  review N               Visually review published scene N.
  status                 Show published scenes, the scene the user is watching, the outline and the cast.
  rewind [N]             Drop scenes from N on (1 = first). Without N: keep up to the scene being watched.
  finish                 Mark the tour as finished.

Optional environment variables:
  PLAN_TOUR_VOICE  edge-tts voice; overrides the one picked from --lang (e.g. es-MX-JorgeNeural)
  PLAN_TOUR_RATE   speaking rate, e.g. +10% or -5% (default +0%)
  PLAN_TOUR_DIR    tour folder (default <system temp>/plan-tour/<project>-<hash>)
  PLAN_TOUR_BROWSER  path to Edge/Chrome/Chromium for the visual review (auto-detected)
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
        for child in ("scenes", "review", "position.json", "plan.md", "draft.json"):
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
        "lang": lang, "voice": voice_for(lang), "outline": None, "plan": None, "scenes": [],
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

STEP_KEYS = {"text", "show", "hide", "set", "move", "focus", "camera", "lines", "run", "pause"}


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


def cmd_outline(_args) -> None:
    """Store the outline: the case and the scene titles."""
    data = read_stdin_json("outline")
    scenes = data.get("scenes") or []
    if not scenes or not all(s.get("title") for s in scenes):
        sys.exit('The outline needs "scenes": [{"title": ..., "goal": ...}, ...]')
    m = load_manifest()
    m["outline"] = {"case": data.get("case", ""), "scenes": scenes}
    m["total"] = max(len(scenes), len(m["scenes"]))
    save_manifest(m)
    print(f"Outline saved: {len(scenes)} scenes")


def as_list(v):
    return [] if v is None else v if isinstance(v, list) else [v]


def selectors_in(step: dict) -> list:
    sels = []
    for k in ("show", "hide", "focus"):
        sels += [x for x in as_list(step.get(k)) if isinstance(x, str)]
    for sp in as_list(step.get("set")) + as_list(step.get("move")):
        if isinstance(sp, dict):
            sels += [sp.get(k) for k in ("sel", "to", "path") if isinstance(sp.get(k), str)]
    cam = step.get("camera")
    if isinstance(cam, (str, list)) and cam != "all":
        sels += [x for x in as_list(cam) if isinstance(x, str)]
    return sels


def validate_scene(scene: dict, m: dict, index: int) -> list:
    """Structural checks. Layout problems are caught later by the visual review."""
    if not scene.get("title"):
        sys.exit("The scene needs a 'title'")
    html = scene.get("html") or ""
    if not html.strip() and not scene.get("continue"):
        sys.exit("The scene needs 'html' (its markup on the 1600x900 canvas)")
    if re.search(r"<script\b", html, re.I):
        sys.exit("No <script> tags in scene html. Use the step 'run' field for custom JavaScript.")
    steps = scene.get("steps") or []
    if not steps:
        sys.exit("The scene needs 'steps' (narrated sentences, each with what changes on screen)")
    warns = []
    if re.search(r"""(?:src|href)\s*=\s*["']https?://""", html, re.I) or re.search(r"url\(\s*['\"]?https?://", scene.get("css", ""), re.I):
        warns.append("the scene loads something from the internet; keep everything inline (it must work offline)")
    # markup from the chain this scene builds on, to sanity-check selectors
    chain_html = html
    j = index
    while scene.get("continue") and j > 0:
        prev = m["scenes"][j - 1]
        chain_html = (prev.get("html") or "") + chain_html
        if not prev.get("continue"):
            break
        j -= 1
    step_nums = {int(n) for n in re.findall(r'data-step\s*=\s*["\'](\d+)["\']', html)}
    if step_nums and max(step_nums) > len(steps):
        warns.append(f"html has data-step={max(step_nums)} but the scene only has {len(steps)} steps")
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
    for si, st in enumerate(steps):
        where = f"Step {si + 1}"
        text = (st.get("text") or "").strip()
        if not text:
            sys.exit(f"{where}: missing 'text' (the narrated sentence)")
        unknown = set(st) - STEP_KEYS
        if unknown:
            sys.exit(f"{where}: unknown field(s) {sorted(unknown)}; valid: {sorted(STEP_KEYS)}")
        if len(text.split()) > 45:
            warns.append(f"{where}: the sentence has {len(text.split())} words; split it (max ~35)")
        changes = (si + 1) in step_nums or any(st.get(k) for k in ("show", "hide", "set", "move", "focus", "lines", "run")) or "camera" in st
        if not changes and si > 0:
            warns.append(f"{where}: nothing changes on screen while this sentence plays")
        for sel in selectors_in(st):
            mid = re.fullmatch(r"#([\w-]+)", sel.strip())
            mcl = re.fullmatch(r"\.([\w-]+)", sel.strip())
            if mid and not re.search(r'id\s*=\s*["\']' + re.escape(mid.group(1)) + r'["\']', chain_html):
                warns.append(f"{where}: selector {sel!r} matches no id in the scene")
            if mcl and not re.search(r'class\s*=\s*["\'][^"\']*\b' + re.escape(mcl.group(1)) + r'\b', chain_html):
                warns.append(f"{where}: selector {sel!r} matches no class in the scene")
        if st.get("lines"):
            ln = st["lines"]
            ln = ln.get("lines") if isinstance(ln, dict) else ln
            try:
                expand_lines(as_list(ln))
            except ValueError:
                sys.exit(f"{where}: invalid 'lines' {ln!r}")
    return warns


def audio_name(text: str, voice: str) -> str:
    return hashlib.sha1(f"{voice}|{RATE}|{text}".encode()).hexdigest()[:16] + ".mp3"


async def synthesize(steps, audio_dir: Path, voice: str) -> None:
    import edge_tts

    async def one(i, st):
        name = audio_name(st["text"], voice)
        if (audio_dir / name).exists():         # cached: same sentence, same voice
            st["src"] = f"audio/{name}"
            return
        try:
            await edge_tts.Communicate(st["text"], voice, rate=RATE).save(str(audio_dir / name))
            st["src"] = f"audio/{name}"
        except Exception as e:  # offline or service down: the player falls back to the browser voice
            (audio_dir / name).unlink(missing_ok=True)
            print(f"Warning: edge-tts failed on step {i + 1} ({e}); the browser voice will be used", file=sys.stderr)
            st["src"] = None

    await asyncio.gather(*(one(i, s) for i, s in enumerate(steps)))


def read_scene(args) -> dict:
    if getattr(args, "file", None) in (None, "-"):
        return read_stdin_json("scene")
    try:
        return json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"Invalid scene JSON: {e}")


def stored_scene(scene: dict, steps: list) -> dict:
    return {"title": scene["title"], "kind": scene.get("kind", "normal"), "plan": scene.get("plan"),
            "continue": bool(scene.get("continue")), "html": scene.get("html", ""), "css": scene.get("css", ""),
            "steps": steps}


def publish(scene: dict, index: int, replace: bool, args) -> None:
    m = load_manifest()
    if not replace:
        index = len(m["scenes"])
    if replace and not (0 <= index < len(m["scenes"])):
        sys.exit(f"There is no scene {index + 1} to replace (published: {len(m['scenes'])})")
    for w in validate_scene(scene, m, index):
        print(f"Warning: {w}", file=sys.stderr)
    steps = [dict(st) for st in scene["steps"]]
    asyncio.run(synthesize(steps, tour_dir() / "audio", m.get("voice") or voice_for(m.get("lang"))))
    m = load_manifest()  # re-read in case a rewind happened while synthesizing
    if replace:
        m["scenes"][index] = stored_scene(scene, steps)
    else:
        index = len(m["scenes"])
        m["scenes"].append(stored_scene(scene, steps))
    m["total"] = max(m.get("total") or 0, len(m["scenes"]))
    save_manifest(m)
    ok = sum(1 for s in steps if s.get("src"))
    print(f"Scene {index + 1} {'replaced' if replace else 'published'} ({ok}/{len(steps)} audio clips from edge-tts)")
    if not getattr(args, "no_review", False):
        run_review(str(index), f"scene-{index + 1}")


def cmd_add(args) -> None:
    publish(read_scene(args), -1, False, args)


def cmd_replace(args) -> None:
    publish(read_scene(args), args.n - 1, True, args)


def cmd_draft(args) -> None:
    """Review a scene without publishing it."""
    scene = read_scene(args)
    m = load_manifest()
    index = len(m["scenes"]) if args.at is None else args.at - 1
    for w in validate_scene(scene, m, index):
        print(f"Warning: {w}", file=sys.stderr)
    (tour_dir() / "draft.json").write_text(json.dumps({"index": index, "scene": scene}, ensure_ascii=False), encoding="utf-8")
    run_review("draft", "draft")


def cmd_review(args) -> None:
    run_review(str(args.n - 1), f"scene-{args.n}")


# ---------- visual review with a headless browser ----------

def find_browser():
    if os.environ.get("PLAN_TOUR_BROWSER"):
        return os.environ["PLAN_TOUR_BROWSER"]
    cands = []
    if sys.platform == "win32":
        for base in filter(None, [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")]):
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                  Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                  Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    for c in cands:
        if c.exists():
            return str(c)
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def run_review(target: str, label: str) -> None:
    import subprocess
    import threading
    browser = find_browser()
    if not browser:
        print("Review skipped: no Edge/Chrome/Chromium found (set PLAN_TOUR_BROWSER to its path).")
        return
    d = tour_dir()
    handler = lambda *a, **kw: NoCacheHandler(*a, directory=str(d), **kw)  # noqa: E731
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    httpd = None
    for port in range(8900, 8960):
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    if httpd is None:
        print("Review skipped: no free local port.")
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    out_dir = d / "review"
    out_dir.mkdir(exist_ok=True)
    png = out_dir / f"{label}.png"
    url = f"http://127.0.0.1:{port}/index.html?review={target}"
    try:
        m = load_manifest()
        if target == "draft":
            n_steps = len(json.loads((d / "draft.json").read_text(encoding="utf-8"))["scene"]["steps"])
        else:
            n_steps = len(m["scenes"][int(target)]["steps"])
        rows = (n_steps + 1) // 2
        size = f"1654,{rows * 524 + 40}"
        profile = tempfile.mkdtemp(prefix="plan-tour-browser-")
        flags = ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                 "--disable-extensions", "--mute-audio", f"--user-data-dir={profile}", "--virtual-time-budget=12000",
                 f"--window-size={size}"]
        if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
            flags.append("--no-sandbox")
        dom = subprocess.run([browser, *flags, "--dump-dom", url], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        subprocess.run([browser, *flags, f"--screenshot={png}", url], capture_output=True, timeout=90)
        shutil.rmtree(profile, ignore_errors=True)
    except Exception as e:
        print(f"Review failed: {e}")
        return
    finally:
        httpd.shutdown()
        httpd.server_close()
    mt = re.search(r'<pre id="lint"[^>]*>(.*?)</pre>', dom.stdout, re.S)
    report = None
    if mt:
        import html as htmlmod
        try:
            report = json.loads(htmlmod.unescape(mt.group(1)))
        except json.JSONDecodeError:
            report = None
    what = "Draft" if target == "draft" else f"Scene {int(target) + 1}"
    if report is None:
        print(f"{what}: the review page didn't finish rendering (check the scene markup).")
    else:
        seen, lines = set(), []
        for it in report["issues"]:
            key = (it["type"], it["el"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"  - step {it['step']}: {it['type']}: {it['el']}: {it['msg']}")
        print(f"{what}: {len(lines)} layout issue(s) found" + (":" if lines else "."))
        for ln in lines[:25]:
            print(ln)
    if png.exists():
        print(f"Snapshot of every step: {png}")
        print("Look at it (Read the image) and fix anything that looks off before moving on.")


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
    s.add_argument("--no-review", action="store_true")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("draft")
    s.add_argument("file", nargs="?", default="-")
    s.add_argument("--at", type=int, default=None, help="scene position it will take (default: next)")
    s.set_defaults(fn=cmd_draft)
    s = sub.add_parser("replace")
    s.add_argument("n", type=int)
    s.add_argument("file", nargs="?", default="-")
    s.add_argument("--no-review", action="store_true")
    s.set_defaults(fn=cmd_replace)
    s = sub.add_parser("review")
    s.add_argument("n", type=int)
    s.set_defaults(fn=cmd_review)
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
