# Aplus → PREM 运行链审计（2026-09-13）

本审计仅比较构建、链接和运行架构；不改变 100-run 的科学输入、six-chunk、384 ranks、stage barrier 或 scratch 生命周期。

## 已确认的 required parity

| 项目 | Aplus 已验证证据 | PREM 要求 |
|---|---|---|
| 编译器 | `ifort` / `icc` / `mpiifort` / `mpiicc` | 由 reference `config.status` 继承并在 Makefile 中审计 |
| oneAPI | `oneapi_2023.1.0/setvars.sh` | 幂等初始化后检查 `ifort`、`mpiifort`、`mpirun` |
| HDF5 | module `hdf5/1.14.3_oneapi2023`；ASDF 链接 `/share/apps/hdf5/1.14.3_oneapi2023.1/lib` | 同一 module；实际 `ldd` 必须没有 unresolved library |
| ASDF | `--with-asdf`，`libasdf` + HDF5 Fortran/high-level libraries | `ldd` 必须解析 HDF5 且无缺库；`libasdf` 可静态链接，因此以 `asdf_initialize_hdf5_f` 符号确认 ASDF |
| 浮点异常 | `config.status` 是 `-fpe0`，但归档成功 `Makefile` 的唯一手工差异为 `-fpe3` | configure 后只重放此已验证 override |
| 输出证据 | Aplus `SRC01_B0` 完整完成，ASDF 有 510 traces × 25400 samples | PREM 保持 ASDF runtime QC 的 1530 traces、510 stations、25400 samples |

成功 Aplus `Makefile` 与 `Makefile.before_fpe3` 的唯一差异是 `FLAGS_CHECK` 中 `-fpe0` 改为 `-fpe3`。PREM 原 build-template 未解析跨行 `FLAGS_CHECK` substitution，也未在 configure 后重放该 override。现有 Whale failure 在首次 `ASDF_initialize_hdf5_f` 处出现 HDF5 native-float initialization 和 `SIGFPE`，与这个 FPE-mode parity regression 一致。

这已足以将缺失 `-fpe3` 定义为修复对象；ASDF smoke 保留为可选的独立诊断，正式生产门禁改由 HDF5 linkage 与 ASDF 初始化符号审计承担。

## intentional differences

- PREM 使用 PREM、three sectors、510 stations、`NCHUNKS=6`、384 ranks 和 B0→TRIULVZ barrier；这些不是 Aplus two-chunk 运行错误。
- 本包的物理参数以冻结 `Par_file` 为准，未因 Aplus 对比而改写。
- 每个 PREM run 仍在自己的 worktree 内编 solver，以使用该 run 的新 mesher header。

## non-blocking

- mesher 未必直接保留 `libasdf` dynamic dependency；其 linkage audit 只拒绝 `not found`。solver linkage audit 必须解析 HDF5 并找到 ASDF 初始化符号。
- configure 中 Makefile.in 正常产生的 `CPPFLAGS/CXXFLAGS` 前缀和 `ADIOS2=no` 时 `MPICC=$(CC)` 继续仅作为 expected difference。

## unresolved / deployment-time validation

- 在 Whale 上运行 `deployment-check`、build-template 后，检查 build manifest、effective Makefile 和 linkage audit；`asdf-smoke` 可按需运行，历史 `.production_runtime/asdf_smoke/` 记录不构成生产门槛。
- 检查 build manifest 的 compiler、effective Makefile flags、`xmeshfem3D` ldd；每个 control job 还会记录 mesher/solver linkage JSON。
- ASDF smoke 只覆盖 serial initialize/create/close/finalize，不覆盖 384-rank mesh、solver 数值稳定性、完整 1530-trace 写出或 QC。

## 提交前命令

```bash
python scripts/production_cli.py deployment-check
python scripts/production_cli.py build-template --reference-build /share/home/yiy/ulvz/database_r1_Aplus/specfem0 --source-tree /path/to/ulvz_specfem --jobs 1
# 可选独立诊断：python scripts/production_cli.py asdf-smoke --source-dir .production_runtime/builds/<inherit>/source/specfem3d_globe
python scripts/production_cli.py materialize
python scripts/production_cli.py submit
```

`submit` 与 `resume` 不读取 ASDF smoke 结果；per-run control 也不自动运行该 probe。solver build 后仍强制检查 `xspecfem3D` 的 HDF5 linkage 与 ASDF 初始化符号。
