import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch
from build_template import inspect_reference, run_build, _verify_local_source, SOURCE_COMMIT, SOURCE_REPOSITORY


class BuildTests(unittest.TestCase):
    def fixture(self, asdf=True):
        root = Path(tempfile.mkdtemp(prefix='build-inheritance-test-'))
        old = root / 'old build'
        old.mkdir()
        flags = ' --with-asdf' if asdf else ''
        (old / 'config.status').write_text("ac_cs_config='FC=gfortran CC=mpicc MPIFC=mpif90 --with-mpi" + flags + "'\nS[\"FC\"]=\"gfortran\"\n")
        (old / 'Makefile').write_text('FC = gfortran\n')
        (old / 'job.lsf').write_text('module load gcc/12\nbsub evil\n./bin/xmeshfem3D\n')
        return root, old

    def test_literal_read_only(self):
        _, old = self.fixture()
        before = {p.name: p.read_bytes() for p in old.iterdir()}
        result = inspect_reference(old)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['module_commands'], [['module', 'load', 'gcc/12']])
        self.assertEqual(before, {p.name: p.read_bytes() for p in old.iterdir()})

    def test_missing_asdf(self):
        _, old = self.fixture(False)
        self.assertIn('ASDF', ' '.join(inspect_reference(old)['errors']))

    def test_manual_makefile_change(self):
        _, old = self.fixture()
        (old / 'Makefile').write_text('FC = ifort\n')
        self.assertTrue(inspect_reference(old)['makefile_differences'])

    def test_expected_specfem_makefile_derivations_do_not_block(self):
        _, old = self.fixture()
        (old / 'config.status').write_text(
            'ac_cs_config=\'FC=gfortran CC=icc MPIFC=mpif90 CXXFLAGS="-g -O2" --with-mpi --with-asdf\'\n'
            'S["FC"]="gfortran"\nS["CC"]="icc"\nS["MPIFC"]="mpif90"\n'
            'S["CPPFLAGS"]=""\nS["CXXFLAGS"]="-g -O2"\nS["LDFLAGS"]=""\nS["MPICC"]="mpiicc"\n')
        (old / 'Makefile').write_text(
            'FC = gfortran\nCPPFLAGS = -I${SETUP}\nCXXFLAGS = -I${SETUP} -g -O2\n'
            'LDFLAGS =\nMPILIBS += $(LDFLAGS)\nCC = icc\nMPICC = $(CC)\nADIOS2 = no\n')
        result = inspect_reference(old)
        self.assertEqual(result['makefile_differences'], [])
        self.assertEqual(len(result['expected_makefile_differences']), 3)
        self.assertFalse(any('Makefile differs' in e for e in result['errors']))

    def test_unexplained_difference_still_blocks(self):
        _, old = self.fixture()
        (old / 'config.status').write_text('ac_cs_config=\'FC=gfortran CC=mpicc MPIFC=mpif90 --with-mpi --with-asdf\'\nS["FC"]="gfortran"\nS["CC"]="mpicc"\nS["MPIFC"]="mpif90"\n')
        (old / 'Makefile').write_text('FC = gfortran\nCC = wrong-cc\n')
        result = inspect_reference(old)
        self.assertTrue(result['makefile_differences'])
        self.assertIn('Makefile differs', ' '.join(result['errors']))

    def test_validated_aplus_fpe3_override_is_preserved(self):
        _, old = self.fixture()
        (old / 'config.status').write_text(
            'ac_cs_config=\'FC=ifort CC=icc MPIFC=mpiifort MPICC=mpiicc --with-asdf\'\n'
            'S["FC"]="ifort"\nS["CC"]="icc"\nS["MPIFC"]="mpiifort"\nS["MPICC"]="mpiicc"\n'
            'S["FLAGS_CHECK"]="-xHost -fpe0 "\\\n"-O3"\n')
        (old / 'Makefile').write_text(
            'FC = ifort\nCC = icc\nMPIFC = mpiifort\nMPICC = mpiicc\nFLAGS_CHECK = -xHost -fpe3 -O3\n')
        result = inspect_reference(old)
        self.assertEqual(result['makefile_differences'], [])
        self.assertEqual(result['required_makefile_overrides'], {'FLAGS_CHECK': '-xHost -fpe3 -O3'})

    def test_offline_archive_requires_and_checks_provenance(self):
        root = Path(tempfile.mkdtemp(prefix='offline-source-test-'))
        source = root / 'ulvz_specfem'
        (source / 'specfem3d_globe').mkdir(parents=True)
        key = source / 'specfem3d_globe/configure'
        key.write_text('pinned configure')
        import hashlib, json
        digest = hashlib.sha256(key.read_bytes()).hexdigest()
        (source / 'SOURCE_PROVENANCE.json').write_text(json.dumps({
            'repository': SOURCE_REPOSITORY, 'commit': SOURCE_COMMIT,
            'key_source_hashes': {'specfem3d_globe/configure': digest}}))
        with patch('build_template.subprocess.check_output', side_effect=subprocess.CalledProcessError(1, 'git')):
            _, evidence = _verify_local_source(source, SOURCE_COMMIT)
        self.assertEqual(evidence['mode'], 'offline_archive')
        key.write_text('tampered')
        with patch('build_template.subprocess.check_output', side_effect=subprocess.CalledProcessError(1, 'git')):
            with self.assertRaises(RuntimeError):
                _verify_local_source(source, SOURCE_COMMIT)

    def test_conflicting_modules(self):
        _, old = self.fixture()
        (old / 'other.sh').write_text('module load intel/19\n')
        self.assertIn('Conflicting', ' '.join(inspect_reference(old)['errors']))

    def test_mock_build_only_compiles(self):
        root, old = self.fixture()
        (root / 'config').mkdir()
        (root / 'config/production.toml').write_text('[paths]\nruntime_root=".production_runtime"\n[source]\nrepository="unused"\ncommit="' + SOURCE_COMMIT + '"\n[environment]\noneapi_setup="/setup.sh"\nmodules=["gcc/12"]\nmpi_launcher="mpirun"\n')
        data = root / 'specfem_template/DATA'
        data.mkdir(parents=True)
        for name in ('Par_file', 'CMTSOLUTION', 'STATIONS', 'ulvz_s40rts.par'):
            (data / name).write_text('canonical')
        calls = []

        def fake_run(argv, cwd=None, **kwargs):
            calls.append(argv)
            if argv[:2] == ['git', 'clone']:
                source = Path(argv[-1]) / 'specfem3d_globe'
                (source / 'DATA').mkdir(parents=True)
                (source / 'configure').touch()
                (source / 'Makefile').write_text('ASDF = yes\n')
                (source / 'bin').mkdir()
                binary = source / 'bin/xmeshfem3D'
                binary.write_text('mock binary')
                binary.chmod(0o755)
            if argv[0] == 'bash':
                return type('Result', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

        with patch('build_template.subprocess.run', side_effect=fake_run), patch('build_template.subprocess.check_output', return_value=SOURCE_COMMIT + '\n'):
            output = run_build(root, old)
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[-2][-4:], ['make', '-j', '1', 'meshfem3D'])
        self.assertEqual(calls[-1][0], 'bash')
        self.assertIn('ldd "$1"', calls[-1][2])
        self.assertNotIn('bsub', str(calls))
        self.assertNotIn('./bin/xmeshfem3D', str(calls))
        self.assertIn('BUILT_MESHER_ONLY', (output / 'build_manifest.json').read_text())

    def test_inspection_never_executes(self):
        root, old = self.fixture()
        (root / 'config').mkdir()
        (root / 'config/production.toml').write_text('[paths]\nruntime_root=".production_runtime"\n[source]\nrepository="unused"\ncommit="' + SOURCE_COMMIT + '"\n[environment]\noneapi_setup="/setup.sh"\nmodules=["gcc/12"]\nmpi_launcher="mpirun"\n')
        (root / 'specfem_template').mkdir()
        with patch('build_template.subprocess.run') as run:
            first = run_build(root, old, True)
            second = run_build(root, old, True)
            run.assert_not_called()
            self.assertNotEqual(first, second)
            self.assertTrue((first / 'build_manifest.json').is_file())


if __name__ == '__main__':
    unittest.main()
