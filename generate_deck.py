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
AUDIO_DIR  = "audio"
CACHE_FILE = "audio_cache.json"
TOKEN_FILE = "token.pickle"
LEDGER_FILE = "cost_ledger.json"

# ── Deck names ──────────────────────────────────────────────────────────────
DECK_CORE      = "German::Core"
DECK_GRAMMAR   = "German::Grammar"
DECK_LISTENING = "German::Listening"

ALLOWED_DECKS  = {"core", "grammar", "listening"}

# ── Feature flags ────────────────────────────────────────────────────────────
# When True, any Core row that has an example sentence will ALSO produce a
# Listening card in German::Listening (audio is reused — no extra TTS calls).
GENERATE_LISTENING_FROM_CORE = True

load_dotenv()
SHEET_URL = os.getenv("SHEET_URL")

elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

VOICE_ID   = "dFA3XRddYScy6ylAYTIO"
MODEL_ID   = "eleven_flash_v2_5"
SPEED      = 0.7

EDGE_VOICE = "de-DE-ConradNeural"

EL_COST_PER_CHAR = 0.05 / 1000

os.makedirs(AUDIO_DIR, exist_ok=True)


# ================== DECK ROUTING ==================
def normalize_deck(value: str) -> str:
    """
    Normalise the raw 'deck' column value.
    - Strips whitespace, case-insensitive.
    - Defaults to 'core' for empty / unrecognised values.
    - Returns one of: 'core' | 'grammar' | 'listening'
    """
    cleaned = value.strip().lower()
    if cleaned in ALLOWED_DECKS:
        return cleaned
    return "core"


DECK_NAME_MAP = {
    "core":      DECK_CORE,
    "grammar":   DECK_GRAMMAR,
    "listening": DECK_LISTENING,
}


# ================== COST LEDGER ==================
def load_ledger() -> dict:
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"runs": [], "all_time_chars": 0, "all_time_cost_usd": 0.0}

def save_ledger(ledger: dict):
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)

