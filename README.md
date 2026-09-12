# PREM three-sector 50-source Whale production package

独立、可搬运的 PREM 三扇区 100-run Whale production package：50 个 source、510 stations、50 个 B0 (`N_ULVZ=0`) 与 50 个 TRIULVZ (`N_ULVZ=3`)。它包含冻结输入、LSF、运行控制、QC 和恢复工具；当前没有生产 mesh、DATABASES_MPI 或波形结果。

完整科学与操作说明见 [中文完整文档](PREM_ThreeSector_50Source_full_documentation_zh.md) 和 [运行手册](PRODUCTION_RUNBOOK_zh.md)。首先审阅 [母包](specfem_template/)、[全部 run 参数总表](preflight/all_runs_parameter_audit.csv) 和 [preflight 报告](preflight/PREFLIGHT_REPORT.md)。

## 在 Whale 继承旧版本编译方法

先只读检查旧的已编译 SPECFEM 目录（也支持其父目录）：

```bash
python scripts/production_cli.py build-template --reference-build /path/to/old/specfem3d_globe --inspect-only
python scripts/production_cli.py build-template --reference-build /path/to/old/specfem3d_globe --jobs 4
```

Whale 无法访问 GitHub 时，提供本地源码树；该树必须是固定 commit，或无 `.git` 时包含经校验的 `SOURCE_PROVENANCE.json`：

```bash
python scripts/production_cli.py build-template \
  --reference-build /share/home/yiy/ulvz/database_r1_Aplus/specfem0 \
  --source-tree /path/to/ulvz_specfem --jobs 1
```

离线源码会先验证 commit/provenance 与关键源码 SHA-256，再复制到独立 runtime 树。原目录不会被修改；程序仍重新 configure 并编译 `meshfem3D`，不会复用旧的 Makefile、二进制或 mesher header。若 reference Makefile 出现 SPECFEM 正常生成的 `-I${SETUP}`、`MPICC=$(CC)`（ADIOS2=no）等差异，它们会进入审计但不阻断；其他未知差异仍阻断。

第二条命令才会下载 config 中固定 commit 的源码，重新 configure 并编译 `meshfem3D`；不执行 mesher、solver 或 bsub。不复制旧二进制、Makefile 或 mesher header；公共 DATA 来自 `specfem_template`。

自动读取 `config.status` 的 configure 参数，并核对 Makefile 中可识别的编译变量；只从旧目录顶层 `.sh`/`.lsf` 读取简单 module 命令，不执行旧脚本。复杂模块初始化、手工 Makefile 修改、无法恢复的参数需要人工处理。旧构建未启用 ASDF 时，仅在有 ASDF_LIBS 证据时补加 `--with-asdf`，否则拒绝构建。不会安装依赖或自动换编译器。请在与旧构建相同的 Whale 环境中执行，并检查继承报告中的 module 顺序和依赖路径。

每次在 `.production_runtime/builds/inherit-*` 新目录留下 `BUILD_INHERITANCE.md`、`build_manifest.json` 和构建日志；不覆盖旧构建，也不改变冻结输入。`--inspect-only` 通过只代表配置可解析，不代表依赖可用。真实编译和链接必须在 Whale 验证。solver 仍须在各 run 独立工作树中、mesher 产生新 header 后编译；报告中的 solver_recipe 仅记录此后步骤，不能提前共享 solver。

`submit` 在 Whale 上通过一个静态 control LSF 作业启动唯一的生产 controller；它只在 preflight 未过期、已 materialize、worktree 与冻结 DATA/LSF 一致且 `bsub` 可用时执行。`mock-submission` 是内存状态机测试：验证 100 个 run、并发上限 2 和 B0→TRIULVZ barrier，但不替代 Whale 的真实 LSF/mesher/solver 验证。

Whale 依赖已冻结为 A+ 运行 profile：oneAPI 2023.1.0、`hdf5/1.14.3_oneapi2023`、`mpirun` 和 `/share/home/yiy/.conda/envs/ulvz-specfem/bin/python3`。环境初始化先检查 `ifort`、`mpiifort`、`mpirun`；只有缺失时才以 `setvars.sh --force` 补全，因此继承的 oneAPI 环境不会重复初始化失败。运行 `deployment-check` 验证实际节点环境后，才允许 build/materialize/submit。
