# 安装 VoxStage

*[English](setup.md)*

VoxStage 整个跑在一台 Mac 上：稿件、模型、音频都留在本机。这一页讲怎么从零装好。这是开发者安装方式：要用终端，大约半小时，大部分时间在下载模型；还不是签名的安装包。

已经装好的 Mac 不需要看这页，双击 `Start VoxStage.command` 即可。

## 需要什么

| | 最低 | 推荐 |
| --- | --- | --- |
| 电脑 | Apple 芯片的 Mac（M1 及以后） | M 系列、32 GB 内存 |
| 内存 | 16 GB：只用小的声音模型 | 32 GB：大声音模型和分角色模型 |
| 空余磁盘 | 约 5 GB | 约 30 GB（加最大的分角色模型约 45 GB） |
| 系统 | 较新的 macOS，装有 Homebrew | 同左 |

不支持 Intel Mac：声音模型跑在 MLX 上（让 AI 模型利用 Apple 芯片计算的框架）。

## 1. 工具

没有 [Homebrew](https://brew.sh) 先装它，然后：

```sh
brew install python@3.12 uv node git ffmpeg llama.cpp
```

- **python@3.12、uv**：服务用的 Python，以及按锁定版本安装依赖的工具。
- **node**：生成一次网页（Node 20.19 以上，或 22.12 以上）。
- **ffmpeg**：1.0× 以外的语速，以及 mp3/m4a 格式的录音。可选；没有它只能原速，录音只收 WAV。
- **llama.cpp**：运行分角色模型（把小说分成旁白和对白、点出说话人）。可选；没有它就导入已标好说话人的剧本（`名字：台词`）。

## 2. 代码和依赖

```sh
git clone https://github.com/hera2019/VoxStage.git
cd VoxStage
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

## 3. 模型

每个模型都从 Hugging Face 按固定版本下载，登记前用 SHA-256 校验；已完整的模型不会重复下载。全部是 Apache-2.0 许可。选一套：

**最低**（16 GB Mac，约 2.5 GB）：模型自带的 9 个音色。

```sh
.venv/bin/python scripts/setup_model.py
```

**推荐**（32 GB Mac，另需约 21 GB）：

```sh
.venv/bin/python scripts/setup_model.py --model base-large     # 克隆：默认音色库和你自己的声线，约 4.2 GB
.venv/bin/python scripts/setup_model.py --model preset-large   # 更大的自带音色模型，约 4.2 GB
.venv/bin/python scripts/setup_model.py --model design         # 按描述设计新声线，约 4.2 GB
.venv/bin/python scripts/setup_model.py --model role-14b       # 分角色模型 Qwen3-14B，约 8.4 GB
```

**可选**，最大的分角色模型（约 17 GB）。装上后在 32 GB Mac 上默认用它，14B 作后备：

```sh
.venv/bin/python scripts/setup_model.py --model role-30b-a3b
```

各模型的用途：

- **自带音色**（`preset`、`preset-large`）：用 9 个音色之一读句子；可以给某一句加语气说明（愤怒、低声）。每次生成略有不同。
- **克隆**（`base`、`base-large`）：用音色库里的声线读句子，包括默认音色库的 14 个、你设计的声线，或你提供并确认授权的录音。默认音色库离不开它：没装时，中文工程改用自带音色。
- **声线设计**（`design`）：按描述生成新声线，你选中的那版存进音色库。
- **分角色模型**（`role-14b`、`role-30b-a3b`）：给小说的每一句拟出说话人，供你复核。

不下载、只查看装了什么：

```sh
.venv/bin/python scripts/setup_model.py --model all --verify-only
```

## 4. 可选：文字检查

句子生成后，用本机语音识别把听到的内容和稿件对比，标出漏字、错字。

```sh
brew install whisper-cpp
.venv/bin/python scripts/setup_asr.py --cli "$(command -v whisper-cli)"
```

会下载一个固定版本的识别模型，约 547 MiB。没有它照样生成、试听，只是少了自动检查。

## 5. 启动

双击 `Start VoxStage.command`（或运行 `.venv/bin/python -m runtime.launcher`）。它先检查环境，再启动服务，并在浏览器打开 http://127.0.0.1:8765。工作时别关终端窗口；按 Ctrl+C 停止。

`Check VoxStage.command` 只输出同样的环境报告、不启动。每一项标「就绪」「提示」（可选部分没装，其余照常）或「需处理」（启动前必须解决），并说明怎么办。

第一次启动时，默认音色库（14 个合成声线，在 `voicepack/`）会装进音色库。

**界面语言**：界面有中文和英文，第一次按浏览器的语言选；侧栏底部的「中文 / English」按钮，或「设置 → 模型与选项」里可以切换。只是这个浏览器的偏好，工程自己的语言（稿件和声音的语言）不变。终端跟着 Mac 的系统语言；`VOXSTAGE_LANG=en` 或 `zh` 可以指定。导出的报告和剪辑说明目前仍是中文。

**同一个 WiFi 下用手机或平板**：双击 `Start VoxStage (局域网).command`。终端会显示地址和访问口令，每台设备输入一次。默认关闭。

## 更新

先退出 VoxStage，备份 `user-data/`，然后：

```sh
git pull
uv pip install --python .venv/bin/python -r requirements.lock.txt
npm --prefix frontend ci && npm --prefix frontend run build
```

## 东西放在哪

你做的一切（工程、音频、音色库、模型）都在 `user-data/`，git 不收它。要整个备份；搬工程要搬整个工程文件夹，不能只拿导出的音频。分享代码时千万别上传 `user-data/`。卸载就是删掉整个文件夹。

## 出问题时

- **提示「Preset-voice model is not installed」**：运行第 3 步的第一条命令。
- **分角色模型未就绪**：`brew install llama.cpp`，再 `setup_model.py --model role-14b`。别处的 `llama-server` 可以用 `VOXSTAGE_ROLE_SERVER=/路径/llama-server` 指定。
- **内存不够或整机变慢**：16 GB 的机器用 0.6B 模型（每个工程的设置里可选 0.6B 或 1.7B），关掉其他大程序；VoxStage 一次只跑一个模型任务。
- **端口 8765 被占用**：多半是已经有一个 VoxStage 在跑，启动器会提示并直接打开它。

## 验证到哪一步

开发用的 Mac（M2 Max，32 GB）上已实测：模型可离线校验；1.7B 自带音色、克隆和声线设计在同一次使用中都载入时，内存峰值 17.7 GB。**还没做过：在一台全新的 Mac 上完整安装一遍**；Homebrew 版的 `llama.cpp`、`whisper-cpp` 也没测过（开发机用的是自己编译的版本），属于有来源、待验证。16 GB 机器的内存说法是推算，没有实测。

最后更新：2026-09-24 · Claude Hera（在 2026-09-13 的安装页基础上重写；原稿 Astra 2026-09-09）