def record_run(ledger: dict, chars: int, cost: float,
               words_generated: int, examples_generated: int,
               core_cards: int, grammar_cards: int, listening_cards: int):
    run = {
        "timestamp":          datetime.datetime.now().isoformat(timespec="seconds"),
        "chars_sent":         chars,
        "cost_usd":           round(cost, 5),
        "words_generated":    words_generated,
        "examples_generated": examples_generated,
        "core_cards":         core_cards,
        "grammar_cards":      grammar_cards,
        "listening_cards":    listening_cards,
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
    key = (prefix + text.strip().lower()).encode("utf-8")
    return hashlib.md5(key).hexdigest()[:12]

def note_guid(english: str, german: str, suffix: str = "") -> str:
    """Stable GUID; suffix differentiates card types for the same word."""
    key = f"{english.strip().lower()}::{german.strip().lower()}::{suffix}".encode("utf-8")
    return hashlib.md5(key).hexdigest()


# ================== CSS ==================

CORE_CSS = """.card {
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 20px;
    text-align: center;
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
    margin: 10px 0 14px;
}
.info-block { max-width: 540px; margin: 10px auto 0; text-align: left; }
.info-row {
    display: grid;
    grid-template-columns: 110px 1fr;
    align-items: baseline;
    gap: 8px;
    margin: 9px 0;
}
.info-label {
    font-family: 'Arial', sans-serif;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #3b6fd4;
    opacity: 0.8;
    padding-top: 3px;
}
.info-value { font-size: 15px; line-height: 1.5; }
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
    margin: 2px 3px 2px 0;
    font-family: 'Arial', sans-serif;
}
.audio-inline { display: inline-flex; align-items: center; gap: 5px; }
.section-divider {
    border: none;
    border-top: 1px solid rgba(128,128,128,0.15);
    margin: 18px auto;
    width: 85%;
}
.section-header {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    font-family: 'Arial', sans-serif;
    opacity: 0.45;
    margin: 0 auto 10px;
    max-width: 540px;
    text-align: left;
}
.example-block {
    border-left: 3px solid #3b6fd4;
    padding: 2px 0 2px 14px;
    margin: 4px auto;
    max-width: 540px;
    text-align: left;
}
.ex-row {
    display: grid;
    grid-template-columns: 110px 1fr;
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
.example-sentence { font-size: 16px; font-style: italic; line-height: 1.4; }
.example-pron { font-size: 13px; font-family: 'Arial', sans-serif; opacity: 0.65; }
.example-translation { font-size: 14px; opacity: 0.85; }
.example-audio-row { display: flex; align-items: center; gap: 4px; }
"""

GRAMMAR_CSS = """.card {
    font-family: 'Courier New', 'Lucida Console', monospace;
    font-size: 18px;
    text-align: left;
    padding: 20px 28px;
    box-sizing: border-box;
}
.front-prompt {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 6px;
}
.front-word {
    font-size: 30px;
    font-weight: 700;
    margin: 4px 0 8px;
}
hr#answer {
    border: none;
    border-top: 2px solid currentColor;
    opacity: 0.3;
    margin: 16px 0;
}
.german-word {
    font-size: 30px;
    font-weight: 700;
    color: #c0392b;
    margin: 6px 0 14px;
}
/* Rule box */
.rule-box {
    background: rgba(240, 173, 78, 0.15);
    border-left: 5px solid #f0ad4e;
    padding: 12px 16px;
    margin: 14px 0;
    border-radius: 0 6px 6px 0;
    max-width: 560px;
}
.rule-box-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #f0ad4e;
    margin-bottom: 6px;
}
.rule-text {
    font-size: 15px;
    line-height: 1.6;
}
.grammar-tag {
    display: inline-block;
    background: #c0392b;
    color: white;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.1px;
    text-transform: uppercase;
    padding: 3px 9px;
    border-radius: 3px;
    margin: 2px 3px 2px 0;
    font-family: 'Courier New', monospace;
}
.info-block { max-width: 560px; margin: 10px 0; }
.info-row {
    display: grid;
    grid-template-columns: 130px 1fr;
    align-items: baseline;
    gap: 8px;
    margin: 8px 0;
    border-bottom: 1px solid rgba(128,128,128,0.25);
    padding-bottom: 8px;
}
.info-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #c0392b;
    opacity: 0.9;
}
.info-value { font-size: 15px; line-height: 1.5; }
.audio-inline { display: inline-flex; align-items: center; gap: 5px; }
.section-divider { border: none; border-top: 1px dashed rgba(128,128,128,0.4); margin: 14px 0; }
.section-header {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    opacity: 0.4;
    margin-bottom: 8px;
}
.example-block { border-left: 4px solid #c0392b; padding: 4px 0 4px 14px; margin: 4px 0; }
.ex-row { display: grid; grid-template-columns: 130px 1fr; gap: 8px; margin: 6px 0; }
.ex-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #c0392b; opacity: 0.9; }
.example-sentence { font-size: 15px; font-style: italic; line-height: 1.4; }
.example-pron { font-size: 13px; opacity: 0.6; }
.example-translation { font-size: 13px; opacity: 0.8; }
.example-audio-row { display: flex; align-items: center; gap: 4px; }
"""

LISTENING_CSS = """.card {
    font-family: 'Helvetica Neue', 'Arial', sans-serif;
    text-align: center;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 220px;
    box-sizing: border-box;
}
/* ── FRONT ── */
.listening-front {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 30px 24px;
    gap: 18px;
}
.listening-icon {
    font-size: 54px;
    line-height: 1;
    opacity: 0.85;
    animation: pulse 2.2s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { transform: scale(1);   opacity: 0.85; }
    50%       { transform: scale(1.08); opacity: 1;   }
}
.listening-cue {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #555;
    opacity: 0.7;
}
.listening-audio-front {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    margin-top: 4px;
}
/* ── BACK ── */
hr#answer {
    border: none;
    border-top: 1px solid rgba(128,128,128,0.25);
    width: 80%;
    margin: 14px auto;
}
.back-wrapper {
    width: 100%;
    max-width: 540px;
    padding: 10px 20px 20px;
    text-align: left;
    box-sizing: border-box;
    margin: 0 auto;
}
.german-word {
    font-size: 28px;
    font-weight: 700;
    color: #2d7d46;
    text-align: center;
    margin: 4px 0 14px;
}
.info-block { max-width: 540px; margin: 0 auto; }
.info-row {
    display: grid;
    grid-template-columns: 120px 1fr;
    align-items: baseline;
    gap: 8px;
    margin: 8px 0;
}
.info-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #2d7d46;
    opacity: 0.8;
}
.info-value { font-size: 14px; line-height: 1.5; }
.grammar-tag {
    display: inline-block;
    background: #2d7d46;
    color: white;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.1px;
    text-transform: uppercase;
    padding: 3px 9px;
    border-radius: 20px;
    margin: 2px 3px 2px 0;
}
.audio-inline { display: inline-flex; align-items: center; gap: 5px; }
.section-divider { border: none; border-top: 1px solid rgba(128,128,128,0.15); margin: 14px auto; width: 85%; }
.section-header { font-size: 10px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; opacity: 0.4; margin-bottom: 8px; }
.example-block { border-left: 3px solid #2d7d46; padding: 4px 0 4px 14px; margin: 4px auto; max-width: 540px; }
.ex-row { display: grid; grid-template-columns: 120px 1fr; gap: 8px; margin: 6px 0; }
.ex-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #2d7d46; opacity: 0.8; }
.example-sentence { font-size: 15px; font-style: italic; line-height: 1.4; }
.example-pron { font-size: 13px; opacity: 0.6; }
.example-translation { font-size: 14px; opacity: 0.85; }
.example-audio-row { display: flex; align-items: center; gap: 4px; }
"""


# ================== Anki Models ==================

# Each model needs a unique stable ID derived from its name so re-runs do not
# create duplicate model definitions.
def _stable_model_id(name: str) -> int:
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16)

