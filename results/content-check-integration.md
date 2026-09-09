# 中英文声音回读检查

技术流程：PASS。差异只作复核提示，不判定为已经确认的漏读。

| 语言 | 台词 | 识别结果 | 状态 |
|---|---|---|---|
| zh | 雨点轻轻敲着窗。 | 雨点轻轻敲着窗 | match |
| zh | 你听见了吗？ | 你听见了吗? | match |
| zh | 别担心，那只是风。 | 别担心那只是风 | match |
| zh | 两个人相视一笑。 | 两个人相视一笑 | match |
| en | Rain tapped against the window. | Rain tapped against the window. | match |
| en | Did you hear that? | Did you hear that? | match |
| en | Just the wind. We are safe here. | Just a wind. We are safe here. | review |
| en | They smiled and went back to their books. | They smiled and went back to their books. | match |

在独立副本中检查既有合成音，原始工程未修改；未把台词作为识别提示。逐句音频 SHA、识别模型和规则身份、差异与实测耗时见 JSON。完整日志保存在各副本的 checks 子目录。
负向控制仅把对照文本加上音频中原本没有的 never，验证差异会标出；不是冒充真实的 TTS 漏读案例。
未用本组样例估计检出率、误报率或语音生成正确率。仍需本人确认真实读音，以及更广样本与实际遗漏音频。

最后更新：2026-09-09 · Astra