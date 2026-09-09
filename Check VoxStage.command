#!/bin/zsh
# Local launch/check entry; Astra, 2026-09-09.
cd "$(dirname "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  echo '尚未建立 VoxStage 的 Python 环境。请按 README 的首次安装步骤设置。'
  read '?按回车关闭。'
  exit 1
fi
.venv/bin/python -m runtime.launcher --check
voxstage_status=$?
read '?按回车关闭。'
exit $voxstage_status
