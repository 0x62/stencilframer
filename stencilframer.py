#!/usr/bin/env python
# -*- coding: utf-8 -*-

# The MIT License (MIT)
#
# Copyright © 2021 Igor Brkic <i@hglt.ch>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the “Software”), to deal in
# the Software without restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
# Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import argparse
import enum
import itertools
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time


class InFormat(enum.Enum):
    KICAD = 0
    GERBER = 1

class Interpolation(enum.Enum):
    LINEAR = 0
    ARC_CW = 1
    ARC_CCW = 2

class CoordFormat(enum.Enum):
    ABSOLUTE = 0
    INCREMENTAL = 1


def rotate_point(point, center, angle_deg):
    """
    Rotate a point around a center point by a given angle (in degrees).

    Arguments are tuples of (x, y) coordinates.
    """
    st = (point[0]-center[0], point[1]-center[1]) # translate to (0,0)
    angle_rad = angle_deg/180.0*math.pi

    # rotate
    sr = (
            st[0]*math.cos(angle_rad) + st[1]*math.sin(angle_rad),
            -st[0]*math.sin(angle_rad) + st[1]*math.cos(angle_rad)
            )

    # translate back
    return (sr[0]+center[0], sr[1]+center[1])


def distance(p1, p2):
    # euclidean distance
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def get_angle(s, e, c):
    # get angle between two points and a center point (in degrees)
    arg = distance(s, e)/2 / distance(s, c)
    return math.asin(arg) * 2 / math.pi * 180


def angle_between(p1, p2):
    return math.atan2(p2[1]-p1[1], p2[0]-p1[0])


def triangle_area(p1, p2, p3):
    return abs((p1[0]*(p2[1]-p3[1]) + p2[0]*(p3[1]-p1[1]) + p3[0]*(p1[1]-p2[1]))/2.0)


def parse_sexp(expr):
    # Simple S-expression parser
    # parse a big s-expression into a dictionary
    # when certain attributes are repeated, they are merged into a list
    #
    # Input is a string containing the s-expression
    # Output is a tuple (attr, dict) where attr is the name of the node and dict is a dictionary
    level = 0
    maxlevel = 0
    start_idx = -1
    end_idx = -1
    children = []
    expr = expr[1:-1] # strip parenthesis
    expr = expr.replace('\"', '')  # remove escaped quotes from fields for easier parsing

    # extract attribute name (first string until whitespace or open parenthesis)
    attr = ''
    inside_quotes = False
    for i in range(len(expr)):
        if expr[i]=='"':
            inside_quotes = not inside_quotes
        if expr[i] in (' ', '(', ')') and not inside_quotes:
            attr = expr[:i]
            break

    if attr=='':
        return expr.strip(), {}

    inside_quotes = False
    for i in range(len(attr), len(expr)):
        if expr[i]=='"':
            inside_quotes = not inside_quotes
        if expr[i]=='(' and not inside_quotes:
            if level==0:
                start_idx = i
            level += 1
            if level>maxlevel:
                maxlevel = level
        elif expr[i]==')' and not inside_quotes:
            if level==1:
                end_idx = i
                k, v = parse_sexp(expr[start_idx:end_idx+1])
                children.append({k: v})
            level -= 1
    if maxlevel==0:
        # no sub-expressions, extract value
        val_raw = expr[len(attr):].strip("() '\"'")
        val = None
        # currently supported values:
        #   - float
        #   - list of floats (space separated)
        #   - string
        try:
            if val_raw.find(' ')!=-1:
                val = [float(x) for x in val_raw.split()]
            else:
                val = float(val_raw)
        except ValueError:
            val = val_raw
        children.append({'value': val})
        #return attr, val

    # if there are multiple children with the same name, merge them into a list
    el = {}
    for i in range(len(children)):
        k = list(children[i].keys())[0]
        if k in el:
            if type(el[k]) is not list:
                el[k] = [el[k]]
            el[k].append(children[i][k])
        else:
            el[k] = children[i][k]
    return attr.strip(), el


def process_kicad_layer(infile):
    """
    Parse the Kicad PCB file and extract all graphic primitives on Edge.Cuts layer.

    Kicad pcb file is just a big s-expression. Main node is "kicad_pcb" and it contains a list
    of all elements as s-expressions.
    Full specification is here: https://dev-docs.kicad.org/en/file-formats/sexpr-intro/index.html#_graphic_items

    infile is a path to a kicad pcb file
    """

    # not the most memory efficient way to parse this but it will be fine for this
    with open(infile, "r") as fin:
        node, data = parse_sexp(fin.read().strip())

    if node!="kicad_pcb" or type(data) is not dict:
        raise ValueError("Invalid Kicad PCB file")

    paths = []

    # make sure all elements are lists to avoid checks later
    for elt in ('gr_arc', 'gr_circle', 'gr_line', 'gr_poly', 'gr_rect'):
        if elt not in data:
            data[elt] = []
        if type(data[elt]) is not list:
            data[elt] = [data[elt]]

    # handle lines
    for p in data['gr_line']:
        if 'layer' not in p or p['layer']['value']!="Edge.Cuts":
            continue
        if 'angle' in p:
            # angle is optional parameter. We need to rotate the line around the center
            cent = ((p['start']['value'][0]+p['end']['value'][0])/2, (p['start']['value'][1]+p['end']['value'][1])/2)
            logging.warning("Line rotation hasn't been tested yet. Please report any issues. %s", p)
            paths.append({
                'type': 'line',
                'start': rotate_point(p['start']['value'], cent, p['angle']['value']),
                'end': rotate_point(p['end']['value'], cent, p['angle']['value']),
                })
        else:
            paths.append({
                'type': 'line',
                'start': p['start']['value'],
                'end': p['end']['value'],
                })

    # handle arcs
    for p in data['gr_arc']:
        if 'layer' not in p or p['layer']['value']!="Edge.Cuts":
            continue
        # we have three points on arc (start, mid, end) and need to calculate the center
        A = p['start']['value']
        B = p['mid']['value']
        C = p['end']['value']
        ma = (B[1]-A[1])/(B[0]-A[0])
        mb = (C[1]-B[1])/(C[0]-B[0])
        x = (ma*mb*(A[1]-C[1]) + mb*(A[0]+B[0]) - ma*(B[0]+C[0]))/(2*(mb-ma))
        y = -1/ma*(x-(A[0]+B[0])/2) + (A[1]+B[1])/2
        cent = (x, y)
        paths.append({
            'type': 'arc',
            'start': A,
            'end': C,
            'center': cent,
            'angle': get_angle(C, A, cent),
            })

    # handle circles
    for p in data['gr_circle']:
        if 'layer' not in p or p['layer']['value']!="Edge.Cuts":
            continue
        # interpret as two arcs
        radius = distance(p['center']['value'], p['end']['value'])
        paths.append({
            'type': 'arc',
            'start': (p['center']['value'][0]+radius, p['center']['value'][1]),
            'end': (p['center']['value'][0]-radius, p['center']['value'][1]),
            'center': p['center']['value'],
            'angle': 180,
            })
        paths.append({
            'type': 'arc',
            'start': (p['center']['value'][0]-radius, p['center']['value'][1]),
            'end': (p['center']['value'][0]+radius, p['center']['value'][1]),
            'center': p['center']['value'],
            'angle': 180,
            })

    # handle polygons
    for p in data['gr_poly']:
        if 'layer' not in p or p['layer']['value']!="Edge.Cuts":
            continue
        for i in range(1, len(p['pts']['xy'])):
            paths.append({
                'type': 'line',
                'start': p['pts']['xy'][i-1]['value'],
                'end': p['pts']['xy'][i]['value']
                })
        paths.append({
            'type': 'line',
            'start': p['pts']['xy'][-1]['value'],
            'end': p['pts']['xy'][0]['value']
            })

    # handle rectangles
    for p in data['gr_rect']:
        if 'layer' not in p or p['layer']['value']!="Edge.Cuts":
            continue
        # interpret as four lines
        start = p['start']['value']
        end = p['end']['value']
        paths.append({
            'type': 'line',
            'start': [start[0], start[1]],
            'end': [end[0], start[1]]
            })
        paths.append({
            'type': 'line',
            'start': [end[0], start[1]],
            'end': [end[0], end[1]]
            })
        paths.append({
            'type': 'line',
            'start': [end[0], end[1]],
            'end': [start[0], end[1]]
            })
        paths.append({
            'type': 'line',
            'start': [start[0], end[1]],
            'end': [start[0], start[1]]
            })

    return paths


