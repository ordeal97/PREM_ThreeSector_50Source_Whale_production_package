# Whale 生产运行手册

本包已冻结科学设计与 100 份 DATA/LSF；未调用 bsub、mesher 或 solver。生产控制器只允许两个 active run，且必须先使 50 个 B0 全部 `DONE + output_qc=PASS`，才解锁 50 个 TRIULVZ。

Whale 运行环境已继承 A+ package：控制 Python 为 `/share/home/yiy/.conda/envs/ulvz-specfem/bin/python3`；LSF 和构建先 `module purge`，检查 `ifort`、`mpiifort`、`mpirun`，仅在其中任一缺失时以 `/share/apps/intel/oneapi_2023.1.0/setvars.sh --force` 补全环境，再加载 `hdf5/1.14.3_oneapi2023`。这使 control→mesher/solver 的继承环境无需重复 source。Python 必须为 3.11 或更新版本，并可导入 `numpy`、`h5py`。`deployment-check` 会检查这些依赖，不运行 bsub、mesher 或 solver。

在 Whale 的 package 根目录执行：

```bash
python3 scripts/production_cli.py validate
python3 scripts/production_cli.py preflight
python3 scripts/production_cli.py deployment-check
python3 scripts/production_cli.py build-template --reference-build /path/to/old/specfem3d_globe --inspect-only
python3 scripts/production_cli.py build-template --reference-build /path/to/old/specfem3d_globe --jobs 1
# 可选独立诊断；不是 submit/resume 门槛：
python3 scripts/production_cli.py asdf-smoke --source-dir .production_runtime/builds/<inherit>/source/specfem3d_globe
python3 scripts/production_cli.py render
python3 scripts/production_cli.py status
python3 scripts/production_cli.py materialize --rebuild-inactive
python3 scripts/production_cli.py deployment-check
python3 scripts/production_cli.py dry-run
python3 scripts/production_cli.py submit
```

`build-template` 仅读取旧 build 的 configure/module 证据，固定 checkout `ordeal97/ulvz_specfem` commit `72f0c39117df9395c12fa901a9ae99fa3e7bdfd9` 并重编 mesher；不复制旧二进制。归档成功 Aplus `Makefile` 将 `FLAGS_CHECK` 的 `-fpe0` 改为 `-fpe3`，而 `config.status` 的该变量是跨行值；新 build-template 会审计并只重放这一已验证的 Makefile override。Whale 离线时增加 `--source-tree /path/to/ulvz_specfem`，Git 树验证 HEAD；ZIP 解压树必须提供 `SOURCE_PROVENANCE.json` 和关键源码 SHA-256。源码先复制到独立 runtime 树，仍重新 configure，不复用旧 Makefile 或 header。`asdf-smoke` 可按需运行，报告仅作诊断，既不阻止 submit/resume，也不会由 control job 自动调用。已有 worktree 的旧 Makefile 不会被 LSF refresh 改写；`materialize --rebuild-inactive` 只接受 `NOT_SUBMITTED` 或 scratch 已清理的 `EXIT/QC_FAIL`，先移到 `.production_runtime/superseded_worktrees/` 再从新 template 创建。它拒绝活动、DONE 或 scratch 未清理 run。每 run control job 依序编 mesh、通过 mesher linkage 检查、提交 mesher、等待成功、按本 run 新 header 编 solver、检查 solver 的 ASDF/HDF5 linkage 后提交 solver。

查询进度：`python3 scripts/production_cli.py status`。`resume` 仅接管未完成/未提交项，不会自动重试失败 run。失败 run 会在所有已知 control/mesher/solver 作业终态、诊断保存完成后自动清理其精确 scratch 目录；提交身份未确认或 cleanup 失败会阻止继续提交。仅在审阅失败证据后执行 `python3 scripts/production_cli.py resume --run-id SRC001_B0` 显式重试。cleanup 默认预览：`python3 scripts/production_cli.py cleanup --run-id SRC001_B0`；执行使用 `python3 scripts/production_cli.py cleanup --run-id SRC001_B0 --execute`，它会取得 controller 锁并再次检查所有已知作业终态。

preflight hash 是 submit 硬门槛；config、manifest、template、DATA 或 rendered LSF 修改后必须重新 preflight。它也会审计已 materialize 的 worktree；submit 在 bsub 前再次验证全部 100 个 worktree。旧 worktree 可用 `materialize --refresh-lsf [--run-id RUN_ID]` 显式刷新三份 LSF，此操作不需要 build-template evidence，活动 run 会被拒绝刷新。`ulvz_normalized.csv` 与 0/3-body manifest、1530 ASDF traces、510 个固定 station identity、每站 E/N/Z、10 Hz、25400 npts、有限值和 matched B0 payload 都在 runtime QC 中检查。

仍需 deployment-time validation：Whale module/MPI、ASDF/HDF5 链接、384 rank/ptile=64 的 LSF host layout、scratch/共享文件系统、磁盘/内存配额以及真实 SPECFEM 输出。 
