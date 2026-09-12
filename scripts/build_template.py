"""Read-only build inheritance; never execute scripts from the reference tree."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib

VARIABLES = {'FC', 'CC', 'CXX', 'MPIFC', 'MPICC', 'FCFLAGS', 'CFLAGS',
             'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'LIBS', 'ASDF_LIBS',
             'HDF5_LIBS', 'HDF5_INC', 'HDF5_FCFLAGS'}
SOURCE_COMMIT = '72f0c39117df9395c12fa901a9ae99fa3e7bdfd9'
SOURCE_REPOSITORY = 'git@github.com:ordeal97/ulvz_specfem.git'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_assignments(text):
    """Parse only single physical make lines; never let whitespace cross a line."""
    return {key: value.strip() for key, value in re.findall(
        r'^(?P<key>[A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(?P<value>[^\r\n]*)$',
        text, re.M)}


def _makefile_differences(makefile, substitutions):
    assignments = _make_assignments(makefile)
    expected, blocking = [], []
    for key, configured in substitutions.items():
        if key not in VARIABLES or key not in assignments:
            continue
        actual = assignments[key]
        reason = None
        if key in {'CPPFLAGS', 'CXXFLAGS'} and actual == ('-I${SETUP}' + ((' ' + configured) if configured else '')):
            reason = 'SPECFEM Makefile.in prepends -I${SETUP}'
        elif key == 'MPICC' and actual == '$(CC)' and assignments.get('ADIOS2') == 'no' and assignments.get('CC') == substitutions.get('CC'):
            reason = 'SPECFEM Makefile.in derives MPICC=$(CC) when ADIOS2=no'
        item = {'variable': key, 'configured': configured, 'makefile': actual}
        if reason:
            item['reason'] = reason
            expected.append(item)
        elif actual != configured:
            blocking.append(item)
    return expected, blocking


def inspect_reference(reference):
    reference = reference.resolve(strict=True)
    if not (reference / 'config.status').is_file():
        reference = reference / 'specfem3d_globe'
    status = (reference / 'config.status').read_text()
    match = re.search(r'^ac_cs_config=(.*)$', status, re.M)
    if not match:
        raise ValueError('Cannot recover ac_cs_config from config.status')
    outer = shlex.split(match[1])
    if len(outer) != 1:
        raise ValueError('Unsupported multiline configure invocation')
    args = shlex.split(outer[0])
    variables, options, errors = {}, [], []
    for arg in args:
        key, sep, value = arg.partition('=')
        if key in VARIABLES and sep:
            variables[key] = value
        elif arg.startswith('--'):
            if key in {'--srcdir', '--prefix', '--exec-prefix', '--cache-file'}:
                errors.append('Relocation-sensitive option needs manual review: ' + arg)
            options.append(arg)
        else:
            errors.append('Unsupported configure argument: ' + arg)
    substitutions = dict(re.findall(r'^S\["(\w+)"\]="([^"\n]*)"$', status, re.M))
    for key in VARIABLES:
        if key not in variables and substitutions.get(key):
            variables[key] = substitutions[key]
    differences = []
    expected_differences = []
    makefile = (reference / 'Makefile').read_text()
    expected_differences, differences = _makefile_differences(makefile, substitutions)
    if differences:
        errors.append('Makefile differs from configure substitutions; manual review required')
    modules = []
    module_sequences = []
    evidence = {}
    # Only inspect direct, recognizable build/job scripts; no recursive search.
    for path in sorted(reference.iterdir()):
        if path.is_file() and (path.name in {'config.status', 'config.log', 'Makefile'} or path.suffix in {'.sh', '.lsf'}):
            evidence[path.name] = sha(path)
            if path.suffix in {'.sh', '.lsf'}:
                sequence = []
                for line in path.read_text(errors='replace').splitlines():
                    line = line.strip()
                    if line.startswith('module '):
                        tokens = shlex.split(line, comments=True)
                        if len(tokens) >= 2 and tokens[1] in {'purge', 'load', 'unload', 'swap'} and all(re.fullmatch(r'[A-Za-z0-9_./+:-]+', x) for x in tokens):
                            sequence.append(tokens)
                        else:
                            errors.append('Unsupported module command: ' + line)
                if sequence and sequence not in module_sequences:
                    module_sequences.append(sequence)
    if len(module_sequences) > 1:
        errors.append('Conflicting module sequences in reference scripts; manual review required')
    elif module_sequences:
        modules = module_sequences[0]
    # Missing explicit compiler selection is not permission to guess a toolchain.
    for key in ('FC', 'CC', 'MPIFC'):
        value = variables.get(key, substitutions.get(key, ''))
        if not value:
            errors.append('Missing compiler evidence: ' + key)
        else:
            variables[key] = value
    if any(x in options for x in ('--without-mpi', '--with-mpi=no')):
        errors.append('Reference disables MPI')
    added = []
    if not any(x in options for x in ('--with-asdf', '--with-asdf=yes')):
        if variables.get('ASDF_LIBS') or substitutions.get('ASDF_LIBS'):
            options = [x for x in options if not x.startswith('--with-asdf') and x != '--without-asdf']
            options.append('--with-asdf')
            variables['ASDF_LIBS'] = variables.get('ASDF_LIBS') or substitutions['ASDF_LIBS']
            added.append('--with-asdf')
        else:
            errors.append('ASDF is not enabled and no ASDF_LIBS evidence exists; provide an ASDF-enabled reference build')
    return {'reference': str(reference), 'options': options, 'variables': variables,
            'module_commands': modules, 'evidence_hashes': evidence,
            'makefile_differences': differences,
            'expected_makefile_differences': expected_differences,
            'added_options': added, 'errors': errors}


def _source_root(path):
    path = Path(path).resolve(strict=True)
    if (path / 'specfem3d_globe' / 'configure').is_file():
        return path
    if (path / 'configure').is_file() and path.name == 'specfem3d_globe':
        return path.parent
    raise RuntimeError('source-tree must contain specfem3d_globe/configure')


def _verify_local_source(path, expected_commit):
    source_root = _source_root(path)
    git_root = None
    try:
        git_root = Path(subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', '--show-toplevel'], text=True, stderr=subprocess.DEVNULL).strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    if git_root:
        head = subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], text=True).strip()
        if head != expected_commit:
            raise RuntimeError(f'Offline source commit mismatch: {head} != {expected_commit}')
        return source_root, {'mode': 'offline_git', 'verified_commit': head}
    provenance = source_root / 'SOURCE_PROVENANCE.json'
    if not provenance.is_file():
        raise RuntimeError('Offline source without .git requires SOURCE_PROVENANCE.json')
    data = json.loads(provenance.read_text())
    if data.get('repository') != SOURCE_REPOSITORY or data.get('commit') != expected_commit:
        raise RuntimeError('Offline SOURCE_PROVENANCE.json repository/commit mismatch')
    hashes = data.get('key_source_hashes')
    if not isinstance(hashes, dict) or not hashes:
        raise RuntimeError('Offline SOURCE_PROVENANCE.json must include key_source_hashes')
    for rel, expected in hashes.items():
        rel_path = Path(rel)
        if rel_path.is_absolute() or '..' in rel_path.parts:
            raise RuntimeError(f'Offline source key path escapes source tree: {rel}')
        target = source_root / rel_path
        if not target.is_file() or sha(target) != expected:
            raise RuntimeError(f'Offline source key hash mismatch: {rel}')
    return source_root, {'mode': 'offline_archive', 'verified_commit': expected_commit, 'key_source_hashes': hashes}


def _copy_clean_source(source_root, destination):
    ignored = {'bin', 'obj', 'DATABASES_MPI', 'OUTPUT_FILES', 'Makefile', 'config.status', 'config.log', 'values_from_mesher.h'}
    def ignore(_directory, names):
        return {name for name in names if name in ignored or name == '.git'}
    shutil.copytree(source_root, destination, ignore=ignore)


def run_build(root, reference, inspect_only=False, jobs=1, source_tree=None):
    if jobs < 1:
        raise ValueError('jobs must be positive')
    recipe = inspect_reference(reference)
    config = tomllib.loads((root / 'config/production.toml').read_text())
    recipe['source'] = config['source']
    if recipe['source'].get('commit') != SOURCE_COMMIT:
        raise RuntimeError('production.toml source commit is not the validated multi-ULVZ commit')
    environment = config['environment']
    recipe['canonical_environment'] = environment
    expected_loads = {f'module load {item}' for item in environment['modules']}
    reference_loads = {' '.join(item) for item in recipe['module_commands'] if len(item) >= 3 and item[1] == 'load'}
    incompatible = sorted(reference_loads - expected_loads)
    if incompatible:
        recipe['errors'].append('Reference module load conflicts with frozen Whale environment: ' + ', '.join(incompatible))
    template = root / 'specfem_template'
    recipe['template_hashes'] = {str(p.relative_to(template)): sha(p) for p in sorted(template.rglob('*')) if p.is_file()}
    runtime = root / config['paths']['runtime_root'] / 'builds'
    runtime.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='inherit-', dir=runtime))
    recipe['status'] = 'BLOCKED' if recipe['errors'] else 'INSPECTED'
    recipe['solver_status'] = 'PENDING_RUN_SPECIFIC_MESHER_HEADER'
    recipe['commands'] = []
    recipe['source_mode'] = 'offline' if source_tree else 'github_clone'

    def save():
        (output / 'build_manifest.json').write_text(json.dumps(recipe, indent=2) + '\n')
        (output / 'BUILD_INHERITANCE.md').write_text(
            '# 编译继承审计\n\n状态：' + recipe['status'] + '\n\n'
            '旧目录只读；不执行旧脚本，不复用旧二进制或 mesher header。\n\n'
            + '\n'.join('- ' + e for e in recipe['errors']) + '\n\n详见 build_manifest.json。\n')

    save()
    print(output)
    if recipe['errors']:
        raise RuntimeError('; '.join(recipe['errors']))
    if inspect_only:
        return output

    def execute(argv, cwd, environment=False):
        recipe['commands'].append(argv)
        save()
        if environment:
            setup = '\n'.join(['module purge',
                f'if [[ -z "${{I_MPI_ROOT:-}}" ]] || ! command -v mpiifort >/dev/null 2>&1; then source "{recipe["canonical_environment"]["oneapi_setup"]}"; fi',
                *[f'module load {item}' for item in recipe['canonical_environment']['modules']]])
            argv = ['bash', '-lc', 'set -e\n' + setup + '\nexec "$@"', 'build-template', *argv]
        with (output / 'build.log').open('a') as log:
            subprocess.run(argv, cwd=cwd, check=True, stdout=log, stderr=subprocess.STDOUT)

    try:
        checkout = output / 'source'
        if source_tree:
            verified_root, source_evidence = _verify_local_source(source_tree, recipe['source']['commit'])
            _copy_clean_source(verified_root, checkout)
            recipe.update(source_evidence)
        else:
            execute(['git', 'clone', '--no-checkout', recipe['source']['repository'], str(checkout)], output)
            execute(['git', 'checkout', '--detach', recipe['source']['commit']], checkout)
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip()
            if head != recipe['source']['commit']:
                raise RuntimeError('Source commit mismatch')
            recipe['verified_commit'] = head
        source = checkout / 'specfem3d_globe'
        if not (source / 'configure').is_file():
            raise RuntimeError('Pinned source lacks specfem3d_globe/configure')
        for name in ('Par_file', 'CMTSOLUTION', 'STATIONS', 'ulvz_s40rts.par'):
            shutil.copyfile(template / 'DATA' / name, source / 'DATA' / name)
        # Pass arguments literally: neither configure values nor old scripts are shell code.
        execute(['./configure', *recipe['options'], *[k + '=' + v for k, v in recipe['variables'].items()]], source, True)
        configured = (source / 'Makefile').read_text()
        if not re.search(r'^ASDF\s*=\s*yes\s*$', configured, re.M):
            raise RuntimeError('Configured build does not enable ASDF')
        execute(['make', '-j', str(jobs), 'meshfem3D'], source, True)
        binary = source / 'bin/xmeshfem3D'
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError('Build did not produce executable xmeshfem3D')
        recipe['mesher'] = str(binary)
        recipe['mesher_hash'] = sha(binary)
        recipe['solver_recipe'] = {'cwd': str(source), 'argv': ['make', '-j', str(jobs), 'specfem3D'],
                                   'requires': 'Isolated per-run tree with fresh values_from_mesher.h; never share across active runs'}
        recipe['status'] = 'BUILT_MESHER_ONLY'
    except Exception as exc:
        recipe['status'] = 'BUILD_FAILED'
        recipe['errors'].append(str(exc))
        raise
    finally:
        save()
    return output