def load_kicad_pcb(infile):
    with open(infile, "r") as fin:
        node, data = parse_sexp(fin.read().strip())

    if node!="kicad_pcb" or type(data) is not dict:
        raise ValueError("Invalid Kicad PCB file")

    return data


def as_list(value):
    if value is None:
        return []
    if type(value) is list:
        return value
    return [value]


def sexp_value(node, default=None):
    if type(node) is dict and 'value' in node:
        return node['value']
    return default


def kicad_at(node):
    value = sexp_value(node, [])
    if type(value) is not list:
        value = [value]
    x = value[0] if len(value)>0 else 0
    y = value[1] if len(value)>1 else 0
    angle = value[2] if len(value)>2 else 0
    return (x, y, angle)


def kicad_layers(node):
    value = sexp_value(node, "")
    if type(value) is list:
        return [str(v) for v in value]
    return str(value).split()


def extract_kicad_paste_pads(infile, paste_layer):
    """
    Extract paste pad centers from a KiCad PCB file.
    """
    data = load_kicad_pcb(infile)
    pads = []

    for footprint in as_list(data.get('footprint')) + as_list(data.get('module')):
        fp_x, fp_y, fp_angle = kicad_at(footprint.get('at', {}))

        for pad in as_list(footprint.get('pad')):
            if paste_layer not in kicad_layers(pad.get('layers', {})):
                continue

            pad_x, pad_y, _pad_angle = kicad_at(pad.get('at', {}))
            pad_pos = rotate_point((pad_x, pad_y), (0, 0), fp_angle)
            pads.append({
                'center': (fp_x+pad_pos[0], fp_y+pad_pos[1]),
                'size': sexp_value(pad.get('size', {}), [0, 0]),
                })

    return pads


def process_gerber_layer(infile):
    """
    Parse the gerber file containing the outline and extract all of the graphic primitives
    """
    decimals = 6
    unit_convert = 1
    total_coord = 6
    interpolation = Interpolation.LINEAR
    point = (0,0)

    paths = []

    outline = []
    with open(infile, "r") as fin:
        for line in fin:
            outline.append(line.strip())

    # convert raw coordinate to float in mm
    coord = lambda x: (float(x)/(10**decimals))*unit_convert

    lineno = 0
    ln = outline[lineno]
    while lineno<len(outline):
        if ln.startswith('%FSLA'):
            # parse decimal format
            try:
                fmts = re.findall(r'FSLAX([0-9]+)Y([0-9]+)', ln)[0]
            except IndexError:
                raise ValueError("Invalid coordinate format specified")
            if len(fmts)!=2 or fmts[0]!=fmts[1]:
                raise ValueError("Invalid coordinate format specified")
            decimals = int(fmts[0][1:])
            logging.debug("coordinate format set to %d.%d", decimals, total_coord)

        elif ln.startswith('%FSA'):  # Altium-generated Gerber defined precision with %FSA line instead of %FSLA
            # parse decimal format
            try:
                fmts = re.findall(r'FSAX([0-9]+)Y([0-9]+)', ln)[0]
            except IndexError:
                raise ValueError("Invalid coordinate format specified")
            if len(fmts)!=2 or fmts[0]!=fmts[1]:
                raise ValueError("Invalid coordinate format specified")
            integers = int(fmts[0][0])
            decimals = int(fmts[0][1:])
            logging.debug("coordinate format set to %d.%d", decimals, total_coord)

        elif ln.startswith('%MOIN') or ln.startswith('G70*'):
            # units in inches - convert to mm
            unit_convert = 25.4
            logging.debug("units set to inches")

        elif ln.startswith('%MOMM') or ln.startswith('G71*'):
            # units in inches - convert to mm
            unit_convert = 1
            logging.debug("units set to mm")

        elif ln.startswith('%ADD'):
            # apertures list
            # since we're only looking for outline we can assume 0.05mm
            # aperture size and skip this for now
            pass

        elif ln.startswith('G01'):
            interpolation = Interpolation.LINEAR
            logging.debug("interpolation set to %s", interpolation)
            ln = ln[3:] # continue parsing the same line
            continue

        elif ln.startswith('G02'):
            interpolation = Interpolation.ARC_CW
            logging.debug("interpolation set to %s", interpolation)
            ln = ln[3:] # continue parsing the same line
            continue

        elif ln.startswith('G03'):
            interpolation = Interpolation.ARC_CCW
            logging.debug("interpolation set to %s", interpolation)
            ln = ln[3:] # continue parsing the same line
            continue

        elif ln.startswith('G04'):
            # just a comment, skip it
            pass

        elif ln.startswith('G75'):
            # multi quadrant mode (legacy)
            pass

        elif ln.startswith('G90'):
            # set the coordinates to absolute (legacy)
            logging.debug("coordinate format set to absolute")
            ln = ln[3:] # continue parsing the same line
            continue
        elif ln.startswith('G91'):
            # set the coordinates to absolute (legacy)
            logging.debug("coordinate format set to incremental")
            ln = ln[3:] # continue parsing the same line
            continue

        elif ln.startswith('D'):
            logging.debug("selecting aperture %s (ignored)", ln)
            # select apperture from the list - skip it (for now)
            pass

        elif ln.startswith('X') or ln.startswith('Y'):
            # move or interpolate command
            x = None
            y = None
            i = None
            j = None
            success = False

            # FIXME: take into consideration absolute/incremental format
            try:
                pts = re.findall(r'X([0-9\-]+)Y([0-9\-]+)I([0-9\-]+)J([0-9\-]+)', ln)[0]
                x = coord(pts[0])
                y = coord(pts[1])
                i = coord(pts[2])
                j = coord(pts[3])
                success = True
            except IndexError:
                pass

            if not success:
                try:
                    pts = re.findall(r'X([0-9\-]+)Y([0-9\-]+)', ln)[0]
                    x = coord(pts[0])
                    y = coord(pts[1])
                    success = True
                except IndexError:
                    pass

            if not success:
                try:
                    pts = re.findall(r'X([0-9\-]+)', ln)[0]
                    x = coord(pts)
                    y = point[1]
                    success = True
                except IndexError:
                    pass

            if not success:
                try:
                    pts = re.findall(r'Y([0-9\-]+)', ln)[0]
                    x = point[0]
                    y = coord(pts)
                    success = True
                except IndexError:
                    pass

            if not success:
                logging.warning("Failed to parse coordinates: %s", ln)

            center = None
            if i is not None and j is not None:
                center = (point[0]+i, point[1]+j)

            if ln.endswith('D02*') or ln.endswith('D2*'):
                # move command
                point = (x, y)
                logging.debug("moving to %s", point)

            elif ln.endswith('D01*') or ln.endswith('D1*'):
                # interpolate command
                pend = (x, y)
                if interpolation==Interpolation.LINEAR:
                    logging.debug("interpolating line from %s to %s", point, pend)
                    paths.append({
                        'type': 'line',
                        'start': point,
                        'end': pend
                        })
                elif interpolation==Interpolation.ARC_CW:
                    logging.debug("interpolating CW arc from %s to %s with center at %s", point, pend, center)
                    paths.append({
                        'type': 'arc',
                        'start': pend,
                        'end': point,
                        'center': center,
                        'angle': get_angle(point, pend, center)
                        })
                elif interpolation==Interpolation.ARC_CCW:
                    logging.debug("interpolating CCW arc from %s to %s with center at %s", point, pend, center)
                    paths.append({
                        'type': 'arc',
                        'start': point,
                        'end': pend,
                        'center': center,
                        'angle': get_angle(point, pend, center)
                        })
                point = pend

            else:
                logging.warning("only supported commands currently are move or interpolate. Continuing...")

        elif ln.startswith('M02*'):
            # end of file
            break

        lineno += 1     # go to the next line
        ln = outline[lineno]

    return paths


