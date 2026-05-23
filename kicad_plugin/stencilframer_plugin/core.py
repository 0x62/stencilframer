import contextlib
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


GERBER_EXTENSIONS = ('.gbr', '.ger', '.gtp', '.gbp', '.gts', '.gbs')
PREFERENCE_DEFAULTS = {
    'offset': '0.15',
    'stencil_offset': '0.1',
    'fill_voids': True,
    'min_void_area': '15',
    'side': 'front',
    'lift_hole_position': 'auto',
    'openscad_path': '',
    'openscad_custom': False,
}


def repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def stencilframer_script_path():
    env_path = os.environ.get('STENCILFRAMER_SCRIPT')
    candidates = []
    if env_path:
        candidates.append(env_path)
    candidates.extend([
        os.path.join(os.path.dirname(__file__), 'stencilframer.py'),
        os.path.join(repo_root(), 'stencilframer.py'),
        os.path.join(os.getcwd(), 'stencilframer.py'),
    ])

    for path in candidates:
        if path and os.path.isfile(path):
            return path

    raise ValueError('Could not find stencilframer.py; set STENCILFRAMER_SCRIPT to its full path')


def default_output_path(board_path):
    project_dir = os.path.dirname(os.path.abspath(board_path)) if board_path else os.getcwd()
    return os.path.join(project_dir, 'stencil_frame.stl')


def default_preferences():
    return dict(PREFERENCE_DEFAULTS)


def preferences_dir():
    env_dir = os.environ.get('STENCILFRAMER_CONFIG_DIR')
    if env_dir:
        return env_dir

    home = os.path.expanduser('~')
    if sys.platform == 'darwin':
        base = os.path.join(home, 'Library', 'Application Support')
    elif sys.platform.startswith('win'):
        base = os.environ.get('APPDATA') or os.path.join(home, 'AppData', 'Roaming')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(home, '.config')

    return os.path.join(base, 'stencilframer-kicad-plugin')


def preferences_path(config_dir=None):
    if config_dir is None:
        config_dir = preferences_dir()
    return os.path.join(config_dir, 'preferences.json')


def load_preferences(path=None):
    prefs = default_preferences()
    if path is None:
        path = preferences_path()

    try:
        with open(path, 'r') as fin:
            saved = json.load(fin)
    except Exception:
        return prefs

    if isinstance(saved, dict):
        for key in prefs:
            if key in saved:
                prefs[key] = saved[key]
    return prefs


def save_preferences(prefs, path=None):
    saved = default_preferences()
    for key in saved:
        if key in prefs:
            saved[key] = prefs[key]

    if path is None:
        path = preferences_path()

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, 'w') as fout:
        json.dump(saved, fout, indent=2, sort_keys=True)
        fout.write('\n')
    return path


def _extract_block(text, block_name):
    start = text.find('({}'.format(block_name))
    if start < 0:
        return None

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return text[start:index+1]
    return None


def detect_pcb_thickness(board_path, default=1.6):
    try:
        with open(board_path, 'r') as fin:
            contents = fin.read()
    except OSError:
        return default

    for block_name in ('general', 'stackup', 'setup'):
        block = _extract_block(contents, block_name)
        if block is None:
            continue
        match = re.search(r'\(thickness\s+([-+]?[0-9]*\.?[0-9]+)\)', block)
        if match:
            return float(match.group(1))

    return default


def is_gerber_file(path):
    return path.lower().endswith(GERBER_EXTENSIONS)


def gerber_sort_key(name):
    base = os.path.basename(name).lower()
    score = 0
    if 'paste' in base:
        score -= 20
    if 'stencil' in base:
        score -= 10
    if base.endswith(('.gtp', '.gbp')):
        score -= 5
    return (score, base)


def extract_gerber_from_zip(zip_path):
    temp_dir = tempfile.mkdtemp(prefix='stencilframer_')
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            candidates = [
                    name for name in archive.namelist()
                    if not name.endswith('/') and is_gerber_file(name)
                    ]
            if not candidates:
                raise ValueError('No Gerber file found inside selected zip file')

            selected = sorted(candidates, key=gerber_sort_key)[0]
            out_path = os.path.join(temp_dir, os.path.basename(selected))
            with archive.open(selected) as fin, open(out_path, 'wb') as fout:
                fout.write(fin.read())
        return out_path, temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def resolve_stencil_input(path):
    if not path:
        raise ValueError('Select a Gerber or zip file')

    if path.lower().endswith('.zip'):
        return extract_gerber_from_zip(path)

    if not is_gerber_file(path):
        raise ValueError('Select a Gerber file or a zip file containing a Gerber file')

    return path, None


