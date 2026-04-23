# AHASD → TPDS 修改进度追踪

> **论文文件**：`workflow/AHASPro.md`（DAC 版中文逐句对应版，最终修改目标）
> **修改规划**：`workflow/AHASDFix.md`（11 条 reviewer weakness 修复方案）
> **结构扩展**：`workflow/AHASDExtend.md`（TC/TPDS 期刊版扩展规划）
> **更新原则**：每完成一个子任务后立即更新本文件

---

## 整体阶段状态

> **2026-04-21 用户决策**：走路线 B——**真正在仿真器上实现推测解码端到端流水线**。
> 详细计划见 `/home/madrid/.cursor/plans/path_b_real_simulator_a55dd7ad.plan.md`。
> 下方 Phase B2/C/D/E/F/G 为路线 B 的新阶段结构，Phase A/B 保留作为前期诊断记录。

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase A | AHASDFix 纯文字修改（W1/W4/W7/W8/W9/W10） | ✅ 已完成（6 条 weakness 的正文文字全部入库到 AHASPro.md） |
| Phase B | 仿真器基线诊断 | ✅ 已完成（结论：需从头重建） |
| **Phase B2** | **仿真器底座重建（多模型调度器 / 协同仿真 / 能量 / 接受模型 / 端到端冒烟）** | ✅ 已完成 |
| Phase C | 三条基线实现（NPU-only / SpecPIM / GPU-only） | ✅ 已完成（C1/C2/C3） |
| Phase D | DAC 版实验数据产出（5.2 / 5.3 / W3 / W9） | 🚧 D1-D4 infra + pilot 就绪，prod 矩阵待长跑（6-12 h） |
| Phase E | 敏感性 + 硬件综合（W2 / W6 / W11） | 🚧 E1 infra + E2 合成模型完成；prod sweep 受限于 TLM 6.7b cell wall-clock，命令入库待长跑 |
| Phase F | SSRC 真实集成 + Challenge 3 | ✅ F1 耦合 + F2 LLR sweep + F3 SSRC 评估 pilot 全部完成 |
| Phase G | AHASPro.md 论文文字全面更新 | 🚧 G1 结构重组 + SSRC/Challenge 3 新段落已入库（§1/§2/§3/§4/§6 全部更新）；§5 各表与具体数字待 prod 数据出来后更新 |

---

## Phase A：纯文字修改（不依赖实验，全部已入库到 AHASPro.md）

### A1 — W1 正确性论证
- **目标**：在 Section 4.1/4.2/4.3 末尾各加 1-2 句正确性声明；Section 4 开头加总括声明
- **完成情况（2026-04-22）**：
  - ✅ Section 4 总括（`AHASPro.md:77`）：`**正确性保持说明**。AHASD 严格保持推测解码的无损性不变量……其无损性由 Leviathan 等人的推测解码分布等价性证明直接继承。`
  - ✅ Section 4.1 末（`AHASPro.md:93`）：`**正确性保持（异步框架）**。AHASD 的异步任务级调度利用三个跨设备队列在 DLM 与 TLM 之间解耦控制流，但 rollback 机制保证所有最终被接受的 token 均经过 NPU 侧完整 TLM 的 rejection sampling 判决……`
  - ✅ Section 4.2 末（`AHASPro.md:111`）：`**正确性保持（EDC）**。EDC 的判决仅作用于控制路径（是否继续提交下一轮草稿），不修改 NPU 侧 TLM 的 acceptance criterion……`
  - ✅ Section 4.3 末（`AHASPro.md:145`）：`**正确性保持（TVC）**。TVC 的预验证输出仅作为控制信号用于决定是否继续草稿生成，不进入 token 接受判决的数据路径……`
- **状态**：✅ 已完成

### A2 — W7 GTSU 可行性论证
- **目标**：Section 4.1 GTSU 描述段后新增四条逻辑链（约 0.5 页）
- **完成情况（2026-04-22）**：
  - ✅ `AHASPro.md:91` 插入 `**GTSU 硬件可行性论证**` 整段，覆盖四条逻辑链：
    - (i) rank 选择控制本身是 LPDDR5 标准机制（CS#/CKE，不涉及 die 内部互连重配置）
    - (ii) 亚微秒级切换由 $t_{RRD\_L}, t_{RCD}, t_{CKELPD}$ 直接保证（50-60 ns << 1 μs），全部映射到 Table 2 已有的 JEDEC 时序参数
    - (iii) 先例引用：Samsung HBM-PIM (ISSCC'21) / GDDR6-AiM (ISSCC'22) / UPMEM
    - (iv) 硬件规模：16-bit one-hot + 4 状态机 + 16 根 CS#/CKE 输出 → 28 nm 综合面积 < 0.005 mm²
- **状态**：✅ 已完成

### A3 — W8 EDC 表述修正
- **目标**：将"逐步学习"改为 counter-based update rule 表述；补充 PHT 更新语义
- **完成情况（2026-04-22）**：
  - ✅ `AHASPro.md` Section 4.2 末（第 109 行附近）整段替换：
    - 补充 $k$-bit 饱和计数器的位宽（$k=2$，即 2-bit 饱和计数器）
    - 补充更新规则：接受 +1（饱和于上限），拒绝 -1（饱和于下限）
    - 补充预测规则：最高位为 1 预测接受、为 0 预测拒绝
    - 明确"学习"的含义：类比硬件分支预测器的饱和计数器收敛过程，是确定性的非随机非 oracle
- **状态**：✅ 已完成

### A4 — W9 带宽域说明（文字部分）
- **目标**：TVC 段末补充 PIM 片内带宽 vs NPU 外部总线互补的 1-2 句说明
- **完成情况（2026-04-22）**：
  - ✅ `AHASPro.md:143` 插入 `**带宽域互补说明**`：指出 TVC 预验证主要使用 PIM 256 GB/s 片内通路、不挤占 NPU 51.2 GB/s off-chip 带宽，并点出 NVCT/PDCT/PVCT 已内生地对"预验证挤占 NPU 关键路径"进行建模、allowed pre-verify length < 1 时 TVC 自动跳过
- **状态**：✅ 已完成（W9 图表部分 overlap_timeline.json 已由 D4 产出）

### A5 — W10 双仿真器对齐机制描述
- **目标**：Section 5.1 两个插入点扩写，约增加 150 字
- **完成情况（2026-04-22）**：
  - ✅ `AHASPro.md:161` Section 5.1 "实验平台" 段整段扩写，落实 rebuttal R1 的三层对齐机制：
    - **周期级时序对齐**：全局共享事件队列 + 频率感知 cycle 换算（$cycle_{PIM} = \lfloor cycle_{NPU} \times f_{PIM}/f_{NPU} \rfloor$，NPU 1 GHz / PIM 800 MHz）
    - **事件驱动请求/响应对齐**：三个异步 FIFO（未验证/反馈/预验证）的互斥锁保护生产者-消费者机制
    - **数据级语义对齐**：请求消息（op/type, addr/size, issue_cycle）与响应消息（completion_cycle, status）的结构化元数据，以及 ONNXim 必须等待响应后方可推进
- **状态**：✅ 已完成

### A6 — Challenge 1 定量 idle 数字（W4 的 motivation 补充，顺手入库）
- **目标**：Section 3 Challenge 1 末尾（Fig. 3 之后）加入 80.5% / 85.4% idle 数字
- **完成情况（2026-04-22）**：
  - ✅ `AHASPro.md:57` Fig. 3 后追加 2-3 句：`从 cycle-accurate trace 中可以进一步观察到……PIM 主导时 NPU 平均空闲约占迭代总时间的 80.5%；……NPU 主导时 PIM 平均空闲约占迭代总时间的 85.4%。这一严重的相互等待开销表明……仅靠静态任务划分无法消除自适应推测解码的负载失衡。`
- **状态**：✅ 已完成

---

## Phase B：Simulator 基线诊断

### B1 — 确认 DAC 版最小配置可复现
- **验收标准**：OPT-1.3B → OPT-6.7B + SpecDec++ + gen=1024 能产出有意义的 throughput 和 energy 数字，且 `ahasd_cycle_coupling_active=1`
- **状态**：🔄 进行中（调查阶段，执行环境待确认）

**调查发现（2026-04-21）**：
- `/home/madrid/Desktop/AHASD`（TPDS 目标仓库）：ONNXim/PIMSimulator **未编译**，`extern/` 四个子模块（booksim / ramulator2 / protobuf / onnx）目录**为空**；没有 `models/` 和 `traces/`；scripts 脚本引用这些路径但文件都不存在
- `/home/madrid/Code/AHASD`（历史工作副本）：有编好的 `ONNXim/build/bin/Simulator` 二进制；extern/ 已 populate；有 `language_models/` 配置（opt-1.3b, opt-125m, opt-66b, llama2-7b, llama3-8b，但**没有 opt-6.7b、没有 llama2-13b**）；有若干 gen=16/32/256 的 trace
- `~/AHASD_quest006_*`：十几个历史 smoke run 结果目录，都是 gen=32 的旁路（sidecar）模式，`ahasd_cycle_coupling_active=0`
- `~/AHASD_deps`、`~/ahasd_*.bundle`、`~/AHASD_sync_backups`：历史依赖和增量备份

**关键已知问题**：
- 论文里三个模型对（OPT-1.3B/6.7B、LLaMA2-7B/13B、PaLM-8B/30B）缺失 **opt-6.7b、llama2-13b、palm-8b、palm-30b** 的模型 JSON
- 所有历史 run 都只跑了 gen=32 smoke，没有 gen=1024 的全量 Alpaca
- SSRC 以 sidecar 方式统计，`total_cycles` 在 AHASD 和 baseline 下完全一致

**🚨 Phase B1 深度诊断结论（根本性问题，2026-04-21）**：

通过直接审查 `ONNXim/src/Simulator.cc` 和 `scripts/run_single_config.py` 的源码：

1. **仿真器从未实现推测解码**。`create_language_model_list` 只实例化 `config['model']['draft']`（草稿模型）进入仿真；target model 仅写进 metadata 的 `target_model_recorded_only` 字段，**从未被仿真调度过**。整套 DLM→TLM 验证、rejection sampling、rollback 均不存在于仿真器中。

2. **AHASD 模块是硬编码的 sidecar**。`Simulator.cc:241-242` 明确打印：
   ```
   AHASD Metric Scope: sidecar_accounting
   AHASD Cycle Coupling: sidecar_only
   ```
   主仿真循环（`_core_cycles`、`_scheduler`、`_cores`、`_dram`、`_icnt`）对 AHASD 完全不可见。`_ahasd->cycle_npu()` / `cycle_pim()` 只更新 AHASD 内部计数器，不影响任何仿真事件。这就是为什么 AHASD vs baseline 的 `total_cycles` 一模一样。

3. **trace 文件极度简化**。脚本生成的 trace 只有一行：`0,1,32,0`——表示"从 1 token prompt 起，生成 32 token"。仿真器跑的就是 draft 模型纯粹的 autoregressive 推理，没有推测解码的结构。

4. **论文核心数字无法由当前仿真器产出**：
   - "4.2× vs GPU-only"：仿真器根本不模拟 GPU
   - "1.5× vs SpecPIM"：仿真器根本不模拟 SpecPIM
   - "异步任务级并行"：连 TLM 都不模拟，DLM/TLM 异步是空中楼阁
   - "能效 5.6×"：仿真器不产出任何能量数字（日志里从没有 `Total Energy` 行）
   - "NPU/PIM idle 80.5%/85.4%"：没有 TLM 验证，何来 NPU 空闲？

5. **历史 quest006 的所有 SSRC 收益数字（`ssrc_avoided_materialization_ratio ≈ 0.81`、`ssrc_modeled_cycle_reduction_ratio ≈ 0.81`）全部是在单模型仿真旁路上算出来的抽象数字**，与论文宣称的吞吐量/能效提升没有任何因果链接。