def parse_gerber_coord_format(line):
    try:
        fmts = re.findall(r'FSL?A?X([0-9]+)Y([0-9]+)', line)[0]
    except IndexError:
        raise ValueError("Invalid coordinate format specified")
    if len(fmts)!=2 or fmts[0]!=fmts[1]:
        raise ValueError("Invalid coordinate format specified")
    return int(fmts[0][1:])


def parse_gerber_aperture(line):
    match = re.match(r'%ADD([0-9]+)([A-Z]),([^*]+)\*%', line)
    if not match:
        return None

    code = int(match.group(1))
    shape = match.group(2)
    params = []
    for part in re.split(r'[Xx]', match.group(3)):
        try:
            params.append(float(part))
        except ValueError:
            pass

    if shape not in ('C', 'R', 'O'):
        return None

    return code, {
            'shape': shape,
            'params': params,
            }


def parse_gerber_xy(line, coord, current_point):
    x = current_point[0]
    y = current_point[1]

    match = re.search(r'X([0-9\-]+)', line)
    if match:
        x = coord(match.group(1))

    match = re.search(r'Y([0-9\-]+)', line)
    if match:
        y = coord(match.group(1))

    return (x, y)


def gerber_command(line):
    match = re.search(r'D0?([123])\*$', line)
    if match:
        return int(match.group(1))
    return None


def is_near_rectangle(pol, tolerance=0.05):
    if len(pol)<4:
        return False

    bounds = polygon_bounds(pol)
    width = bounds['xmax']-bounds['xmin']
    height = bounds['ymax']-bounds['ymin']
    if width<=tolerance or height<=tolerance:
        return False

    side_touches = {
            'xmin': False,
            'xmax': False,
            'ymin': False,
            'ymax': False,
            }
    for point in pol:
        if point[0]<bounds['xmin']-tolerance or point[0]>bounds['xmax']+tolerance:
            return False
        if point[1]<bounds['ymin']-tolerance or point[1]>bounds['ymax']+tolerance:
            return False

        if abs(point[0]-bounds['xmin'])<=tolerance:
            side_touches['xmin'] = True
        if abs(point[0]-bounds['xmax'])<=tolerance:
            side_touches['xmax'] = True
        if abs(point[1]-bounds['ymin'])<=tolerance:
            side_touches['ymin'] = True
        if abs(point[1]-bounds['ymax'])<=tolerance:
            side_touches['ymax'] = True

    if not all(side_touches.values()):
        return False

    return abs(polygon_area(pol))/(width*height) >= 0.70


def is_rectangular_footprint_points(points, tolerance=0.05):
    if len(points)<4:
        return False

    bounds = polygon_bounds(points)
    if bounds['xmax']-bounds['xmin']<=tolerance or bounds['ymax']-bounds['ymin']<=tolerance:
        return False

    side_touches = {
            'xmin': False,
            'xmax': False,
            'ymin': False,
            'ymax': False,
            }
    for point in points:
        on_xmin = abs(point[0]-bounds['xmin'])<=tolerance
        on_xmax = abs(point[0]-bounds['xmax'])<=tolerance
        on_ymin = abs(point[1]-bounds['ymin'])<=tolerance
        on_ymax = abs(point[1]-bounds['ymax'])<=tolerance
        if not (on_xmin or on_xmax or on_ymin or on_ymax):
            return False

        side_touches['xmin'] = side_touches['xmin'] or on_xmin
        side_touches['xmax'] = side_touches['xmax'] or on_xmax
        side_touches['ymin'] = side_touches['ymin'] or on_ymin
        side_touches['ymax'] = side_touches['ymax'] or on_ymax

    return all(side_touches.values())


def path_endpoints(paths):
    points = []
    for path in paths:
        points.append(path['start'])
        points.append(path['end'])
    return points


def segment_length(path):
    return distance(path['start'], path['end'])


def point_in_bounds(point, bounds):
    return bounds['xmin'] <= point[0] <= bounds['xmax'] and bounds['ymin'] <= point[1] <= bounds['ymax']


def axis_segment_groups(paths, tolerance=0.5, min_segment_length=1.0):
    vertical_groups = []
    horizontal_groups = []

    def add_group(groups, coord, length):
        for group in groups:
            if abs(group['coord']-coord)<=tolerance:
                total = group['length'] + length
                group['coord'] = (group['coord']*group['length'] + coord*length)/total
                group['length'] = total
                return
        groups.append({
            'coord': coord,
            'length': length,
            })

    for path in paths:
        dx = path['end'][0]-path['start'][0]
        dy = path['end'][1]-path['start'][1]
        length = math.hypot(dx, dy)
        if length<min_segment_length:
            continue

        if abs(dx)<=tolerance and abs(dy)>tolerance:
            add_group(vertical_groups, (path['start'][0]+path['end'][0])/2.0, length)
        elif abs(dy)<=tolerance and abs(dx)>tolerance:
            add_group(horizontal_groups, (path['start'][1]+path['end'][1])/2.0, length)

    return {
            'vertical': vertical_groups,
            'horizontal': horizontal_groups,
            }


