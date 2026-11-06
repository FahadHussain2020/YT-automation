# YT Automation

A YouTube video pipeline that runs on your own computer, for free:
competitor research → script → voice → render → review dashboard → upload → Shorts → analytics.
It has a "kids" mode for made-for-kids songs and stories (ages 0 to 6) and a default mode
for researched, sourced narration videos.

The code lives in [`yt-autopilot/`](yt-autopilot). Its own README covers every command and option.

> **AI models are not in this repo** (they are hundreds of MB). One script downloads them, see step 3.

---

## Quick start

### 1. Install the tools you need

| Tool | Version | Linux (Ubuntu/Debian) | macOS |
|---|---|---|---|
| git | any | `sudo apt install git` | `xcode-select --install` |
| Python | 3.10+ | `sudo apt install python3 python3-venv` | `brew install python` |
| ffmpeg | any | `sudo apt install ffmpeg` | `brew install ffmpeg` |
| curl | any | `sudo apt install curl` | built in |

On Windows, use WSL (Ubuntu) and follow the Linux column.

### 2. Get the code

```bash
git clone <repo-url> yt-automation
cd yt-automation
python3 -m venv .venv
source .venv/bin/activate          # run this again in every new terminal
pip install -r yt-autopilot/requirements.txt
```

### 3. Download the voice model (once, about 340 MB)

```bash
./scripts/download_models.sh
```

This puts the free [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) TTS model in `models/`
and links it into `yt-autopilot/models/`. Both are git-ignored.

### 4. Configure and test

```bash
cd yt-autopilot
cp .env.example .env               # fill in only what you need; it is git-ignored
python -m pytest -q                # all tests run offline, no keys needed
```

Then edit `config/channel.yaml` for your own channel: name, niche, audience, keywords,
competitor channels, voice, video length, and (optionally) recurring characters.

### 5. Make a video

```bash
python run.py competitors @SomeChannel        # what's working for other channels
python run.py make --topic "Five little ducks"  # one long video
python run.py make --short --topic "..."        # one Short
python run.py --help                            # every command
```

See [`yt-autopilot/README.md`](yt-autopilot/README.md) for keys, the YouTube API setup,
the review dashboard and the daily workflow.

---

## Costs

Nothing per video with the defaults: Kokoro voice runs locally, music comes from free
CC0/CC BY tracks (credited automatically), and scripts can be written in `AI_MODE=offline`
(paste the prompt into Claude) or with a local Ollama model. Paid keys
(`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`) are optional.

## Never commit

`.env`, anything in `secrets/`, OAuth `client_secret*.json` / `token*.json`, model files,
rendered videos or audio, `data/`. All of these are already in `.gitignore`.

## Setting up with Claude Code

Open the cloned folder in [Claude Code](https://claude.ai/code) and say:
"Set up this project by following README.md and run the tests."
[`CLAUDE.md`](CLAUDE.md) tells Claude the exact steps and rules.

## Troubleshooting

| Problem | Fix |
|---|---|
| `models/kokoro-v1.0.onnx` not found | Run `./scripts/download_models.sh` from the repo root. |
| `ffmpeg: not found` | Install ffmpeg (step 1). |
| Tests fail on import | Activate the venv (`source .venv/bin/activate`) and reinstall requirements. |
| Uploads stay private | Expected until your Google Cloud project passes YouTube's API audit; publish from YouTube Studio. |
