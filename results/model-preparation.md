# 模型准备与离线校验

状态：PASS。判定者：Astra。

当前 Mac 实际运行 `HF_HUB_OFFLINE=1 .venv/bin/python scripts/setup_model.py --model all --verify-only`，预设模型与固定声线模型均通过权重 SHA-256 及关键文件存在检查，downloaded=false、read_only=true。结果见同名 JSON。

独立测试覆盖已有文件复用、固定提交下载、损坏文件强制重新下载、校验失败不登记、只校验不写入、共享链接不修改和失效链接保护。最终统一回归结果见 workflow-checks。

没有用当前 Mac 的成功冒充全新 Mac 安装通过；下载分支使用小文件夹具，不是重新下载真实权重。校验通过也不等于声音质量通过。

最后更新：2026-09-09 · Astra
