# 在另一台 Mac 准备 VoxStage

目前是开发预览的安装流程，还不是签名安装包。本机已经配置好，日常使用直接双击 Start VoxStage.command，无需重复安装。

## 准备基础工具

目标为 Apple Silicon Mac。先安装 Python 3.12、uv 和 Node.js。当前锁定的前端构建工具要求 Node 20.19 以上的 20.x，或 Node 22.12 及以上；使用原生 Apple Silicon 环境。

取得项目文件后，在项目根目录依次执行：

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

这些步骤用于新环境。已有工程请先关闭 VoxStage，并备份整个 user-data 目录，再维护依赖；不要用新环境覆盖现有用户资料。

## 按需要准备声音模型

基础预设声音：

```sh
.venv/bin/python scripts/setup_model.py
```

要使用“固定为此角色声线”，再准备固定声线模型：

```sh
.venv/bin/python scripts/setup_model.py --model base
```

更大的预设声音模型（1.7B）。装了它以后，**新建工程默认用它**；已有工程保持原来的模型；
内存较小（16 GB）的机器可以在「整个作品 → 预设音色模型」里选回 0.6B：

```sh
.venv/bin/python scripts/setup_model.py --model preset-large
```

声音设计——用一句话描述生成一个声线，试听满意后存进音色库：

```sh
.venv/bin/python scripts/setup_model.py --model design
```

也可以一次准备全部：

```sh
.venv/bin/python scripts/setup_model.py --model all
```

脚本固定模型版本，校验权重和所需关键文件，再登记。文件齐全时复用已有模型；缺文件会下载，权重损坏时请求重新下载。
预设模型 0.6B 约 2.5 GB，1.7B 与声音设计各约 4.2 GB；全装约 15 GB，请留足下载与缓存空间。
实测（2026-09-13，M2 Max 32 GB）：1.7B 生成速度比 0.6B 慢约 15%，峰值内存约 8 GB——这是只驻留一个模型时的数字。
同日一次 93 句整篇生成，预设、克隆、声音设计四个模型都驻留在内存里：1.7B 实时率 0.61（每秒音频约 0.6 秒生成），峰值 17.7 GB。
所有模型均为 Apache-2.0。

不想下载或更改文件，只查看完整性：

```sh
.venv/bin/python scripts/setup_model.py --model all --verify-only
```

如果模型目录是指向共享文件的链接，脚本不会覆盖或向链接目标下载。链接失效时先恢复共享模型的位置。复制本项目到另一台 Mac 不会自动复制链接指向的权重；需要在新电脑安装模型。

## 可选：本地文字检查

另行准备兼容的 whisper.cpp whisper-cli，然后指定实际程序路径：

```sh
.venv/bin/python scripts/setup_asr.py --cli /path/to/whisper-cli
```

此步骤下载约 547 MiB 的固定识别模型。没有配置它也能生成、试听和人工标错，只是不能自动做文字检查。现阶段尚未自动安装或编译 whisper.cpp。

## 启动与检查

双击 Check VoxStage.command 查看环境提示，双击 Start VoxStage.command 打开工作台。首次生成或识别还会执行相关模型校验；环境就绪不等于音质已经验收。

稿件、生成声音、参考副本、模型与日志都在本地 user-data 下。分享源码时不应把这个目录一起上传。搬家或备份工程时要保留完整工程文件夹，避免只留下导出的音频。

当前证据：本机的两套模型离线校验通过，安装失败/链接保护等分支已用独立夹具验证；尚未在一台全新 Mac 完整安装，不能把本说明当成该项实机验收结果。

最后更新：2026-09-09 · Astra（模型一节 2026-09-13 随 1.7B / 声音设计更新）


## 可选：加速试听与导出

1.1–1.3 倍作品语速需要本机 FFmpeg。默认从环境路径及常见本机安装位置查找，也可用 VOXSTAGE_FFMPEG 指定可执行文件。本机已就绪；脚本不会自动安装该工具。缺少它仍可使用原速生成、试听与导出。

中文同音比较依赖已锁定的 pypinyin 0.55.0，按上面的依赖安装步骤即可获得。

最后更新：2026-09-09 · Astra