def _stable_deck_id(name: str) -> int:
    return int(hashlib.md5(name.encode()).hexdigest()[8:16], 16)


CORE_FIELDS = [
    {'name': 'English'},
    {'name': 'German'},
    {'name': 'Literal'},
    {'name': 'Pronunciation'},
    {'name': 'ExampleSentence'},
    {'name': 'ExamplePronunciation'},
    {'name': 'ExampleTranslation'},
    {'name': 'GrammarTags'},
    {'name': 'Notes'},
    {'name': 'AudioEL'},
    {'name': 'AudioEdge'},
    {'name': 'AudioExampleEL'},
    {'name': 'AudioExampleEdge'},
]

CORE_ANSWER_TMPL = """{{FrontSide}}
<hr id="answer">
<div class="german-word">{{German}}</div>
<div class="info-block">
  {{#GrammarTags}}
  <div class="info-row">
    <span class="info-label">Grammar</span>
    <div class="info-value">{{GrammarTags}}</div>
  </div>
  {{/GrammarTags}}
  {{#Pronunciation}}
  <div class="info-row">
    <span class="info-label">Pronunciation</span>
    <div class="info-value">/ {{Pronunciation}} /</div>
  </div>
  {{/Pronunciation}}
  <div class="info-row">
    <span class="info-label">Audio</span>
    <div class="info-value audio-inline">{{AudioEL}}{{AudioEdge}}</div>
  </div>
  {{#Literal}}
  <div class="info-row">
    <span class="info-label">Literal</span>
    <div class="info-value">{{Literal}}</div>
  </div>
  {{/Literal}}
  {{#Notes}}
  <div class="info-row">
    <span class="info-label">Notes</span>
    <div class="info-value">{{Notes}}</div>
  </div>
  {{/Notes}}
</div>
{{#ExampleSentence}}
<hr class="section-divider">
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

CoreNoteModel = genanki.Model(
    _stable_model_id("German Core v1"),
    "German Core v1",
    fields=CORE_FIELDS,
    templates=[{
        'name': 'Core Card',
        'qfmt': '<div class="front-word">{{English}}</div>',
        'afmt': CORE_ANSWER_TMPL,
    }],
    css=CORE_CSS,
)


# ── Grammar model ─────────────────────────────────────────────────────────────
GRAMMAR_FIELDS = [
    {'name': 'English'},
    {'name': 'German'},
    {'name': 'Pronunciation'},
    {'name': 'GrammarTags'},
    {'name': 'Notes'},           # grammar rule / explanation (prominently shown)
    {'name': 'Literal'},
    {'name': 'ExampleSentence'},
    {'name': 'ExamplePronunciation'},
    {'name': 'ExampleTranslation'},
    {'name': 'AudioEL'},
    {'name': 'AudioEdge'},
    {'name': 'AudioExampleEL'},
    {'name': 'AudioExampleEdge'},
]

GRAMMAR_ANSWER_TMPL = """{{FrontSide}}
<hr id="answer">
<div class="german-word">{{German}}</div>

