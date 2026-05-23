#!/usr/bin/env python3
import os
import sys
import zipfile


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PLUGIN_SRC = os.path.join(ROOT, 'kicad_plugin', 'stencilframer_plugin')
METADATA = os.path.join(ROOT, 'kicad_plugin', 'pcm', 'metadata.json')
OUTPUT = os.path.join(ROOT, 'kicad_plugin', 'stencilframer-kicad-plugin.zip')


def add_file(archive, source, target):
    archive.write(source, target)


def main():
    output = sys.argv[1] if len(sys.argv)>1 else OUTPUT
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        add_file(archive, METADATA, 'metadata.json')
        for filename in ('__init__.py', 'action.py', 'core.py'):
            add_file(
                    archive,
                    os.path.join(PLUGIN_SRC, filename),
                    os.path.join('plugins', filename))
        add_file(
                archive,
                os.path.join(ROOT, 'stencilframer.py'),
                os.path.join('plugins', 'stencilframer.py'))

    print(output)


if __name__ == '__main__':
    main()
