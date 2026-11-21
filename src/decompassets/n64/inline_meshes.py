"""Indexed F3DEX2 lists with a per-object vertex segment and linked headers."""

import re
import struct
from bisect import bisect_right
from collections import defaultdict
from itertools import pairwise

from . import display_meshes

_HEADER_TRAILER = re.compile(rb'\x00\x00\x01\x01\xff{4}\x7f{3}\x00')
_DIRECTORY = re.compile(rb'(?=\x80[\x00-\x7f]..\x80[\x00-\x7f]..)', re.S)
_WORD = struct.Struct('>I')
_HEADER_BYTES = 32
_SEARCH = 0x38000


def _headers(image, check):
    headers = [match.start()-20 for match in _HEADER_TRAILER.finditer(image)
               if match.start() >= 20 and match.start()%8 == 4]
    anchors = defaultdict(list)
    for previous, current in pairwise(headers):
        check()
        if not 40 <= current-previous < 0x8000 or image[current-8:current] != b'\xdf'+bytes(7):
            continue
        address, = _WORD.unpack_from(image,current+16)
        if 0x80000000 <= address < 0x80800000 and address%8 == 0:
            anchors[previous+_HEADER_BYTES-(address & 0xffffff)].append(current)
    return headers, anchors


def _groups(image, headers, anchors, check):
    header_set = set(headers)
    for displacement, markers in anchors.items():
        if len(markers) < 3:
            continue
        start, end = max(0,markers[0]-_SEARCH), min(len(image),markers[-1]+_SEARCH)
        for candidate in _DIRECTORY.finditer(image,start,end):
            cursor = candidate.start()
            if cursor%4 or cursor+12 > len(image):
                continue
            check()
            vertex, first = struct.unpack_from('>2I',image,cursor)
            vertex = (vertex & 0xffffff)+displacement
            first = (first & 0xffffff)+displacement
            if first not in header_set or vertex in header_set or vertex%8 or not 0 <= vertex < first <= vertex+0x10000:
                continue
            entries = []
            for cursor in range(cursor+4,min(cursor+4*65,len(image)-3),4):
                address, = _WORD.unpack_from(image,cursor)
                if not address:
                    if entries:
                        yield vertex, entries, displacement
                    break
                mapped = (address & 0xffffff)+displacement
                if (not 0x80000000 <= address < 0x80800000 or mapped not in header_set
                        or (entries and mapped <= entries[-1])):
                    break
                entries.append(mapped)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    headers, anchors = _headers(image,check)
    header_set = set(headers)
    candidates = defaultdict(set)
    for vertex, entries, displacement in _groups(image,headers,anchors,check):
        for entry in entries:
            address, = _WORD.unpack_from(image,entry+16)
            mapped = (address & 0xffffff)+displacement-_HEADER_BYTES
            if 0x80000000 <= address < 0x80800000 and mapped in header_set and vertex < mapped < entry:
                candidates[mapped].add(vertex)
    result = []
    for header, mappings in sorted(candidates.items()):
        check()
        start = header+_HEADER_BYTES
        next_header = bisect_right(headers,header)
        end = headers[next_header] if next_header < len(headers) else len(image)
        validated = []
        for vertex in mappings:
            parsed = display_meshes.geometry(image,start,end,{1: vertex},vertex_end=header)
            if parsed and len(set(parsed[1])) >= 3:
                validated.append((vertex,parsed))
        if len(validated) != 1:
            continue
        vertex, (end, vertices, faces) = validated[0]
        result.append(dict(offset=start,size=end-start,kind='3d model',layout='f3dex-mesh',confidence='validated',
                           label='Indexed F3DEX2 mesh',media='model',vertices=len(vertices),triangles=len(faces),
                           address_maps=[(1,vertex)],vertex_end=header,
                           reason='Linked headers and the object directory resolve the segmented vertex loads.',
                           preview_settings=dict(format='auto',source='rom',offset=start)))
    return result
