# YT Autopilot

Your own YouTube pipeline, built to keep a channel **monetisable**: researched,
sourced, original scripts; real footage before AI images; your voice in the
loop; nothing uploads until you approve it; everything goes up private first.

**One command, niche in, finished video out:**

```bash
python run.py make --niche "untold history stories"      # finds a topic, writes, voices, renders
python run.py make --topic "The Great Emu War" --minutes 5
```

It stops before upload: watch the video in `python run.py dashboard`, approve, then
`python run.py publish`.

```
scout → script → produce → review → (you approve) → publish → shorts → analytics
  ↑                                                                      │
  └──────────────────── lessons from your own numbers ←──────────────────┘
```

## Why it's built this way (YouTube rules, checked October 2026)

- **Inauthentic content.** Since 16 July 2026 YouTube clearly won't monetise channels
  with too much *generic, repetitive or template* content that's easy to mass-produce
  with AI, *distressing bait*, or *AI personas of real people talking finance/legal/health*.
  AI use itself is allowed. So the pipeline rotates story structures and hooks,
  checks scripts against your earlier scripts, demands your own take
  (`my_take.md`) or your own recorded voice, caps AI images, and keeps a human
  approval step.
- **AI disclosure.** Uploads set `containsSyntheticMedia` (YouTube's "altered or
  synthetic content" flag) whenever AI images or an AI voice are used, and AI
  images get an on-screen "AI illustration" label.
- **Copyright.** Only media licensed for commercial reuse with changes is used
  (no NC/ND, no "fair use"). Every item is stored in `licences.json`, and
  credits are written into the description for you.
- **YouTube API audit.** A Google Cloud project that hasn't passed YouTube's API
  compliance audit uploads every video **locked private**. Scheduling then does
  nothing, and you set the video public yourself in YouTube Studio. That's fine
  to start with. Once the channel is steady, apply for the audit (YouTube API
  Services "Audit and Quota Extension" form) so scheduled publishing works.

## 1. Install (once)

You need Python 3.10+ and ffmpeg.

```bash
cd yt-autopilot
sudo apt install ffmpeg            # or a static build in ~/.local/bin (no sudo); Mac: brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env
mkdir -p secrets models
python -m pytest -q                # 19 tests, no keys needed
```

**English voice (free, local):**
```bash
cd models
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

**Urdu voice:** set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID_UR` in `.env`,
set `languages.ur.enabled: true` in `config/channel.yaml`, and put a translated
`script_ur.json` (same shape and line count as `script.json`) in the video folder.

**Script writer**, in `.env` `AI_MODE`:
- `auto` (default): the API if `ANTHROPIC_API_KEY` is set, otherwise the **Claude Code CLI**
  (`claude`, uses your Claude login, no key), otherwise Ollama, otherwise `offline`.
- `claude`: always the Claude Code CLI. `CLAUDE_MODEL=sonnet` picks a model.
- `anthropic`: the Claude API.
- `ollama`: a local model.
- `offline`: writes a prompt file and stops; paste it into any chat, save the reply where
  it tells you, run the stage again.

**Picture check:** install [Ollama](https://ollama.com) and `ollama pull llava:13b`.
Without it pictures are used unchecked (the review will still show them to you).

**Footage:** Wikimedia Commons, Openverse and Internet Archive need no key. Add the free
`PEXELS_API_KEY` and `PIXABAY_API_KEY` for stock video clips, which make videos look far
better in most niches.

**AI images (optional, last resort, labelled on screen, max 25% of shots):**
- On an NVIDIA GPU: `pip install torch diffusers transformers accelerate`. Stable Diffusion XL
  (about 7 GB, downloaded on first use) then runs locally. `AI_IMAGE_PROVIDER=none` turns it off.
- Or any AUTOMATIC1111-compatible server: `AI_IMAGE_URL=http://127.0.0.1:7860`.

**Music:** tracks you're licensed to use in `assets/music/` (the YouTube Audio Library is
a safe source). With none there, a free CC0/CC BY track is fetched from Openverse and
credited in the description (`format.auto_music: false` turns that off).

### YouTube API

1. Google Cloud Console → new project → enable *YouTube Data API v3* and *YouTube Analytics API*.
2. OAuth consent screen → External → add yourself as a test user.
3. Credentials → OAuth client ID → **Desktop app** → download JSON → save as `secrets/client_secret.json`.
4. (Optional, for scout) Credentials → API key → `YOUTUBE_API_KEY` in `.env`.
5. The first `publish` opens a browser to log in; the token is saved to `secrets/token.json`.

## 2. Set up your channel

Edit `config/channel.yaml`: niche, audience, seed keywords, competitor channel IDs,
voice settings, length, and **`originality.voice_mode`**:

| voice_mode | what you do | monetisation safety |
|---|---|---|
| `own` | record every line yourself | best |
| `commentary` (default) | record only your opinion lines; AI reads the facts | good |
| `ai` | nothing | riskiest |

When your voice is needed, the produce stage writes `recordings/TO_RECORD.md`
listing each line and the file name to save (`line_007.wav` …).

## 3. Daily use

```bash
python run.py idea "The Library of Alexandria" --angle "it didn't burn in one night"
python run.py scout --count 3          # or let it find ideas (uses YOUTUBE_API_KEY)
# optional but recommended: write 2-3 sentences of your own view in data/videos/<id>/my_take.md
python run.py script                   # research → script → fact/timing/copy/quality checks
python run.py produce                  # voice → footage → vision check → render → thumbnails
python run.py review                   # automatic review
python run.py dashboard                # open http://127.0.0.1:8000, watch, pick title + thumbnail, approve
python run.py publish                  # private upload, scheduled, captions, thumbnail
python run.py shorts                   # 2 vertical Shorts per video, linking to it
python run.py analytics                # weekly: numbers + comments → data/lessons.json
python run.py status
```

`python run.py daily` runs script → produce → review → publish (approved only) →
shorts. Run it from cron/launchd if you like; approval stays manual.

Edited a script by hand? Change `script.json`, then `python run.py recheck <id>`.

## What each check does

| check | fails when |
|---|---|
| facts | a factual line has no source, cites an unknown source, or has a number/year not found in its cited source |
| timing | narration is >15% off target, the hook runs over ~45 s, or one section is far longer than the rest |
| copying | an 8-word run is shared with a source, your last 30 scripts, or **transcripts of the competitor videos** the idea came from (>14-word run or >4% overlap) |
| quality | filler phrases ("in this video", "delve"…), repetitive sentence openings, a vague hook, no lines of your own view |
| review | any check failed, no creator input, too many AI images, missing visuals, unlicensed media, no thumbnail, no sources in the description |

## Folder layout

```
run.py                  all commands
config/channel.yaml     your channel settings
.env                    keys (never commit; git-ignored)
secrets/                client_secret.json, token.json (git-ignored)
models/                 Kokoro voice model (git-ignored)
assets/music/           your licensed music
autopilot/              the code (one file per stage)
data/videos/<id>/       one folder per video: state.json, sources.json, script.json,
                        checks.json, timeline_en.json, visuals.json, licences.json,
                        final_en.mp4, captions_en.srt, thumbnails/, shorts/, log.txt
data/lessons.json       what your analytics taught the pipeline
```

## Safety notes

- Keys live only in `.env` and `secrets/`, both git-ignored. Keep personal documents
  (ID card scans etc.) **out of this folder** entirely.
- The dashboard only listens on 127.0.0.1, needs `DASHBOARD_PASSWORD`, blocks
  cross-site form posts and only serves files from inside a video's folder.
- Web pages, transcripts and **viewer comments are treated as untrusted data**:
  they're wrapped as data in prompts and can never change settings or trigger actions.
- Everything uploads private. Nothing goes public without your approval.

## Monetisation checklist (YouTube Partner Program)

- 1,000 subscribers + 4,000 public watch hours in 12 months, or 10M Shorts views in 90 days.
- No active Community Guidelines strikes; 2-step verification on the Google account.
- One clear niche, consistent schedule, your own perspective in every video.
- Reply to comments yourself; the pipeline never auto-replies.
