import genanki
import csv
import random
import asyncio
import os
import json
import hashlib
from elevenlabs.client import ElevenLabs
from elevenlabs import save
from edge_tts import Communicate
from dotenv import load_dotenv

# ================== CONFIG ==================
DECK_NAME  = "German Vocab"
MODEL_NAME = "English → German (Dual Audio)"
AUDIO_DIR  = "audio"
CACHE_FILE = "audio_cache.json"   # tracks which words already have audio

load_dotenv()

elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

VOICE_ID   = "dFA3XRddYScy6ylAYTIO" # this is paid voice, go to https://elevenlabs.io/app/voice-library for all voices
MODEL_ID   = "eleven_flash_v2_5"
SPEED      = 0.7

EDGE_VOICE = "de-DE-ConradNeural"

os.makedirs(AUDIO_DIR, exist_ok=True)

# ================== Cache helpers ==================
def load_cache() -> dict:
    """Load existing cache, or start fresh."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def text_hash(text: str) -> str:
    """Short, stable ID for any german string."""
    return hashlib.md5(text.strip().lower().encode("utf-8")).hexdigest()[:12]

# ================== Anki Model ==================
model_id = random.randrange(1 << 30, 1 << 31)
deck_id  = random.randrange(1 << 30, 1 << 31)

my_model = genanki.Model(
    model_id, MODEL_NAME,
    fields=[
        {'name': 'English'},
        {'name': 'German'},
        {'name': 'Literal'},
        {'name': 'Pronunciation'},
        {'name': 'Notes'},
        {'name': 'AudioEL'},
        {'name': 'AudioEdge'},
    ],
    templates=[{
        'name': 'Card 1',
        'qfmt': '{{English}}',
        'afmt': '''{{FrontSide}}
<hr id="answer">

<div style="font-size: 28px; color: #2c7a7b; margin: 15px 0;">
    <b>{{German}}</b>
</div>

<div style="margin: 12px 0 4px 0;">
    <span style="font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 1px;">
        🎙 ElevenLabs (slow &amp; clear)
    </span><br>
    {{AudioEL}}
</div>

<div style="margin: 12px 0 16px 0;">
    <span style="font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 1px;">
        🇩🇪 Native German accent
    </span><br>
    {{AudioEdge}}
</div>

{{#Pronunciation}}
<b style="color: #444;">Pronunciation:</b> {{Pronunciation}}<br><br>
{{/Pronunciation}}

{{#Literal}}
<b style="color: #444;">Literal:</b> {{Literal}}<br><br>
{{/Literal}}

{{#Notes}}
<b style="color: #444;">Notes:</b> {{Notes}}
{{/Notes}}'''
    }],
    css=""".card {
        font-family: Arial, sans-serif;
        font-size: 22px;
        text-align: center;
        color: black;
        background-color: white;
        padding: 20px;
    }"""
)

deck = genanki.Deck(deck_id, DECK_NAME)

# ================== Edge TTS helper ==================
async def generate_edge_audio(text: str, filename: str):
    path = os.path.join(AUDIO_DIR, filename)
    communicate = Communicate(text.strip(), EDGE_VOICE)
    await communicate.save(path)

# ================== Main ==================
cache     = load_cache()
all_audio = []

total_chars = 0
total_cost  = 0.0
skipped     = 0
generated   = 0

print(f"📦 Cache loaded: {len(cache)} words already have audio\n")
print(f"🎤 ElevenLabs: {VOICE_ID}  |  Speed: {SPEED}x")
print(f"🇩🇪 Edge TTS : {EDGE_VOICE}\n")
print("─" * 70)

with open('your_file.csv', 'r', encoding='utf-8') as f:
    reader     = list(csv.DictReader(f))
    total_rows = len(reader)

    for i, row in enumerate(reader):
        german_text = row.get('german', '').strip()
        prefix      = f"[{i+1:3d}/{total_rows}] {german_text[:48]:48}"

        if not german_text:
            print(f"{prefix} → Skipped (empty)")
            continue

        h             = text_hash(german_text)
        el_filename   = f"german_el_{h}.mp3"
        edge_filename = f"german_edge_{h}.mp3"
        el_path       = os.path.join(AUDIO_DIR, el_filename)
        edge_path     = os.path.join(AUDIO_DIR, edge_filename)

        # ── Cache hit: both files exist ──────────────────────────────────
        if h in cache and os.path.exists(el_path) and os.path.exists(edge_path):
            print(f"{prefix} → ⚡ Cached (skipped API)")
            skipped += 1
            el_field   = f"[sound:{el_filename}]"
            edge_field = f"[sound:{edge_filename}]"
            all_audio.extend([el_path, edge_path])

        # ── Cache miss: generate fresh audio ────────────────────────────
        else:
            el_field   = ""
            edge_field = ""
            status     = []

            # ElevenLabs
            try:
                char_count   = len(german_text)
                total_chars += char_count
                total_cost  += (char_count / 1000) * 0.05

                audio = elevenlabs.text_to_speech.convert(
                    text=german_text,
                    voice_id=VOICE_ID,
                    model_id=MODEL_ID,
                    output_format="mp3_44100_128",
                    voice_settings={
                        "speed": SPEED,
                        "stability": 0.75,
                        "similarity_boost": 0.85,
                    }
                )
                save(audio, el_path)
                el_field = f"[sound:{el_filename}]"
                all_audio.append(el_path)
                status.append("✅ EL")
            except Exception as e:
                status.append(f"❌ EL({e})")

            # Edge TTS
            try:
                asyncio.run(generate_edge_audio(german_text, edge_filename))
                edge_field = f"[sound:{edge_filename}]"
                all_audio.append(edge_path)
                status.append("✅ Edge")
            except Exception as e:
                status.append(f"❌ Edge({e})")

            # Save to cache only if at least one succeeded
            if el_field or edge_field:
                cache[h] = {
                    "german": german_text,
                    "el":     el_filename,
                    "edge":   edge_filename,
                }
                save_cache(cache)   # write after each word → safe if script crashes mid-run

            generated += 1
            print(f"{prefix} → {' | '.join(status)}")

        # Build Anki note
        note = genanki.Note(
            model=my_model,
            fields=[
                row.get('english', '').strip(),
                german_text,
                row.get('literal', '').strip(),
                row.get('pronunciation', '').strip(),
                row.get('notes', '').strip(),
                el_field,
                edge_field,
            ]
        )
        deck.add_note(note)

# ================== Package & Summary ==================
output_file = 'german_deck_dual_audio.apkg'
genanki.Package(deck, media_files=all_audio).write_to_file(output_file)

print("\n" + "=" * 70)
print("✅ DONE!")
print(f"  Total rows       : {total_rows}")
print(f"  ⚡ Cached (free)  : {skipped}")
print(f"  🆕 Generated      : {generated}")
print(f"  Characters sent  : {total_chars:,}")
print(f"  Estimated cost   : ${total_cost:.3f} USD  (ElevenLabs only)")
print(f"  Deck saved as    : {output_file}")
print("=" * 70)
