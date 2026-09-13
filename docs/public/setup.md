# Setting up VoxStage on another Mac

This is the development-preview install, not a signed installer. A Mac that
is already set up needs none of it: double-click `Start VoxStage.command`.

## Base tools

Target: an Apple Silicon Mac. Install Python 3.12, uv and Node.js. The pinned
frontend toolchain wants Node 20.19 or later in the 20 line, or 22.12 and
later; use a native Apple Silicon environment, not Rosetta.

In the project root, in order:

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

These steps are for a fresh environment. On a machine with existing projects,
quit VoxStage and back up the whole `user-data` directory before touching
dependencies; never let a new environment overwrite existing user data.

## Voice models, as needed

The basic preset voices (0.6B):

```sh
.venv/bin/python scripts/setup_model.py
```

To use **fix this voice for the character** (固定为此角色声线), add the
cloning model:

```sh
.venv/bin/python scripts/setup_model.py --model base
```

The larger preset-voice model (1.7B). Once installed, **new projects use it by
default**; existing projects keep the model they were made with. A machine
with less memory (16 GB) can switch a project back to 0.6B under
整个作品 → 预设音色模型:

```sh
.venv/bin/python scripts/setup_model.py --model preset-large
```

Voice design — a voice generated from a one-sentence description, kept in the
voice library once you have listened and approved it:

```sh
.venv/bin/python scripts/setup_model.py --model design
```

Or everything at once:

```sh
.venv/bin/python scripts/setup_model.py --model all
```

The script pins each model to a revision, verifies the weights and the files
it needs, then registers the model. A complete model is reused; missing files
are downloaded; a corrupt weight file asks for a fresh download. The 0.6B
preset model is about 2.5 GB, the 1.7B and the voice-design models about
4.2 GB each; everything is about 15 GB, so leave room for the download and
its cache. Measured (2026-09-13, M2 Max, 32 GB): 1.7B generates about 15%
slower than 0.6B, with peak memory around 8 GB. Every model is Apache-2.0.

To check integrity without downloading or changing anything:

```sh
.venv/bin/python scripts/setup_model.py --model all --verify-only
```

If a model directory is a link to shared files, the script neither overwrites
the link nor downloads into its target; restore the shared location first if
the link is broken. Copying this project to another Mac does not copy weights
behind a link — install the models on the new machine.

## Optional: the local text check

Obtain a compatible whisper.cpp `whisper-cli`, then point the script at it:

```sh
.venv/bin/python scripts/setup_asr.py --cli /path/to/whisper-cli
```

This downloads a pinned recognition model of about 547 MiB. Without it you can
still generate, listen and mark errors by hand; only the automatic text check
is unavailable. whisper.cpp is not installed or compiled for you at this stage.

## Optional: faster listening and export

Project speeds of 1.1–1.3× need FFmpeg on this machine. It is looked for on
the PATH and in the usual install locations, or named with `VOXSTAGE_FFMPEG`.
The scripts do not install it; without it, generation, listening and export
work at normal speed.

The Chinese homophone comparison in the text check relies on the pinned
pypinyin 0.55.0, which the dependency step above installs.

## Starting and checking

Double-click `Check VoxStage.command` for an environment report, and
`Start VoxStage.command` to open the workstation. The first generation or
recognition also verifies the model involved. An environment that is ready
says nothing about whether the audio has passed review.

Scripts, generated audio, reference copies, models and logs all live under
the local `user-data`. Do not upload that directory when sharing the source.
When moving or backing up a project, keep the whole project folder — not only
the exported audio.

Evidence so far: both model sets verified offline on the development machine;
the failure branches (failed install, link protection) are covered by
separate fixtures. **A complete install on a brand-new Mac has not been
done**, so this page is not an acceptance record of that.

Last updated: 2026-09-13 · Claude Hera (English edition of setup-zh.md, Astra 2026-09-09; model section as of 2026-09-13)