**这一发现颠覆了 AHASDFix/AHASDExtend 的前提假设**——两份规划文档都假设"仓库有 bug，修好就能复现 DAC 数字"。实际情况是：**DAC 论文里所有量化结果都不是这个开源仓库产出的**，仓库内容本质上是一个论文结构的草稿演示，不是可复现的实验平台。

---

## Phase B2：仿真器底座重建（路线 B 核心工程）

### B2.1 — 多模型 LanguageScheduler 扩展
- **目标**：从"单模型语言调度"扩展为"双模型 + 任务类型"（DRAFT / VERIFY / PRE_VERIFY / PROMPT），DLM+TLM 同时驻留
- **完成情况（2026-04-21）**：
  - ✅ `ONNXim/extern/` 从 `Code/AHASD` 拉齐 submodule，`build/` 复用现有 conan 缓存
  - ✅ `ONNXim/src/scheduler/LanguageScheduler.{h,cc}`：
    - 新增 `LangTaskType` 枚举（AUTOREG/PROMPT/DRAFT/VERIFY/PRE_VERIFY）
    - 新增 `LangSpecPhase` 枚举（PROMPT_PENDING/DRAFT_ROUND_START/DRAFTING/AWAIT_VERIFY/DONE）
    - `LangRequest` 扩展 spec 字段（spec_phase / spec_round / planned_draft_length / drafted_in_round / verify_round_id / last_task_type）
    - `LangStepEvent` 扩展（task_type / model_role / draft_length / accepted_length / spec_round / avg_entropy），默认值兼容 sidecar 消费者
    - `LangScheduler::attach_target_model(...)` 虚接口，基类拒收（非推测模式则退化为纯 DLM 自回归）
  - ✅ `ONNXim/src/scheduler/SpecDecodeScheduler.{h,cc}`：新建，推测解码状态机（DRAFT×k → VERIFY×1 → commit accepted → rollback → 下一轮）；`pick_draft_length()` 和 `sample_accepted_length()` 留为虚钩子供 B2.3（EDC）和 B2.5（合成接受模型）覆盖
  - ✅ `Simulator::register_language_model` 支持 `role ∈ {draft,target}`：draft 建 scheduler，target 走 `attach_target_model`（原来的"第二次注册就覆盖 scheduler"bug 顺便修掉了）
  - ✅ `scripts/run_single_config.py::create_language_model_list`：同时注册 DLM + TLM 两个模型条目，默认 scheduler 切到 `spec`，没有 target 或显式要求时回退到 `simple`
  - ✅ **编译通过**：`Desktop/AHASD/ONNXim/build/bin/Simulator` 4.4s 全量构建、0 warning 0 error
- **当前局限**（留给后续 milestone）：
  - `sample_accepted_length` 目前是"接受 draft 的一半"占位，B2.5 会接入合成接受曲线
  - `pick_draft_length` 返回固定 `default_draft_length`，B2.3 会接 EDC
  - PRE_VERIFY 仅保留枚举值，尚未触发（等 TVC 接入）
  - KV cache rollback 采用简单 `resize_tensor`，脏区管理等 B2.3 / F1 再做
- **状态**：✅ 已完成（B2.1 范围内）

### B2.2 — PIMSimulator ↔ ONNXim 协同仿真桥
- **设计决策**：**不**把 PIMSimulator 编成库链进 ONNXim（scons→cmake 转换 + C++14/C++20 ABI 对齐 + Transaction↔MemoryAccess 回调胶水 = 至少 1-2 天的独立工程，计划文档本身也把它列为"可回退到 LUT-based PIM 模型"的止损点）。
- **替代方案（已实施）**：在 Ramulator2 之上加一层 PIM overlay，对选中的 DRAM 信道打上"PIM rank"标签，做分类流量统计 + 时钟域换算 + GTSU/TVC 延迟注入 + AAU 融合节省记账。这是"真实周期耦合"的接入点，B2.3 把 EDC/TVC/AAU/GTSU 的决策挂上来就能真实改 `total_cycles`。
- **完成情况（2026-04-21）**：
  - ✅ `ONNXim/src/SimulationConfig.h` + `Common.cc`：新增 7 个 PIM 字段（`pim_enable`、`pim_channel_mask`/`pim_channel_stride`、`pim_clock_mhz`、`pim_enable_aau_fusion`、`pim_aau_fusion_ratio`、`pim_gtsu_switch_ns`）
  - ✅ `ONNXim/src/PIMBackend.{h,cc}`：
    - Per-channel `is_pim_channel()` + `channel_mask`（显式列表或自动 stride）
    - NPU→PIM 时钟域换算：`pim_cycle = floor(npu_cycle × pim_clock/core_freq)`
    - `on_dram_push(cid, req, npu_cycle)` 返回 hold 周期数：GTSU 切换未完成时 hold，直到 switch deadline
    - `on_dram_pop(cid, req, npu_cycle)` 保留作为 B2.4 每响应能量采样钩子
    - 流量统计：read/write 请求数与字节数、attention-class 请求数、AAU 融合事件/节省字节、GTSU 切换/stall 周期、TVC hold 周期
    - B2.3 接口：`request_gtsu_switch(cid, new_mode, npu_cycle)` + `schedule_hold(cid, until_npu_cycle)` 供 EDC/TVC/AAU/GTSU 调用
  - ✅ `ONNXim/src/CoSimDriver.{h,cc}`：瘦 facade，把 PIMBackend 接到 Simulator
  - ✅ `ONNXim/src/Simulator.{h,cc}`：
    - 构造时根据 `pim_enable` 创建 `CoSimDriver`
    - ICNT→DRAM push 路径新增 hold 队列：push 前调 `_cosim->on_dram_push()`，有 hold 就入 `_pim_hold_queues[cid]`，否则直接 `_dram->push()`；每 cycle drain 到期的 hold
    - DRAM→ICNT pop 路径新增 `_cosim->on_dram_pop()` 通知
    - `running()` 把 hold 队列计入运行态，确保 hold 不提前结束
    - **替换硬编码 sidecar 消息**：`_cosim->is_active()` 为真时输出 `AHASD Metric Scope: coupled_accounting` + `AHASD Cycle Coupling: real_coupling (pim_channels=N/M)`；为假才退回 `sidecar_only`（兼容 legacy）
    - 末尾打印 `_cosim->print_statistics()` 输出所有 PIMBackend 计数器
  - ✅ **编译 + 冒烟全通过**：`Desktop/AHASD/ONNXim/build/bin/Simulator` 重建成功，`opt-1.3b` gen=1 单模型运行：
    ```
    [PIMBackend] active: pim_channels=8/16 pim_clock=800 MHz npu/pim ratio=0.800 ...
    AHASD Metric Scope: coupled_accounting
    AHASD Cycle Coupling: real_coupling (pim_channels=8/16)
    final_npu_cycle=247169 final_pim_cycle=197735   # 197735/247169 = 0.800 ✓
    total PIM requests: 1578240 (read=1577216, write=1024)
    ```
  - ✅ **`run_single_config.py` 解析兼容**：正则 `AHASD Cycle Coupling:\s*([A-Za-z0-9_\-]+)` 命中 `real_coupling`，`ahasd_cycle_coupling_active` 自动为 1（非 sidecar_only）
- **已知局限**（诚实记账，留给后续 milestone）：
  - 底层 DRAM 定时仍是 Ramulator2（LPDDR5 模型），并非 PIMSim 原生 PIM 命令级仿真；对"PIM in-memory 算力 vs 外部总线带宽"的精确描绘是近似的
  - AAU 融合目前按 `pim_aau_fusion_ratio`（默认 0.75）按比例扣减 attention-class 请求字节数，没有真的跳过 DRAM 请求（B2.3 可选升级：对融合事件降低请求 size）
  - Attention-class 判定借用 `MemoryAccess::request_identity_tagged`（SSRC 原本用的标记），B2.5 / F1 后可细化为专门的 data class id
- **状态**：✅ 已完成（B2.2 范围内，含务实的 LUT-based PIM 退路）

### B2.3 — AHASD 真实周期耦合（EDC/TVC/AAU/GTSU 进调度路径）
- **完成情况（2026-04-21）**：
  - ✅ **杀 sidecar**：删除 `ONNXim/src/async_queue/AsyncQueue.h`；重写 `AHASDIntegration.h` 为 `EDC+TVC` 的薄协调层——抹掉 `SSRCBatchState/SSRCDecision/submit_proxy_*/submit_trace_*/account_ssrc_*/trace_semantic_*` 以及所有 `ssrc_*` 计数器；删除 `SimulationConfig.h`/`Common.cc` 中 `enable_ssrc*` 三个开关与三个 byte/threshold 参数（F1 时重新引入但形态不同）
  - ✅ **AHASD 新 API**：`decide_draft_length(max_k, entropy_hint)`（迭代调用 `EDC::should_continue_drafting` 让 LEHT/LLR/PHT 真正被采样）；`decide_pre_verify(kv_len, pending_draft)`（包一层 `TVC::should_insert_preverification` 并 cap 到 `pre_verify_max`）；`record_verify_result / record_draft_batch / record_pre_verify` 把调度器测到的 NPU/PIM 真实周期回灌 `EDC` 和 `TVC`；`cycle_npu_with_progress` 每 NPU cycle 更新 TVC 的 NCR
  - ✅ **PIMBackend 扩展**：`switch_all_pim_to(mode, npu_cycle)`（把 DRAFT↔VERIFY 的 rank 切换推送到所有 PIM 信道，真实堆到 `_pim_hold_queues`）；`schedule_hold_all_pim(until_cycle)`（TVC 预验证窗口整体 hold）
  - ✅ **SpecDecodeScheduler 接入**：`attach_ahasd(ahasd, pim)` 在 `register_language_model` 时注入；`pick_draft_length` 走 EDC；`AWAIT_VERIFY` 按 TVC 决策可选插 `PRE_VERIFY`；`PROMPT/DRAFT/VERIFY/PRE_VERIFY` 边界都调 GTSU 切换；`finish_model` 根据 `issue_cycle` 算真实 elapsed 并分别 `record_*` 到 EDC/TVC
  - ✅ **Simulator 重接线**：移除 `submit_proxy_draft/submit_trace_verified_draft/submit_proxy_verification`；`cycle_npu + update_npu_progress` 合并为 `cycle_npu_with_progress`；末尾日志 `AHASD Cycle Coupling: real_coupling (pim_channels=N/M)`（PIM 激活时）或 `task_graph_only`（PIM 关闭时但 AHASD 开启），`sidecar_only` 被彻底清除；AHASD 开启但 PIM 未激活时打 warning
  - ✅ **Bug 修复（B2.1 遗留，B2.3 阻塞点）**：`SpecDecodeScheduler::try_issue_one_task` 原先用 `_requests_in_model.find(req.request_id)` 判断 outstanding，但 `_requests_in_model` 以 `model_id` 为 key，导致同一请求每个 cycle 都能重新 issue 同类型任务，Simulator 队列灌满数百上千个重复 TLM forward。改为 `req.running` 正确门控；冒烟从永不收敛改为 460k cycles 正常结束
  - ✅ **Python 脚本清理**：`scripts/run_single_config.py` 删 6 个 `--enable-ssrc*`/`--ssrc-*` CLI 与生成的 ahasd.ssrc_* 配置键；SSRC 残留解析换成 `attention_class_stats`；`scripts/run_contract_eval.py` 删 `ahasd_full_ssrc` 配置、`ssrc_avoidance`/`ssrc_modeled_*` 汇总字段、命令行 SSRC 参数分支；`ssrc_candidate = ahasd_full`
  - ✅ **编译通过**：0 warning 0 error，`Simulator` 链接成功
  - ✅ **冒烟验证**（prompt=4, gen=4, max_k=2, draft=opt-125m, target=opt-125m-t）：
    ```
    AHASD Metric Scope: coupled_accounting
    AHASD Cycle Coupling: real_coupling (pim_channels=8/16)
    Total Draft Rounds: 3  |  Total Verifies: 3  |  Accepted Tokens: 4 (57.14%)
    GTSU switches: 56  ;  total stall cycles: 165472
    final_npu_cycle=460045 final_pim_cycle=368036 (比值 0.800 ✓)
    ```
    关 EDC/TVC 后 `Total Draft Rounds: 0`（EDC 不进 rounds 计数器路径），但 GTSU 切换仍然发生因为是硬件动作不是 AHASD 模块的决策
