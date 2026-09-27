# 网站最新 PDF 提取失败诊断（2026-09-25）

结论：本次失败来自旧版 v4 的变例补全链，不能用来判断新来源优先 v6 管线是否失败。直接触发是 8192 输出预算全部消耗于推理；更深一层有可复现的 provider 选择错误，以及旧链把局部补全失败升级为整段失败的行为。单纯提高全局 token 上限无效，提高补全内部上限也不能保证正确提取。

## 实际任务与响应

- run：`585796cd-a225-5bbb-ac66-7e66bab5faf6`。
- 书与页段：Catalan，PDF 物理 p6–9；实际 `pipeline_version=pdf-extraction:v4`。
- 创建时间：2026-09-25 05:20:42 UTC（北京时间 13:20:42）；05:26:32 UTC 失败。
- 错误码：`ccef_coverage_repair_failed`；执行一次，未自动重试。
- 失败补全响应：模型 `deepseek-flash`；`finish_reason=length`；输入 17,025 tokens，输出 8,192，其中 reasoning 8,192，最终 content 长度 0。
- 首次主生成另有保存响应：输入 45,960、输出 77,905 tokens；最初本地错误为 `ccef_missing_content`（annotation / reading-flow 内容缺失）。该记录和失败补全不是全部中间调用的完整用量账单。
- SQL 工件只有页图和文本证据，没有已提交的候选 CCEF。调试原响应保存在 gitignored `data/debug/extraction-failures/<run>/attempt-1/`。

## 代码根因

1. `extraction/coverage.py` 将补全请求预算固定为 `min(context.max_output_tokens, 8192)`；当前全局输出上限已是 128000，再提高全局值也突破不了这个内部上限。
2. `services/pdf_extraction.py` 的任务入口先创建主 provider（v4 开启 thinking），再以 `provider=active_provider` 传入 `_process_ccef_candidate`。后者只有在 `provider is None` 时才创建 recovery provider，因此真实生产路径跳过 recovery 设置，复用主模型。
3. 当前 recovery effort 配置为 `none`，主模型 effort 为 `high`。使用假传输、假证据、不读写生产任务的离线调用链探针确认：仅创建一个 provider，coverage 与主 provider 相同，thinking=True、effort=high。并非 API 忽略了已正确传出的非推理参数，而是代码未选中该配置。
4. `extraction/recovery.py` 把 coverage 的 provider 错误抛成整任务失败；这就是局部遗漏仍然阻断整段结果的旧架构问题。
5. 网站选择器默认 legacy；旧任务菜单中的“重新提取同一页段”从原任务版本取值，不读取上方新任务表单的选择器。故即使表单选了来源优先，重跑旧任务仍是 v4。数据库无法说明用户具体点击了哪个入口，只能确认本次运行是 v4。

## 对提高额度的判断

- 提高补全步骤本身的额度可能让这次请求产生最终 JSON，但不能保证结束推理、分支关系正确、内容完整或通过后续检查。
- 若继续保留旧补全链，应先修复 provider 选择，使已配置的非推理修复生效，再按实际输出长度决定预算；不能用更多推理掩盖错误调用。
- 新 v6 使用分块语义事件和本地编译，不经过这条 coverage supplement 链；应从新任务表单明确选择来源优先并确认版本为 v6 后再评价。新管线仍需要实际网站运行和未测 P6 窗口的验收，不能把本次诊断当作其稳定性证明。
- UI 后续宜明确标出任务使用的提取方式，并使“按旧方式重跑”和“用新流程提取”可区分。

本次仅进行只读任务/工件检查、官方参数文档核对和无网络的调用链探针；未修改功能代码、数据库、模型配置，也未发起新的模型调用。分析结论已同步到 HANDOFF。