def find_openscad():
    return shutil.which('openscad') or shutil.which('OpenSCAD')


def stencilframer_argv(board_path, stencil_path, output_path, openscad_path=None, offset=None, stencil_offset=None, fill_voids=False, min_void_area=None, mirror=False, lift_hole_position=None, pcb_thickness=None, script_path=None):
    if script_path is None:
        script_path = stencilframer_script_path()

    argv = [
            script_path,
            '--stencil-file',
            stencil_path,
            ]
    if openscad_path:
        argv.extend(['--openscad', openscad_path])
    if mirror:
        argv.append('--mirror')
    if offset is not None:
        argv.extend(['--offset', str(offset)])
    if stencil_offset is not None:
        argv.extend(['--stencil-offset', str(stencil_offset)])
    if lift_hole_position:
        argv.extend(['--lift-hole-position', str(lift_hole_position)])
    if pcb_thickness is not None:
        argv.extend(['--pcb-thickness', str(pcb_thickness)])
    if fill_voids:
        argv.append('--fill-voids')
        if min_void_area is not None:
            argv.extend(['--min-void-area', str(min_void_area)])
    argv.extend([board_path, output_path])
    return argv


def build_stencilframer_command(board_path, stencil_path, output_path, openscad_path=None, offset=None, stencil_offset=None, fill_voids=False, min_void_area=None, mirror=False, lift_hole_position=None, pcb_thickness=None, script_path=None, python_executable=None):
    if python_executable is None:
        python_executable = sys.executable
    cmd = [python_executable]
    cmd.extend(stencilframer_argv(
            board_path,
            stencil_path,
            output_path,
            openscad_path=openscad_path,
            offset=offset,
            stencil_offset=stencil_offset,
            fill_voids=fill_voids,
            min_void_area=min_void_area,
            mirror=mirror,
            lift_hole_position=lift_hole_position,
            pcb_thickness=pcb_thickness,
            script_path=script_path))
    return cmd


def run_stencilframer(board_path, stencil_path, output_path, openscad_path=None, offset=None, stencil_offset=None, fill_voids=False, min_void_area=None, mirror=False, lift_hole_position=None, pcb_thickness=None, script_path=None):
    argv = stencilframer_argv(
            board_path,
            stencil_path,
            output_path,
            openscad_path=openscad_path,
            offset=offset,
            stencil_offset=stencil_offset,
            fill_voids=fill_voids,
            min_void_area=min_void_area,
            mirror=mirror,
            lift_hole_position=lift_hole_position,
            pcb_thickness=pcb_thickness,
            script_path=script_path)
    script_path = argv[0]

    stdout = io.StringIO()
    old_argv = sys.argv[:]
    module_name = '_stencilframer_plugin_runner'
    root_logger = logging.getLogger()
    old_handlers = list(root_logger.handlers)
    old_level = root_logger.level
    old_basic_config = logging.basicConfig
    capture_handler = logging.StreamHandler(stdout)

    def plugin_basic_config(**kwargs):
        level = kwargs.get('level')
        if level is not None:
            root_logger.setLevel(level)
        fmt = kwargs.get('format')
        datefmt = kwargs.get('datefmt')
        style = kwargs.get('style', '%')
        if fmt is not None:
            capture_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt, style=style))

    try:
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        module = importlib.util.module_from_spec(spec)
        sys.argv = argv
        root_logger.handlers = [capture_handler]
        root_logger.setLevel(logging.INFO)
        logging.basicConfig = plugin_basic_config
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
            spec.loader.exec_module(module)
            result = module.main()
    except SystemExit as exc:
        result = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
        logging.basicConfig = old_basic_config
        root_logger.handlers = old_handlers
        root_logger.setLevel(old_level)

    if result is None:
        result = 0
    return int(result), stdout.getvalue()


def reveal_command(path, platform=None):
    if platform is None:
        platform = sys.platform

    if platform == 'darwin':
        return ['open', '-R', path]
    if platform.startswith('win'):
        return ['explorer', '/select,{}'.format(path)]
    return ['xdg-open', os.path.dirname(path)]


def reveal_output(path):
    subprocess.Popen(reveal_command(path))


def reveal_label(platform=None):
    if platform is None:
        platform = sys.platform
    if platform == 'darwin':
        return 'Reveal in Finder'
    if platform.startswith('win'):
        return 'Reveal in Explorer'
    return 'Reveal in File Manager'
