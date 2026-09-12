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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    makefile = (reference / 'Makefile').read_text()
    for key, value in re.findall(r'^(\w+)\s*=\s*(.*?)\s*$', makefile, re.M):
        if key in VARIABLES and key in substitutions:
            if value != substitutions[key]:
                differences.append({'variable': key, 'configured': substitutions[key], 'makefile': value})
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
            'makefile_differences': differences, 'added_options': added, 'errors': errors}


def run_build(root, reference, inspect_only=False, jobs=1):
    if jobs < 1:
        raise ValueError('jobs must be positive')
    recipe = inspect_reference(reference)
    config = tomllib.loads((root / 'config/production.toml').read_text())
    recipe['source'] = config['source']
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
