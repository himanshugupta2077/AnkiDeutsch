from pydub import AudioSegment
import subprocess
import requests
import genanki
import random
import asyncio
import os
import json
import hashlib
import pickle
import datetime
from elevenlabs.client import ElevenLabs
from elevenlabs import save
from edge_tts import Communicate
from dotenv import load_dotenv
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ================== CONFIG ==================
DECK_NAME  = "German Vocab"
MODEL_NAME = "English → German (Dual Audio v2)"
AUDIO_DIR  = "audio"
CACHE_FILE = "audio_cache.json"
TOKEN_FILE = "token.pickle"
LEDGER_FILE = "cost_ledger.json"  # 💰 Tracks all-time API costs

SHEET_URL = os.getenv("SHEET_URL")

load_dotenv()

elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

VOICE_ID   = "dFA3XRddYScy6ylAYTIO"
MODEL_ID   = "eleven_flash_v2_5"
SPEED      = 0.7

EDGE_VOICE = "de-DE-ConradNeural"
# Alternatives: de-DE-AmalaNeural (female), de-DE-FlorianNeural (male)

# ElevenLabs pricing: $0.05 per 1,000 chars (flash model)
EL_COST_PER_CHAR = 0.05 / 1000

os.makedirs(AUDIO_DIR, exist_ok=True)

# ================== COST LEDGER ==================
def load_ledger() -> dict:
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"runs": [], "all_time_chars": 0, "all_time_cost_usd": 0.0}

def save_ledger(ledger: dict):
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)

def record_run(ledger: dict, chars: int, cost: float, words_generated: int, examples_generated: int):
    run = {
        "timestamp":          datetime.datetime.now().isoformat(timespec="seconds"),
        "chars_sent":         chars,
        "cost_usd":           round(cost, 5),
        "words_generated":    words_generated,
        "examples_generated": examples_generated,
    }
    ledger["runs"].append(run)
    ledger["all_time_chars"] += chars
    ledger["all_time_cost_usd"] = round(ledger["all_time_cost_usd"] + cost, 5)
    save_ledger(ledger)
    return run