def axis_segment_outline_rect(groups, tolerance=0.5):
    vertical_groups = groups['vertical']
    horizontal_groups = groups['horizontal']

    if len(vertical_groups)<2 or len(horizontal_groups)<2:
        return None

    max_vertical = max(group['length'] for group in vertical_groups)
    max_horizontal = max(group['length'] for group in horizontal_groups)
    vertical_candidates = [group for group in vertical_groups if group['length']>=max_vertical*0.5]
    horizontal_candidates = [group for group in horizontal_groups if group['length']>=max_horizontal*0.5]
    if len(vertical_candidates)<2 or len(horizontal_candidates)<2:
        return None

    xmin = min(group['coord'] for group in vertical_candidates)
    xmax = max(group['coord'] for group in vertical_candidates)
    ymin = min(group['coord'] for group in horizontal_candidates)
    ymax = max(group['coord'] for group in horizontal_candidates)
    if xmax-xmin<=tolerance or ymax-ymin<=tolerance:
        return None

    return rect_from_bounds({
            'xmin': xmin,
            'xmax': xmax,
            'ymin': ymin,
            'ymax': ymax,
            })


def detect_outline_axis_segments(paths, tolerance=0.5):
    groups = axis_segment_groups(paths, tolerance=tolerance)
    outline = axis_segment_outline_rect(groups, tolerance=tolerance)
    if outline is None:
        return None
    return {
            'outline': outline,
            'bounds': polygon_bounds(outline),
            'strategy': 'axis_segments_fast',
            }


def rect_from_bounds(bounds):
    return [
            (bounds['xmin'], bounds['ymin']),
            (bounds['xmin'], bounds['ymax']),
            (bounds['xmax'], bounds['ymax']),
            (bounds['xmax'], bounds['ymin']),
            ]


def polygon_bounds(pol):
    return {
            'xmin': min([p[0] for p in pol]),
            'xmax': max([p[0] for p in pol]),
            'ymin': min([p[1] for p in pol]),
            'ymax': max([p[1] for p in pol]),
            }


def closed_outline_candidates(paths):
    shapes = sort_paths(paths) if paths else []
    polygons = []
    for shape in shapes:
        if distance(shape[0]['start'], shape[-1]['end'])<0.01:
            pol = paths_to_polygon(shape)
            if len(pol)>=3:
                polygons.append(pol)
    return polygons


def detect_outline_closed_loops(paths):
    polygons = closed_outline_candidates(paths)
    if not polygons:
        return None

    closed_outline = max(polygons, key=lambda pol: abs(polygon_area(pol)))
    if not is_near_rectangle(closed_outline):
        return {
                'error': "Largest stencil outline is not rectangular",
                'outline_area': abs(polygon_area(closed_outline)),
                }

    bounds = polygon_bounds(closed_outline)
    outline = rect_from_bounds(bounds)
    return {
            'outline': outline,
            'bounds': bounds,
            'strategy': 'closed_loops',
            'outline_area': abs(polygon_area(closed_outline)),
            }


def detect_outline_endpoint_fallback(paths, tolerance=0.5):
    outline = path_endpoints(paths)
    if not is_rectangular_footprint_points(outline, tolerance=tolerance):
        return None

    bounds = polygon_bounds(outline)
    return {
            'outline': rect_from_bounds(bounds),
            'bounds': bounds,
            'strategy': 'endpoint_fallback',
            }


def choose_stencil_outline(paths):
    axis_outline = detect_outline_axis_segments(paths, tolerance=0.5)
    if axis_outline is not None:
        return axis_outline

    closed_outline = detect_outline_closed_loops(paths)

    if closed_outline is not None and 'outline' in closed_outline:
        return closed_outline

    endpoint_outline = detect_outline_endpoint_fallback(paths, tolerance=0.5)
    if endpoint_outline is not None:
        return endpoint_outline

    if closed_outline is not None and 'error' in closed_outline:
        raise ValueError(closed_outline['error'])

    raise ValueError("No closed stencil outline found in Gerber file")


def closed_region_center(region):
    if not region['points'] or distance(region['first'], region['last'])>=0.01:
        return None
    return (
            sum(point[0] for point in region['points'])/float(len(region['points'])),
            sum(point[1] for point in region['points'])/float(len(region['points'])),
            )


def parse_gerber_stencil(infile):
    """
    Parse a Gerber stencil file for flashed apertures and the largest closed outline.
    """
    started = time.time()
    decimals = 6
    unit_convert = 1
    point = (0, 0)
    selected_aperture = None
    current_operation = None
    apertures = {}
    paths = []
    flashes = []
    regions = []
    region = None

    with open(infile, "r") as fin:
        lines = [line.strip() for line in fin]

    coord = lambda x: (float(x)/(10**decimals))*unit_convert

    for line in lines:
        if not line:
            continue

        if line.startswith('%FSLA') or line.startswith('%FSA'):
            decimals = parse_gerber_coord_format(line)
            coord = lambda x: (float(x)/(10**decimals))*unit_convert
            continue

        if line.startswith('%MOIN') or line.startswith('G70*'):
            unit_convert = 25.4
            coord = lambda x: (float(x)/(10**decimals))*unit_convert
            continue

        if line.startswith('%MOMM') or line.startswith('G71*'):
            unit_convert = 1
            coord = lambda x: (float(x)/(10**decimals))*unit_convert
            continue

        if line.startswith('%ADD'):
            aperture = parse_gerber_aperture(line)
            if aperture is not None:
                apertures[aperture[0]] = aperture[1]
            continue

        if line.startswith('G04') or line.startswith('%'):
            continue

        if line.startswith('G36'):
            region = {
                    'points': [],
                    'first': None,
                    'last': None,
                    }
            continue

        if line.startswith('G37'):
            if region is not None:
                regions.append(region)
            region = None
            continue

        if line.startswith('D') and line.endswith('*'):
            try:
                selected_aperture = int(line[1:-1])
            except ValueError:
                pass
            continue

        if line.startswith('G01'):
            line = line[3:]
        elif line.startswith('G02') or line.startswith('G03'):
            # Use a chord for rounded stencil corners. The rectangular footprint
            # comes from the largest outline bounds, so exact arc geometry is not
            # needed for stencil sizing.
            line = line[3:]

        if not (line.startswith('X') or line.startswith('Y')):
            continue

        new_point = parse_gerber_xy(line, coord, point)
        command = gerber_command(line)
        if command is None:
            command = current_operation
        else:
            current_operation = command

        if command==2:
            point = new_point
        elif command==1:
            if region is None:
                path = {
                    'type': 'line',
                    'start': point,
                    'end': new_point,
                    }
                paths.append(path)
            else:
                if region['first'] is None:
                    region['first'] = point
                region['points'].append(point)
                region['last'] = new_point
            point = new_point
        elif command==3:
            aperture = apertures.get(selected_aperture)
            if aperture is not None:
                flashes.append({
                    'center': new_point,
                    'aperture': aperture,
                })
            point = new_point

    outline_info = choose_stencil_outline(paths)
    outline = outline_info['outline']
    outline_bounds = outline_info['bounds']

    flashes = [flash for flash in flashes if point_in_bounds(flash['center'], outline_bounds)]
    region_centers = []
    for region in regions:
        center = closed_region_center(region)
        if center is None:
            continue
        if point_in_bounds(center, outline_bounds):
            region_centers.append(center)

    pads = [flash['center'] for flash in flashes] + region_centers
    if len(pads)<3:
        raise ValueError("Stencil Gerber contains fewer than 3 usable apertures inside the outline")

    logging.info(
            "Stencil parse strategy: %s, %d pads inside outline, %.3f s",
            outline_info['strategy'],
            len(pads),
            time.time()-started)

    return {
            'outline': outline,
            'pads': pads,
            'outline_strategy': outline_info['strategy'],
            }


