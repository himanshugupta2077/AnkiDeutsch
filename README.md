# 🇩🇪 AnkiDeutsch: AI-Powered German Flashcard Generator

> Pull vocab from a Google Sheet, generate dual AI audio, and ship a polished Anki deck: with smart caching so you never pay for the same word twice.

---

## ✨ What It Does

You maintain a Google Sheet of German vocabulary. Run the script and it produces a ready-to-import `.apkg` Anki deck where every card has:

- 🎙 **ElevenLabs voice**: slow, clear pronunciation (great for drilling)
- 🇩🇪 **Microsoft Edge TTS**: native German accent (free, no API key needed)
- 📖 **Example sentence**: with its own dual audio, pronunciation guide, and English translation
- 🏷 **Grammar tags**: rendered as colour-coded badges on the card
- ⚡ **Smart caching**: audio is generated once and reused forever; re-run daily and only new words hit the API
- 💰 **Cost ledger**: every run is logged to `cost_ledger.json` so you always know your ElevenLabs spend

---

## 🖥️ Terminal Output

<p align="center">
  <img width="700" alt="Terminal: running the script, generating audio" src="https://github.com/user-attachments/assets/eadb6e78-5e6a-4715-9f13-ec5f218f5516" />
</p>
<p align="center">
  <img width="700" alt="Terminal: cache hits and run summary" src="https://github.com/user-attachments/assets/9efc35cf-2dc8-4ce3-978b-f0289b7d4398" />
</p>

---

## 📸 Card Preview

<p align="center">
  <img width="700" alt="Anki card: German word, grammar tags, pronunciation, example sentence" src="https://github.com/user-attachments/assets/ae855015-69f8-46da-9e99-d3a25d8b39ef" />
</p>

Each card shows the German word, grammar tag badges, pronunciation with inline audio buttons, and a fully labelled example sentence block (sentence → pronunciation → meaning → audio). Cards inherit Anki's native light/dark theme automatically.

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
```

Get a free key at [elevenlabs.io](https://elevenlabs.io): the free tier includes 10,000 chars/month.

### 3. Set up Google Sheets access

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project
2. Enable the **Google Sheets API**
3. Create an **OAuth 2.0 Desktop credential** and download it as `credentials.json` into the project root
4. On first run the script will print an auth URL: open it in your browser, approve access, and paste the code back into the terminal. A `token.pickle` is saved so you won't be asked again.

### 4. Prepare your Google Sheet

The sheet must have these column headers in row 1 (order doesn't matter):

| Column | Required | Description |
|---|---|---|
| `english` | ✅ | Front of the card |
| `german` | ✅ | The word/phrase: this is what gets spoken |
| `pronunciation` | optional | Phonetic guide, e.g. `vee gayt es EE-nen` |
| `literal` | optional | Word-for-word translation |
| `grammar tags` | optional | Comma-separated tags, e.g. `verb, separable` |
| `notes` | optional | Usage tips, grammar context |
| `example sentence` | optional | A German example sentence |
| `example sentence pronunciation` | optional | Phonetic guide for the example |
| `example sentence translation` | optional | English meaning of the example |

For pronunciation-only rows (e.g. teaching the `ch` sound), leave `english` blank and put the rule in `german`: the script handles it.

### 5. Paste your Sheet URL into the script

```python
SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit"
```

### 6. Run

```bash
python generate_deck.py
```

### 7. Import into Anki

Open Anki → **File → Import** → select `german_deck_dual_audio.apkg`

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

**Keep these between runs:**
```
audio/             ← generated MP3 files
audio_cache.json   ← the hash index
```

Editing a German phrase (even fixing a typo) changes its hash, so it gets regenerated automatically: which is the correct behaviour.

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
      "examples_generated": 6
    }
  ],
  "all_time_chars": 4821,
  "all_time_cost_usd": 0.24105
}
```

The terminal summary always shows both this-run and all-time totals:

```
╔══════════════════════════════════════════════════════════════════════╗
║  THIS RUN: ElevenLabs API                                           ║
║    Characters sent    : 312                                          ║
║    Cost               : $0.01560 USD                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║  ALL TIME  (9 run(s) total)                                          ║
║    Total characters   : 4,821                                        ║
║    Total cost         : $0.24105 USD                                 ║
╚══════════════════════════════════════════════════════════════════════╝
```

Only ElevenLabs is billed: Edge TTS is always free.

---

## ⚙️ Configuration

All settings are at the top of `generate_deck.py`:

```python
VOICE_ID   = "dFA3XRddYScy6ylAYTIO"   # ElevenLabs voice ID
MODEL_ID   = "eleven_flash_v2_5"       # ElevenLabs model
SPEED      = 0.7                        # 0.7 = slow & clear, 1.0 = normal speed

EDGE_VOICE = "de-DE-ConradNeural"      # Microsoft Neural German voice
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
| Edge TTS (Microsoft) | **Free**: unlimited |
| ElevenLabs flash model | ~$0.05 per 1,000 characters |

A 200-word deck with example sentences (~10,000 chars total) costs roughly **$0.50**: and you only ever pay once per phrase.

---

## 📁 Project Structure

```
ankideutsch/
├── generate_deck.py              # Main script
├── credentials.json              # Google OAuth credential (never commit)
├── token.pickle                  # Auto-saved auth token
├── .env                          # ElevenLabs API key (never commit)
├── audio_cache.json              # Auto-generated cache index
├── cost_ledger.json              # All-time cost log
├── audio/                        # Auto-generated MP3 files
│   ├── german_el_a3f9c1.mp3      # ElevenLabs audio
│   └── german_edge_a3f9c1.mp3   # Edge TTS audio
└── german_deck_dual_audio.apkg   # Output: import this into Anki
```

---

## 🧠 Why Anki?

Anki uses spaced repetition: it shows you cards right before you'd forget them. It's consistently one of the most efficient methods for long-term vocabulary retention. This tool removes the friction of building and maintaining a high-quality audio deck so you can focus entirely on learning.

---

## 📄 License

MIT: do whatever you want with it.
