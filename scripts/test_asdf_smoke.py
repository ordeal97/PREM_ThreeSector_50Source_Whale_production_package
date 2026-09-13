import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import asdf_smoke
import linkage_audit
import production_cli
from production_common import ROOT, load_config


class AsdfSmokeTests(unittest.TestCase):
    def source(self, root, flags='-fpe3'):
        source = root / 'source'
        source.mkdir()
        (source / 'Makefile').write_text(
            'ASDF = yes\nMPIFC = mpiifort\nFCLINK = $(MPIFCCOMPILE_CHECK)\n'
            f'FLAGS_CHECK = -xHost {flags}\nMPILIBS = -lasdf -lhdf5\nLDFLAGS =\nLIBS =\n')
        return source

    def test_static_gate_requires_validated_fpe3(self):
        root = Path(tempfile.mkdtemp())
        report = asdf_smoke.run(self.source(root, '-fpe0'), root / 'out')
        self.assertEqual(report['status'], 'FAIL')
        self.assertIn('lacks validated A+ -fpe3', ' '.join(report['errors']))
        self.assertTrue((root / 'out' / 'summary.json').is_file())

    def test_mock_compile_and_run_produces_pass_summary(self):
        root = Path(tempfile.mkdtemp())
        source = self.source(root)
        calls = []
        def fake_run(argv, cwd, **kwargs):
            calls.append(argv)
            if argv[0] == 'make':
                binary = Path(cwd) / 'asdf_hdf5_smoke'
                binary.write_text('mock'); binary.chmod(0o755)
            else:
                (Path(cwd) / 'asdf_smoke.h5').write_bytes(b'hdf5')
            return type('Result', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
        with patch('asdf_smoke.subprocess.run', side_effect=fake_run):
            report = asdf_smoke.run(source, root / 'out', 'config-hash')
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['config_hash'], 'config-hash')
        self.assertEqual(calls[0][:3], ['make', '-f', 'Makefile'])
        self.assertEqual(calls[1][0], str(root / 'out' / 'asdf_hdf5_smoke'))

    def test_linkage_requires_asdf_and_hdf5(self):
        binary = Path(tempfile.mkdtemp()) / 'xspecfem3D'
        binary.write_text('mock')
        with patch('linkage_audit.subprocess.run', return_value=type('Result', (), {'returncode': 0, 'stdout': 'libasdf.so\nlibhdf5.so\n', 'stderr': ''})()):
            self.assertEqual(linkage_audit.inspect(binary, True)['status'], 'PASS')
        with patch('linkage_audit.subprocess.run', return_value=type('Result', (), {'returncode': 0, 'stdout': 'libmpi.so\n', 'stderr': ''})()):
            self.assertEqual(linkage_audit.inspect(binary, True)['status'], 'FAIL')

    def test_submit_gate_requires_fresh_smoke_for_pinned_commit(self):
        root = Path(tempfile.mkdtemp())
        cfg = load_config(ROOT / 'config/production.toml')
        cfg['paths']['runtime_root'] = root
        summary = root / 'asdf_smoke' / 'summary.json'
        summary.parent.mkdir()
        summary.write_text(json.dumps({'status': 'PASS', 'config_hash': production_cli.digest(ROOT / 'config/production.toml'),
                                       'source_commit': cfg['source']['commit']}))
        production_cli.asdf_smoke_gate(cfg)
        summary.write_text(json.dumps({'status': 'PASS', 'config_hash': 'stale', 'source_commit': cfg['source']['commit']}))
        with self.assertRaises(RuntimeError):
            production_cli.asdf_smoke_gate(cfg)


if __name__ == '__main__':
    unittest.main()