def sort_paths(paths):
    """
    Sorts the paths into shapes - each shape is a list of paths that are connected to each other
    """
    rest = paths[1:]

    shapes = []
    current_shape = [paths[0],]
    while len(rest):
        for idx, p in enumerate(rest):
            # check if it starts at the end of the previous segment
            if distance(p['start'], current_shape[-1]['end'])<0.01:
                break
            if distance(p['end'], current_shape[-1]['end'])<0.01:
                s = p['start']
                p['start'] = p['end']
                p['end'] = s
                p['swapped'] = True
                break
        else:
            #raise ValueError("the outline isn't a closed shape")
            shapes.append(current_shape)
            current_shape = [rest.pop(), ]
            continue

        current_shape.append(rest[idx])
        del rest[idx]

    shapes.append(current_shape)
    return shapes


def paths_to_polygon(paths):
    """
    Expand a closed path into a polygon suitable for OpenSCAD.
    """
    pol = []
    for p in paths:
        if p['type']=='arc':
            # add points across the arc
            angle_step = 1 # 1°
            angle = 0
            if p['angle']==0:
                p['angle'] = 360 # circle
            while abs(angle)<abs(p['angle']):
                pol.append(rotate_point(point=p['start'], center=p['center'], angle_deg=angle))
                angle += angle_step * (1 if p.get('swapped', False) else -1)
        else:
            pol.append(p['start'])

    return pol


def polygon_area(pol):
    """
    Return the signed area of a polygon.
    """
    area = 0
    for i in range(len(pol)):
        p1 = pol[i]
        p2 = pol[(i+1)%len(pol)]
        area += p1[0]*p2[1] - p2[0]*p1[1]
    return area/2.0


def point_in_polygon(point, pol):
    """
    Return True if point is inside pol.
    """
    inside = False
    j = len(pol)-1
    for i in range(len(pol)):
        pi = pol[i]
        pj = pol[j]
        if ((pi[1]>point[1]) != (pj[1]>point[1])):
            x_intersect = (pj[0]-pi[0]) * (point[1]-pi[1]) / (pj[1]-pi[1]) + pi[0]
            if point[0] < x_intersect:
                inside = not inside
        j = i
    return inside


def polygon_center(pol):
    """
    Return a simple center point for containment and translation.
    """
    return (sum((p[0] for p in pol))/len(pol), sum((p[1] for p in pol))/len(pol), )


def transform_polygon(pol, center, mirror_y=False, mirror_x=False):
    """
    Translate and mirror a polygon using the same transforms as the selected PCB outline.
    """
    pol = [(p[0]-center[0], p[1]-center[1],) for p in pol]
    if mirror_y:
        pol = [(p[0], -p[1]) for p in pol]
    if mirror_x:
        pol = [(-p[0], p[1]) for p in pol]
    return pol


def format_polygon(pol):
    """
    Format polygon points for OpenSCAD.
    """
    return str([list(p) for p in pol])


def find_void_polygons(shapes, selected_idx, selected_polygon, selected_center, min_area, mirror_y=False, mirror_x=False):
    """
    Find closed shapes inside selected_polygon that are large enough to fill.
    """
    void_polygons = []
    for idx, shape in enumerate(shapes):
        if idx==selected_idx:
            continue

        void_raw = paths_to_polygon(shape)
        if len(void_raw)<3:
            continue

        if abs(polygon_area(void_raw)) < min_area:
            continue

        if not point_in_polygon(polygon_center(void_raw), selected_polygon):
            continue

        void_polygons.append(transform_polygon(void_raw, selected_center, mirror_y=mirror_y, mirror_x=mirror_x))

    return void_polygons


def select_anchor_pads(points):
    if len(points)<3:
        raise ValueError("At least 3 pads are required for stencil alignment")

    farthest = None
    farthest_distance = -1
    for p1, p2 in itertools.combinations(points, 2):
        dd = distance(p1, p2)
        if dd>farthest_distance:
            farthest = (p1, p2)
            farthest_distance = dd

    third = None
    max_area = -1
    for point in points:
        if point==farthest[0] or point==farthest[1]:
            continue
        area = triangle_area(farthest[0], farthest[1], point)
        if area>max_area:
            third = point
            max_area = area

    if third is None or max_area<0.01:
        raise ValueError("Could not find 3 well-spaced stencil pads for alignment")

    return [farthest[0], farthest[1], third]


def nearest_unused_point(point, candidates, used):
    nearest_idx = None
    nearest_dist = None
    for idx, candidate in enumerate(candidates):
        if idx in used:
            continue
        dd = distance(point, candidate)
        if nearest_dist is None or dd<nearest_dist:
            nearest_idx = idx
            nearest_dist = dd
    return nearest_idx, nearest_dist


def translation_matches(anchors, pcb_points, offset):
    used = set()
    matches = []
    max_residual = 0
    for anchor in anchors:
        target = (anchor[0]+offset[0], anchor[1]+offset[1])
        idx, residual = nearest_unused_point(target, pcb_points, used)
        if idx is None:
            return None, None
        used.add(idx)
        max_residual = max(max_residual, residual)
        matches.append(pcb_points[idx])
    return max_residual, matches


def refine_translation(anchors, matches):
    dx = sum([matches[i][0]-anchors[i][0] for i in range(len(anchors))])/float(len(anchors))
    dy = sum([matches[i][1]-anchors[i][1] for i in range(len(anchors))])/float(len(anchors))
    return (dx, dy)


def transform_stencil_points(points, flip_y=False, angle_rad=0, offset=(0, 0)):
    transformed = []
    for point in points:
        p = (point[0], -point[1]) if flip_y else point
        if angle_rad:
            p = rotate_point_math(p, (0, 0), angle_rad)
        transformed.append((p[0]+offset[0], p[1]+offset[1]))
    return transformed


def find_rigid_match(stencil_points, pcb_points, tolerance=0.25):
    anchors = select_anchor_pads(stencil_points)
    best = None

    for i, j in itertools.permutations(range(len(anchors)), 2):
        a1 = anchors[i]
        a2 = anchors[j]
        anchor_dist = distance(a1, a2)
        if anchor_dist<0.01:
            continue

        for p1, p2 in itertools.permutations(pcb_points, 2):
            if abs(distance(p1, p2)-anchor_dist)>tolerance:
                continue

            angle = normalize_angle_rad(angle_between(p1, p2) - angle_between(a1, a2))
            rotated = [rotate_point_math(anchor, (0, 0), angle) for anchor in anchors]
            offset = (p1[0]-rotated[i][0], p1[1]-rotated[i][1])
            residual, matches = translation_matches(rotated, pcb_points, offset)
            if matches is None:
                continue

            refined = refine_translation(rotated, matches)
            residual, matches = translation_matches(rotated, pcb_points, refined)
            if matches is None:
                continue

            if best is None or residual<best['residual']:
                best = {
                        'offset': refined,
                        'residual': residual,
                        'anchors': anchors,
                        'angle_rad': angle,
                        'angle_deg': angle*180.0/math.pi,
                        }

    if best is not None and best['residual']<=tolerance:
        return best

    return None


def rotate_point_math(point, center, angle_rad):
    st = (point[0]-center[0], point[1]-center[1])
    return (
            center[0] + st[0]*math.cos(angle_rad) - st[1]*math.sin(angle_rad),
            center[1] + st[0]*math.sin(angle_rad) + st[1]*math.cos(angle_rad),
            )