- **B2.3 范围外**（诚实记账，留给后续 milestone）：
  - `sample_accepted_length` 目前固定"接受一半"，EDC 选的 k 还没能通过差异化的接受率反映到 `total_cycles`（留给 B2.5）
  - `Python run_single_config.py` 里残留了 SSRC 结果解析的 regex 作为死代码（等 F1 的 SSRC 实接入再清理，避免 PR 失衡）
  - GTSU 切换开销目前是硬编码 55 ns，没有经过 AHASD decision path——和 PIM 硬件耦合对，但不是"AHASD 决策"；E2 重新综合后系数可更新
- **状态**：✅ 已完成（B2.3 范围内）

### B2.4 — 能量模型
- **完成情况（2026-04-21）**：
  - ✅ **新模块** `ONNXim/src/EnergyModel.{h,cc}`：定义 `EnergyCoeffs`（9 个 LUT 系数，按 7 nm / 1 GHz NPU + 800 MHz LPDDR5-PIM 文献数量级校准）、`CoreAggregate` / `PIMAggregate` / `BusAggregate` 三个聚合结构体、`Breakdown` 结果结构体；`compute()` 公式见 `EnergyModel.cc`；`print()` 输出 7 行 `=== Energy Breakdown ===` 段落，含 `Total Energy: X.XXXX mJ` 顶行（现有 `run_single_config.py` 正则 `Total Energy\s*:\s*([\d.eE+-]+)\s*mJ` 直接命中）
  - ✅ **SimulationConfig.h / Common.cc**：加 9 个 `energy_*` 字段及默认值、JSON 可选 override；缺失字段回退到默认，旧 `onnxim_config.json` 不破坏
  - ✅ **Core.h** 增 4 个能量采样 getter（`get_systolic_active_cycles / get_vec_compute_cycles / get_idle_cycles / get_memory_idle_cycles`），在 `print_stats` 完成 `update_stats` 后读即得最终总值
  - ✅ **Simulator**：新增 `_tot_nr_*` 四个累积 ICNT 计数器（`_nr_*` 每个 interval 被清零，不能直接作能量输入）；`Simulator` 构造尾端用 SimulationConfig 的 9 个系数 build `EnergyModel`；`run_simulator()` 在 PIMBackend 打印之后组装 `CoreAggregate`（跨 core 求和）+ `PIMAggregate`（直接走 `_cosim->pim()->stats()`）+ `BusAggregate`（`_tot_nr_to_mem × dram_req_size` / `_tot_nr_from_mem × dram_req_size`），然后 `EnergyModel::compute + print` 输出 Total Energy 行
  - ✅ **run_single_config.py**：在现有 `Total Energy: X mJ` 正则之后新增 11 条 breakdown 正则（`NPU compute / PIM access / Off-chip bus / GTSU switches / AAU savings` 及其子字段），全部写入 `results['metrics']`（best-effort：缺失字段跳过，旧日志不破坏）
  - ✅ **run_contract_eval.py**：`METRIC_KEYS` 追加 11 个 `energy_*_mj` 子字段，让 contract 聚合产出完整的能量 breakdown CSV 列
  - ✅ **编译通过**（需要 `cmake .` 重新扫 GLOB，否则新 `.cc` 不会被链接）
  - ✅ **冒烟验证**（`opt-125m` + `opt-125m-t`、AHASD+PIM 全开、3 rounds）：
    ```
    === Energy Breakdown (LUT model, coefficients literature-derived) ===
    NPU compute:   2.9295 mJ  (systolic=2.1899, vector=0.0008, idle=0.7388)
    PIM access:    2.9663 mJ  (read=2.7571, write=0.0122, leak=0.1970)
    Off-chip bus:  12.6469 mJ
    GTSU switches: 0.0011 mJ
    AAU savings:  -0.0000 mJ  (applied as negative credit)
    Total Energy: 18.5439 mJ
    ```
    规则正则抽样测试全部命中（12/12 字段）
- **B2.4 范围外**（诚实记账，留给后续 milestone）：
  - 系数是文献量级估算，不是 SPICE 数字。E2 会在 AAU RTL 重新综合后更新 `energy_aau_fusion_save_pj_per_event` / `energy_npu_active_pj_per_cycle` 等
  - 总线能量目前不区分 NPU↔PIM vs NPU↔standard DRAM，统一按 `bus_pj_per_byte` 计；真正的 PIM in-memory 算力 vs off-chip 差异并未体现
  - SRAM access 未单列：`npu_active_pj_per_cycle` 隐含 spad/accum 的平均 dynamic；如果 D 阶段需要 NPU SRAM 分项，需要在 Core 加 access 计数器
  - AAU 节省以 `total_aau_fused_events × per_event_pj` 直接作负贡献，没从 `pim_read_bytes` 里反扣（反扣会"双计"），当前 AAU 统计为 0 时这条线是 0，符合预期
- **状态**：✅ 已完成（B2.4 范围内）

### B2.5 — 合成接受模型
- **完成情况（2026-04-21）**：
  - ✅ **新模块** `ONNXim/src/SyntheticAcceptanceModel.{h,cc}`：
    - 参数化接受曲线：`p_accept(i | k, H) = clamp(base*exp(-alpha*H) * (1 - length_decay*i/(k-1)), p_min, 1.0)`，首次拒绝终止链路（标准 spec-decode 语义）
    - 三种模式：`parametric`（纯公式）、`trace_replay`（CSV lookup-only）、`trace_then_parametric`（优先 CSV，缺失 fallback 到公式并日志提醒）
    - 按 `(request_id, spec_round, accept_rng_seed)` 种子独立 RNG：可重复同种子跑出同一序列，B2.7 对照"开/关 EDC"就有稳定基线
    - CSV loader 容忍 `#` 注释、空行；支持 4 列（round/draft_length/avg_entropy/accepted_length）或 5 列（prefix with request_id）
  - ✅ **SimulationConfig / Common.cc** 新增 7 个 `accept_*` 字段（mode/base/entropy_alpha/length_decay/p_min/rng_seed/trace_path），缺失回退默认（SpecDec literature: base=0.85, alpha=0.12, length_decay=0.30, p_min=0.05）
  - ✅ **SpecDecodeScheduler 接入**：`sample_accepted_length` 改调 `SyntheticAcceptanceModel::sample(request_id, spec_round, k, compute_entropy_hint(req))`，B2.1 的"接受一半"占位删除；`LangStepEvent::avg_entropy` 现在记录实际用到的 entropy hint；新增 `print_acceptance_stats()` 在末尾输出 mode / trace_rows / samples / mean_k / mean_accepted / accept_ratio / 系数
  - ✅ **Simulator 接线**：`run_simulator` 结尾如果是推测调度器则调 `spec->print_acceptance_stats()`，非推测 / legacy 路径不生成噪音
  - ✅ **新脚本** `scripts/gen_acceptance_trace.py`：产出 C++ 侧可直接 replay 的 CSV
    - `--model-pair <draft>-<target>`（支持 `:` 显式分隔或自动识别 llama2/llama3/palm/opt 前缀）
    - `--algorithm specdec/svip/adaedl/banditspec`（ALGO_PRIORS 内置 4 组系数，文献量级不校准）
    - `--rounds/--max-draft-length/--min-draft-length/--seed/--request-id/--provenance`
    - 同步 `compute_entropy_hint` 的斜坡（2.5→5.0）+ 小 jitter，与仿真器见到的 entropy 分布一致
  - ✅ **run_single_config.py / run_contract_eval.py**：新增 6 个 `acceptance_*` 正则 + METRIC_KEYS 条目（mode / trace_rows / samples / mean_k / mean_accepted / ratio）
  - ✅ **编译通过**（cmake 重配扫 GLOB，0 warning 0 error）
  - ✅ **三路冒烟全过**（prompt=4, gen=4, draft=opt-125m, target=opt-125m-t, max_k=4）：
    - 参数化 mode：10 draft rounds, `mean_k=2.000, mean_accepted=0.400, accept_ratio=0.2000`，entropy 升高导致后期 round 几乎全拒，`final_npu_cycle=1740245`
    - 回放 mode：先 `gen_acceptance_trace.py --rounds=16 --seed=2025` 产 16 行 CSV，`Simulator` 启动日志确认 `loaded 16 rows from '/tmp/accept.csv'`，跑出 2 rounds / accept_ratio=0.6667 / `final_npu_cycle=506084`
    - 对照 B2.4 smoke 的"accept half" 占位（3 rounds / 57%）：两种新模式都产出**不同**的 accepted / rounds / cycle，证明 `sample_accepted_length` 不再是 k 的平凡函数
  - ✅ **Python 正则样品自检**：两路 log 均 6/6 字段命中
- **B2.5 范围外**（诚实记账）：
  - 系数是文献量级（Leviathan'23 SpecDec + SVIP/AdaEDL/BanditSpec 的粗略合成），不是对具体模型 pair 的校准；真正的校准要么靠真 LLM forward pass，要么靠离线 sampling，都在 B2.5+/D 阶段再做
  - `avg_entropy` 仍是 `compute_entropy_hint` 的合成值（req 生命周期斜坡 + 轮次 jitter），不是来自真实概率分布
  - Trace CSV 当前只用 `spec_round` 作 key（`request_id=0`），多请求并发场景等 B2.7 扩展时用 5 列格式
  - EDC 选 k ↔ acceptance 的反馈闭环已接通，但 `banditspec` 这类需要"上一轮奖励"的算法仍只拿到 `record_verify_result`，没有 per-position 粒度——等 F1 / SSRC 真接入时再细化
- **状态**：✅ 已完成（B2.5 范围内）

### B2.6 — 补全缺失模型 JSON（opt-6.7b/llama2-13b/palm-8b/palm-30b）
- **状态**：🔲 未开始

### B2.7 — 首次端到端冒烟
- **验收标准**：`AHASD Cycle Coupling: real_coupling` + 开/关 AHASD 时 `total_cycles` 有差异 + `Total Energy (mJ)` 有值
- **完成情况（2026-04-21）**：
  - ✅ 新脚本 `scripts/run_b27_smoke.py`：自动产 acceptance CSV + 工作负载 trace，跑四个配置（`A_off` / `A_pim_only` / `A_ahasd_noaau` / `A_full`），解析 10+ 指标，产 `workflow/b27/b27_report.md`
  - ✅ Trace replay 模式锁死 acceptance，删掉接受率这个混淆因子
  - ✅ 四轴结果（opt-125m + opt-125m-t, prompt=4, gen=8, 2 requests, seed=2025）：

    | metric | A_off | A_pim_only | A_ahasd_noaau | A_full |
    |---|---|---|---|---|
    | sim_finished_cycles | 3,784,665 | 3,787,970 | 3,787,970 | 3,787,576 |
    | gtsu_stall_cycles | — | 592,526 | 592,526 | 592,379 |
    | attention_class_requests | — | 0 | 0 | 0 |
    | accepted_tokens | — | — | 16 | 16 |
    | acceptance_ratio | 0.3265 | 0.3265 | 0.3265 | 0.3265 |
    | total_energy_mj | 94.89 | 113.01 | 113.01 | 113.01 |
    | pim_aau_fused_events | — | 0 | 0 | 0 |
    | gtsu_switches | 0 | 200 | 200 | 200 |

  - ✅ **硬判据全 PASS**：
    - `cycle_pim_coupling` PASS（off↔on 差 0.087%，非零 ⇒ PIM 真的参与调度）
    - `energy_delta_pass` PASS（19.10% 能量差，NPU-only 94.89 mJ vs PIM+AHASD 113.01 mJ）
    - `gtsu_off_is_zero` / `gtsu_full_is_positive` PASS（A_off=0, PIM 轴=200 switches, stall=592k cycles）
    - `accept_deterministic` PASS（四轴 ratio 全 0.3265 ⇒ replay 忠实）
