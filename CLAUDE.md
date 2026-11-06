# Notes for Claude

This repo is a local YouTube video pipeline (`yt-autopilot/`). Read README.md first.

## Setting the project up for a user
1. Check `git`, `python3` (3.10+), `ffmpeg`, `curl` exist; install missing ones with the OS package manager after asking.
2. From the repo root: `python3 -m venv .venv && source .venv/bin/activate && pip install -r yt-autopilot/requirements.txt`.
3. `./scripts/download_models.sh` (Kokoro voice model, about 340 MB, into `models/`).
4. `cp yt-autopilot/.env.example yt-autopilot/.env`, then `cd yt-autopilot && python -m pytest -q` (all offline).
5. Help the user fill in `yt-autopilot/config/channel.yaml` for their own channel.

## Hard rules
- Never commit models (`*.onnx`, `*.bin`, `*.safetensors`, ...), `.env`, `secrets/`, OAuth JSON files, `data/`, or rendered `.mp4`/`.wav`. They are in `.gitignore`; do not force-add them.
- Never add paid API keys (ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, paid image servers) without the user saying so. The default setup costs nothing.
- Kids mode: audience is ages 0 to 6, cartoon characters only, never use photos of real children as AI input.
- Keep this repo generic: no specific channel's branding, characters or assets.
