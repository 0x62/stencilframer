import os
import logging
import shutil
import tempfile
import unittest
import zipfile

from kicad_plugin.stencilframer_plugin import core


class KiCadPluginCoreTest(unittest.TestCase):
    def test_default_output_path_uses_project_directory(self):
        self.assertEqual(
            core.default_output_path('/tmp/project/board.kicad_pcb'),
            '/tmp/project/stencil_frame.stl')

    def test_builds_stencilframer_command(self):
        cmd = core.build_stencilframer_command(
            '/tmp/project/board.kicad_pcb',
            '/tmp/stencil.gbr',
            '/tmp/project/stencil_frame.stl',
            openscad_path='/usr/bin/openscad',
            offset=0.2,
            stencil_offset=0.3,
            mirror=True,
            lift_hole_position='br',
            pcb_thickness=1.2,
            fill_voids=True,
            min_void_area=25,
            script_path='/repo/stencilframer.py',
            python_executable='python',
        )

        self.assertEqual(cmd, [
            'python',
            '/repo/stencilframer.py',
            '--stencil-file',
            '/tmp/stencil.gbr',
            '--openscad',
            '/usr/bin/openscad',
            '--mirror',
            '--offset',
            '0.2',
            '--stencil-offset',
            '0.3',
            '--lift-hole-position',
            'br',
            '--pcb-thickness',
            '1.2',
            '--fill-voids',
            '--min-void-area',
            '25',
            '/tmp/project/board.kicad_pcb',
            '/tmp/project/stencil_frame.stl',
        ])

    def test_finds_repo_stencilframer_script(self):
        self.assertTrue(core.stencilframer_script_path().endswith('stencilframer.py'))

    def test_find_openscad_returns_none_for_missing_path(self):
        original_path = os.environ.get('PATH')
        try:
            os.environ['PATH'] = ''
            self.assertIsNone(core.find_openscad())
        finally:
            if original_path is None:
                del os.environ['PATH']
            else:
                os.environ['PATH'] = original_path

    def test_preferences_round_trip(self):
        temp_dir = tempfile.mkdtemp()
        prefs_path = os.path.join(temp_dir, 'preferences.json')
        try:
            core.save_preferences({
                'offset': '0.25',
                'stencil_offset': '0.05',
                'fill_voids': False,
                'min_void_area': '30',
                'side': 'back',
                'lift_hole_position': 'br',
                'openscad_path': '/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD',
                'openscad_custom': True,
            }, path=prefs_path)

            prefs = core.load_preferences(path=prefs_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(prefs['offset'], '0.25')
        self.assertEqual(prefs['stencil_offset'], '0.05')
        self.assertFalse(prefs['fill_voids'])
        self.assertEqual(prefs['min_void_area'], '30')
        self.assertEqual(prefs['side'], 'back')
        self.assertEqual(prefs['lift_hole_position'], 'br')
        self.assertEqual(prefs['openscad_path'], '/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD')
        self.assertTrue(prefs['openscad_custom'])

    def test_load_preferences_merges_with_defaults(self):
        temp_dir = tempfile.mkdtemp()
        prefs_path = os.path.join(temp_dir, 'preferences.json')
        try:
            with open(prefs_path, 'w') as fout:
                fout.write('{"offset": "0.4"}')

            prefs = core.load_preferences(path=prefs_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(prefs['offset'], '0.4')
        self.assertEqual(prefs['stencil_offset'], '0.1')
        self.assertTrue(prefs['fill_voids'])
        self.assertEqual(prefs['min_void_area'], '15')
        self.assertEqual(prefs['side'], 'front')
        self.assertEqual(prefs['lift_hole_position'], 'auto')

    def test_runs_stencilframer_script_in_process(self):
        fd, script_path = tempfile.mkstemp(suffix='.py')
        os.close(fd)
        fd, output_path = tempfile.mkstemp()
        os.close(fd)
        try:
            with open(script_path, 'w') as fout:
                fout.write(
                    'import sys\n'
                    'def main():\n'
                    '    print("ARGS=" + "|".join(sys.argv[1:]))\n'
                    '    return 0\n')

            returncode, output = core.run_stencilframer(
                '/tmp/board.kicad_pcb',
                '/tmp/stencil.gbr',
                output_path,
                openscad_path='/tmp/openscad',
                offset=0.2,
                stencil_offset=0.3,
                mirror=True,
                lift_hole_position='tl',
                pcb_thickness=1.4,
                fill_voids=True,
                min_void_area=25,
                script_path=script_path,
            )
        finally:
            os.unlink(script_path)
            os.unlink(output_path)

        self.assertEqual(returncode, 0)
        self.assertIn('--stencil-file|/tmp/stencil.gbr|--openscad|/tmp/openscad|--mirror|--offset|0.2|--stencil-offset|0.3|--lift-hole-position|tl|--pcb-thickness|1.4|--fill-voids|--min-void-area|25|/tmp/board.kicad_pcb|{}'.format(output_path), output)

    def test_captures_logging_when_root_handlers_exist(self):
        fd, script_path = tempfile.mkstemp(suffix='.py')
        os.close(fd)
        root_logger = logging.getLogger()
        original_handlers = list(root_logger.handlers)
        original_level = root_logger.level
        root_logger.handlers = [logging.NullHandler()]
        try:
            with open(script_path, 'w') as fout:
                fout.write(
                    'import logging\n'
                    'def main():\n'
                    '    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")\n'
                    '    logging.error("boom")\n'
                    '    return 1\n')

            returncode, output = core.run_stencilframer(
                '/tmp/board.kicad_pcb',
                '/tmp/stencil.gbr',
                '/tmp/out.stl',
                script_path=script_path,
            )
        finally:
            root_logger.handlers = original_handlers
            root_logger.level = original_level
            os.unlink(script_path)

        self.assertEqual(returncode, 1)
        self.assertIn('[ERROR] boom', output)

    def test_detects_pcb_thickness_from_kicad_file(self):
        fd, board_path = tempfile.mkstemp(suffix='.kicad_pcb')
        os.close(fd)
        try:
            with open(board_path, 'w') as fout:
                fout.write(
                    '(kicad_pcb\n'
                    '  (general\n'
                    '    (thickness 1.8)\n'
                    '  )\n'
                    ')\n')

            thickness = core.detect_pcb_thickness(board_path)
        finally:
            os.unlink(board_path)

        self.assertEqual(thickness, 1.8)

    def test_extracts_preferred_gerber_from_zip(self):
        fd, zip_path = tempfile.mkstemp(suffix='.zip')
        os.close(fd)
        try:
            with zipfile.ZipFile(zip_path, 'w') as archive:
                archive.writestr('readme.txt', 'ignore')
                archive.writestr('board_outline.gbr', 'outline')
                archive.writestr('stencil_paste.gbr', 'paste')

            gerber_path, temp_dir = core.resolve_stencil_input(zip_path)
            with open(gerber_path, 'r') as fin:
                contents = fin.read()
            self.assertTrue(os.path.isdir(temp_dir))
        finally:
            os.unlink(zip_path)
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(contents, 'paste')

    def test_reveal_command_by_platform(self):
        self.assertEqual(core.reveal_command('/tmp/out.stl', platform='darwin'), ['open', '-R', '/tmp/out.stl'])
        self.assertEqual(core.reveal_command('C:\\tmp\\out.stl', platform='win32'), ['explorer', '/select,C:\\tmp\\out.stl'])
        self.assertEqual(core.reveal_label(platform='darwin'), 'Reveal in Finder')
        self.assertEqual(core.reveal_label(platform='win32'), 'Reveal in Explorer')


if __name__ == '__main__':
    unittest.main()
