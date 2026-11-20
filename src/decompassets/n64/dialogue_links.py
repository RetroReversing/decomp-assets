"""Resolve dialogue resource links using filename keys and verified directory entries."""

import re
import struct
from collections import defaultdict

from ..rnc import RncError, unpack_sum32
from . import dialogue
from .emsh_links import _directory as packed_directory

KEY_ROW = struct.Struct('>IhH')
VOICE_ROW = struct.Struct('>HH')
SPEECH_END = b'\0\0\0\0\xff\xff\0\0'
CUTSCENE_END = b'\xff\xff\xff\xff\xff\xff\0\0'
CUTSCENE_PATH = re.compile(rb'(cutscene\\scripts\\english\\[a-z0-9_\\]{1,100}?)([0-9]{2,4})\.ncs\0')
NUMERIC_CUE = re.compile(r'S([0-9]{6}[A-Z])')
MAX_ROWS = 2048


def _filename_key(path):
    key = 0
    salt = len(path) * 8192 | len(path)
    mask = 0xffffffff
    for index, char in enumerate(path.upper()):
        if not (48 <= char <= 57 or 65 <= char <= 90):
            continue
        key ^= (char << (index & 7)) ^ salt
        amount = (char + index) & 7
        key = ((key << amount) | (key >> (32 - amount))) & mask
        salt = ((salt >> amount) | (salt << (32 - amount))) & mask
    return key


def _keys_before(image, end, lower, limit, names=None):
    keys = {}
    ids = set()
    for at in range(end - KEY_ROW.size, lower - 1, -KEY_ROW.size):
        key, index, pad = KEY_ROW.unpack_from(image, at)
        if (pad or not 0 <= index < limit or key in (0, 0xffffffff) or key in keys or index in ids
                or (names is not None and key not in names)):
            break
        keys[key] = index
        ids.add(index)
    return keys


def _voice_map(image, start, count, target_count):
    pairs = {}
    for at in range(start, min(len(image) - VOICE_ROW.size + 1, start + count * VOICE_ROW.size),
                    VOICE_ROW.size):
        source, target = VOICE_ROW.unpack_from(image, at)
        if source >= count or target >= target_count or source in pairs:
            break
        pairs[source] = target
    targets = set(pairs.values())
    if len(targets) >= 4 and targets == set(range(len(targets))):
        return pairs
    return {}


def _speech_directory(image, target_root, count, check):
    needle = struct.pack('>I', dialogue.ROW.size * count)
    begin = max(0, target_root - 128 * 1024)
    while (root := image.find(needle, begin, target_root)) != -1:
        check()
        begin = root + 4
        if root % 4:
            begin = root + 1
            continue
        offsets = packed_directory(image, root)
        if not offsets or len(offsets) != count:
            continue
        last = offsets[-1]
        packed, = struct.unpack_from('>I', image, last + 8)
        trailer = (last + 18 + packed + 3) & ~3
        if target_root in (trailer + 4, trailer + 8):
            return offsets
    return []


def _speech(image, cues, target_root, targets, check):
    cue_keys = defaultdict(list)
    for cue in cues:
        match = NUMERIC_CUE.fullmatch(cue)
        if match:
            name = match[1].lower().encode('ascii')
            path = b'audio\\speech\\english\\level' + name[:2] + b'\\scene' + name[2:4] + b'\\'
            cue_keys[_filename_key(path + name + b'.wav')].append(cue)

    candidates = []
    end = 0
    while (end := image.find(SPEECH_END, end)) != -1:
        at = end
        end += len(SPEECH_END)
        if at % 4:
            continue
        check()
        keys = _keys_before(image, at, max(0, at - MAX_ROWS * KEY_ROW.size), MAX_ROWS)
        count = len(keys)
        if count < 4 or set(keys.values()) != set(range(count)) or len(keys.keys() & cue_keys.keys()) < 4:
            continue
        voices = _voice_map(image, end, count, len(targets))
        if not voices or not (offsets := _speech_directory(image, target_root, count, check)):
            continue
        links = {}
        for key in keys.keys() & cue_keys.keys():
            index = keys[key]
            if index not in voices or len(cue_keys[key]) != 1:
                continue
            check()
            offset = offsets[index]
            length, packed = struct.unpack_from('>II', image, offset + 4)
            if length > 16 * 1024:
                continue
            try:
                metadata = unpack_sum32(image[offset:offset + 18 + packed], max_output=16 * 1024)
            except RncError:
                continue
            if len(metadata) >= 12 and metadata[:4] == b'FFIR' and metadata[8:12] == b'EVAW':
                links[cue_keys[key][0]] = targets[voices[index]]
        if links:
            candidates.append(links)
    return candidates[0] if len(candidates) == 1 else {}


def _cutscenes(image, root, targets, check):
    size, = struct.unpack_from('>I', image, root)
    offsets = [root + relative for relative, _, _ in dialogue.ROW.iter_unpack(image[root:root + size])]
    scripts = {}
    for path in CUTSCENE_PATH.finditer(image):
        check()
        width = len(path[2])
        names = defaultdict(list)
        for i in range(10 ** width):
            if i % 256 == 0:
                check()
            name = path[1] + str(i).zfill(width).encode('ascii') + b'.ncs'
            names[_filename_key(name)].append(name)
        lower = max(0, path.start() - 512)
        for sentinel in re.finditer(re.escape(CUTSCENE_END), image[lower:path.start()]):
            end = lower + sentinel.start()
            if end % 4:
                continue
            keys = _keys_before(image, end, max(0, end - 64 * KEY_ROW.size), len(offsets), names)
            if len(keys) < 4:
                continue
            if any(offsets[index] not in targets for index in keys.values()):
                continue
            for key, index in keys.items():
                scripts.setdefault(index, set()).update(names[key])
    return [
        dict(offset=offsets[index], label=next(iter(names)).decode('ascii').replace('\\', '/').split('/', 3)[-1]
             if len(names) == 1 else f'Cutscene resource {index}')
        for index, names in sorted(scripts.items(), key=lambda item: (min(item[1]), item[0]))
    ]


def link(image, assets, check=lambda: None):
    audio = defaultdict(list)
    cutscenes = set()
    for asset in assets:
        if asset.get('audio_kind') == 'dean stream':
            audio[asset['table_offset']].append(asset['offset'])
        if asset.get('layout') == 'scene-records' and asset.get('label') == 'NCS cutscene commands':
            cutscenes.add(asset['offset'])
    for asset in assets:
        if asset.get('dialogue', {}).get('language') != 'English':
            continue
        if audio:
            record = dialogue._record(image, asset['offset'])
            doc = dialogue._document(record[0], check) if record else None
            if doc:
                cues = [line['cue_id'] for scene in doc[2] for line in scene['lines']]
                matches = [_speech(image, cues, root, sorted(offsets), check) for root, offsets in audio.items()]
                matches = [mapping for mapping in matches if mapping]
                if len(matches) == 1:
                    asset['cue_audio'] = matches[0]
        if cutscenes:
            related = _cutscenes(image, asset['directory_offset'], cutscenes, check)
            if related:
                asset['cutscene_resources'] = related
