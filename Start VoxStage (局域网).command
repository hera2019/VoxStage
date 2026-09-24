#!/bin/zsh
# Same as Start VoxStage.command, but also reachable from the phones and iPads on
# this network — behind the access key the terminal prints. Claude Hera, 2026-09-22.
cd "$(dirname "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  echo '尚未建立 VoxStage 的 Python 环境。请按 README 的首次安装步骤设置。'
  echo 'The Python environment for VoxStage is not set up yet. Follow the install guide (docs/public/setup.md).'
  read '?按回车关闭 · Press Return to close.'
  exit 1
fi
.venv/bin/python -m runtime.launcher --lan
voxstage_status=$?
if [[ $voxstage_status -ne 0 ]]; then
  read '?按回车关闭 · Press Return to close.'
fi
exit $voxstage_status