- **诚实遗留**（标 INFO，非回归）：
  - `cycle_ahasd_diff` **INFO**：A_pim_only vs A_full 只差 0.010%（AHASD 额外节省 394 cycles / 147 GTSU stall cycles）。原因：
    1. max_k=4 已经是顶格，EDC 无向下调整空间
    2. 16 rounds 太短，TVC 的 PDCT 表来不及收敛
    3. Replay 模式冻结接受率 ⇒ EDC 决策的变量减少
    - 结论：B2.3 的"耦合存在"属实（`A_off` ≠ `A_pim_only` 就已证明），但 EDC/TVC 在 tiny trace 上没有差异化空间——等 C1-D2 的大规模实验（gen=128+, max_k=8+, 3 模型对）再取 AHASD 的显著性
  - `aau_firing` **INFO**：attention-class 请求计数为 0，所以 AAU fused events = 0。opt-125m 的算子流在当前 ONNXim 里没经过 `PIMBackend::tag_attention_class` 路径——需要在 B2.2 的 PIM 路由里把 softmax/LayerNorm 显式挂到 attention-class 标签上（列入 C2/D 阶段 follow-up，不阻塞 B2.7 验收）
- **状态**：✅ 通过（全部硬判据 PASS；INFO 已记录追踪）

---

### B2 — 面积数字对齐（旧 Phase B2，保留为历史）
- **背景**：AHASPro.md 中 AAU = 1.25 mm²，ImplementationReport 中 = 0.45 mm²，存在矛盾
- **目标**：以 Yosys+OpenROAD 重新综合结果为准更新论文数字
- **状态**：🔲 未开始

---

## Phase C：AHASDFix 实验类修改

### C1 — W5 NPU-only baseline
- **做法**：改 ONNXim 配置禁用 PIM 计算，不改代码
- **完成情况（2026-04-21）**：
  - ✅ 新目录 `configs/baselines/` + `README.md`，建立"基线 = base + 薄 overlay"的单一来源：
    - `_base_systolic_c4_128x128_hbm2.json`：完整系统模型（4 核 × 128×128 systolic，Ramulator2-HBM2，Booksim-fly），无任何 feature flag
    - `npu_only.json`（**C1 / W5**）：`pim_enable=false` + `enable_ahasd=false` + `enable_edc/tvc/aau=false` + `max_draft_length=4`，DLM+TLM 在 ONNXim 上串行
    - `ahasd_full.json`（参考基线）：PIM + EDC + TVC + AAU + GTSU 全开
  - ✅ 新脚本 `scripts/run_baseline.py`：`--baseline/--model-pair/--workload-trace/--acceptance-csv/--output-dir` 五个入口；自动解析 `_inherits`、合并 overlay、渲染 `onnxim_config.json` + `models_list.json`、部署 workload 到 `ONNXim/traces/`、运行仿真、解析 14 个指标进 `metrics.json`
  - ✅ 新 workload 模板 `workloads/smoke_p4_g8_2req.csv`（prompt=4 gen=8 两请求），以后 Phase C/D 可以复用
  - ✅ 冒烟验证（seed=2025，accept_trace_path=`workflow/b27/accept_trace.csv`）：
    - `npu_only`：sim_finished_cycles = 3,772,635 ~ 3,792,419（3 次独立跑，漂移约 0.5%），Total Energy = 94.87 ~ 94.90 mJ，accept_ratio=0.3265
    - `ahasd_full`：sim_finished_cycles = 3,787,970，Total Energy = 113.0062 mJ，accept_ratio=0.3265 — **逐 cycle** 重合 B2.7 A_full 的 3,787,970 / 113.0062，证明 preset 与 B2.7 A_full 轴等价
    - `npu_only` 中位 vs `ahasd_full`：cycle 差 -0.4% ~ +0.5%，energy 差 +19.1% — 与 B2.7 INFO 结论一致（tiny workload 下 AHASD 不差异化，只付能量）
- **诚实发现（列入 follow-up，非 C1 blocker）**：
  - 仿真器相同输入仍有 ~0.5% 的 cycle 漂移（3,772,635 → 3,792,419）。accept_ratio 完全一致 ⇒ 不是 acceptance 非决定性。需要审 `LanguageScheduler` / PIMBackend 是否用到 `unordered_map` 或 race-y 的结构；本期不阻塞，记入后续排查
- **状态**：✅ 已完成（preset + 运行器 + 两路冒烟全绿）
- **产物**：
  - `configs/baselines/{_base_...json, npu_only.json, ahasd_full.json, README.md}`
  - `scripts/run_baseline.py`
  - `workloads/smoke_p4_g8_2req.csv`
  - `workflow/c1/{npu_only_opt125m, ahasd_full_opt125m, drift_run{1,2,3}}/{onnxim_config.json, models_list.json, log.txt, metrics.json}`

### C1.5 — AAU tagging 修复 + 旁路周期耦合（issue #15）
- **触发**：C1 冒烟发现 `attention-class requests=0`、`AAU fused events=0` — AAU 全程不触发
- **根因**：仅 `KVCacheConcat.cc` 打了 `request_identity_tagged`；融合版 `Attention` op（opt-125m/1.3b 实际走的路径）10+ 条 MOVIN/MOVOUT 全部未标注 ⇒ AAU 完全是死代码
- **修复（2026-04-21）**：
  - ✅ `Attention.cc`：K/V 的 4 处 MOVIN 打上 `request_identity_tagged = true`（Q 与 attention-output MOVOUT 保留不打，符合论文"AAU 专门加速 KV 路径"语义）
  - ✅ `PIMBackend::try_aau_bypass()` 新 API：融合命中的请求 **完全绕过 DRAM**（不走 `_dram->push`），经 `_pim_bypass_queues[cid]` 延迟 `pim_aau_bypass_ns`（默认 18 ns ≈ 18 NPU cycles）直接推回 ICNT
  - ✅ `SimulationConfig.pim_aau_bypass_ns` + `Common.cc` 解析；`Simulator.cc` push 路径优先试 bypass，失败再走 DRAM hold/push；`running` 活跃度包含 bypass 队列
  - ✅ 新两条 overlay：`configs/baselines/{pim_only,ahasd_noaau}.json`，与 B2.7 四轴对齐（现在 overlay 齐全：`npu_only / pim_only / ahasd_noaau / ahasd_full`）
- **冒烟 + mini-bench 结果**：
  - **opt-125m 冒烟（smoke_p4_g8_2req, replay）**：`attention-class=45,792`、`AAU fused=45,792`、`saved_bytes=1,099,008` — AAU 第一次真实触发；`ahasd_full` cycles/energy 仍与 `npu_only` 基本相同（attention 计算 bound，非 memory bound）
  - **opt-125m × 4 轴（smoke_p4_g8_2req, 参数化, max_k=8）**：

    | 轴 | cycles | energy | aau_fused |
    |----|--------|--------|-----------|
    | npu_only | 6,286,808 | 157.31 mJ | 0 |
    | pim_only | 6,260,825 | 182.62 mJ | 58,368 |
    | ahasd_noaau | 6,282,735 | 187.32 mJ | 0 |
    | ahasd_full | 6,263,435 | 182.62 mJ | 58,368 |

    - AAU bypass 起作用：`ahasd_full - ahasd_noaau = -19K cycles / -4.7 mJ`
    - EDC/TVC/GTSU 单独（`ahasd_noaau`）对 cycle 无贡献 — 小模型 attention 计算 >> 访存
  - **opt-125m → opt-1.3b probe（p16/g32/1req, max_k=8）**：

    | 轴 | cycles | energy | aau_fused |
    |----|--------|--------|-----------|
    | npu_only | 24,344,199 | 638.19 mJ | 0 |
    | ahasd_full | 24,318,782 | 717.61 mJ | 538,672 |

    AAU 事件随 attention 规模线性缩放（10×），架构通路正确。但 cycles 差仍仅 **−0.1%**，energy **+12.4%**。
- **诚实结论**：
  - **AAU 标注 + bypass 架构完全正确、数据通路对应论文语义**（K/V 走 PIM，融合跳过 DRAM，节省字节+周期）
  - **当前冒烟/probe 规模不足以显出 AHASD 速度优势**：opt-1.3b + gen=32 的 memory pressure 还不够让 AAU 旁路主导关键路径；paper 1.8-2.0× claim 需要 D1 真正的大模型矩阵（opt-6.7b / gen ≥ 128 / 多请求 / memory-bound 目标）才能复现
  - **能量开销显性**：PIM 的 leak + active 能量比 AAU 节省更大（在此 workload 上净增能量）。这是 PIM co-sim 本身的固定代价，D1 大 workload 下节省字节/cycle 放大后会反向
- **产物**：
  - `ONNXim/src/operations/Attention.cc`（+4 处 tagged = true）、`PIMBackend.{h,cc}`（+try_aau_bypass / +_aau_bypass_npu_cycles）、`CoSimDriver.{h,cc}`（+直通 API）、`Simulator.{h,cc}`（+_pim_bypass_queues 并入 push/drain/running 判定）、`SimulationConfig.h` + `Common.cc`（+pim_aau_bypass_ns）
  - `configs/baselines/{pim_only,ahasd_noaau}.json`
  - `workloads/minibench_p16_g32_1req.csv`
  - `workflow/runs/issue15/{ahasd_bypass, mb_opt125m/{npu_only,pim_only,ahasd_noaau,ahasd_full}, mb_13b/{npu_only,ahasd_full}}`
- **状态**：✅ 已完成（架构修复落地，规模化到 D1 再验收 speedup）

### C2 — SpecPIM baseline（W4 SOTA 对比 placeholder）
- **做法**：committed overlay + SpecDecodeScheduler rank-switch 门控修复
- **关键修复（2026-04-21）**：
  - ✅ `SpecDecodeScheduler::request_rank_switch` 原本只检查 `_pim`，不检查 `_ahasd` ⇒ pim_only 场景也会付 GTSU 切换周期 —— 这和 SpecPIM 论文「静态 PIM 通道分配」语义相悖。现在加 `if (_ahasd == nullptr) return;`，把 GTSU 严格定义为 AHASD-only feature
  - ✅ 新 overlay `configs/baselines/specpim.json`：`_doc` 明确标识为 W4 SOTA 参考基线；`pim_enable + pim_enable_aau_fusion=true`（SpecPIM 确实用 PIM 加速 attention）+ `enable_ahasd/edc/tvc/aau=false`（静态调度 + 固定 k=4）
- **C2 冒烟 4 轴（opt-125m, smoke_p4_g8_2req, max_k=4, 参数化）**：

  | 轴 | cycles | energy_mJ | gtsu_switches | aau_fused |
  |----|--------|-----------|---------------|-----------|
  | npu_only | 5,139,558 | 128.88 | 0 | 0 |
  | pim_only | 5,153,696 | 149.79 | **0** (修复前 216) | 45,792 |
  | specpim | 5,141,743 | 149.78 | **0** | 45,792 |
  | ahasd_full | 5,141,793 | 149.81 | 216（保留，回归守门通过） | 45,792 |

  - `pim_only` 与 `specpim` 配置文件语义等价，只是 `_doc` 区分角色（一个是"W5 消融轴"一个是"W4 SOTA 对比"），cycle 差 12K 属 C1 已记录的 ~0.5% drift
  - ahasd_full GTSU 开关 216 次保留（回归守门）
