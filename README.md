# 🇩🇪 AnkiDeutsch: AI-Powered German Flashcard Generator

> Turn your German vocabulary CSV into a professional Anki deck: with **two AI voices**, smart caching, and zero repeated API calls.

---

## ✨ What It Does

You maintain a simple CSV file of German vocab. Run this script and it generates a ready-to-import `.apkg` Anki deck where every card has:

- 🎙 **ElevenLabs voice**: slow, clear pronunciation (great for learning)
- 🇩🇪 **Microsoft Neural voice (Edge TTS)**: native German accent (free, no API key needed)
- 📝 English prompt on the front, German + pronunciation guide + notes on the back
- ⚡ **Smart caching**: audio is only generated once per phrase. Re-run daily, pay only for new words.

---

## 📸 Card Preview

**Front:**
```
How are you?
```

**Back:**
```
Wie geht es Ihnen?

🎙 ElevenLabs (slow & clear)   ▶
🇩🇪 Native German accent        ▶

Pronunciation: vee gayt es EE-nen
Literal: How goes it you (formal)?
Notes: Formal version. Use "dir" with friends.
```

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install genanki elevenlabs edge-tts python-dotenv
```

### 2. Set up your ElevenLabs API key

Create a `.env` file in the project root:

```env
ELEVENLABS_API_KEY=your_api_key_here
```

Get a free key at [elevenlabs.io](https://elevenlabs.io): free tier gives 10,000 chars/month.

### 3. Prepare your CSV

Save it as `your_file.csv` with these columns:

```csv
english,german,literal,pronunciation,notes
How are you?,Wie geht es Ihnen?,How goes it you?,"vee gayt es EE-nen","Formal. Use 'dir' with friends."
Good morning,Guten Morgen,Good morning,GOO-ten MOR-gen,Standard greeting
```

| Column | Required | Description |
|---|---|---|
| `english` | ✅ | The front of the card (your prompt) |
| `german` | ✅ | The answer + what gets spoken aloud |
| `literal` | optional | Word-for-word translation |
| `pronunciation` | optional | Phonetic guide |
| `notes` | optional | Grammar tips, usage context, etc. |

### 4. Run the script

```bash
python generate_deck.py
```

### 5. Import into Anki

Open Anki → **File → Import** → select `german_deck_dual_audio.apkg`

> ⚠️ If you've imported this deck before, **delete the old deck first** before re-importing so Anki picks up the new audio files.

---

## ⚡ Smart Caching: How It Works

Every German phrase is hashed (MD5) and stored in `audio_cache.json`. On re-runs:

```
[  1/52] Guten Morgen                     → ⚡ Cached (skipped API)
[  2/52] Wie geht es Ihnen?               → ⚡ Cached (skipped API)
[ 52/52] Auf Wiedersehen                  → ✅ EL | ✅ Edge   ← new word
```

Only **new words** hit the API. Your existing audio is reused and repackaged every time.

**Keep these two things between runs:**
```
audio/             ← your generated MP3 files
audio_cache.json   ← the index
```

If you edit a German phrase (even a typo fix), the hash changes and it gets regenerated automatically: which is the correct behaviour.

---

## ⚙️ Configuration

All settings are at the top of `generate_deck.py`:

```python
VOICE_ID   = "dFA3XRddYScy6ylAYTIO"   # Your ElevenLabs voice ID
MODEL_ID   = "eleven_flash_v2_5"       # ElevenLabs model
SPEED      = 0.7                        # 0.7 = slow/clear, 1.0 = normal

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

## 💰 Cost

| Source | Cost |
|---|---|
| Edge TTS (Microsoft) | **Free**: unlimited |
| ElevenLabs | ~$0.05 per 1,000 characters |

A typical deck of 200 phrases (~5,000 chars) costs roughly **$0.25** in ElevenLabs credits: and you only pay once per phrase thanks to caching.

---

## 📁 Project Structure

```
ankideutsch/
├── generate_deck.py         # Main script
├── your_file.csv            # Your vocabulary (you maintain this)
├── .env                     # API key (never commit this)
├── audio_cache.json         # Auto-generated cache index
├── audio/                   # Auto-generated MP3 files
│   ├── german_el_a3f9c1.mp3
│   └── german_edge_a3f9c1.mp3
└── german_deck_dual_audio.apkg   # Output: import this into Anki
```

---

## 🧠 Why Anki?

Anki uses **spaced repetition**: it shows you cards right before you'd forget them. Studies consistently show it's one of the most efficient ways to build long-term vocabulary retention. This tool removes the friction of creating and maintaining a high-quality deck so you can focus entirely on learning.

---

## 🤝 Contributing

PRs welcome! Ideas for future improvements:

- [ ] Google Sheets integration (auto-pull from a live sheet)
- [ ] Support for other languages
- [ ] Sentence example audio
- [ ] Reverse cards (German → English)

---

## 📄 License

MIT: do whatever you want with it.