# ================== Google Sheets Auth ==================
def get_sheet_rows() -> list[dict]:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds  = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob"
            )
            auth_url, _ = flow.authorization_url(prompt="consent")

            print("\n─────────────────────────────────────────────")
            print("Open this URL in your Windows browser:\n")
            print(auth_url)
            print("\n─────────────────────────────────────────────")
            code  = input("Paste the code shown by Google here: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials

        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    gc        = gspread.authorize(creds)
    worksheet = gc.open_by_url(SHEET_URL).sheet1
    rows      = worksheet.get_all_records()
    print(f"✅ Sheet loaded: {len(rows)} rows\n")
    return rows

# ================== Cache helpers ==================
def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def text_hash(text: str, prefix: str = "") -> str:
    """Stable 12-char ID. Use prefix to differentiate word vs example audio."""
    key = (prefix + text.strip().lower()).encode("utf-8")
    return hashlib.md5(key).hexdigest()[:12]

# ================== Anki Model ==================
model_id = random.randrange(1 << 30, 1 << 31)
deck_id  = random.randrange(1 << 30, 1 << 31)

CARD_CSS = """.card {
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 20px;
    text-align: center;
    /* No background or color — inherits Anki's light/dark theme */
    padding: 20px 24px;
    box-sizing: border-box;
}

.front-word {
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -0.5px;
    margin: 12px 0 6px;
}

hr#answer {
    border: none;
    border-top: 1px solid rgba(128,128,128,0.3);
    margin: 16px auto;
    width: 85%;
}

.german-word {
    font-size: 34px;
    font-weight: 700;
    color: #3b6fd4;
    letter-spacing: -0.5px;
    margin: 10px 0 6px;
}

.grammar-tag {
    display: inline-block;
    background: #3b6fd4;
    color: white;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.1px;
    text-transform: uppercase;
    padding: 3px 9px;
    border-radius: 20px;
    margin: 2px 3px;
    font-family: 'Arial', sans-serif;
}

/* ── Audio-only row (no pronunciation field) ── */
.pron-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    margin: 6px 0 4px;
}

/* ── Pronunciation text + buttons on one line ── */
.pron-inline {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: 'Arial', sans-serif;
    font-size: 14px;
    opacity: 0.75;
    flex-wrap: wrap;
}

.pron-inline .anki-play-btn,
.pron-inline .replay-button { margin: 0; }

/* ── Meta rows (Pronunciation, Literal, Notes) ── */
.meta-row {
    font-size: 15px;
    margin: 8px 0;
    line-height: 1.6;
    opacity: 0.9;
}

.meta-label {
    font-weight: 700;
    color: #3b6fd4;
    font-family: 'Arial', sans-serif;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* ── Example sentence block ── */
.section-header {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    font-family: 'Arial', sans-serif;
    opacity: 0.45;
    margin: 20px 0 8px;
}

.example-block {
    border-left: 3px solid #3b6fd4;
    padding: 2px 0 2px 14px;
    margin: 4px auto;
    max-width: 540px;
    text-align: left;
}

/* Each labelled row inside the example block */
.ex-row {
    display: grid;
    grid-template-columns: 90px 1fr;
    align-items: baseline;
    gap: 8px;
    margin: 7px 0;
}

.ex-label {
    font-family: 'Arial', sans-serif;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #3b6fd4;
    opacity: 0.8;
    padding-top: 2px;
}

.example-sentence {
    font-size: 16px;
    font-style: italic;
    line-height: 1.4;
}

.example-pron {
    font-size: 13px;
    font-family: 'Arial', sans-serif;
    opacity: 0.65;
}

.example-translation {
    font-size: 14px;
    opacity: 0.85;
}

.example-audio-row {
    display: flex;
    align-items: center;
    gap: 4px;
}
"""

ANSWER_TEMPLATE = """{{FrontSide}}
<hr id="answer">

<div class="german-word">{{German}}</div>

{{#GrammarTags}}
<div style="margin: 4px 0 10px;">{{GrammarTags}}</div>
{{/GrammarTags}}

{{#Pronunciation}}
<div class="meta-row">
  <span class="meta-label">Pronunciation</span><br>
  <span class="pron-inline">/ {{Pronunciation}} / &nbsp;{{AudioEL}}{{AudioEdge}}</span>
</div>
{{/Pronunciation}}
{{^Pronunciation}}
<div class="pron-row">{{AudioEL}}{{AudioEdge}}</div>
{{/Pronunciation}}

{{#Literal}}
<div class="meta-row">
  <span class="meta-label">Literal</span><br>{{Literal}}
</div>
{{/Literal}}

{{#Notes}}
<div class="meta-row">
  <span class="meta-label">Notes</span><br>{{Notes}}
</div>
{{/Notes}}

{{#ExampleSentence}}
<div class="section-header">Example Sentence</div>
<div class="example-block">
  <div class="ex-row">
    <span class="ex-label">Sentence</span>
    <div class="example-sentence">{{ExampleSentence}}</div>
  </div>
  {{#ExamplePronunciation}}
  <div class="ex-row">
    <span class="ex-label">Pronunciation</span>
    <div class="example-pron">/ {{ExamplePronunciation}} /</div>
  </div>
  {{/ExamplePronunciation}}
  {{#ExampleTranslation}}
  <div class="ex-row">
    <span class="ex-label">Meaning</span>
    <div class="example-translation">{{ExampleTranslation}}</div>
  </div>
  {{/ExampleTranslation}}
  <div class="ex-row">
    <span class="ex-label">Audio</span>
    <div class="example-audio-row">{{AudioExampleEL}}{{AudioExampleEdge}}</div>
  </div>
</div>
{{/ExampleSentence}}
"""

my_model = genanki.Model(
    model_id, MODEL_NAME,
    fields=[
        {'name': 'English'},
        {'name': 'German'},
        {'name': 'Literal'},
        {'name': 'Pronunciation'},
        {'name': 'ExampleSentence'},
        {'name': 'ExamplePronunciation'},
        {'name': 'ExampleTranslation'},
        {'name': 'GrammarTags'},
        {'name': 'Notes'},
        {'name': 'AudioEL'},           # ElevenLabs word audio
        {'name': 'AudioEdge'},         # Edge TTS word audio
        {'name': 'AudioExampleEL'},    # ElevenLabs example audio
        {'name': 'AudioExampleEdge'},  # Edge TTS example audio
    ],
    templates=[{
        'name': 'Card 1',
        'qfmt': '<div class="front-word">{{English}}</div>',
        'afmt': ANSWER_TEMPLATE,
    }],
    css=CARD_CSS,
)

deck = genanki.Deck(deck_id, DECK_NAME)

# ================== Audio helpers ==================
async def generate_edge_audio(text: str, filepath: str):
    communicate = Communicate(text.strip(), EDGE_VOICE)
    await communicate.save(filepath)

def pad_audio(filepath: str, silence_ms: int = 300):
    """Prepend silence to avoid playback clipping."""
    audio = AudioSegment.from_mp3(filepath)
    silence = AudioSegment.silent(duration=silence_ms)
    padded = silence + audio
    padded.export(filepath, format="mp3")

def generate_el_audio(text: str, filepath: str) -> int:
    """Generate ElevenLabs audio. Returns character count used."""
    audio = elevenlabs_client.text_to_speech.convert(
        text=text,
        voice_id=VOICE_ID,
        model_id=MODEL_ID,
        output_format="mp3_44100_128",
        voice_settings={
            "speed": SPEED,
            "stability": 0.75,
            "similarity_boost": 0.85,
        }
    )
    save(audio, filepath)
    pad_audio(filepath)
    return len(text)

def make_grammar_tags_html(raw: str) -> str:
    """Convert comma-separated grammar tags to styled HTML badges."""
    if not raw.strip():
        return ""
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return " ".join(f'<span class="grammar-tag">{t}</span>' for t in tags)

def generate_audio_pair(text: str, hash_prefix: str, label: str, cache: dict, all_audio: list) -> tuple[str, str, int]:
    """
    Generate EL + Edge audio for a given text. Uses cache if available.
    Returns (el_field, edge_field, new_chars_used).
    """
    h             = text_hash(text, prefix=hash_prefix)
    el_filename   = f"german_el_{h}.mp3"
    edge_filename = f"german_edge_{h}.mp3"
    el_path       = os.path.join(AUDIO_DIR, el_filename)
    edge_path     = os.path.join(AUDIO_DIR, edge_filename)

    el_field   = f"[sound:{el_filename}]"
    edge_field = f"[sound:{edge_filename}]"

    if h in cache and os.path.exists(el_path) and os.path.exists(edge_path):
        all_audio.extend([el_path, edge_path])
        return el_field, edge_field, 0, True  # cached

    chars_used = 0
    el_ok = edge_ok = False

    try:
        chars_used += generate_el_audio(text, el_path)
        all_audio.append(el_path)
        el_ok = True
    except Exception as e:
        el_field = ""
        print(f"        ❌ EL ({label}): {e}")

    try:
        asyncio.run(generate_edge_audio(text, edge_path))
        pad_audio(edge_path)
        all_audio.append(edge_path)
        edge_ok = True
    except Exception as e:
        edge_field = ""
        print(f"        ❌ Edge ({label}): {e}")

    if el_ok or edge_ok:
        cache[h] = {"text": text, "el": el_filename, "edge": edge_filename}
        save_cache(cache)

    return el_field, edge_field, chars_used, False  # not cached

# ================== Main ==================
print()
print("╔══════════════════════════════════════════════════════════════════════╗")
print("║           🇩🇪  German Anki Deck Generator  v2.0                     ║")
print("╚══════════════════════════════════════════════════════════════════════╝")
print()

ledger = load_ledger()
prev_runs = len(ledger["runs"])
print(f"📊 Cost ledger: {prev_runs} previous run(s)  |  All-time: ${ledger['all_time_cost_usd']:.4f} USD")
print()

print("🔗 Connecting to Google Sheets…")
reader     = get_sheet_rows()
total_rows = len(reader)

cache     = load_cache()
all_audio = []

this_run_chars            = 0
this_run_cost             = 0.0
words_cached              = 0
words_generated           = 0
examples_generated        = 0
examples_cached           = 0

print(f"📦 Cache      : {len(cache)} entries already have audio")
print(f"🎤 ElevenLabs : voice={VOICE_ID}  model={MODEL_ID}  speed={SPEED}x")
print(f"🇩🇪 Edge TTS  : {EDGE_VOICE}")
print()
print("─" * 74)
print(f"{'#':>4}  {'German / Example':52}  {'Word':8}  {'Example':8}")
print("─" * 74)

for i, row in enumerate(reader):
    german_text   = str(row.get('german', '')).strip()
    english_text  = str(row.get('english', '')).strip()
    example_text  = str(row.get('example sentence', '')).strip()
    example_pron  = str(row.get('example sentence pronunciation', '')).strip()
    example_trans = str(row.get('example sentence translation', '')).strip()
    grammar_raw   = str(row.get('grammar tags', '')).strip()

    row_num = f"[{i+1:3d}/{total_rows}]"

    if not german_text and not example_text:
        print(f"  {row_num}  {'(empty row)':52}  {'—':8}  {'—':8}")
        continue

    # ── Word audio ───────────────────────────────────────────────────────
    word_status = "—"
    el_word = edge_word = ""

    if german_text:
        el_word, edge_word, chars, was_cached = generate_audio_pair(
            german_text, "word:", "word", cache, all_audio
        )
        if was_cached:
            word_status = "⚡ cache"
            words_cached += 1
        else:
            this_run_chars += chars
            this_run_cost  += chars * EL_COST_PER_CHAR
            word_status = "✅ new"
            words_generated += 1

    # ── Example sentence audio ───────────────────────────────────────────
    ex_status = "—"
    el_ex = edge_ex = ""

    if example_text:
        el_ex, edge_ex, chars, was_cached = generate_audio_pair(
            example_text, "ex:", "example", cache, all_audio
        )
        if was_cached:
            ex_status = "⚡ cache"
            examples_cached += 1
        else:
            this_run_chars += chars
            this_run_cost  += chars * EL_COST_PER_CHAR
            ex_status = "✅ new"
            examples_generated += 1

    display_name = (german_text or example_text)[:50]
    print(f"  {row_num}  {display_name:52}  {word_status:8}  {ex_status:8}")

    # ── Grammar tags → HTML badges ───────────────────────────────────────
    grammar_html = make_grammar_tags_html(grammar_raw)

    # ── Anki note ────────────────────────────────────────────────────────
    note = genanki.Note(
        model=my_model,
        fields=[
            english_text,
            german_text,
            str(row.get('literal', '')).strip(),
            str(row.get('pronunciation', '')).strip(),
            example_text,
            example_pron,
            example_trans,
            grammar_html,
            str(row.get('notes', '')).strip(),
            el_word,
            edge_word,
            el_ex,
            edge_ex,
        ]
    )
    deck.add_note(note)

# ================== Cost ledger update ==================
run_record = record_run(
    ledger,
    chars=this_run_chars,
    cost=this_run_cost,
    words_generated=words_generated,
    examples_generated=examples_generated,
)

# ================== Package ==================
output_file = 'german_deck_dual_audio.apkg'
genanki.Package(deck, media_files=all_audio).write_to_file(output_file)

# ================== Summary ==================
print("─" * 74)
print()
print("╔══════════════════════════════════════════════════════════════════════╗")
print("║                         ✅  RUN COMPLETE                            ║")
print("╠══════════════════════════════════════════════════════════════════════╣")
print(f"║  Total rows           : {total_rows:<46}║")
print(f"║                                                                      ║")
print(f"║  WORDS                                                               ║")
print(f"║    ⚡ Cached           : {words_cached:<46}║")
print(f"║    🆕 Generated        : {words_generated:<46}║")
print(f"║                                                                      ║")
print(f"║  EXAMPLE SENTENCES                                                   ║")
print(f"║    ⚡ Cached           : {examples_cached:<46}║")
print(f"║    🆕 Generated        : {examples_generated:<46}║")
print(f"║                                                                      ║")
print("╠══════════════════════════════════════════════════════════════════════╣")
print(f"║  THIS RUN — ElevenLabs API                                           ║")
print(f"║    Characters sent    : {this_run_chars:<,}".ljust(72) + "║")
print(f"║    Cost               : ${this_run_cost:.5f} USD".ljust(72) + "║")
print(f"║    Timestamp          : {run_record['timestamp']:<46}║")
print("╠══════════════════════════════════════════════════════════════════════╣")
print(f"║  ALL TIME  ({len(ledger['runs'])} run(s) total)".ljust(72) + "║")
print(f"║    Total characters   : {ledger['all_time_chars']:,}".ljust(72) + "║")
print(f"║    Total cost         : ${ledger['all_time_cost_usd']:.5f} USD".ljust(72) + "║")
print(f"║    Ledger saved to    : {LEDGER_FILE:<46}║")
print("╠══════════════════════════════════════════════════════════════════════╣")
print(f"║  Deck saved as        : {output_file:<46}║")
print("╚══════════════════════════════════════════════════════════════════════╝")
print()

# ================== AnkiConnect auto-import ==================
def get_windows_host_ip() -> str:
    result = subprocess.run(["ip", "route", "show"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default" in line:
            return line.split()[2]
    return "172.27.64.1"

def import_to_anki(apkg_path: str):
    result = subprocess.run(
        ["wslpath", "-w", os.path.abspath(apkg_path)],
        capture_output=True, text=True
    )
    windows_path = result.stdout.strip()
    host_ip = get_windows_host_ip()
    payload = {
        "action": "importPackage",
        "version": 6,
        "params": {"path": windows_path}
    }
    try:
        r = requests.post(f"http://{host_ip}:8765", json=payload, timeout=10)
        resp = r.json()
        if resp.get("error"):
            print(f"⚠️  AnkiConnect error: {resp['error']}")
        else:
            print(f"✅ Auto-imported into Anki!")
    except requests.exceptions.ConnectionError:
        print(f"⚠️  Couldn't reach Anki at {host_ip}:8765 — is Anki open with AnkiConnect?")

import_to_anki(output_file)
print()