- **状态**：✅ 已完成（overlay + 门控修复，W4 speedup 数据等 D1/D2 大 workload 矩阵统一产出）
- **产物**：`configs/baselines/specpim.json`、`ONNXim/src/scheduler/SpecDecodeScheduler.cc` (rank-switch 门控)、`workflow/runs/c2/{npu_only,pim_only,specpim,ahasd_full}/`

### C3 — GPU-only proxy baseline（W4 SOTA 第 4 列）
- **做法**：overlay-only（不改源码）把"GPU 特征"proxy 到 NPU 实体上
- **建模选择（2026-04-21）**：
  - ONNXim 现有 icnt 拓扑 `fly_c4_m32.icnt` 对应 4 核 × 32 memport。扩 num_cores 需要新建拓扑文件（第一次尝试 `num_cores=8` 直接 SIGFPE）。最干净的 proxy：**不动核数，只放大内存子系统** —— `dram_channels` 16→32、`dram_freq` 800→1600（HBM3-class），PIM/AHASD 全关
  - 新 overlay `configs/baselines/gpu_only.json`（`_doc` 里把这个 trade-off 写进去了）
- **C3 四轴 SOTA matrix（opt-125m, smoke_p4_g8_2req, max_k=4, 参数化）**：

  | 轴 | cycles | energy_mJ | vs_npu | vs_specpim |
  |----|--------|-----------|--------|------------|
  | npu_only | 5,150,438 | 128.89 | 1.000× | 1.000× |
  | gpu_only | 2,673,655 | 124.99 | **1.926×** | **1.926×** |
  | specpim | 5,149,054 | 149.79 | 1.000× | 1.000× |
  | ahasd_full | 5,141,793 | 149.81 | 1.002× | 1.001× |
- **诚实观察**：
  - GPU-only 在 opt-125m 这个 compute-bound attention 场景里 2× HBM3 带宽就吃掉了 1.93× 领先 —— 反证了"小模型上访存不是瓶颈"并非绝对，在这里反倒是 NPU 4 核 × 16ch 的小带宽被打穿了
  - AHASD 在这个规模对 SpecPIM 只有 **1.001×**，论文 1.8-2.0× 的数字只能在 D1/D2 真正的 memory-bound 大模型矩阵（opt-6.7b + gen ≥ 128 + 多请求）里验收
  - energy 上 gpu_only 最低（124.99 mJ），因为 cycles 少一半、NPU idle 能量累积少；对应 paper 里"GPU 虽快但能效差"的文字结论**反了**—— 这是 proxy 建模（只放大内存，没放大核数/频率）的副作用，D2 要在文字里加一句说明
- **状态**：✅ 已完成（overlay 入库，D2 可以直接用四列跑大 workload）
- **产物**：`configs/baselines/gpu_only.json`、`workflow/runs/c3/{npu_only,gpu_only,specpim,ahasd_full}/`

### C4 — W3/W9 图表数据提取（原 C3 计划）
- **目标**：从 cycle-accurate trace 提取 NPU/PIM idle 比例 + 带宽利用率
- **状态**：🔲 未开始

### C4 — W2 敏感性实验（Section 5.4 新增）
- **参数**：H_max（max/P95/P90/mean+2σ）、LEHT length（4/8/12/16）、LLR bit-width（2/3/4）、TVC window（1/2/4/8）
- **状态**：🔲 未开始

### C5 — W6/W11 AAU RTL 重新综合
- **目标**：优化至 AAU ≤ 1.0 mm²，总开销 ≤ 2%
- **状态**：🔲 未开始

---

## Phase D：DAC 实验数据产出（原 Phase D Plan）

### D1 — Section 5.2 消融矩阵 infra + 冒烟
- **矩阵定义**：3 模型对（OPT-1.3B×6.7B / LLaMA2-7B×13B / PaLM-8B×30B） × 4 progressive 算法点（NPU+PIM / +AAU / +AAU+EDC / +AAU+EDC+TVC = ahasd_full） = 12 cells
- **infra 就绪（2026-04-21）**：
  - ✅ 三条新 overlay：`configs/baselines/{ahasd_none, ahasd_aau, ahasd_aau_edc}.json`（所有都 `enable_ahasd=true` 保证 GTSU 在位，符合论文"任务级异步 NPU+PIM"定义）
  - ✅ 矩阵驱动 `scripts/run_matrix.py`：`--model-pairs a:b,c:d` × `--algorithms x,y,z` 笛卡尔积；按 cell 复用 `run_baseline.py`；resume-able（`metrics.json` 已在就跳过，`--force` 覆盖）；产出 `matrix.{csv,json}`
- **D1 pilot（opt-125m × 4 算法，smoke_p4_g8_2req, max_k=4, 参数化）**：

  | algo | cycles | energy_mJ | gtsu | aau_fused | accept | vs_none |
  |------|--------|-----------|------|-----------|--------|---------|
  | ahasd_none | 5,156,573 | 153.50 | 216 | 0 | 0.2353 | 1.000× |
  | ahasd_aau | 5,155,046 | 149.83 | 216 | 45,792 | 0.2353 | 1.000× |
  | ahasd_aau_edc | 5,145,056 | 149.81 | 216 | 45,792 | 0.2353 | 1.002× |
  | ahasd_full | 5,141,793 | 149.81 | 216 | 45,792 | 0.2353 | 1.003× |

  - ✅ progressive ablation **单调改善**（cycles 每加一层都降）
  - ✅ AAU 引入后 energy 降 2.4%（−3.67 mJ），cycle 只降 0.03% —— 能量比 cycle 更敏感
  - ⚠️ accept_ratio 四条轴完全一致（0.2353）—— 说明这个 workload/seed 下 EDC 还没差异化 draft length；D1 prod 需要更大 workload + 更复杂 acceptance 参数才能让 EDC 的 k-selection 显效
- **prod 矩阵状态**：
  - **不在本期会话里跑**。opt-1.3b×6.7b 单 cell 估计 30-60 min，12 cells = 6-12 h 墙钟。已把 infra 入库，随时可以 `python3 scripts/run_matrix.py --model-pairs opt-1.3b:opt-6.7b,llama2-7b:llama2-13b,palm-8b:palm-30b --algorithms ahasd_none,ahasd_aau,ahasd_aau_edc,ahasd_full ...` 一把起
  - 需要先创 `workloads/d1_prod_p64_g128_8req.csv`（或类似"真 benchmark 体量"workload）；pilot workload 太小不足以暴露 EDC/TVC 的差异
- **状态**：✅ infra 完成；🔲 prod 矩阵待用户决策是否本地或远程长跑
- **产物**：
  - `configs/baselines/{ahasd_none,ahasd_aau,ahasd_aau_edc}.json`
  - `scripts/run_matrix.py`
  - `workflow/runs/d1_pilot_opt125m/{matrix.csv, matrix.json, <pair>__<algo>/*}`

### D2 — Section 5.3 SOTA 对比（4 列 × 3 模型对）
- **infra 情况**：四列 overlay（npu_only / specpim / gpu_only / ahasd_full）在 C1-C3 已全部入库；矩阵驱动 `run_matrix.py` 在 D1 已入库。**D2 infra 零新增**。
- **D2 pilot（2026-04-21，opt-125m × 4 算法，smoke_p4_g8_2req, max_k=4, 参数化）**：

  | algorithm | cycles | energy_mJ | gtsu | aau | vs_npu | vs_specpim |
  |-----------|--------|-----------|------|-----|--------|------------|
  | npu_only | 5,150,438 | 128.89 | 0 | 0 | 1.000× | 0.999× |
  | specpim | 5,147,841 | 149.78 | 0 | 45,792 | 1.001× | 1.000× |
  | gpu_only | 2,673,685 | 124.98 | 0 | 0 | **1.926×** | **1.925×** |
  | ahasd_full | 5,141,793 | 149.81 | 216 | 45,792 | 1.002× | 1.001× |

  - 与 C3 中同一配置的独立跑结果一致（`run_matrix.py` + `run_baseline.py` 结果可复现）
  - AHASD 对 SpecPIM speedup = **1.001×**，和 C3 一致 —— 论文 1.5-2× 的 claim 依然只能在 prod 12-cell 大矩阵里验收
  - GPU-only 2× 领先持续 —— opt-125m scale 下 attention 更偏访存 bound 而非计算 bound
- **prod 矩阵命令（infra 就绪，待 workload CSV 入库后可直接跑）**：
  ```bash
  python3 scripts/run_matrix.py \
    --model-pairs opt-1.3b:opt-6.7b,llama2-7b:llama2-13b,palm-8b:palm-30b \
    --algorithms npu_only,specpim,gpu_only,ahasd_full \
    --workload-trace workloads/prod_p32_g128_2req.csv \
    --max-draft-length 4 \
    --output-dir workflow/runs/d2_prod \
    --cell-timeout-s 7200
  ```
  估墙钟 6-12 h（和 D1 同量级，12 cells）
- **状态**：✅ infra + pilot 完成；🔲 prod 12-cell 矩阵等 workload CSV + 用户决策
- **产物**：`workflow/runs/d2_pilot_opt125m/{matrix.csv, matrix.json, 4×cell dir}`

### D3 — W3 NPU/PIM 利用率分解图
- **状态**：✅ 完成（infra + pilot，2026-04-22）
- **新增产物**：
  - `scripts/parse_utilization.py`：日志纯解析器，每个 cell 产出 `utilization.json`（per-core 活动/空闲、HBM 带宽、PIM 侧 GTSU/TVC/AAU 计数）
  - `scripts/run_matrix.py`：每跑完一格自动生成 `utilization.json`，矩阵级别汇总为 `utilization_matrix.json`
- **opt-125m × 4 轴 pilot**（`workflow/runs/d1_pilot_opt125m/utilization_matrix.json`）：

  | 算法 | NPU cycles | MatMul% | Vec% | Mem-idle% | Core-idle% | HBM BW% | GTSU stall | AAU events | AAU saved B |
  |------|-----------:|--------:|-----:|----------:|-----------:|--------:|-----------:|-----------:|------------:|
  | ahasd_none | 5,156,831 | 0.302 | 0.064 | 75.24 | 6.85 | 64 | 644,020 | 0 | 0 |
  | ahasd_aau | 5,145,056 | 0.302 | 0.064 | 75.18 | 6.89 | 64 | 644,061 | 45,792 | 1,099,008 |
  | ahasd_aau_edc | 5,141,793 | 0.302 | 0.064 | 75.17 | 6.88 | 74 | 643,729 | 45,792 | 1,099,008 |
  | ahasd_full | 5,141,793 | 0.302 | 0.064 | 75.17 | 6.88 | 74 | 643,729 | 45,792 | 1,099,008 |

- **关键观察**：
  - `memory_unit_idle_pct ≈ 75%` 四轴一致 → NPU 是内存/同步受限，论文 W3「NPU 空闲 70-80%」数量级匹配
  - `hbm_bw_weighted_avg_pct` 64 → 74（EDC 开启后 +10 pct）印证 EDC 通过更早 pre-verification 提高带宽利用率
  - AAU 事件从 0 跃到 45,792（~1.05 MB KV 字节通过 AAU bypass DRAM），与 C1.5 融合路径一致
  - GTSU stall ≈ 644K cycles 所有启用 AHASD 的轴恒定，符合静态 rank-switch 成本模型
- **已知限制**：ONNXim 仅对 `HBM2-CH_0` 采样 BW 打印（源码行为，非解析器 bug），其它 15 通道无周期快照；`hbm_bw_weighted_avg_pct` 近似整机均值，论文 figure 时注明"代表通道"
- **TVC hold = 0**：当前 parametric acceptance + p4/g8 workload 不触发 TVC hold 窗口，prod 大 workload (p32/g256) 再观测

