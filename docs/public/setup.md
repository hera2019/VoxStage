# Installing VoxStage

*[中文](setup-zh.md)*

VoxStage runs entirely on one Mac: the scripts, the models and the audio stay
on it. This page takes a Mac from nothing to a working install. It is a
developer install — a terminal and about half an hour, most of it downloading
models — not a signed app.

A Mac that is already set up needs none of it: double-click
`Start VoxStage.command`.

## What you need

| | Minimum | Recommended |
| --- | --- | --- |
| Computer | Apple Silicon Mac (M1 or later) | M-series with 32 GB of memory |
| Memory | 16 GB — the small voice models only | 32 GB — the larger voices and the speaker model |
| Free disk | about 5 GB | about 30 GB (45 GB with the largest speaker model) |
| System | a recent macOS with Homebrew | the same |

Intel Macs are not supported: the voice models run on Apple's MLX framework
(a library that runs AI models on Apple Silicon).

## 1. Tools

Install [Homebrew](https://brew.sh) if the Mac does not have it, then:

```sh
brew install python@3.12 uv node git ffmpeg llama.cpp
```

- **python@3.12, uv**: the Python the service runs on, and the tool that
  installs its exact dependencies.
- **node**: builds the web page once (Node 20.19+, or 22.12+).
- **ffmpeg**: speeds other than 1.0×, and recordings supplied as mp3/m4a.
  Optional; without it everything plays at normal speed and recordings must
  be WAV.
- **llama.cpp**: runs the speaker model that splits prose into narration and
  dialogue and names who speaks. Optional; without it you import scripts that
  already say who speaks (`Name: line`).

## 2. The code and its dependencies

```sh
git clone https://github.com/hera2019/VoxStage.git
cd VoxStage
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

## 3. Models

Each model is downloaded from Hugging Face at a pinned revision and checked
by SHA-256 before it is registered; a complete model is never downloaded
twice. All of them are Apache-2.0. Pick a set:

**Minimum** (16 GB Mac, ~2.5 GB): the model's nine built-in voices.

```sh
.venv/bin/python scripts/setup_model.py
```

**Recommended** (32 GB Mac, ~21 GB more):

```sh
.venv/bin/python scripts/setup_model.py --model base-large     # cloning: the default voice pack and your own voices, ~4.2 GB
.venv/bin/python scripts/setup_model.py --model preset-large   # larger built-in voices, ~4.2 GB
.venv/bin/python scripts/setup_model.py --model design         # a new voice from a description, ~4.2 GB
.venv/bin/python scripts/setup_model.py --model role-14b       # speaker model, Qwen3-14B, ~8.4 GB
```

**Optional**, the largest speaker model (~17 GB). On a 32 GB Mac it becomes the
default when installed, with the 14B as its fallback:

```sh
.venv/bin/python scripts/setup_model.py --model role-30b-a3b
```

What each model is for:

- **Built-in voices** (`preset`, `preset-large`): read lines in one of nine
  voices; a line can carry a tone instruction (angry, whispering). Each take
  varies a little.
- **Cloning** (`base`, `base-large`): reads lines in a voice from the voice
  library — the fourteen voices of the default pack, voices you designed, or
  a recording you supply with consent. Needed for the default pack: without
  it, Chinese projects fall back to the built-in voices.
- **Voice design** (`design`): makes a new voice from a description; the
  library keeps the one you choose.
- **Speaker model** (`role-14b`, `role-30b-a3b`): drafts who says each line of
  prose, for you to review.

To check what is installed without downloading anything:

```sh
.venv/bin/python scripts/setup_model.py --model all --verify-only
```

## 4. Optional: the text check

After a line is generated, a local speech recogniser can compare what was
said with the script and flag missing or wrong words.

```sh
brew install whisper-cpp
.venv/bin/python scripts/setup_asr.py --cli "$(command -v whisper-cli)"
```

This downloads a pinned recognition model of about 547 MiB. Without it you
generate and listen as usual; only the automatic check is missing.

## 5. Start

Double-click `Start VoxStage.command` (or run
`.venv/bin/python -m runtime.launcher`). It checks the environment, starts
the service and opens http://127.0.0.1:8765 in the browser. Keep the
terminal window open while you work; Ctrl+C stops it.

`Check VoxStage.command` prints the same environment report without
starting anything. Each item is marked 就绪 (ready), 提示 (an optional part
is missing; the rest works) or 需处理 (must be fixed before starting), with
what to do.

The first time the service starts, the default voice pack (fourteen synthetic
voices, `voicepack/`) is added to the voice library.

**From a phone or tablet on the same Wi-Fi**: double-click
`Start VoxStage (局域网).command`. The terminal prints the address and an
access key; each device types the key once. It is off by default.

## Updating

Quit VoxStage, back up `user-data/`, then:

```sh
git pull
uv pip install --python .venv/bin/python -r requirements.lock.txt
npm --prefix frontend ci && npm --prefix frontend run build
```

## Where things are

Everything you make — projects, audio, the voice library, the models — is in
`user-data/`, which git ignores. Back it up as a whole; moving a project means
moving its folder, not only its exported audio. Never upload `user-data/`
when sharing the code. To remove VoxStage, delete the folder.

## If something is wrong

- **"Preset-voice model is not installed"**: run step 3's first command.
- **The speaker model is not ready**: `brew install llama.cpp`, then
  `setup_model.py --model role-14b`. A `llama-server` elsewhere can be named
  with `VOXSTAGE_ROLE_SERVER=/path/to/llama-server`.
- **Out of memory, or everything slows down**: on 16 GB use the 0.6B models
  (each project's settings choose 0.6B or 1.7B) and close other large
  programs; VoxStage runs one model task at a time.
- **Port 8765 is busy**: another VoxStage is probably running; the launcher
  says so and opens it.

## What has been verified

Measured on the development Mac (M2 Max, 32 GB): the models verify offline;
with the 1.7B built-in voices, cloning and voice design loaded in one
session, peak memory was 17.7 GB. **Not yet done: a complete install on a brand-new Mac**,
and Homebrew's `llama.cpp` and `whisper-cpp` builds (the development Mac uses
its own builds) — sourced, to be verified. The memory figures for 16 GB are
estimated, not measured.

Last updated: 2026-09-24 · Claude Hera (rewritten from the setup page of 2026-09-13, Astra 2026-09-09)