{{#GrammarTags}}
<div class="info-block">
  <div class="info-row">
    <span class="info-label">Grammar</span>
    <div class="info-value">{{GrammarTags}}</div>
  </div>
</div>
{{/GrammarTags}}

{{#Notes}}
<div class="rule-box">
  <div class="rule-box-label">Rule / Explanation</div>
  <div class="rule-text">{{Notes}}</div>
</div>
{{/Notes}}

<div class="info-block">
  {{#Pronunciation}}
  <div class="info-row">
    <span class="info-label">Pronunciation</span>
    <div class="info-value">/ {{Pronunciation}} /</div>
  </div>
  {{/Pronunciation}}
  <div class="info-row">
    <span class="info-label">Audio</span>
    <div class="info-value audio-inline">{{AudioEL}}{{AudioEdge}}</div>
  </div>
  {{#Literal}}
  <div class="info-row">
    <span class="info-label">Literal</span>
    <div class="info-value">{{Literal}}</div>
  </div>
  {{/Literal}}
</div>

{{#ExampleSentence}}
<hr class="section-divider">
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

GrammarNoteModel = genanki.Model(
    _stable_model_id("German Grammar v1"),
    "German Grammar v1",
    fields=GRAMMAR_FIELDS,
    templates=[{
        'name': 'Grammar Card',
        'qfmt': '<div class="front-prompt">Grammar · Pronunciation</div>'
                '<div class="front-word">{{English}}</div>',
        'afmt': GRAMMAR_ANSWER_TMPL,
    }],
    css=GRAMMAR_CSS,
)


# ── Listening models — two separate note types ────────────────────────────────
#
#  ListeningSentenceModel  →  front: example-sentence audio
#                             back:  example sentence text + pronunciation +
#                                    translation + word audio
#
#  ListeningWordModel      →  front: German word audio
#                             back:  German word + pronunciation + grammar +
#                                    notes + literal + English translation
#
# Both share the same field list so a single builder can populate them.

LISTENING_FIELDS = [
    {'name': 'English'},
    {'name': 'German'},
    {'name': 'ExampleSentence'},
    {'name': 'ExamplePronunciation'},
    {'name': 'ExampleTranslation'},
    {'name': 'GrammarTags'},
    {'name': 'Notes'},
    {'name': 'Pronunciation'},
    {'name': 'Literal'},
    {'name': 'AudioEL'},           # word audio
    {'name': 'AudioEdge'},         # word audio
    {'name': 'AudioExampleEL'},    # sentence audio
    {'name': 'AudioExampleEdge'},  # sentence audio
]

# ── Card 1: Sentence listening ─────────────────────────────────────────────
_LS_SENTENCE_FRONT = """<div class="listening-front">
  <div class="listening-icon">🎧</div>
  <div class="listening-cue">Listen &amp; Understand</div>
  <div class="listening-audio-front">
    {{AudioExampleEL}}{{AudioExampleEdge}}
  </div>
</div>
"""

_LS_SENTENCE_BACK = """{{FrontSide}}
<hr id="answer">
<div class="back-wrapper">
  {{#ExampleSentence}}<div class="german-word">{{ExampleSentence}}</div>{{/ExampleSentence}}
  <div class="info-block">
    {{#ExampleTranslation}}
    <div class="info-row">
      <span class="info-label">Translation</span>
      <div class="info-value"><strong>{{ExampleTranslation}}</strong></div>
    </div>
    {{/ExampleTranslation}}
    {{#ExamplePronunciation}}
    <div class="info-row">
      <span class="info-label">Pronunciation</span>
      <div class="info-value example-pron">/ {{ExamplePronunciation}} /</div>
    </div>
    {{/ExamplePronunciation}}
  </div>
</div>
"""

ListeningSentenceModel = genanki.Model(
    _stable_model_id("German Listening Sentence v1"),
    "German Listening Sentence v1",
    fields=LISTENING_FIELDS,
    templates=[{
        'name': 'Listening Sentence Card',
        'qfmt': _LS_SENTENCE_FRONT,
        'afmt': _LS_SENTENCE_BACK,
    }],
    css=LISTENING_CSS,
)

# ── Card 2: Word listening ─────────────────────────────────────────────────
_LS_WORD_FRONT = """<div class="listening-front">
  <div class="listening-icon">🔊</div>
  <div class="listening-cue">What does this word mean?</div>
  <div class="listening-audio-front">
    {{AudioEL}}{{AudioEdge}}
  </div>
</div>
"""

_LS_WORD_BACK = """{{FrontSide}}
<hr id="answer">
<div class="back-wrapper">
  <div class="german-word">{{German}}</div>
  <div class="info-block">
    <div class="info-row">
      <span class="info-label">Translation</span>
      <div class="info-value"><strong>{{English}}</strong></div>
    </div>
    {{#Pronunciation}}
    <div class="info-row">
      <span class="info-label">Pronunciation</span>
      <div class="info-value">/ {{Pronunciation}} /</div>
    </div>
    {{/Pronunciation}}
    {{#GrammarTags}}
    <div class="info-row">
      <span class="info-label">Grammar</span>
      <div class="info-value">{{GrammarTags}}</div>
    </div>
    {{/GrammarTags}}
    {{#Notes}}
    <div class="info-row">
      <span class="info-label">Notes</span>
      <div class="info-value">{{Notes}}</div>
    </div>
    {{/Notes}}
    {{#Literal}}
    <div class="info-row">
      <span class="info-label">Literal</span>
      <div class="info-value">{{Literal}}</div>
    </div>
    {{/Literal}}
  </div>
</div>
"""

ListeningWordModel = genanki.Model(
    _stable_model_id("German Listening Word v1"),
    "German Listening Word v1",
    fields=LISTENING_FIELDS,
    templates=[{
        'name': 'Listening Word Card',
        'qfmt': _LS_WORD_FRONT,
        'afmt': _LS_WORD_BACK,
    }],
    css=LISTENING_CSS,
)


# ================== Deck objects ==================
deck_core      = genanki.Deck(_stable_deck_id(DECK_CORE),      DECK_CORE)
deck_grammar   = genanki.Deck(_stable_deck_id(DECK_GRAMMAR),   DECK_GRAMMAR)
deck_listening = genanki.Deck(_stable_deck_id(DECK_LISTENING), DECK_LISTENING)

DECK_OBJ_MAP = {
    "core":      deck_core,
    "grammar":   deck_grammar,
    "listening": deck_listening,
}


# ================== Audio helpers ==================
async def generate_edge_audio(text: str, filepath: str):
    communicate = Communicate(text.strip(), EDGE_VOICE)
    await communicate.save(filepath)

def pad_audio(filepath: str, silence_ms: int = 300):
    audio   = AudioSegment.from_mp3(filepath)
    silence = AudioSegment.silent(duration=silence_ms)
    padded  = silence + audio
    padded.export(filepath, format="mp3")

def generate_el_audio(text: str, filepath: str) -> int:
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

def make_grammar_tags_html(raw: str, deck_type: str = "core") -> str:
    if not raw.strip():
        return ""
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return " ".join(f'<span class="grammar-tag">{t}</span>' for t in tags)

def generate_audio_pair(text: str, hash_prefix: str, label: str,
                        cache: dict, all_audio: list) -> tuple:
    """
    Returns (el_field, edge_field, chars_used, was_cached).
    Audio files are only created when missing; existing files are reused.
    """
    h             = text_hash(text, prefix=hash_prefix)
    el_filename   = f"german_el_{h}.mp3"
    edge_filename = f"german_edge_{h}.mp3"
    el_path       = os.path.join(AUDIO_DIR, el_filename)
    edge_path     = os.path.join(AUDIO_DIR, edge_filename)

    el_field   = f"[sound:{el_filename}]"
    edge_field = f"[sound:{edge_filename}]"

    if h in cache and os.path.exists(el_path) and os.path.exists(edge_path):
        # Files already on disk — register in all_audio list without re-generating
        for p in [el_path, edge_path]:
            if p not in all_audio:
                all_audio.append(p)
        return el_field, edge_field, 0, True

    chars_used = 0
    el_ok = edge_ok = False

    try:
        chars_used += generate_el_audio(text, el_path)
        if el_path not in all_audio:
            all_audio.append(el_path)
        el_ok = True
    except Exception as e:
        el_field = ""
        print(f"        ❌ EL ({label}): {e}")

    try:
        asyncio.run(generate_edge_audio(text, edge_path))
        pad_audio(edge_path)
        if edge_path not in all_audio:
            all_audio.append(edge_path)
        edge_ok = True
    except Exception as e:
        edge_field = ""
        print(f"        ❌ Edge ({label}): {e}")

    if el_ok or edge_ok:
        cache[h] = {"text": text, "el": el_filename, "edge": edge_filename}
        save_cache(cache)

    return el_field, edge_field, chars_used, False


def audio_files_for(text: str, hash_prefix: str) -> list[str]:
    """Return the expected on-disk paths for a text (for AnkiConnect upload)."""
    h = text_hash(text, prefix=hash_prefix)
    return [
        p for p in [
            os.path.join(AUDIO_DIR, f"german_el_{h}.mp3"),
            os.path.join(AUDIO_DIR, f"german_edge_{h}.mp3"),
        ]
        if os.path.exists(p)
    ]


# ================== AnkiConnect helpers ==================
def get_windows_host_ip() -> str:
    result = subprocess.run(["ip", "route", "show"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default" in line:
            return line.split()[2]
    return "172.27.64.1"

def ankiconnect_request(action: str, **params) -> dict:
    host_ip = get_windows_host_ip()
    payload = {"action": action, "version": 6, "params": params}
    try:
        r = requests.post(f"http://{host_ip}:8765", json=payload, timeout=10)
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"error": f"Couldn't reach Anki at {host_ip}:8765"}

def get_existing_note_ids_by_guid(deck_name: str) -> dict:
    resp = ankiconnect_request("findNotes", query=f'deck:"{deck_name}"')
    if resp.get("error") or not resp.get("result"):
        return {}
    note_ids = resp["result"]
    if not note_ids:
        return {}
    resp2 = ankiconnect_request("notesInfo", notes=note_ids)
    if resp2.get("error"):
        return {}
    guid_to_id = {}
    for info in resp2["result"]:
        eng = info["fields"].get("English", {}).get("value", "").strip().lower()
        ger = info["fields"].get("German", {}).get("value", "").strip().lower()
        logical_key = f"{eng}::{ger}"
        guid_to_id[logical_key] = info["noteId"]
    return guid_to_id

def update_note_in_anki(note_id: int, fields: dict, audio_files: list[str]) -> bool:
    resp = ankiconnect_request("updateNoteFields", note={
        "id": note_id,
        "fields": fields,
    })
    if resp.get("error"):
        print(f"        ⚠️  updateNoteFields error: {resp['error']}")
        return False
    host_ip = get_windows_host_ip()
    for path in audio_files:
        if not os.path.exists(path):
            continue
        filename = os.path.basename(path)
        with open(path, "rb") as f:
            import base64
            data_b64 = base64.b64encode(f.read()).decode()
        ankiconnect_request("storeMediaFile", filename=filename, data=data_b64)
    return True


# ================== Note builders ==================

def build_core_note(row_data: dict, el_word: str, edge_word: str,
                    el_ex: str, edge_ex: str, grammar_html: str) -> genanki.Note:
    fields_dict = {
        'English':              row_data['english'],
        'German':               row_data['german'],
        'Literal':              row_data['literal'],
        'Pronunciation':        row_data['pronunciation'],
        'ExampleSentence':      row_data['example'],
        'ExamplePronunciation': row_data['example_pron'],
        'ExampleTranslation':   row_data['example_trans'],
        'GrammarTags':          grammar_html,
        'Notes':                row_data['notes'],
        'AudioEL':              el_word,
        'AudioEdge':            edge_word,
        'AudioExampleEL':       el_ex,
        'AudioExampleEdge':     edge_ex,
    }
    return genanki.Note(
        model=CoreNoteModel,
        guid=note_guid(row_data['english'], row_data['german'], "core"),
        fields=list(fields_dict.values()),
        tags=[DECK_CORE.replace("::", "-"), "core"] + row_data['tag_list'],
    ), fields_dict


def build_grammar_note(row_data: dict, el_word: str, edge_word: str,
                       el_ex: str, edge_ex: str, grammar_html: str) -> genanki.Note:
    fields_dict = {
        'English':              row_data['english'],
        'German':               row_data['german'],
        'Pronunciation':        row_data['pronunciation'],
        'GrammarTags':          grammar_html,
        'Notes':                row_data['notes'],
        'Literal':              row_data['literal'],
        'ExampleSentence':      row_data['example'],
        'ExamplePronunciation': row_data['example_pron'],
        'ExampleTranslation':   row_data['example_trans'],
        'AudioEL':              el_word,
        'AudioEdge':            edge_word,
        'AudioExampleEL':       el_ex,
        'AudioExampleEdge':     edge_ex,
    }
    return genanki.Note(
        model=GrammarNoteModel,
        guid=note_guid(row_data['english'], row_data['german'], "grammar"),
        fields=list(fields_dict.values()),
        tags=[DECK_GRAMMAR.replace("::", "-"), "grammar", "pronunciation"]
              + row_data['tag_list'],
    ), fields_dict


def _listening_fields_dict(row_data: dict, el_word: str, edge_word: str,
                           el_ex: str, edge_ex: str, grammar_html: str) -> dict:
    """Shared field population for both listening card variants."""
    return {
        'English':              row_data['english'],
        'German':               row_data['german'],
        'ExampleSentence':      row_data['example'],
        'ExamplePronunciation': row_data['example_pron'],
        'ExampleTranslation':   row_data['example_trans'],
        'GrammarTags':          grammar_html,
        'Notes':                row_data['notes'],
        'Pronunciation':        row_data['pronunciation'],
        'Literal':              row_data['literal'],
        'AudioEL':              el_word,
        'AudioEdge':            edge_word,
        'AudioExampleEL':       el_ex,
        'AudioExampleEdge':     edge_ex,
    }


def build_listening_sentence_note(row_data: dict, el_word: str, edge_word: str,
                                  el_ex: str, edge_ex: str, grammar_html: str):
    """Card 1 — front: example-sentence audio → back: sentence text + word audio."""
    fields_dict = _listening_fields_dict(
        row_data, el_word, edge_word, el_ex, edge_ex, grammar_html
    )
    note = genanki.Note(
        model=ListeningSentenceModel,
        guid=note_guid(row_data['english'], row_data['german'], "listening-sentence"),
        fields=list(fields_dict.values()),
        tags=[DECK_LISTENING.replace("::", "-"), "listening", "sentence"]
              + row_data['tag_list'],
    )
    return note, fields_dict


def build_listening_word_note(row_data: dict, el_word: str, edge_word: str,
                              el_ex: str, edge_ex: str, grammar_html: str):
    """Card 2 — front: German word audio → back: German word + grammar + translation."""
    fields_dict = _listening_fields_dict(
        row_data, el_word, edge_word, el_ex, edge_ex, grammar_html
    )
    note = genanki.Note(
        model=ListeningWordModel,
        guid=note_guid(row_data['english'], row_data['german'], "listening-word"),
        fields=list(fields_dict.values()),
        tags=[DECK_LISTENING.replace("::", "-"), "listening", "word"]
              + row_data['tag_list'],
    )
    return note, fields_dict


NOTE_BUILDERS = {
    "core":    build_core_note,
    "grammar": build_grammar_note,
    # listening is handled inline — produces 2 notes per row
}



# ================== Main ==================
print()
print("╔══════════════════════════════════════════════════════════════════════╗")
print("║         🇩🇪  German Anki Deck Generator  v4.0  (Multi-Deck)         ║")
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
all_audio = []   # collected across all card types; deduped via set-check above

this_run_chars            = 0
this_run_cost             = 0.0
words_cached              = 0
words_generated           = 0
examples_generated        = 0
examples_cached           = 0
core_card_count           = 0
grammar_card_count        = 0
listening_card_count      = 0

# Fetch existing notes per deck
# Listening deck stores 2 note-types per row; we key them by suffix.
print("🔍 Fetching existing Anki notes for update detection…")
existing_notes = {
    "core":                get_existing_note_ids_by_guid(DECK_CORE),
    "grammar":             get_existing_note_ids_by_guid(DECK_GRAMMAR),
    "listening-sentence":  get_existing_note_ids_by_guid(DECK_LISTENING),
    "listening-word":      get_existing_note_ids_by_guid(DECK_LISTENING),
}
print(f"   {DECK_CORE}: {len(existing_notes['core'])} existing note(s)")
print(f"   {DECK_GRAMMAR}: {len(existing_notes['grammar'])} existing note(s)")
print(f"   {DECK_LISTENING}: {len(existing_notes['listening-sentence'])} existing note(s)")
print()

notes_added   = 0
notes_updated = 0

print(f"📦 Cache      : {len(cache)} entries already have audio")
print(f"🎤 ElevenLabs : voice={VOICE_ID}  model={MODEL_ID}  speed={SPEED}x")
print(f"🇩🇪 Edge TTS  : {EDGE_VOICE}")
print(f"🔀 Auto-Listening from Core: {'ON' if GENERATE_LISTENING_FROM_CORE else 'OFF'}")
print()
print("─" * 90)
print(f"{'#':>4}  {'German':38}  {'Deck':10}  {'Word':8}  {'Ex':8}  {'Action':10}")
print("─" * 90)

for i, row in enumerate(reader):
    german_text   = str(row.get('german', '')).strip()
    english_text  = str(row.get('english', '')).strip()
    example_text  = str(row.get('example sentence', '')).strip()
    example_pron  = str(row.get('example sentence pronunciation', '')).strip()
    example_trans = str(row.get('example sentence translation', '')).strip()
    grammar_raw   = str(row.get('grammar tags', '')).strip()
    deck_raw      = str(row.get('deck', '')).strip()

    deck_key  = normalize_deck(deck_raw)
    deck_name = DECK_NAME_MAP[deck_key]
    row_num   = f"[{i+1:3d}/{total_rows}]"

    if not german_text and not example_text:
        print(f"  {row_num}  {'(empty row)':38}  {'—':10}  {'—':8}  {'—':8}  {'—':10}")
        continue

    # Build auto-tag list from grammar column
    tag_list = []
    if grammar_raw:
        for t in grammar_raw.split(","):
            clean = t.strip().lower().replace(" ", "-")
            if clean:
                tag_list.append(clean)
    if deck_key == "grammar":
        tag_list += ["grammar", "pronunciation"]
    elif deck_key == "listening":
        tag_list.append("listening")

    row_data = {
        'english':      english_text,
        'german':       german_text,
        'literal':      str(row.get('literal', '')).strip(),
        'pronunciation': str(row.get('pronunciation', '')).strip(),
        'example':      example_text,
        'example_pron': example_pron,
        'example_trans': example_trans,
        'notes':        str(row.get('notes', '')).strip(),
        'tag_list':     tag_list,
    }

    grammar_html = make_grammar_tags_html(grammar_raw, deck_key)

    # ── Word audio ─────────────────────────────────────────────────────────
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

    # ── Example sentence audio ─────────────────────────────────────────────
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

    display_name = (german_text or example_text)[:36]

    # ── Audio needed for AnkiConnect upload (both listening cards share these) ──
    ac_audio     = (audio_files_for(german_text, "word:")
                    + audio_files_for(example_text, "ex:"))
    logical_key  = f"{english_text.lower()}::{german_text.lower()}"
    action_parts = []

    # ── Helper: add one note to a deck, handling update-in-place ─────────────
    def _add_note(note, fields_dict, deck_obj, existing_key: str, label: str):
        global notes_added, notes_updated
        ex = existing_notes.get(existing_key, {})
        if logical_key in ex:
            update_note_in_anki(ex[logical_key], fields_dict, ac_audio)
            notes_updated += 1
            action_parts.append(f"🔄{label}")
        else:
            notes_added += 1
            action_parts.append(f"➕{label}")
        deck_obj.add_note(note)

    # ── Primary card (Core or Grammar) ────────────────────────────────────────
    if deck_key in NOTE_BUILDERS:
        note, fields_dict = NOTE_BUILDERS[deck_key](
            row_data, el_word, edge_word, el_ex, edge_ex, grammar_html
        )
        if deck_key == "core":
            core_card_count += 1
        elif deck_key == "grammar":
            grammar_card_count += 1
        _add_note(note, fields_dict, DECK_OBJ_MAP[deck_key], deck_key, deck_key[0].upper())

    # ── Listening cards — always 2 per row when example audio exists ──────────
    # Triggered by:  deck=Listening   OR   (deck=Core + GENERATE_LISTENING_FROM_CORE)
    want_listening = (
        deck_key == "listening"
        or (deck_key == "core" and GENERATE_LISTENING_FROM_CORE)
    )
    has_sentence_audio = bool(example_text and (el_ex or edge_ex))
    has_word_audio     = bool(german_text  and (el_word or edge_word))

    if want_listening and has_sentence_audio:
        # Card 1 — sentence audio front
        note_s, fd_s = build_listening_sentence_note(
            row_data, el_word, edge_word, el_ex, edge_ex, grammar_html
        )
        listening_card_count += 1
        _add_note(note_s, fd_s, deck_listening, "listening-sentence", "LS")

        # Card 2 — word audio front (only if we actually have word audio)
        if has_word_audio:
            note_w, fd_w = build_listening_word_note(
                row_data, el_word, edge_word, el_ex, edge_ex, grammar_html
            )
            listening_card_count += 1
            _add_note(note_w, fd_w, deck_listening, "listening-word", "LW")

    action_str = " ".join(action_parts)
    print(f"  {row_num}  {display_name:38}  {deck_name.split('::')[1]:10}  "
          f"{word_status:8}  {ex_status:8}  {action_str}")


# ================== Cost ledger ==================
run_record = record_run(
    ledger,
    chars=this_run_chars,
    cost=this_run_cost,
    words_generated=words_generated,
    examples_generated=examples_generated,
    core_cards=core_card_count,
    grammar_cards=grammar_card_count,
    listening_cards=listening_card_count,
)

# ================== Package all decks ==================
output_file = 'german_deck_multi.apkg'
all_decks   = [deck_core, deck_grammar, deck_listening]
genanki.Package(all_decks, media_files=all_audio).write_to_file(output_file)

# ================== Summary ==================
print("─" * 90)
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
print(f"║  CARDS GENERATED                                                     ║")
print(f"║    📘 Core cards       : {core_card_count:<46}║")
print(f"║    📗 Grammar cards    : {grammar_card_count:<46}║")
print(f"║    🎧 Listening cards  : {listening_card_count:<46}║")
print(f"║    ─────────────────────────────────────────────────────────────    ║")
total_cards = core_card_count + grammar_card_count + listening_card_count
print(f"║    Total cards         : {total_cards:<46}║")
print(f"║                                                                      ║")
print(f"║  ANKI NOTES                                                          ║")
print(f"║    ➕ Added (new)      : {notes_added:<46}║")
print(f"║    🔄 Updated (exist)  : {notes_updated:<46}║")
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
            print(f"✅ Auto-imported into Anki (new cards added, existing progress preserved)!")
    except requests.exceptions.ConnectionError:
        print(f"⚠️  Couldn't reach Anki at {host_ip}:8765 — is Anki open with AnkiConnect?")

import_to_anki(output_file)
print()
