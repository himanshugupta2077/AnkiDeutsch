# 🇩🇪 AnkiDeutsch: AI-Powered German Flashcard Generator

> Pull vocab from a Google Sheet, generate dual AI audio, and ship a polished multi-deck Anki package — with smart caching so you never pay for the same word twice.

---

## ✨ What It Does

You maintain a Google Sheet of German vocabulary. Run the script and it produces a ready-to-import `.apkg` with **three separate Anki decks** where every card has:

- 🎙 **ElevenLabs voice**: slow, clear pronunciation (great for drilling)
- 🇩🇪 **Microsoft Edge TTS**: native German accent (free, no API key needed)
- 📖 **Example sentence**: with its own dual audio, pronunciation guide, and English translation
- 🏷 **Grammar tags**: rendered as colour-coded badges on the card
- ⚡ **Smart caching**: audio is generated once and reused forever; re-run daily and only new words hit the API
- 💰 **Cost ledger**: every run is logged to `cost_ledger.json` so you always know your ElevenLabs spend
- 🌙 **Light/dark theme aware**: all card styles inherit Anki's native theme automatically

---

## 📦 The Three Decks

| Deck | Purpose | Card front |
|---|---|---|
| `German::Core` | Standard vocabulary | English word → German word + audio + example |
| `German::Grammar` | Grammar rules & pronunciation | English prompt → German + rule/explanation box + audio |
| `German::Listening` | Comprehension training | Audio only → reveal text (2 card types per row) |

### Listening cards (auto-generated)

Each row with an example sentence produces **two** listening cards:

- **Sentence card** — front: example sentence audio → back: sentence text + translation
- **Word card** — front: German word audio → back: German word + grammar + English

Core rows automatically generate listening cards too (controlled by the `GENERATE_LISTENING_FROM_CORE` flag). Audio files are shared — no extra API calls.

---

## 🖥️ Terminal Output

<p align="center">
  <img width="700" alt="Terminal: running the script, generating audio" src="https://github.com/user-attachments/assets/722f3fc3-5a9b-4de0-bc80-52fdf22e1786" />
</p>
<p align="center">
  <img width="700" alt="Terminal: cache hits and run summary" src="https://github.com/user-attachments/assets/ea34181e-c411-420d-88c3-22c27af5e873" />
</p>

---

## 📸 Card Preview
- Imported Decks
<p align="center">
  <img width="700" alt="Anki card: German word, grammar tags, pronunciation, example sentence" src="https://github.com/user-attachments/assets/447679a3-54d5-4325-b6f9-12aafa2732d1" />
</p>
- Core Subdeck
<p align="center">
  <img width="700" alt="Anki card: German word, grammar tags, pronunciation, example sentence" src="https://github.com/user-attachments/assets/1249b0fa-6ed5-4eb9-a12b-a261ced0361a" />
</p>
- Grammer Subdeck
<p align="center">
  <img width="700" alt="Anki card: German word, grammar tags, pronunciation, example sentence" src="https://github.com/user-attachments/assets/82f16c8a-c368-478f-bb5b-a3c30b88b100" />
</p>
- Listening Subdeck
<p align="center">
  <img width="700" alt="Anki card: German word, grammar tags, pronunciation, example sentence" src="https://github.com/user-attachments/assets/9786ead1-def5-41df-878b-18e79ff99243" />
</p>

