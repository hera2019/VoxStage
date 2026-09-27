# Contributing to VoxStage

Thank you for helping. Bug reports, reproductions and small, focused pull
requests are the most useful.

## Before you open a pull request

- Run the checks: `.venv/bin/python -m pytest -q` and
  `npm --prefix frontend run build`. Say which you ran.
- Keep private material out: no human recordings (yours included), no
  copyrighted texts, no model weights, no local paths or keys. Test texts
  must be your own or in the public domain.
- Interface text goes through `tr()`, with its English in
  `frontend/src/locales/`; the tests fail when an entry is missing.

## Contribution terms

VoxStage is offered under the AGPL-3.0 and, separately, under a commercial
licence (see [LICENSING.md](LICENSING.md)). To keep both possible, by
submitting a contribution you confirm that:

1. it is your own work, or you have the right to submit it;
2. you license it to Houjun Co., Ltd. under the AGPL-3.0-only, and also grant
   Houjun Co., Ltd. a perpetual, worldwide, non-exclusive, royalty-free,
   irrevocable licence to use, change, sublicense and distribute it under
   other terms, including commercial licences;
3. you keep the copyright in your contribution and may use it elsewhere as you
   like.

If you cannot agree to these terms, please open an issue describing the change
instead of a pull request.

Last updated: 2026-09-28 · Claude Hera
