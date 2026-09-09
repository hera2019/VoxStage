#!/bin/zsh
# Local launch/check entry; Astra, 2026-09-09.
cd "$(dirname "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  echo '尚未建立 VoxStage 的 Python 环境。请按 README 的首次安装步骤设置。'
  read '?按回车关闭。'
  exit 1
fi
.venv/bin/python -m runtime.launcher
voxstage_status=$?
if [[ $voxstage_status -ne 0 ]]; then
  read '?按回车关闭。'
fi
exit $voxstage_status
