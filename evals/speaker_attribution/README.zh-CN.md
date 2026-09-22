# 中英文说话人归属小规模评测

16 个自写场景，中英各 8；每语言 2 个开发、6 个冻结留出。Astra 在模型输出前编写文本及参考答案，尚未经本人独立审核，不能称人工双重标注的标准数据集。嵌套引语使用外层朗读者；未说出口的思想、标牌归旁白；证据不足使用 UNKNOWN。

目标是比较本机现有 Qwen3-4B-Instruct-2507 Q8_0 与新下载 Qwen2.5-1.5B-Instruct Q4_K_M，两者同一模型家族、不同规模与量化，不能拆解各因素贡献。参考官方模型资料：[Qwen3](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)、[Qwen2.5 GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)。运行使用本地 llama.cpp Metal，并保存构建 commit、文件 SHA 和参数。

先固定 prompt.txt 与 corpus.sha256。所有输出逐条保存；结构或文本保全失败会在严格指标中使该场景全部单位计错，不从分母去掉失败。分语言和开发/留出报告：文本原样保全、旁白/对白完整单位判断、完整对白单位角色正确率、歧义 UNKNOWN、同角色多段一致性与时长。角色名仅按预先标注的别名表规范化。严禁看结果后修改参考答案或选择性重跑。

小样本只筛选下一步候选，不给总体产品通过结论；长章节、人物名单自动建立、多家族比较、日文、重复运行稳定性和实际审核时间另测。

最后更新：2026-09-09 · Astra


接口验证修正：首轮使用了 llama.cpp README 中的 schema 简写，但本机构建实际要求 response_format.json_schema.schema。首轮输出保留为技术失败记录，不作为受 schema 约束的模型成绩；纠正请求结构后以新标签完整重跑。语料、答案和任务提示不变，没有针对样例改提示。留出集已在技术首轮处理过，不声称从未见过该批输出。

最后更新：2026-09-09 · Astra


## 原文绑定对照与复现

基线已暴露改原文问题，另建 source_units.py + prompt-anchored.txt：切分只使用原文本身的引号位置，不接触 gold；模型仅标 id/kind/speaker，正文由程序恢复。新流程测试原 16 例及 fresh-holdout.json 中 4 个提前冻结的新探针，后者不是旧输出调参集。完整结果见 results/speaker-attribution-summary.md/json。

调用 evaluate.py 时提供 --server 本机 llama-server 路径、--model GGUF 路径、--label 新运行名称、--build-commit 实际构建提交；加 --anchored 使用绑定流程，否则使用自由输出基线。它启动仅监听本机的独立评测进程，结束后关闭；已存在同名汇总会拒绝覆盖。模型版本见 model-manifest.json。

新流程 20 例均保留原文，4B 对白原始严格角色分数 34/40；LEO/Leo 等仅大小写差异另算辅助诊断为 37/40，不覆盖原分数。完整场景 8/20；尚不满足无人审核使用。评分和原文保护测试已纳入完整 121 项回归。测试新增时一次字符串转义错误被语法检查捕获，修正后测试通过。

最后更新：2026-09-09 · Astra