Each card shows the German word, grammar tag badges, pronunciation with inline audio buttons, and a fully labelled example sentence block (sentence → pronunciation → meaning → audio). Cards adapt to Anki's light and dark themes automatically.

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install genanki elevenlabs edge-tts pydub python-dotenv gspread google-auth google-auth-oauthlib requests
```

### 2. Set your ElevenLabs API key

Create a `.env` file in the project root:

```env
ELEVENLABS_API_KEY=your_api_key_here
SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit
```

Get a free key at [elevenlabs.io](https://elevenlabs.io) — the free tier includes 10,000 chars/month.

### 3. Set up Google Sheets access

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project
2. Enable the **Google Sheets API**
3. Create an **OAuth 2.0 Desktop credential** and download it as `credentials.json` into the project root
4. On first run the script prints an auth URL — open it in your browser, approve access, and paste the code back into the terminal. A `token.pickle` is saved so you won't be asked again.

### 4. Prepare your Google Sheet

The sheet must have these column headers in row 1 (order doesn't matter):

| Column | Required | Description |
|---|---|---|
| `english` | ✅ | Front of the card |
| `german` | ✅ | The word/phrase — this is what gets spoken |
| `deck` | optional | `core` (default), `grammar`, or `listening` |
| `pronunciation` | optional | Phonetic guide, e.g. `vee gayt es EE-nen` |
| `literal` | optional | Word-for-word translation |
| `grammar tags` | optional | Comma-separated tags, e.g. `verb, separable` |
| `notes` | optional | Usage tips or grammar rule (shown prominently on Grammar cards) |
| `example sentence` | optional | A German example sentence |
| `example sentence pronunciation` | optional | Phonetic guide for the example |
| `example sentence translation` | optional | English meaning of the example |

**Deck routing:** set the `deck` column to `grammar` to route a row into `German::Grammar`, or `listening` for `German::Listening`. Anything else (or blank) goes to `German::Core`. Invalid values silently default to `core`.

### 5. Run

```bash
python generate_deck.py
```

### 6. Import into Anki

Open Anki → **File → Import** → select `german_deck_multi.apkg`

> ⚠️ If you've imported this deck before, delete the old deck in Anki first so it picks up the refreshed audio files correctly.

---

## ⚡ Smart Caching

Every German phrase is hashed (MD5) and stored in `audio_cache.json`. On re-runs:

```
[  1/30] Guten Morgen                      ⚡ cache   ⚡ cache
[  2/30] Wie geht es Ihnen?                ⚡ cache   ⚡ cache
[ 30/30] Auf Wiedersehen                   ✅ new     ✅ new   ← new word
```

Only new words hit the API. Everything else is repackaged from your local `audio/` folder for free.

Audio is shared across card types — a Core row and its auto-generated Listening cards use the same MP3 files. No duplicate API calls.

**Keep these between runs:**
```
audio/             ← generated MP3 files
audio_cache.json   ← the hash index
```

Editing a German phrase (even fixing a typo) changes its hash, so it gets regenerated automatically — the correct behaviour.

---

## 💰 Cost Tracking

Every run appends a record to `cost_ledger.json`:

```json
{
  "runs": [
    {
      "timestamp": "2025-07-01T14:32:10",
      "chars_sent": 312,
      "cost_usd": 0.01560,
      "words_generated": 8,
      "examples_generated": 6,
      "core_cards": 5,
      "grammar_cards": 2,
      "listening_cards": 10
    }
  ],
  "all_time_chars": 4821,
  "all_time_cost_usd": 0.24105
}
```

The terminal summary always shows both this-run and all-time totals:

```
╔══════════════════════════════════════════════════════════════════════╗
║  CARDS GENERATED                                                     ║
║    📘 Core cards       : 5                                           ║
║    📗 Grammar cards    : 2                                           ║
║    🎧 Listening cards  : 10                                          ║
║    Total cards         : 17                                          ║
╠══════════════════════════════════════════════════════════════════════╣
║  THIS RUN — ElevenLabs API                                           ║
║    Characters sent    : 312                                          ║
║    Cost               : $0.01560 USD                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║  ALL TIME  (9 run(s) total)                                          ║
║    Total characters   : 4,821                                        ║
║    Total cost         : $0.24105 USD                                 ║
╚══════════════════════════════════════════════════════════════════════╝
```

Only ElevenLabs is billed — Edge TTS is always free.

---

## ⚙️ Configuration

All settings are at the top of `generate_deck.py`:

```python
# ElevenLabs
VOICE_ID   = "dFA3XRddYScy6ylAYTIO"   # ElevenLabs voice ID
MODEL_ID   = "eleven_flash_v2_5"       # ElevenLabs model
SPEED      = 0.7                        # 0.7 = slow & clear, 1.0 = normal speed

# Edge TTS
EDGE_VOICE = "de-DE-ConradNeural"      # Microsoft Neural German voice

# Deck behaviour
GENERATE_LISTENING_FROM_CORE = True    # Auto-create Listening cards for Core rows
```

**Alternative Edge TTS voices:**

| Voice ID | Gender | Style |
|---|---|---|
| `de-DE-ConradNeural` | Male | Natural, clear (default) |
| `de-DE-AmalaNeural` | Female | Warm, natural |
| `de-DE-FlorianNeural` | Male | Expressive |
| `de-DE-KatjaNeural` | Female | Professional |

---

## 💵 Pricing at a Glance

| Source | Cost |
|---|---|
| Edge TTS (Microsoft) | **Free** — unlimited |
| ElevenLabs flash model | ~$0.05 per 1,000 characters |

A 200-word deck with example sentences (~10,000 chars total) costs roughly **$0.50** — and you only ever pay once per phrase.

---

## 📁 Project Structure

```
ankideutsch/
├── generate_deck.py              # Main script
├── credentials.json              # Google OAuth credential (never commit)
├── token.pickle                  # Auto-saved auth token
├── .env                          # ElevenLabs API key + Sheet URL (never commit)
├── audio_cache.json              # Auto-generated cache index
├── cost_ledger.json              # All-time cost log
├── audio/                        # Auto-generated MP3 files
│   ├── german_el_a3f9c1.mp3      # ElevenLabs audio
│   └── german_edge_a3f9c1.mp3   # Edge TTS audio
└── german_deck_multi.apkg        # Output: import this into Anki
```

---

## 🧠 Why Anki?

Anki uses spaced repetition — it shows you cards right before you'd forget them. It's consistently one of the most efficient methods for long-term vocabulary retention. This tool removes the friction of building and maintaining a high-quality audio deck so you can focus entirely on learning.

---

## 📄 License

MIT — do whatever you want with it.