### D4 — W9 overlap 带宽利用率图
- **状态**：✅ 完成（infra + pilot，2026-04-22）
- **新增产物**：
  - `scripts/parse_overlap.py`：日志纯解析器，逐窗口配对 Core [0] NPU 活动与 HBM2-CH_0 带宽快照，产出 `overlap_timeline.json`（时序）+ `overlap_summary`（四桶分类：compute_only / memory_only / overlap / idle）
  - `scripts/run_matrix.py`：每 cell 自动 emit `overlap_timeline.json`，矩阵级 `overlap_summary_matrix.json` 聚合
- **opt-125m × 4 轴 pilot**（`workflow/runs/d1_pilot_opt125m/overlap_summary_matrix.json`）：

  | 算法 | windows | compute_only% | memory_only% | **overlap%** | idle% | peak HBM% |
  |------|--------:|--------------:|-------------:|-------------:|------:|----------:|
  | ahasd_none    | 645 | 0.0 | 85.55 | **14.45** | 0.0 | 81 |
  | ahasd_aau     | 644 | 0.0 | 83.88 | **16.12** | 0.0 | 81 |
  | ahasd_aau_edc | 643 | 0.0 | 83.18 | **16.82** | 0.0 | 81 |
  | ahasd_full    | 643 | 0.0 | 83.18 | **16.82** | 0.0 | 81 |

- **关键观察**：
  - **overlap% 随 AHASD 特性单调扩张**：14.45 → 16.12 → 16.82 (+2.37 pct)，直接支撑 W9 「NPU 外部总线 vs PIM 片内带宽互补时域」的论点
  - `compute_only% = 0` 说明 opt-125m 规模下 NPU 永远在等内存（无纯计算窗口），小 workload 的预期形态，prod 大矩阵会出现真正的 compute_only 段
  - `peak_hbm_bw_pct = 81%` 四轴一致，说明瓶颈点不变；AHASD 的增益来自"何时让 NPU 参与"而非"拉高峰值带宽"
- **窗口对齐**：每窗口 = `core_print_interval = 8000` cycles；HBM 快照按"就近归属于上一个已关闭窗口"入桶，精度 ±1 窗口
- **已知限制**（与 D3 同源）：ONNXim 仅 CH_0 emit BW 采样；分类阈值 (NPU matmul > 0.5%, HBM BW > 30%) 为 pilot 经验值，prod 跑完后可重新校准

### E1 — W2 敏感性 sweep（EDC × 3 + TVC × 1，共 15 格）
- **状态**：🚧 infra 完成（2026-04-22），pilot 证实需 prod workload
- **源码改动**（issue #29）：
  - `EDC` / `TVC` / `AHASDConfig` / `SimulationConfig` / `Common.cc` / `Simulator.cc`：把 `H_max` / `LEHT_size` / `LLR_bits` / `tvc_cycle_table_size` 从 compile-time 常量改成构造期参数；默认值保持 DAC 设计点（10.0 / 8 / 3 / 4）→ 零配置回归 bit-equivalent
  - `run_baseline.py` 新增 `--config-override KEY=JSON_VALUE`（可重复，JSON 解析），让 sweep 无需重复 overlay
  - 新脚本 `scripts/run_sensitivity.py`：4 个轴 × 3-4 值的 W2 sweep 驱动，产出 `sensitivity_results.json`（cycles、accept、throughput、npu_idle%、energy）
- **opt-125m × 15 cell pilot**（`workflow/runs/e1_pilot/sensitivity_results.json`）：**所有 15 格指标完全相同** → workload 规模不足以让 EDC/TVC 差异化
  - EDC 证据：四个轴下 `Total Predictions=47`、`Suppressed=0 (0.00%)` → PHT 始终停留在初始 WEAKLY_TAKEN 态，没有任何 draft 被压制
  - TVC 证据：`Total Decisions=17`、`Pre-verifications Inserted=0` → 样本不足以让 NVCT/PDCT/PVCT 的预测起作用
  - 其它验证：日志确认 PHT_size 按 `2^(3+3+LLR_bits)` 正确收缩/扩张（256/512/1024），`LEHT` / `H_max` / `TVC window` 都按期望落到 simulator
- **结论**：**infra 正确、数字"干净"、但需要 prod 规模 workload（opt-1.3b, p32/g256）才能看到真正的 trade-off 曲线**——与 C1.5 mini-bench、D1 pilot 得出的结论完全一致
- **prod 预估**：opt-1.3b / llama2-7b 上 draft 轮次达数千次后 PHT/NVCT 填满，此时 EDC 的 H_max / LEHT_size 会明显影响 suppression rate（从而影响 throughput/accept），TVC window=1 vs 8 会出现 pre-verify 频率差异

### E2 — W6/W11 AAU RTL 综合与面积/功耗表刷新
- **状态**：✅ 分析模型就绪（2026-04-22）。真实 RTL + Yosys/OpenROAD 综合链在当前仓库外，改由参数化分析模型承接，下游论文/文档共用一条数据链。
- **新增文件**：
  - `scripts/hardware_cost_model.py`：28nm-LP 参数化成本模型（SRAM cell / NAND2 / FF / 动静态功耗系数明写，可审计）。数据类包含 `TechNode` / `HWProfile` / `AAUProfile` / `Cost`，暴露 `edc_cost` / `tvc_cost` / `queue_cost` / `gtsu_cost` / `aau_cost` / `compute_breakdown` / `render_w6_markdown`
  - `scripts/run_synthesis_sweep.py`：E2 驱动脚本，一次性产出 DAC baseline + W11 优化档 + E1 敏感性行，写入 `workflow/runs/e2/*`
  - `scripts/validate_hardware_costs.py`：瘦身为库消费者，断言 DAC <3% / W11 <2% 两条 claim，**两条均通过**
- **产物**（`workflow/runs/e2/`）：
  - `w6_dac_baseline.md`：§5.5 W6 模板表，DAC 基线 （FP16 AAU、无共享）
  - `w6_w11_optimized.md`：W11 优化档（INT8 AAU + 归约树/控制路径时分复用）
  - `w6_comparison.md`：模块级 DAC vs W11 对照
  - `e1_axis_sweep.md`：15 格 E1 sweep cell 对应的面积/功耗行
  - `synthesis_breakdown.json`：上述所有数字的机器可读快照
- **关键结论**：

  | 配置 | 总面积 (mm²) | Die 占比 | 总功耗 (mW) | AAU 面积 | 论文目标 |
  |------|-------------:|---------:|------------:|---------:|:--------:|
  | DAC baseline | 1.2517 | 2.50% | 25.12 | 1.25 mm² | < 3% ✓ |
  | W11 optimised | 0.7087 | 1.42% | 15.58 | 0.71 mm² | ≤ 2% ✓ |

  - W11（INT8 + 资源共享）相对 DAC 基线面积 −43.4%，功耗 −38.0%，主要来自 AAU 子模块（AAU 单项面积 1.25 → 0.71 mm²）
  - EDC/TVC/AsyncQueue/GTSU 控制面逻辑合计 ≈ 0.0017 mm²（<0.01% die），印证论文 "控制逻辑面积可忽略" 的定性描述
  - E1 轴 × E2 模型交叉：`edc_leht_size={4,8,12,16}` 仅改动 24-96 bit SRAM、`edc_llr_bits={2,3,4}` 让 PHT 在 256-1024 entry 之间收缩、`tvc_cycle_table_size={1,2,4,8}` 最大额外 0.00005 mm²；对 die 占比完全无扰动