def normalize_angle_rad(angle_rad):
    while angle_rad<=-math.pi:
        angle_rad += 2*math.pi
    while angle_rad>math.pi:
        angle_rad -= 2*math.pi
    return angle_rad


def build_point_grid(points, cell_size):
    grid = {}
    for idx, point in enumerate(points):
        key = (
                int(math.floor(point[0]/cell_size)),
                int(math.floor(point[1]/cell_size)),
                )
        grid.setdefault(key, []).append((idx, point))
    return grid


def nearest_unused_grid_point(point, grid, used, cell_size, tolerance):
    cell = (
            int(math.floor(point[0]/cell_size)),
            int(math.floor(point[1]/cell_size)),
            )
    best = None
    max_delta = max(1, int(math.ceil(tolerance/cell_size)))
    for dx in range(-max_delta, max_delta+1):
        for dy in range(-max_delta, max_delta+1):
            for idx, candidate in grid.get((cell[0]+dx, cell[1]+dy), []):
                if idx in used:
                    continue
                dd = distance(point, candidate)
                if dd>tolerance:
                    continue
                if best is None or dd<best[1]:
                    best = (idx, dd, candidate)
    return best


def validate_anchor_transform(anchors, pcb_grid, pcb_points, angle_rad, offset, tolerance):
    transformed = transform_stencil_points(anchors, angle_rad=angle_rad, offset=offset)
    used = set()
    matches = []
    residual = 0
    for point in transformed:
        match = nearest_unused_grid_point(point, pcb_grid, used, tolerance, tolerance)
        if match is None:
            return None
        used.add(match[0])
        matches.append(match[2])
        residual = max(residual, match[1])

    delta = refine_translation(transformed, matches)
    refined = (offset[0]+delta[0], offset[1]+delta[1])
    transformed = transform_stencil_points(anchors, angle_rad=angle_rad, offset=refined)
    used = set()
    residual = 0
    for point in transformed:
        match = nearest_unused_grid_point(point, pcb_grid, used, tolerance, tolerance)
        if match is None:
            return None
        used.add(match[0])
        residual = max(residual, match[1])

    return {
            'offset': refined,
            'residual': residual,
            'angle_rad': angle_rad,
            'angle_deg': angle_rad*180.0/math.pi,
            'anchors': anchors,
            }


def solve_transform_from_pair(source_a, source_b, target_a, target_b):
    angle = normalize_angle_rad(angle_between(target_a, target_b) - angle_between(source_a, source_b))
    rotated_a = rotate_point_math(source_a, (0, 0), angle)
    offset = (target_a[0]-rotated_a[0], target_a[1]-rotated_a[1])
    return angle, offset


def anchor_direct_match(stencil_points, pcb_points, tolerance=0.25):
    anchors = select_anchor_pads(stencil_points)
    pcb_anchors = select_anchor_pads(pcb_points)
    pcb_grid = build_point_grid(pcb_points, tolerance)
    best = None

    for src in ((0, 1), (1, 0)):
        for dst in itertools.permutations(range(len(pcb_anchors)), 2):
            angle, offset = solve_transform_from_pair(
                    anchors[src[0]],
                    anchors[src[1]],
                    pcb_anchors[dst[0]],
                    pcb_anchors[dst[1]])
            match = validate_anchor_transform(anchors, pcb_grid, pcb_points, angle, offset, tolerance)
            if match is not None and (best is None or match['residual']<best['residual']):
                best = match

    if best is not None:
        best['strategy'] = 'anchor_direct'
    return best


def pair_distance_match(stencil_points, pcb_points, tolerance=0.25):
    anchors = select_anchor_pads(stencil_points)
    pair = (anchors[0], anchors[1])
    anchor_dist = distance(pair[0], pair[1])
    pcb_grid = build_point_grid(pcb_points, tolerance)
    best = None

    for i in range(len(pcb_points)):
        p1 = pcb_points[i]
        for j in range(i+1, len(pcb_points)):
            p2 = pcb_points[j]
            if abs(distance(p1, p2)-anchor_dist)>tolerance:
                continue
            for source_a, source_b in ((pair[0], pair[1]), (pair[1], pair[0])):
                for target_a, target_b in ((p1, p2), (p2, p1)):
                    angle, offset = solve_transform_from_pair(source_a, source_b, target_a, target_b)
                    match = validate_anchor_transform(anchors, pcb_grid, pcb_points, angle, offset, tolerance)
                    if match is not None and (best is None or match['residual']<best['residual']):
                        best = match

    if best is not None:
        best['strategy'] = 'pair_distance'
    return best


def exhaustive_rigid_match(stencil_points, pcb_points, tolerance=0.25):
    anchors = select_anchor_pads(stencil_points)
    pcb_grid = build_point_grid(pcb_points, tolerance)
    best = None

    for i, j in itertools.permutations(range(len(anchors)), 2):
        a1 = anchors[i]
        a2 = anchors[j]
        anchor_dist = distance(a1, a2)
        if anchor_dist<0.01:
            continue

        for p1, p2 in itertools.permutations(pcb_points, 2):
            if abs(distance(p1, p2)-anchor_dist)>tolerance:
                continue

            angle, offset = solve_transform_from_pair(a1, a2, p1, p2)
            match = validate_anchor_transform(anchors, pcb_grid, pcb_points, angle, offset, tolerance)
            if match is not None and (best is None or match['residual']<best['residual']):
                best = match

    if best is not None:
        best['strategy'] = 'exhaustive_rigid'
    return best


def strategy_label(strategy):
    return getattr(strategy, '__name__', str(strategy))


def match_stencil_to_pcb_pads(stencil_points, pcb_pads, tolerance=0.25):
    pcb_points = [pad['center'] if type(pad) is dict else pad for pad in pcb_pads]
    best = None
    started = time.time()
    strategies = (
            anchor_direct_match,
            pair_distance_match,
            exhaustive_rigid_match,
            )
    early_exit_residual = tolerance * 0.5

    for flip_y in (True, False):
        variant = transform_stencil_points(stencil_points, flip_y=flip_y)
        for strategy in strategies:
            strategy_started = time.time()
            match = strategy(variant, pcb_points, tolerance=tolerance)
            elapsed = time.time()-strategy_started
            if match is None:
                logging.debug(
                        "Stencil match strategy %s (%s) failed in %.3f s",
                        strategy_label(strategy),
                        'flip_y' if flip_y else 'native',
                        elapsed)
                continue

            match['flip_y'] = flip_y
            match['strategy'] = match.get('strategy', strategy_label(strategy))
            logging.info(
                    "Stencil match strategy: %s (%s), residual %.3f mm, rotation %.3f deg, %.3f s",
                    match['strategy'],
                    'flip_y' if flip_y else 'native',
                    match['residual'],
                    match['angle_deg'],
                    elapsed)
            if best is None or match['residual']<best['residual']:
                best = match
            if match['residual']<=early_exit_residual:
                logging.info("Stencil matching completed in %.3f s", time.time()-started)
                return best
            break

    if best is not None:
        logging.info("Stencil matching completed in %.3f s", time.time()-started)
        return best

    raise ValueError("Could not match stencil apertures to PCB paste pads")


