import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from build_template import inspect_reference, run_build


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

    def test_conflicting_modules(self):
        _, old = self.fixture()
        (old / 'other.sh').write_text('module load intel/19\n')
        self.assertIn('Conflicting', ' '.join(inspect_reference(old)['errors']))

    def test_mock_build_only_compiles(self):
        root, old = self.fixture()
        (root / 'config').mkdir()
        (root / 'config/production.toml').write_text('[paths]\nruntime_root=".production_runtime"\n[source]\nrepository="unused"\ncommit="fixed"\n')
        data = root / 'specfem_template/DATA'
        data.mkdir(parents=True)
        for name in ('Par_file', 'CMTSOLUTION', 'STATIONS', 'ulvz_s40rts.par'):
            (data / name).write_text('canonical')
        calls = []

        def fake_run(argv, cwd, **kwargs):
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

        with patch('build_template.subprocess.run', side_effect=fake_run), patch('build_template.subprocess.check_output', return_value='fixed\n'):
            output = run_build(root, old)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[-1][-4:], ['make', '-j', '1', 'meshfem3D'])
        self.assertNotIn('bsub', str(calls))
        self.assertNotIn('./bin/xmeshfem3D', str(calls))
        self.assertIn('BUILT_MESHER_ONLY', (output / 'build_manifest.json').read_text())

    def test_inspection_never_executes(self):
        root, old = self.fixture()
        (root / 'config').mkdir()
        (root / 'config/production.toml').write_text('[paths]\nruntime_root=".production_runtime"\n[source]\nrepository="unused"\ncommit="fixed"\n')
        (root / 'specfem_template').mkdir()
        with patch('build_template.subprocess.run') as run:
            first = run_build(root, old, True)
            second = run_build(root, old, True)
            run.assert_not_called()
            self.assertNotEqual(first, second)
            self.assertTrue((first / 'build_manifest.json').is_file())


if __name__ == '__main__':
    unittest.main()