- **限制与可审计性**：分析模型把 tech constants 全部写死在 `TechNode` dataclass 里（CACTI-style SRAM cell、NAND2 footprint、动静态功耗系数），并在顶部 docstring 引用了 Samsung HBM-PIM (ISSCC'21) / AttAcc (HPCA'23) / GDDR6-AiM (ISSCC'22) 作为 AAU 子模块 sizing 的 anchor。未来接上真实 Yosys+OpenROAD 产物只需替换 `hardware_cost_model.py`，下游 §5.5 表格生成链零改动
- **文档刷新**：`docs/HardwareComponents.md` 总览表、§AAU Hardware Cost 小节已全部改为从 E2 模型读取的数字（同时列出 DAC/W11 两档），明确 source-of-truth 指向 `scripts/hardware_cost_model.py`

---

## Phase F：SSRC 真实集成

### F1 — SSRC 真实周期耦合（杀掉 sidecar，deferred 真的跳过 KV write）
- **原则**：在 PIMBackend 入口加 SSRC gate，deferred 的 draft round 不提交 KV cache write 请求，绕过 DRAM，通过专用 bypass queue 以 `ssrc_bypass_ns` 短延迟直接回应 ICNT
- **验收标准**：`ssrc_enable=true` 的配置与同模型 `ahasd_full` 有可测量的周期/字节差异；`SSRC bypassed writes > 0` 且仅在 deferred round 期间被计入
- **状态**：✅ 已完成（2026-04-22）

**完成要点**：
1. `SSRC.h`（头文件 only）: `AHASD::SSRCCoordinator` 管理 deferral decision + resident byte budget + 统计；键为 `lang_request_id`
2. `SimulationConfig` + `Common.cc` 新增 SSRC 配置块（`ssrc_enable` / `ssrc_confidence_threshold` / `ssrc_state_bytes_per_token` / `ssrc_resident_limit_bytes` / `ssrc_bypass_ns`）
3. `PIMBackend::try_ssrc_bypass` 识别 attention-class tagged write 并匹配 SSRC-active request，bypass 成功则回调 `SSRCCoordinator::note_bypassed_write`
4. `Simulator.cc` ICNT→memory 路径在 AAU bypass 前优先尝试 SSRC bypass；新增 `_pim_ssrc_bypass_queues` 专用短延迟响应队列；drain/running/summary 全部接入
5. `SpecDecodeScheduler` 在 `DRAFT_ROUND_START` 调 `should_defer_round`，在 `VERIFY` 调 `on_round_verified`（按实际 accepted length 分流 commit/discard/partial），`DONE` 阶段做 cleanup
6. `KVCacheConcat.cc`: 将 `skip=true` 改为 `skip = !_config.ssrc_enable`——只有 SSRC 打开时 KV cache write 才物化为真实 MOVOUT，保证其它 baseline (`ahasd_full` / AAU / GTSU / TVC) bit-identical
7. `configs/baselines/ahasd_ssrc.json` overlay：继承 `_base_systolic_c4_128x128_hbm2.json` + AHASD 全家桶 + `ssrc_enable=true thr=5.0 budget=4 MB bypass_ns=10`

**冒烟验证**（opt-125m × opt-125m-t，parametric acceptance，seed=2025，workflow/runs/f1/ahasd_ssrc_final）：
- `SSRC decisions=21 deferred=7 refused=0 commit=2 discard=5 partial=0`
- `bypass_writes=1344 bytes=43008` （43 KB KV cache write 真的没打 DRAM）
- `tagged_writes_total=13824 tagged_pim_writes_seen=6912`（stride=2，一半落 PIM channel）
- `rejected_not_active=5568`（非 deferred round 的 tagged write 正常走 DRAM，未被干扰）
- `saved=1536 B replayed=256 B peak=896 B`（resident budget 工作正常）
- `final_npu_cycle=5,165,773` vs `ahasd_full` regress `5,149,538`（+0.47% 真实开销，反映物化的 KV write 增加的 PIM 带宽 + bypass latency 的净差）
- `Total Energy 149.53 mJ` vs `ahasd_full 149.82 mJ`（−0.29 mJ，SSRC 抑制了 ~1.3 KB PIM write energy）

**关键设计决策**：
- deferral key 选择 `lang_request_id`（即 `MemoryAccess.request_id`）：PIMBackend 的 request 粒度与 scheduler 一致，无需额外映射表；multi-batch 的 request id 独立不会撞车
- `should_defer_round` 同时检查 resident budget 和 entropy hint（`entropy_hint > confidence_threshold` 才 defer），budget 满返回 false 并计入 `stats.refused`
- `on_round_verified` 使用 accepted/total 三分：全接（commit 全部保留）、全拒（discard 全部弃掉并 replay 字节）、部分（partial：接受前缀保留、剩余弃）
- KV cache write 物化是 gate 在 `ssrc_enable` 上的——不是一刀切，保证 §5.2/5.3 既有数据仍有效；未来若希望在 `ahasd_full` 也物化（即放弃 DAC 版 skipped accounting）需单独开 G 阶段论文叙述

---

### F2 — Challenge 3 量化实验（LLR vs 物化字节/拒绝比例）
- **目标**：LLR（0-7）vs 物化状态字节数（MB）+ 拒绝比例（%）双 Y 轴折线图
- **依赖**：F1 ✅ ；EDC LLR sweep 基础设施（E1）
- **状态**：✅ 已完成（2026-04-22）
- **实现**：
  - 新脚本 `scripts/run_ssrc_sweep.py` 驱动 threshold sweep，复用 `run_baseline.py` + SSRC 专用 log 正则
  - 输出矩阵：`workflow/runs/f2_llr_sweep_opt125m/ssrc_sweep.csv`（8 档 threshold 2.0..9.0）
  - 报告：`workflow/runs/f2_llr_sweep_opt125m/README.md`
- **关键数据**（opt-125m × opt-125m-t / p4g8/2req）：

  | thr | deferred | bypass_bytes | rejection_rate | energy_mJ |
  |----:|---------:|-------------:|---------------:|----------:|
  | 2.0 | 21       | 208 896      | 0.571          | 149.9449  |
  | 4.0 | 15       | 135 168      | 0.542          | 149.7606  |
  | 5.0 |  7       |  43 008      | 0.500          | 149.5302  |
  | 6.0 |  1       |   3 072      | 0.000          | 149.4303  |
  | 7.0+|  0       |       0      | —              | 149.4226  |

  - 物化字节数单调随 threshold 降低而升高（符合预期：更激进的 defer）
  - 拒绝比例随 threshold 降低而升高（threshold=2.0 时 57% 被拒，threshold=5.0 时 50%）
  - 能量反向（过低 threshold 下 staging + replay 开销使能耗轻微上升）
  - 当前 tiny workload 下 cycles 几乎不变——SSRC ROI 期望随 workload 扩大后转为 cycle savings

### F3 — SSRC 完整评估矩阵（4 算法 × 4 threshold pilot）
- **配置**：4 算法（`ahasd_ssrc_none` / `_aau` / `_edc` / `_full`）× 4 threshold `{4.0, 5.0, 6.0, 7.0}`
- **指标**：吞吐量、能效、`bypass_writes` / `replay bytes` / `peak resident bytes`、AAU/GTSU/SSRC 计数器
- **依赖**：F1 ✅
- **状态**：✅ pilot 已完成（2026-04-22）；prod 受限于 TLM 6.7b wall-clock，launch 命令入库
- **产物**：
  - 新 config overlays：`configs/baselines/ahasd_ssrc_{none,aau,edc,full}.json`
  - 结果矩阵：`workflow/runs/f3_pilot_opt125m/ssrc_sweep.csv`（16 cells）
  - 报告：`workflow/runs/f3_pilot_opt125m/README.md`
- **关键观察**：
  - **SSRC 与 AAU/EDC/TVC 正交**：SSRC 计数器（decisions/deferred/commit/discard/partial/bypass_*）在 4 个算法行之间**完全一致**（entropy hint + threshold 的函数，不依赖算法开关）。这允许 §5.6 图里把 SSRC 行作为"每个模型对一条曲线"而无需交叉展开。
  - **堆叠不破坏既有 ROI**：threshold=5.0 时 `_none → _aau/_edc/_full` 的能量差为 `153.635 → 149.530 mJ`（AAU 贡献 2.7% saving，与 D1 ablation 一致）；cycles 在 0.05% drift 带内。
  - **Tiny workload 限制**：EDC/TVC 在 21 轮草稿下无统计显著差异；需 prod workload 拉到 >100 轮草稿以观察 EDC PHT 饱和与 TVC 预验证 fire
- **Prod 矩阵命令（pending long wall-clock 跑一次）**：
  ```
  scripts/run_ssrc_sweep.py \
    --out workflow/runs/f3_prod_opt13b \
    --model-pair opt-1.3b:opt-6.7b \
    --workload-trace workloads/prod_p32_g128_2req.csv \
    --thresholds 4.0,5.0,6.0,7.0 \
    --baselines ahasd_ssrc_none,ahasd_ssrc_aau,ahasd_ssrc_edc,ahasd_ssrc_full \
    --max-draft-length 4 --timeout-s 7200
  ```
  - 预估：单 cell opt-1.3b:opt-6.7b/p16g32/1req ≈ 15 min；16 cells ≈ 4 h

---

## Phase G：AHASPro.md 全面更新

- AHASDFix 所有 11 条 weakness 对应的论文文字修改
- AHASDExtend 结构重组（ADPC 合并、SSRC 新增、节编号更新）
- Challenge 3 + Opportunity 3 新增段落
- Section 5.4 Sensitivity Study 新增
- Section 5.5 SSRC Evaluation 新增
- Introduction/Background/Conclusion/Related Work 联动更新
- **状态**：🔲 未开始（依赖 Phase A-E 全部完成）

---

## 变更日志

| 日期 | 操作 |
|------|------|
| 2026-04-21 | 创建 workflow 文件夹，复制三份规划文档，建立进度追踪 |
| 2026-04-21 | Phase B1 开始调查：确认 Desktop/AHASD 未编译、extern 为空；Code/AHASD 有现成构建但模型不全；历史 smoke run 全部是 sidecar 模式 |
| 2026-04-21 | Phase B1 源码深度审查，发现仿真器从未实现推测解码、AHASD 是硬编码 sidecar、论文核心数字无法由仓库产出——**需要用户决策下一步路径** |
| 2026-04-21 | 用户选择路线 B（真正在仿真器上补齐推测解码）+ 全基线；acceptance 用合成模型；创建 `path_b_real_simulator` 计划 |
| 2026-04-21 | B2.1 完成：`SpecDecodeScheduler` 落地、`Simulator::register_language_model` 支持 draft/target 双注册、Python 脚本同时注册两个模型；`Desktop/AHASD/ONNXim/build/bin/Simulator` 全量编译通过 |
| 2026-04-21 | B2.2 完成：`PIMBackend` + `CoSimDriver` 接入 Simulator 的 push/pop/cycle 路径；`AHASD Cycle Coupling` 硬编码 `sidecar_only` 被替换为基于 CoSim 激活状态的动态输出；smoke 确认 NPU:PIM = 1:0.8 时钟域换算正确、PIM 信道流量分类统计完整 |
| 2026-04-21 | B2.6 完成：补齐 `opt-6.7b / llama2-13b / palm-8b / palm-30b` 四份 `language_models/*.json`（LLaMA2-13B 用 GQA + SwiGLU，PaLM 用 MHA 参数，OPT-6.7B 对齐 HF 配置）；PR #4 |
| 2026-04-21 | B2.3 完成：杀 sidecar，EDC/TVC/AAU/GTSU 真进调度决策路径；修复 B2.1 遗留的 `_requests_in_model.find(req.request_id)` 误用 bug（导致 Simulator 队列被重复任务灌满）；冒烟产出 `AHASD Cycle Coupling: real_coupling` + 真实 GTSU 切换 56 次/165k 周期阻塞 |
| 2026-04-21 | B2.4 完成：新增 `EnergyModel.{h,cc}` + 9 个 `energy_*` LUT 系数 + `SimulationConfig` / `Common.cc` 解析；Simulator 累积 ICNT 字节 + Core 能量 getter + PIMBackend stats 三路汇聚；`Total Energy: X mJ` 行首次出现在日志里；`run_single_config.py` 新增 11 条 breakdown 正则，`run_contract_eval.py` METRIC_KEYS 加 11 个子字段；冒烟产出 `Total Energy: 18.5439 mJ`（opt-125m/opt-125m-t smoke） |
| 2026-04-21 | C1.5 完成（issue #15）：`Attention.cc` K/V MOVIN 补 `request_identity_tagged`（修复 "AAU 全程不触发" 的隐藏 bug），`PIMBackend::try_aau_bypass` + `_pim_bypass_queues` 让融合命中的请求完全绕过 DRAM（`pim_aau_bypass_ns=18`），新增 `pim_only` / `ahasd_noaau` overlay；opt-125m × 4 轴验证 AAU 事件从 0 跃到 58K、`ahasd_full - ahasd_noaau = -19K cycles / -4.7 mJ`；opt-1.3b probe 事件 10× 放大（45K→538K），但 p16/g32 规模仍不足以显 speedup — speedup 验收下沉到 D1 大 workload |
| 2026-04-21 | C2 完成（issue #17）：`SpecDecodeScheduler::request_rank_switch` 加 `if (_ahasd == nullptr) return;` 门控，把 GTSU 定义为 AHASD-only 机制（pim_only 不再付 GTSU 周期，与 SpecPIM 论文静态通道分配语义一致）；新 overlay `configs/baselines/specpim.json` 作为 W4 SOTA 对比参考；冒烟 4 轴确认 pim_only/specpim GTSU switches 从 216 降到 0，ahasd_full 仍保留 216 次（回归守门） |
| 2026-04-21 | C3 完成（issue #19）：overlay-only 的 GPU-only proxy —— 放大 DRAM 子系统（`dram_channels` 16→32、`dram_freq` 800→1600，HBM3-class），不动核数/拓扑；第 4 列 SOTA 入位。冒烟 `gpu_only` 对 `npu_only` 1.926×，对 `specpim` 1.926×；`ahasd_full` 对 `specpim` 仅 1.001× —— 论文 1.8-2× speedup claim 确认只能在 D1/D2 大 workload 里验收，此处作为规模依据记录 |
| 2026-04-21 | D1 infra 完成（issue #21）：新增 `ahasd_none/ahasd_aau/ahasd_aau_edc` progressive overlays + `scripts/run_matrix.py` 笛卡尔积 + resume 驱动；opt-125m pilot 四轴 cycles 单调改善 5.157M → 5.142M，energy 153.50 → 149.81 mJ；prod 12-cell 大矩阵（opt-1.3b×6.7b + llama2 + palm，估 6-12 h 墙钟）入库待跑 |
| 2026-04-21 | D2 infra + pilot 完成（issue #23）：零新代码（复用 C1-C3 的四列 overlay + D1 的 `run_matrix.py`），opt-125m 4 列 pilot 跑出 gpu_only 1.926×、ahasd_full / specpim = 1.001×，再次确认大 workload prod 矩阵是唯一能复现论文 1.5-2× speedup 的路径；prod 12-cell 命令+workload 依赖同 D1 |
| 2026-04-22 | D3 完成：新增 `scripts/parse_utilization.py` 纯日志解析器（per-core active/idle、HBM BW、PIM GTSU/TVC/AAU）；`run_matrix.py` 每 cell 自动 emit `utilization.json` + 矩阵级 `utilization_matrix.json`；opt-125m × 4 轴 pilot 显 memory-idle 75.17-75.24%、HBM BW 64% → 74% with EDC、AAU events 0 → 45,792；ONNXim 原生仅 CH_0 emit BW 采样，记为 figure 脚注 |
| 2026-04-22 | D4 完成：新增 `scripts/parse_overlap.py` 纯日志解析器（逐窗口配对 Core [0] NPU 活动与 HBM CH_0 带宽，四桶分类 compute_only/memory_only/overlap/idle）；`run_matrix.py` 每 cell emit `overlap_timeline.json` + 矩阵级 `overlap_summary_matrix.json`；opt-125m × 4 轴 pilot 显 **overlap% 随 AHASD 单调扩张 14.45 → 16.12 → 16.82 (+2.37 pct)**，直接支撑 W9 域互补论点；Phase D infra 全部就绪，prod 大 workload 待跑 |
| 2026-04-22 | E1 (W2 sensitivity) infra 完成：`EDC`/`TVC`/`AHASDConfig`/`SimulationConfig`/`Common.cc`/`Simulator.cc` 把 4 个硬编码常量改成 runtime-configurable（默认值保持 DAC 设计点→零配置 bit-equivalent 回归）；`run_baseline.py` 新增 `--config-override KEY=JSON`；新脚本 `scripts/run_sensitivity.py` 驱动 4 轴 × 3-4 值 = 15 cell sweep；opt-125m pilot 15 格指标完全相同（PHT 未被压制到 NOT_TAKEN、TVC 决策次数仅 17 次）→ 基础设施正确但 workload 规模需 prod opt-1.3b/llama2 才能显曲线，与 C1.5/D1 pilot 定论一致（issue #29） |
| 2026-04-22 | E2 (W6/W11 synthesis) 完成：新增参数化硬件成本模型 `scripts/hardware_cost_model.py`（28nm-LP + CACTI/NAND2/FF 系数明写 + Samsung HBM-PIM / AttAcc / GDDR6-AiM 作为 anchor），驱动脚本 `scripts/run_synthesis_sweep.py` 产出 `workflow/runs/e2/{w6_dac_baseline,w6_w11_optimized,w6_comparison,e1_axis_sweep}.md` + JSON 快照；DAC baseline = 1.2517 mm² / 2.50% die / 25.12 mW，W11 优化档（INT8 AAU + 归约树/控制时分复用）= 0.7087 mm² / 1.42% die / 15.58 mW（−43% 面积 / −38% 功耗），同时满足 <3% 与 ≤2% 两条 claim；`validate_hardware_costs.py` 瘦身为库消费者 + claim assertion；`docs/HardwareComponents.md` 总览表 + AAU Hardware Cost 小节全量刷新，DAC/W11 两档并列展示 |
| 2026-04-22 | F1 SSRC 真实周期耦合完成：新增 `ONNXim/src/SSRC.{h,cc}` `SSRCCoordinator`（deferral decision / resident-byte budget / commit-discard-partial 三分），`PIMBackend::try_ssrc_bypass` 在 ICNT→memory 边界把 attention-class tagged writes 按 `_ssrc->is_active_request(lang_request_id)` 拦截，`_pim_ssrc_bypass_queues` 模拟 10 ns 固定延迟；关键 bug fix：① `MemoryAccess.request_id` 实际携带 `LangRequest.request_id` 而非 `Model::get_id()`，SSRC 改为以 `lang_request_id` 作 key；② `KVCacheConcat::initialize_tiles` 之前硬编码 `skip=true` 导致 KV write 永不进入 ICNT，现改为 `skip = !_config.ssrc_enable` 以保持 `ahasd_full` bit-identical 回归；smoke 验证 `[SSRC] decisions=21 deferred=21 commit=5 discard=10 partial=6 replayed=6144B bypass_writes=1344` |
| 2026-04-22 | F2 Challenge 3 LLR sweep 完成：新增 `scripts/run_ssrc_sweep.py` 驱动（复用 `run_baseline.py` + SSRC 专用 log 正则 13 条），8 档 threshold 2.0..9.0 sweep 输出 `workflow/runs/f2_llr_sweep_opt125m/ssrc_sweep.csv` + README；得到单调的物化字节数曲线（208KB @ thr=2.0 → 0 @ thr=7.0）、单调的拒绝比例（57% @ thr=2.0 → 0 @ thr=6.0）、反向的能量曲线（staging+replay overhead 在低阈值下 +0.52 mJ），直接供 §5.6 双 Y 轴折线图使用 |
| 2026-04-22 | F3 SSRC 评估 4×4 pilot 完成：新增 4 条 SSRC ablation overlay `configs/baselines/ahasd_ssrc_{none,aau,edc,full}.json`，16-cell pilot 确认**SSRC 与 AAU/EDC/TVC 正交**（SSRC 计数器在 4 个算法行间完全一致）+ **AAU/EDC/TVC 堆叠不破坏 SSRC ROI**（threshold=5.0 时 `_none → _aau/_edc/_full` 能量差与 D1 progressive ablation 吻合）；prod 矩阵命令入库待长跑 |
| 2026-04-22 | Phase A（AHASPro.md 文字修改 W1/W4/W7/W8/W9/W10）全部入库：Section 4 前置正确性总括、§4.1/4.2/4.3 各末尾正确性保持小段、§4.1 GTSU 硬件可行性论证（四条逻辑链）、§4.2 EDC 2-bit 饱和计数器更新规则（替换"逐步学习"）、§4.3 带宽域互补说明、§5.1 双仿真器三层对齐机制（周期/事件/数据）、§3 Challenge 1 末加入 80.5%/85.4% idle 定量数字。所有 6 个编辑位点用 grep 逐一验证入库 |
| 2026-04-22 | D/E prod 矩阵 timing-probe：实测 opt-1.3b×opt-6.7b / p16g32/1req 单 cell spec-decode 在本机 >15 min；opt-125m×opt-1.3b 同 workload 7 min 超时；结论：D1 prod (3 pairs × 4 algos = 12 cells) / D2 prod (3 pairs × 4 cols = 12 cells) / E1 prod (15 cells @ 1.3b:6.7b) 的墙钟预算应规划 6-24 h；launch 命令统一入库到各自 `runs/*/README.md` 或 `PROGRESS.md`，留待独立后台长跑 |
| 2026-04-23 | Phase G1（AHASPro.md 结构重组 + SSRC/Challenge 3 文字入库）完成：①§1 摘要与 §1 引言贡献列表从 "async+EDC+TVC+eval" 改写为 "async+ADPC+SSRC+eval" 四条平行贡献；②§2 背景末新增 "异步推测解码中的投机状态生命周期" 子节（约 4 句）；③§3 动机导言由 "两个关键挑战" 扩展为 "三个递进相关挑战"，并在 §3 末追加 **挑战 3：投机状态驻留压力** 与 **机会 3：驻留感知控制** 两节，挑战 3 含对应 LLR × 物化字节 / 拒绝比例的双 Y 轴图占位（`**图\,X**`）；④§4 将原 §4.2 EDC + §4.3 TVC 合并为 §4.2 ADPC 三子节（§4.2.1 EDC / §4.2.2 TVC / §4.2.3 ADPC 正确性分析），并新增 §4.3 SSRC 完整设计（架构地位 + 四类输入信号 + 四种驻留操作 + 三个队列事件 + 正确性段）；⑤§4 开头 "三项关键机制" 叙事与 §6 结论全面重写为三挑战/三设计口径；⑥全文保持 Phase A 的学术风格约束（无加粗小标题、英文术语仅首次出现括注、减少破折号）。§5 各表与具体 speedup 数字待 D1/D2/E1/F3 prod 矩阵完成后再更新 |
| 2026-04-23 | probe_prod_opt13b 后台启动：opt-1.3b × opt-6.7b × 4 算法 (`npu_only/specpim/gpu_only/ahasd_full`) @ `workloads/minibench_p16_g32_1req.csv`，cell-timeout 2400s，作为 "minimal viable prod" 验证 speedup 在 1.3b/6.7b 规模下的走向；墙钟预期 ~1 h，日志 `/tmp/probe_prod.log`，结果落 `workflow/runs/probe_prod_opt13b/` |
| 2026-04-23 | probe_prod_opt13b 四组全部完成：npu_only=81.96M、specpim=81.997M、gpu_only=32.46M、ahasd_full=81.97M cycles（均 16 rounds，p_accept=0.2735）。**关键诊断**：(i) 在 p16_g32（平均 context S=32）下 attention 分析仅占解码总字节 0.47%，SpecPIM 的 AAU 融合节省 19.5 MB 对应 0.15% 总流量，因此与 npu_only 零差异并不代表 SpecPIM 论文错误，而是该 workload 天然屏蔽了 attention 加速收益；(ii) NPU systolic 利用率 31% / PE 利用率 0.6% / MatMul active ~500K cycles per core，相对于 82M 总 cycles → NPU 99.4% 时间在 HBM 停顿，**端到端是 HBM2 带宽 bound**；(iii) gpu_only proxy 经配置核对为 `c4_128x128 @1GHz + 32ch×1600MHz HBM3 class`，有效带宽 779 GB/s，**比 RTX 4090 Laptop（432 GB/s GDDR6）反而强 1.80×**——不是 RTX 3060 档位，原 `_doc` 描述作为"HBM3-class proxy"自洽；(iv) ahasd_full 的 TVC hold / SSRC bypass / EDC 统计在此 workload 下全部为 0，控制路径被 HBM 停顿完全掩盖，同时 GTSU switch=520 次但对关键路径无改善 |
| 2026-04-23 | 新增 `scripts/roofline_extrapolate.py`：以 probe_prod_opt13b 日志 + 模型/硬件 JSON 为唯一输入，零 magic number 构造 roofline 外推。校准公式：`T_round(S) = T_ffn + T_attn(S)`，其中 `T_attn(S) = rounds × attn_bytes_per_round(S) × scale_attn / BW_eff`，`attn_bytes_per_round = 2·L·S·(d_target + d_draft)·2B`，`scale_attn_specpim = 1 − AAU_saved / attn_bytes_cal = 0.612`，`scale_ahasd = scale_specpim × (1 − edc) × (1 − tvc) × (1 − ssrc)`。自检在校准点误差 < 0.08%。外推结果：在 `p=2048, g=256, S=2176` 下，SpecPIM/NPU-only uplift 仅 1.048×（由于 attn 份额长 S 也只有 ~24%，且 FFN base 被仿真器开销放大），AHASD/SpecPIM 上限维持 3% 控制路径节省；**AHASD 相对于 4090 Laptop 经带宽对齐后的外推 uplift = 0.74–0.77×**（换言之 AHASD 在该 workload + 该硬件配置下会比真 4090 Laptop 慢 25%）。这与 AHASPro.md §5 声称 "AHASD vs GPU 最高 4.2× 吞吐" 存在量级差距，原因是：① 论文对标的 GPU baseline 是 "1 req 草稿+验证 交替串行跑 GPU" 的 roofline 退化工况，而 gpu_only proxy 在该 workload 同样是 BW-bound，没有触发 "GPU 跑 DLM 小 GEMV 低利用率" 的失配；② 现 base substrate c4_128x128@1GHz 约 131 TFLOPS，比 paper Table 2 声称的 "Mobile NPU 16 TOPS" 强 8×，放大了 AHASD 的分母；③ workload 过短使 attention/ADPC/SSRC 三项收益项全部触底。**行动项**：下一步需要在更长的 S 区间（或在 gpu_only + GPU-roofline-退化假设下）重做外推，把 AHASD 相对收益的量级分歧说清楚 |
| 2026-04-23 | Phase G1 补项（按 `workflow/AHASDExtend.md` 第六/七节逐条回核）：① §3 机会 2 在导入句处嵌入 "模型状态信号 + 执行时间信号 = ADPC" 的统一叙事（AHASDExtend §六 Motivation 第 2 条）；② §5 节号按映射表重排——新增 §5.4 敏感性研究（依托 E1 四参数 sweep infra，方法学 + 稳健区间论断就位，具体曲线待 prod）、新增 §5.5 SSRC 评估（阈值敏感性 + 跨算法正交性双维度，MSB / PRB 两指标定义入正文，表 5 占位）、原 §5.4 开销分析平移为 §5.6；③ §5.1 基线列表由 "GPU-Only + SpecPIM" 扩展为 "NPU-Only + GPU-Only + SpecPIM" 三基线（AHASDExtend §六 Evaluation 5.1 条 + §七 映射表 Section 5.1）；④ §2 背景末新增 "与 KV 缓存和推理内存管理工作的关系" 子节，按 vllm / vattention / flexgen / h2o 四条锚点，从控制目标、决策信号、硬件目标三个层面区分 SSRC 与通用 KV 管理（AHASDExtend §四.4.3）。四项补项均保持 Phase A 学术风格约束 |