def aligned_stencil_polygon(stencil_polygon, alignment):
    return transform_stencil_points(
            stencil_polygon,
            flip_y=alignment.get('flip_y', False),
            angle_rad=alignment.get('angle_rad', 0),
            offset=alignment['offset'])


def is_supported_stencil_file(path):
    return path.lower().endswith(('.gbr', '.ger', '.gtp', '.gbp', '.gts', '.gbs'))


def automatic_lift_hole(pol):
    maxlen = 0
    maxidx = -1
    for i in range(len(pol)):
        dd = distance(pol[i], pol[(i-1)%len(pol)])
        if dd>maxlen:
            maxidx = i
            maxlen = dd

    d = min(maxlen/2, 10)
    return {
            'x': (pol[maxidx][0]+pol[(maxidx-1)%len(pol)][0])/2,
            'y': (pol[maxidx][1]+pol[(maxidx-1)%len(pol)][1])/2,
            'r': d/2,
            }


def positioned_lift_hole(pol, position):
    if position=='auto':
        return automatic_lift_hole(pol)

    bounds = polygon_bounds(pol)
    xmid = (bounds['xmin']+bounds['xmax'])/2
    ymid = (bounds['ymin']+bounds['ymax'])/2
    radius = automatic_lift_hole(pol)['r']
    positions = {
            'l': (bounds['xmin'], ymid),
            'r': (bounds['xmax'], ymid),
            't': (xmid, bounds['ymin']),
            'b': (xmid, bounds['ymax']),
            'tl': (bounds['xmin'], bounds['ymin']),
            'tr': (bounds['xmax'], bounds['ymin']),
            'bl': (bounds['xmin'], bounds['ymax']),
            'br': (bounds['xmax'], bounds['ymax']),
            }
    x, y = positions[position]
    return {
            'x': x,
            'y': y,
            'r': radius,
            }


