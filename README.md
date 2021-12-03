# Stencilframer

A script which will take the KiCAD PCB  or Gerber file and, using OpenSCAD, generate the 3D model of a fixture able to hold the stencil and the PCB in place (for applying the solder paste). It can also generate a frame to hold the stencil in place.

Only dependencies are OpenSCAD and Python (works in both 2 and 3). For Python versions lower than 3.4 additional dependency is enum module (add it with `pip install enum` if needed).

It can generate STL or AMF file for slicing, PNG image or directly output the OpenSCAD code for further editing.

More info at [https://hyperglitch.com/articles/stencilframer](https://hyperglitch.com/articles/stencilframer)

![Fixture holding the PCB and stencil](https://hyperglitch.com/public/images/stencilframer/stencilframer4.jpg)


## Usage

Run the script with `-h` or `--help` to see the usage options.

```
> ./stencilframer.py --help
usage: stencilframer.py [-h] [-l MARGIN_LEFT] [-r MARGIN_RIGHT] [-t MARGIN_TOP] [-b MARGIN_BOTTOM] [-m] [-p PCB_THICKNESS] [-s SHAPE]
                        [-f] [-k] [-o OFFSET] [--stencil-offset STENCIL_OFFSET] [--openscad OPENSCAD]
                        infile outfile

positional arguments:
  infile                path to KiCad PCB or gerber file (.kicad_pcb, .gbr, .gm1)
  outfile               path to output file (extension can be .stl, .amf, .png, .pdf, .scad)

optional arguments:
  -h, --help            show this help message and exit
  -l MARGIN_LEFT, --margin-left MARGIN_LEFT
                        Left margin (mm) (default: 20)
  -r MARGIN_RIGHT, --margin-right MARGIN_RIGHT
                        Right margin (mm) (default: 20)
  -t MARGIN_TOP, --margin-top MARGIN_TOP
                        Top margin (mm) (default: 20)
  -b MARGIN_BOTTOM, --margin-bottom MARGIN_BOTTOM
                        Bottom margin (mm) (default: 20)
  -m, --mirror          Mirror the PCB (to get the bottom side up) (default: False)
  -p PCB_THICKNESS, --pcb-thickness PCB_THICKNESS
                        Thickness of the PCB (mm) (default: 1.6)
  -s SHAPE, --shape SHAPE
                        Index of the desired shape from input file (default: 0)
  -f, --frame           Generate stencil holding frame instead of stencil frame (default: False)
  -c CHAMFER, --chamfer CHAMFER
                        Specify the percentage of the frame side length to chamfer (max 50) (default: 20)
  -k, --skip-holes      Don't add holes for easy removal in the fixture (default: False)
  -o OFFSET, --offset OFFSET
                        Offset between the PCB/stencil and frame edge (mm) (default: 0.1)
  --stencil-offset STENCIL_OFFSET
                        Offset between the stencil and frame edge (mm). If not specified, the --offset is used (default: None)
  --openscad OPENSCAD   Path to OpenSCAD executable (default: openscad)
```

## Example usage

```
> ./stencilframer.py --pcb-thickness 1.55 path_to_pcb_file.kicad_pcb holder.stl
> ./stencilframer.py --frame path_to_pcb_file.kicad_pcb frame.stl
```

