# Canonical SPECFEM template

`DATA/Par_file` is the common six-chunk PREM configuration. Every rendered run must inherit it except LOCAL_PATH/LOCAL_TMP_PATH, CMTSOLUTION and ULVZ body data. Build the referenced source on Whale during deployment validation.

Whale runtime is frozen in `../config/production.toml`: `/share/home/yiy/.conda/envs/ulvz-specfem/bin/python3`, `/share/apps/intel/oneapi_2023.1.0/setvars.sh`, `hdf5/1.14.3_oneapi2023`, and `mpirun`. These settings are inherited from the A+ Whale package and are used by build-template and all rendered LSF jobs.
