# PREM 三扇区、50 震源、100-run Whale 生产包

## 冻结科学设计

本包服务 50 个固定在 `(0°, 0°)` 的震源，每个震源有一个 matched B0 与一个 TRIULVZ run，因此共 100 runs。深度配额为 `<70 km=39`、`70–150 km=4`、`150–300 km=3`、`300–500 km=1`、`500–700 km=3`；机制覆盖由 `catalogs/source_ensemble.csv` 冻结。台站是原 A+ 170 台阵列及其绕 source radial axis 严格球面旋转 `+120°`、`+240°` 的副本，共 510 台；距离和相对方位审计在 `catalogs/station_geometry_audit.json`。

B0 明确为 `N_ULVZ=0`，没有 dummy body。TRIULVZ 明确为 `N_ULVZ=3`，body 1/2/3 分别服务 A/B/C sector。A 的 G01–G08 CMB illumination positions 经同一球面旋转映射到 B/C；参数与 position 独立分配，并在 `catalogs/ulvz_overlap_clearance_audit.csv` 中通过三对 clearance 检查。

150 个 ULVZ body 来自 `legacy_parameter_anchor`、`family_interpolant`、`survey_family_sample` 三类。它们遵守生产兼容 family 内插值，保留来源与证据，不做跨 family 笛卡尔组合。所有 body 的 `LATERAL_TAPER_KM=0`、`TOP_TAPER_KM=0`；不支持的椭圆、梯度、分层和任意形状没有伪装为标签。

## 公共 SPECFEM 设置

唯一公共入口是 `specfem_template/`。其 Par_file 冻结 PREM、six chunks、`NEX_XI/NEX_ETA=448/448`、`NPROC_XI/NPROC_ETA=8/8`、384 MPI ranks、ASDF 输出、DT=0.1 s、42 min、NSTEP/expected npts=25400。物理设置为 OCEANS=false、ELLIPTICITY=true、TOPOGRAPHY=false、GRAVITY=true、ROTATION=true、ATTENUATION=true、ABSORBING_CONDITIONS=false。每 run 仅替换 CMTSOLUTION、ULVZ bodies、LOCAL_PATH/LOCAL_TMP_PATH 和 identity。

multi-ULVZ 源码基准为 `git@github.com:ordeal97/ulvz_specfem.git` 的 `72f0c39117df9395c12fa901a9ae99fa3e7bdfd9`。该 commit 的真实 mesher 验证属于上游证据；本包未重跑 mesher 或 solver。

Whale 的运行 profile 继承 A+ package：control Python 为 `/share/home/yiy/.conda/envs/ulvz-specfem/bin/python3`，要求 Python ≥3.11 且可导入 `numpy`、`h5py`；LSF/build 通过 `/share/apps/intel/oneapi_2023.1.0/setvars.sh` 初始化 oneAPI，加载 `hdf5/1.14.3_oneapi2023`，MPI launcher 为 `mpirun`。这些设定在 `config/production.toml` 中冻结，并由 build-template 与 rendered LSF 共同使用。

## 输入冻结与 preflight

`production_run_manifest.csv`、catalogs、100 份 `production_inputs/*/DATA`、`rendered_lsf/` 与母包共同定义冻结输入。`scripts/preflight.py` 从 rendered DATA 对照 source、station、parameter、instance 与 manifest；检查 50/510/100/150 计数、39/4/3/1/3 深度配额、0/3 bodies、zero taper、clearance、唯一 scratch、公共 Par_file、source pairing 与阶段身份。若 worktree 已存在，也逐项比对实际 DATA、三份 LSF 与 identity；不一致会使 preflight 失败。`preflight/all_runs_parameter_audit.csv` 是一行一个 run 的人工审查总表。

submit 前 `preflight_summary.json` 必须 PASS，且 config、contract、manifest、template、DATA、rendered LSF hashes 与当时结果一致。任意修改均使 gate 过期；不会 warning 后继续提交。

## Whale 执行与控制

完整命令顺序见 `PRODUCTION_RUNBOOK_zh.md`。build-template 从用户指定的旧 build 只读提取 configure 和简单 module 证据，在独立 runtime 目录 checkout pinned source、重新 configure 并编 mesher。无 GitHub 网络时使用 `--source-tree`：Git 树验证固定 HEAD；ZIP 树必须携带 `SOURCE_PROVENANCE.json`，程序重新验证关键源码 SHA-256。旧二进制、Makefile 和 mesher header 不复用；缺 ASDF 证据、未知 Makefile/config 冲突或工具链不完整会停止。归档成功 Aplus 的唯一已验证手工 Makefile 差异是 `FLAGS_CHECK` 从 `-fpe0` 变为 `-fpe3`；新包会在 configure 后重放并审计此值。build 后的 `asdf-smoke` 使用实际 compiler、flags、ASDF/HDF5 linkage 调用 production serial writer 的 initialize/create/close/finalize 接口，生成的 PASS 报告是 submit/resume hard gate；每 run control 还会在本 worktree 重跑该 probe。SPECFEM Makefile.in 的其他已知派生差异只进入审计，不降低其他安全检查。

materialize 仅在 build evidence 兼容时创建 100 个独立 worktree。已有 tree 默认不覆盖；`--refresh-lsf` 是显式的三份 LSF 刷新操作，并拒绝活动 run。controller 是唯一调用 bsub 的组件，使用原子 CSV、控制锁和配置的 `max_active_runs=2`。per-run control 使用原子 job metadata、`bjobs`/`bhist` 状态回退和独立 LSF 资源声明。它不依赖 manifest 排序模拟阶段门槛：只有全部 B0 处于 DONE 且 output QC PASS，才选取 TRIULVZ。失败不会自动 retry；只有所有已知作业终态、诊断已保存且 scratch 成功清理后才可显式 retry。

运行后 QC 读取 `OUTPUT_FILES/ulvz_normalized.csv`，严格核对 PREM background、B0 的一条 N_ULVZ=0 provenance 和 TRIULVZ 的三条唯一 body、中心、R/H、dVs/dVp/dRho、taper；NaN/Inf 会失败。ASDF 必须有 510 个固定 station identity、每站唯一 E/N/Z、1530 traces、10 Hz、25400 samples 与有限值。TRIULVZ 和 matched B0 全部 waveform payload bitwise identical 时失败；不要求每站响应。cleanup 默认 preview，`--execute` 时才会在作业终态检查后清理精确 scratch target。

## 已完成与部署边界

本包已静态验证 rendered DATA、科学 audit、preflight、dry-run、LSF bash syntax 和 scheduler mock；这些检查没有调用 bsub、mesher 或 solver。oneAPI 初始化按实际 `ifort`、`mpiifort`、`mpirun` 命令决定是否执行 `setvars.sh --force`，因此控制作业继承的环境不会因重复 source 退出。部署时仍需检查 module/MPI 与 ASDF/HDF5、pinned-source build、LSF queue 和 384-rank ptile=64 host layout、scratch/共享文件系统、内存和存储，以及实际 mesher/solver/output QC 行为。详见 `design_summary.json` 与 `preflight/PREFLIGHT_REPORT.md`。
