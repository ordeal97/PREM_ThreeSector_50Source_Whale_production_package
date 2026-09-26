# PREM 三扇区 50 震源 P/Pdiff 与 S/Sdiff 时窗建议

## 适用范围与结论

本表覆盖冻结设计中的 50 个震源、510 个台站（A/B/C 三扇区）和两个相位族，共 51,000 行。TauP/PREM 提供名义到时锚点；窗口偏移沿用 A+ PREM 估计包，是训练及后处理建议。有限频率波包、ULVZ 延迟、散射和 postcursor 不由 TauP 单独确定；本表不是波形拾取或 ULVZ 结构约束。

| 相位族 | 主窗 | 扩展训练窗 | 主分量 | 全部锚点范围 (s) | 扩展范围 (s) |
| --- | --- | --- | --- | ---: | ---: |
| P/Pdiff | family_first−20 至 family_last+20 s | anchor−30 至 anchor+80 s | Z（R辅助） | 714.6–978.0 | 684.6–1058.0 |
| S/Sdiff | family_first−20 至 family_last+20 s | anchor−30 至 anchor+120 s | T | 1316.7–1811.5 | 1286.7–1931.5 |

不同深度震源和三扇区几何均按各自的 TauP/PREM 路径计算。P 与 Pdiff、S 与 Sdiff 的最早分支会随距离切换；95°–105°行标记为 `transition_distance_flag=true`，此一维模型切换不代表有限频率物理边界。具体锚点分支计数见 `phase_window_validation.json`。

## 证据与窗口映射

- **文献处理结果：** Kim 等报告 Pdiff 窗为 PREM 到时 −30 至 +70 s（`pilot::E001`，`extraction/pilot_evidence_matrix.csv`，第2行，PDF 页索引2、印刷页2、Fig. 1）；同一研究报告 Pdiff 延迟约10–30 s、Sdiff 延迟约25–45 s（`pilot::E002`，同表第3行，PDF 页索引3、印刷页3、Fig. 1F）。
- **文献观测：** Li 等报告 Sdiff postcursor 在10–20 s周期约35–50 s、短周期约50–70 s（`batch_02::B02-E052`，`extraction/batch_02_evidence_matrix.csv`，第20行，PDF 页索引2、印刷页3、Fig. 3）。
- **项目历史处理：** Event‑1 分析的 S/Sdiff extended tail 为 `family_last+20` 至 `family_last+120 s`，见 `/import/freenas-m-01-seismology/xjiang/ulvz_database/scripts/run_event1_reanalysis.py` 的 `CONFIG['windows']`；该历史配置作为处理先例。
- **项目建议：** P/Pdiff 扩展窗将 Kim 的 −30…+70 s 向后延长10 s；S/Sdiff 采用历史分析中的 +120 s 尾窗。两项设置是处理建议，不是观测到时或跨研究综合估计。

## 使用与审查

1. `taup_anchor_s` 是 TauP 最早候选分支到时；`taup_anchor_phase` 保留实际相名，不应将 P/S 锚点改称 Pdiff/Sdiff。
2. 主窗用于主波包测量；扩展窗容纳候选延迟与后续能量。`overlap_flag=true` 时保留重叠信息，训练或评估应按该标记分层。
3. 同源 B0/TRIULVZ 波形可用后，再按分量和扇区复核建议窗口；此表本身不表示模型验证通过。

`catalogs/station_phase_windows.csv` 给出逐源—逐站—逐相位族建议；`catalogs/phase_window_method.json` 记录规则、输入哈希与解释状态；`catalogs/phase_window_source_inventory.csv` 记录输入大小和 SHA-256；`catalogs/phase_window_validation.json` 验证结果为 **PASS**，包含 51,000 行，S/Sdiff 到时与冻结审计表最大差 5e-07 s。
