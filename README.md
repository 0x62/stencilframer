# Stencilframer

This is a fork of Stencilframer by `igor_b`: [https://bitbucket.org/igor_b/stencilframer/src/master/](https://bitbucket.org/igor_b/stencilframer/src/master/).

A script which will take a KiCad PCB or Gerber file and, using OpenSCAD, generate the 3D model of a fixture able to hold the stencil and the PCB in place (for applying the solder paste). It can also generate a frame to hold the stencil in place.

Only dependencies are OpenSCAD and Python (works in both 2 and 3). For Python versions lower than 3.4 additional dependency is enum module (add it with `pip install enum` if needed).

It can generate STL or AMF file for slicing, PNG image or directly output the OpenSCAD code for further editing.

More info at [https://hyperglitch.com/articles/stencilframer](https://hyperglitch.com/articles/stencilframer)

![Fixture holding the PCB and stencil](https://hyperglitch.com/public/images/stencilframer/stencilframer4.jpg)

Update 2023/10/29: updated to support KiCad 6 and newer.

## Fork changes

This fork adds a few workflow improvements for PCB/stencil alignment:

- Automatically size and align the stencil recess from a stencil Gerber with `--stencil-file`.
- Use the stencil fabrication output from JLCPCB: download the stencil fabrication/design outputs for the stencil, then pass the stencil Gerber file to `--stencil-file` along with the KiCad PCB file. The script uses the stencil outline for width/height and matches stencil apertures to KiCad paste pads to place the PCB cutout correctly.
- Fill large internal PCB voids with `--fill-voids`, with `--min-void-area` defaulting to `15 mm^2`.
- Choose the PCB lift cutout position with `--lift-hole-position`.
- Keep separate PCB and stencil clearance controls with `--offset` and `--stencil-offset`.

## Usage

Run the script with `-h` or `--help` to see the usage options.

```
> ./stencilframer.py --help
usage: stencilframer.py [-h] [-l MARGIN_LEFT] [-r MARGIN_RIGHT]
                        [-t MARGIN_TOP] [-b MARGIN_BOTTOM] [-m]
                        [-p PCB_THICKNESS] [-s SHAPE] [--fill-voids]
                        [--min-void-area MIN_VOID_AREA]
                        [--stencil-file STENCIL_FILE] [-f] [-c CHAMFER] [-k]
                        [--lift-hole-position {auto,l,r,t,b,tl,tr,bl,br}]
                        [-o OFFSET] [--stencil-offset STENCIL_OFFSET]
                        [--base-thickness BASE_THICKNESS] [-d] [-w]
                        [--openscad OPENSCAD]
                        infile outfile

positional arguments:
  infile                path to KiCad PCB or gerber file (.kicad_pcb, .gbr,
                        .gm1)
  outfile               path to output file (extension can be .stl, .amf,
                        .png, .pdf, .scad)

options:
  -h, --help            show this help message and exit
  -l, --margin-left MARGIN_LEFT
                        Left margin (mm) (default: 20)
  -r, --margin-right MARGIN_RIGHT
                        Right margin (mm) (default: 20)
  -t, --margin-top MARGIN_TOP
                        Top margin (mm) (default: 20)
  -b, --margin-bottom MARGIN_BOTTOM
                        Bottom margin (mm) (default: 20)
  -m, --mirror          Mirror the PCB (to get the bottom side up) (default:
                        False)
  -p, --pcb-thickness PCB_THICKNESS
                        Thickness of the PCB (mm) (default: 1.6)
  -s, --shape SHAPE     Index of the desired shape from input file (default:
                        0)
  --fill-voids          Fill PCB voids larger than --min-void-area (default:
                        False)
  --min-void-area MIN_VOID_AREA
                        Minimum PCB void area to fill (mm^2) (default: 15)
  --stencil-file STENCIL_FILE
                        Gerber stencil file to automatically size and align
                        the stencil opening (default: None)
  -f, --frame           Generate stencil holding frame instead of stencil frame (default: False)
  -c, --chamfer CHAMFER
                        Specify the percentage of the frame side length to chamfer (max 50) (default: 20)
  -k, --skip-holes      Don't add holes for easy removal in the fixture (default: False)
  --lift-hole-position {auto,l,r,t,b,tl,tr,bl,br}
                        PCB lift cutout position (default: auto)
  -o, --offset OFFSET
                        Offset between the PCB/stencil and frame edge (mm) (default: 0.1)
  --stencil-offset STENCIL_OFFSET
                        Offset between the stencil and frame edge (mm). If not specified, the --offset is used (default: None)
  --base-thickness BASE_THICKNESS
                        Height of the base of the stencil frame (mm) (default: 1)
  -d, --debug           Show debugging info (default: False)
  -w, --use-temp-file   Use temporary file when calling OpenSCAD (used by default on Windows) (default: False)
  --openscad OPENSCAD   Path to OpenSCAD executable (default: openscad)
```

## Example usage

```
> ./stencilframer.py --pcb-thickness 1.55 path_to_pcb_file.kicad_pcb holder.stl
> ./stencilframer.py --stencil-file jlcpcb_stencil_output.gbr path_to_pcb_file.kicad_pcb holder.stl
> ./stencilframer.py --fill-voids path_to_pcb_file.kicad_pcb holder.scad
> ./stencilframer.py --fill-voids --min-void-area 30 path_to_pcb_file.kicad_pcb holder.scad
> ./stencilframer.py --lift-hole-position br path_to_pcb_file.kicad_pcb holder.scad
> ./stencilframer.py --frame path_to_pcb_file.kicad_pcb frame.stl
```

For JLCPCB stencil output, use the Gerber file from the downloaded stencil fabrication/design files as `--stencil-file`. This replaces manually choosing `-l`, `-r`, `-t`, and `-b` because the generated fixture is sized from the stencil outline and aligned from the stencil apertures.