def main():
    extensions = ('.stl', '.amf', '.png', '.pdf', '.scad')
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    # stencil margins
    parser.add_argument('-l', '--margin-left', help="Left margin (mm)", type=float, default=20)
    parser.add_argument('-r', '--margin-right', help="Right margin (mm)", type=float, default=20)
    parser.add_argument('-t', '--margin-top', help="Top margin (mm)", type=float, default=20)
    parser.add_argument('-b', '--margin-bottom', help="Bottom margin (mm)", type=float, default=20)

    # pcb properties
    parser.add_argument('-m', '--mirror', help="Mirror the PCB (to get the bottom side up)", action='store_true')
    parser.add_argument('-p', '--pcb-thickness', help="Thickness of the PCB (mm)", type=float, default=1.6)
    parser.add_argument('-s', '--shape', help="Index of the desired shape from input file", type=int, default=0)
    parser.add_argument('--fill-voids', help="Fill PCB voids larger than --min-void-area", action='store_true')
    parser.add_argument('--min-void-area', help="Minimum PCB void area to fill (mm^2)", type=float, default=15)
    parser.add_argument('--stencil-file', help="Gerber stencil file to automatically size and align the stencil opening", type=str, default=None)

    # 3D model specifics
    parser.add_argument('-f', '--frame', help="Generate stencil holding frame instead of stencil frame", action='store_true')
    parser.add_argument('-c', '--chamfer', help="Specify the percentage of the frame side length to chamfer (max 50)", type=float, default=20)
    parser.add_argument('-k', '--skip-holes', help="Don't add holes for easy removal in the fixture", action='store_true')
    parser.add_argument('--lift-hole-position', help="PCB lift cutout position", choices=('auto', 'l', 'r', 't', 'b', 'tl', 'tr', 'bl', 'br'), default='auto')
    parser.add_argument('-o', '--offset', help="Offset between the PCB/stencil and frame edge (mm)", type=float, default=0.1)
    parser.add_argument('--stencil-offset', help="Offset between the stencil and frame edge (mm). If not specified, the --offset is used", type=float, default=None)

    parser.add_argument('--base-thickness', help="Height of the base of the stencil frame (mm)", type=float, default=1)

    parser.add_argument('-d', '--debug', help="Show debugging info", action='store_true')
    parser.add_argument('-w', '--use-temp-file', help="Use temporary file when calling OpenSCAD (used by default on Windows)", action='store_true')

    parser.add_argument('--openscad', help="Path to OpenSCAD executable", type=str, default="openscad")
    parser.add_argument('infile', help="path to KiCad PCB or gerber file (.kicad_pcb, .gbr, .gm1)")
    parser.add_argument('outfile', help="path to output file (extension can be %s)"%(", ".join(extensions),))

    args = parser.parse_args()

    logfmt = '[%(levelname)s] %(message)s'
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format=logfmt)
    else:
        logging.basicConfig(level=logging.INFO, format=logfmt)

    if not any([args.outfile.endswith(ext) for ext in extensions]):
        logging.warning("unsupported output file extension")
        return 1

    try:
        subprocess.check_output((args.openscad, "-v",))
    except (OSError, subprocess.CalledProcessError):
        logging.warning("OpenSCAD executable not found on the system.")
        return 1

    if args.stencil_offset is None:
        args.stencil_offset = args.offset

    if args.infile.lower().endswith('.kicad_pcb'):
        informat = InFormat.KICAD
    elif args.infile.lower()[-4:] in ('.gbr', '.gm1'):
        informat = InFormat.GERBER
    else:
        logging.warning("invalid input file format")
        return 1

    if args.stencil_file is not None:
        if informat!=InFormat.KICAD:
            logging.error("--stencil-file requires a .kicad_pcb input so PCB paste pads can be matched")
            return 1
        if not is_supported_stencil_file(args.stencil_file):
            logging.error("--stencil-file currently supports Gerber files only")
            return 1

    shapes = []
    try:
        if informat==InFormat.KICAD:
            shapes = sort_paths(process_kicad_layer(args.infile))
        elif informat==InFormat.GERBER:
            shapes = sort_paths(process_gerber_layer(args.infile))
    except IOError:
        logging.error("error while processing the input file")
        return 1

    if len(shapes)>0:
        logging.info("Found %d closed shapes inside the file", len(shapes))
    else:
        logging.warning("No shapes found in the PCB file")
        return 1

    # TODO: find the outer shape (the one with greatest surface, for now just take the first one)
    try:
        paths = shapes[args.shape]
    except IndexError:
        logging.error("Invalid shape index (the file contains only %d closed shapes)", len(shapes))
        return

    # prepare list of points for OpenSCAD polygon (i.e. expand arcs)
    pol_raw = paths_to_polygon(paths)

    if not pol_raw:
        logging.warning("no shape found on Edge.Cuts layer")
        return 1

    # find center and translate
    pth_c = polygon_center(pol_raw)
    pol = transform_polygon(pol_raw, pth_c)

    # since the KiCAD and OpenSCAD use different y-axis direction, the polygon is mirrored
    # by default
    if informat==InFormat.KICAD:
        pol = transform_polygon(pol_raw, pth_c, mirror_y=True)

    if args.mirror:
        # mirror around y axis
        pol = [(-p[0], p[1]) for p in pol]

    void_polygons = []
    if args.fill_voids:
        if args.min_void_area < 0:
            logging.error("minimum void area must be non-negative")
            return 1

        void_polygons = find_void_polygons(
                shapes=shapes,
                selected_idx=args.shape,
                selected_polygon=pol_raw,
                selected_center=pth_c,
                min_area=args.min_void_area,
                mirror_y=(informat==InFormat.KICAD),
                mirror_x=args.mirror)
        logging.info("Filling %d PCB void(s) with area >= %s mm^2", len(void_polygons), args.min_void_area)

    base_margin = 5

    if args.stencil_file is not None:
        try:
            paste_layer = 'B.Paste' if args.mirror else 'F.Paste'
            pcb_pads = extract_kicad_paste_pads(args.infile, paste_layer)
            if len(pcb_pads)<3:
                logging.error("PCB contains fewer than 3 %s pads for stencil alignment", paste_layer)
                return 1

            stencil = parse_gerber_stencil(args.stencil_file)
            alignment = match_stencil_to_pcb_pads(stencil['pads'], pcb_pads)
            stencil_raw = aligned_stencil_polygon(stencil['outline'], alignment)
            pol_stencil = transform_polygon(stencil_raw, pth_c, mirror_y=True, mirror_x=args.mirror)
            logging.info(
                    "Using stencil file bounds; matched %s with residual %.3f mm and rotation %.3f deg",
                    paste_layer,
                    alignment['residual'],
                    alignment.get('angle_deg', 0))
        except (IOError, ValueError) as e:
            logging.error(str(e))
            return 1
    else:
        # find polygon boundaries
        bounds = polygon_bounds(pol)
        pol_stencil = [
                (bounds['xmin']-args.margin_left, bounds['ymin']-args.margin_top),
                (bounds['xmin']-args.margin_left, bounds['ymax']+args.margin_bottom),
                (bounds['xmax']+args.margin_right, bounds['ymax']+args.margin_bottom),
                (bounds['xmax']+args.margin_right, bounds['ymin']-args.margin_top)
                ]

    stencil_bounds_for_base = polygon_bounds(pol_stencil)
    pol_base = [
            (stencil_bounds_for_base['xmin']-base_margin, stencil_bounds_for_base['ymin']-base_margin),
            (stencil_bounds_for_base['xmin']-base_margin, stencil_bounds_for_base['ymax']+base_margin),
            (stencil_bounds_for_base['xmax']+base_margin, stencil_bounds_for_base['ymax']+base_margin),
            (stencil_bounds_for_base['xmax']+base_margin, stencil_bounds_for_base['ymin']-base_margin)
            ]

    # OpenSCAD code generation start
    # ----------------------------------
    code = ""

    if args.frame:
        # generate just the frame to hold the stencil in place
        stencil_bounds = {
                'xmin': min([p[0] for p in pol_stencil]),
                'xmax': max([p[0] for p in pol_stencil]),
                'ymin': min([p[1] for p in pol_stencil]),
                'ymax': max([p[1] for p in pol_stencil]),
                }
        # add chamfer to frame
        args.chamfer = min((args.chamfer, 50,))
        chamf = min([(stencil_bounds['xmax']-stencil_bounds['xmin'])*args.chamfer/100.0, (stencil_bounds['ymax']-stencil_bounds['ymin'])*args.chamfer/100.0])
        pol_frame_out = [
            (stencil_bounds['xmin']+chamf, stencil_bounds['ymin']),
            (stencil_bounds['xmax']-chamf, stencil_bounds['ymin']),

            (stencil_bounds['xmax'], stencil_bounds['ymin']+chamf),
            (stencil_bounds['xmax'], stencil_bounds['ymax']-chamf),

            (stencil_bounds['xmax']-chamf, stencil_bounds['ymax']),
            (stencil_bounds['xmin']+chamf, stencil_bounds['ymax']),

            (stencil_bounds['xmin'], stencil_bounds['ymax']-chamf),
            (stencil_bounds['xmin'], stencil_bounds['ymin']+chamf),
            ]

        frame_out = "linear_extrude(height=5) offset(r={offset}) polygon(points={points}, convexity=10);".format(points=str([list(p) for p in pol_frame_out]), offset=args.stencil_offset)
        frame_in = "translate([0, 0, -2]) linear_extrude(height=10) offset(r={offset}) polygon(points={points}, convexity=10);".format(points=str([list(p) for p in pol_frame_out]), offset=-5)

        code="difference(){{ {fout} {fin} }}".format(fout=frame_out, fin=frame_in)

    else:
        # generate the actual stencil frame

        # arrange cutouts for PCB and stencil
        pcb_cutout_outer = "linear_extrude(height=10) offset(r={offset}) polygon(points={points}, convexity=10);".format(points=format_polygon(pol), offset=args.offset)
        if void_polygons:
            pcb_void_fills = ""
            for void_pol in void_polygons:
                pcb_void_fills += "linear_extrude(height=12) offset(r={offset}) polygon(points={points}, convexity=10);".format(points=format_polygon(void_pol), offset=-args.offset)
            pcb_cutout = "difference(){{ {outer} union(){{ {voids} }} }}".format(outer=pcb_cutout_outer, voids=pcb_void_fills)
        else:
            pcb_cutout = pcb_cutout_outer

        stencil_cutout = "translate([0, 0, {thick}]) linear_extrude(height=5) offset(r={offset}) polygon(points={points});".format(points=format_polygon(pol_stencil), offset=args.stencil_offset, thick=args.pcb_thickness)

        base = "translate([0, 0, {vert}]) linear_extrude(height={height}) polygon(points={points});".format(points=format_polygon(pol_base), height=2+args.pcb_thickness+args.base_thickness, vert=-args.base_thickness+0.005) # add 5um to avoid z-fighting

        holes = ""
        if not args.skip_holes:
            # add hole on the longest side of the PCB for easier PCB extraction
            lift_hole = positioned_lift_hole(pol, args.lift_hole_position)
            holes = "translate([{x}, {y}, 0]) cylinder(h=20, r={r}, center=true, $fn=100);".format(x=lift_hole['x'], y=lift_hole['y'], r=lift_hole['r'])

            # add holes for the stencil removal
            for i in range(4):
                holes += "translate([{x}, {y}, 0]) cylinder(h=20, r={r}, center=true, $fn=100);".format(x=(pol_base[i][0]+pol_base[(i-1)%len(pol_base)][0])/2, y=(pol_base[i][1]+pol_base[(i-1)%len(pol_base)][1])/2, r=7+base_margin)

        code = "difference(){{ \n{base} union(){{ {pcb} {stenc} {holes} }} }}".format(base=base, pcb=pcb_cutout, stenc=stencil_cutout, holes=holes)

    # produce the output file
    if args.outfile.endswith(".scad"):
        with open(args.outfile, "w") as f:
            f.write(code)
    else:
        if args.use_temp_file or os.name!='posix':
            # Windows will report "command line too long" if all code is passed as a command line argument
            # that's why we'll use temporary file
            fd, name = tempfile.mkstemp()
            os.write(fd, code.encode('utf-8'))
            os.close(fd)
            cmd = (args.openscad, name, '-o', args.outfile,)
            try:
                subprocess.check_output(cmd)
            except subprocess.CalledProcessError as e:
                print("Failed to generate the output file")
                print(str(e))
            os.unlink(name)

        else:
            cmd = (args.openscad, '/dev/null', '-D', code, '-o', args.outfile,)
            try:
                subprocess.check_output(cmd)
            except subprocess.CalledProcessError as e:
                print("Failed to generate the output file")
                print(str(e))

    return 0


if __name__=='__main__':
    sys.exit(main())
