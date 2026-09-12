# Whale 生产运行手册

本包已冻结科学设计与 100 份 DATA/LSF；未调用 bsub、mesher 或 solver。生产控制器只允许两个 active run，且必须先使 50 个 B0 全部 `DONE + output_qc=PASS`，才解锁 50 个 TRIULVZ。

Whale 运行环境已继承 A+ package：控制 Python 为 `/share/home/yiy/.conda/envs/ulvz-specfem/bin/python3`；LSF 和构建先加载 `/share/apps/intel/oneapi_2023.1.0/setvars.sh`，再加载 `hdf5/1.14.3_oneapi2023`，以 `mpirun` 运行 MPI。Python 必须为 3.11 或更新版本，并可导入 `numpy`、`h5py`。`deployment-check` 会检查这些依赖，不运行 bsub、mesher 或 solver。

在 Whale 的 package 根目录执行：

```bash
python3 scripts/production_cli.py validate
python3 scripts/production_cli.py preflight
python3 scripts/production_cli.py deployment-check
python3 scripts/production_cli.py build-template --reference-build /path/to/old/specfem3d_globe --inspect-only
python3 scripts/production_cli.py build-template --reference-build /path/to/old/specfem3d_globe --jobs 1
python3 scripts/production_cli.py render
python3 scripts/production_cli.py materialize
python3 scripts/production_cli.py deployment-check
python3 scripts/production_cli.py dry-run
python3 scripts/production_cli.py submit
```

`build-template` 仅读取旧 build 的 configure/module 证据，固定 checkout `ordeal97/ulvz_specfem` commit `72f0c39117df9395c12fa901a9ae99fa3e7bdfd9` 并重编 mesher；不复制旧二进制。Whale 离线时增加 `--source-tree /path/to/ulvz_specfem`，Git 树验证 HEAD；ZIP 解压树必须提供 `SOURCE_PROVENANCE.json` 和关键源码 SHA-256。源码先复制到独立 runtime 树，仍重新 configure，不复用旧 Makefile 或 header。materialize 为每个 run 创建独立可写源树、DATA、obj/bin 和 LSF。每 run control job 依序编 mesh、提交 mesher、等待成功、按本 run 新 header 编 solver、提交 solver。

查询进度：`python3 scripts/production_cli.py status`。`resume` 仅接管未完成/未提交项，不会自动重试失败 run。仅在确认无活动作业、审阅失败证据后执行 `python3 scripts/production_cli.py resume --run-id SRC001_B0` 显式重试。QC PASS 后可先预览 cleanup：`python3 scripts/production_cli.py cleanup --run-id SRC001_B0`；没有 `--execute` 不会删除任何内容。若要执行，直接调用 `cleanup_scratch.py --execute`，且只允许 `DONE + output_qc PASS`。

preflight hash 是 submit 硬门槛；config、manifest、template、DATA 或 rendered LSF 修改后必须重新 preflight。`ulvz_normalized.csv` 与 0/3-body manifest、1530 ASDF traces、510 stations、10 Hz、25400 npts、有限值和 matched B0 payload 都在 runtime QC 中检查。EXIT/QC_FAIL 永不自动 cleanup。

仍需 deployment-time validation：Whale module/MPI、ASDF/HDF5 链接、384 rank/ptile=64 的 LSF host layout、scratch/共享文件系统、磁盘/内存配额以及真实 SPECFEM 输出。 
