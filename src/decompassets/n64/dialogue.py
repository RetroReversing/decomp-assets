"""Read scene-tagged dialogue scripts from checked RAW! directory entries."""

import re
import struct

from ..formats import AssetError, integer
from .resource_inspection import table

HEADERS = {b'KEY:': 'English', b'SCHL\xdcSSEL:': 'German'}
SIGNATURE = re.compile(rb'RAW!....(?:KEY:|SCHL\xdcSSEL:)\t', re.S)
SCENE = re.compile(r'^<([A-Z0-9_]{2,40})>[ \t]*(.*)$')
SPEAKER = re.compile(r'^\s*([A-Z])=[ \t]+(.+)$')
CUE = re.compile(r'^([A-Z][A-Z0-9-]{7})[ ]*\t+[ \t]*(\S.*)$')
ROW = struct.Struct('>III')
MAX_SCRIPT = 256 * 1024
MAX_DIRECTORY = 2048
MAX_SCENES = 256
MAX_LINES = 4096
RECORD_TAGS = (b'RNC\1', b'RNX\1', b'RAW!', b'FILL')


def _document(data, check=lambda: None):
    if len(data) > MAX_SCRIPT or any(c < 32 and c not in (9, 10, 13) for c in data):
        return None
    header = bytes(data.split(b'\t', 1)[0])
    if header not in HEADERS:
        return None
    speakers = {}
    scenes = []
    seen = set()
    heading_language = header.decode('cp1252')
    finished = False
    for index, original in enumerate(data.decode('cp1252', errors='replace').splitlines()):
        if index % 64 == 0:
            check()
        line = original.rstrip()
        if finished:
            if line:
                return None
            continue
        if heading := SCENE.fullmatch(line):
            name, caption = heading.groups()
            if name == 'END':
                finished = True
                continue
            if len(scenes) >= MAX_SCENES or len(caption) > 160:
                return None
            scenes.append(dict(name=name, caption=caption, lines=[]))
        elif not scenes:
            if speaker := SPEAKER.fullmatch(line.removeprefix(heading_language)):
                code, name = speaker.groups()
                if code in speakers or len(name) > 128:
                    return None
                speakers[code] = name
        elif cue := CUE.fullmatch(line):
            identifier, text = cue.groups()
            if identifier in seen or len(seen) >= MAX_LINES or len(text) > 2048:
                return None
            seen.add(identifier)
            speaker = identifier[-1]
            scenes[-1]['lines'].append(dict(cue_id=identifier, speaker=speakers.get(speaker, speaker),
                                             text=text, speaker_code=speaker, scene=scenes[-1]['name']))
    if not finished or not speakers or not scenes or not seen:
        return None
    return HEADERS[header], speakers, scenes


def _record(image, offset):
    if not 0 <= offset <= len(image) - 12 or image[offset:offset + 4] != b'RAW!':
        return None
    size, = struct.unpack_from('>I', image, offset + 4)
    end = offset + 8 + size
    trailer = (end + 3) & ~3
    if not 0 < size <= MAX_SCRIPT or trailer + 4 > len(image) or image[trailer:trailer + 4] != b'END!':
        return None
    return image[offset + 8:end], trailer + 4


def _directory(image, offset, data, end):
    key = struct.pack('>II', len(data), sum(data))
    start = max(4, offset - 1024 * 1024)
    for _ in range(32):
        entry = image.find(key, start, offset) - 4
        if entry < 0:
            break
        start = entry + 5
        relative, = struct.unpack_from('>I', image, entry)
        root = offset - relative
        if not 0 <= root <= entry or root % 4 or (entry - root) % ROW.size:
            continue
        size, = struct.unpack_from('>I', image, root)
        if (not 2 * ROW.size <= size <= MAX_DIRECTORY * ROW.size or size % ROW.size
                or not entry < root + size <= offset):
            continue
        previous = root + size - 1
        for relative, length, checksum in ROW.iter_unpack(image[root:root + size]):
            at = root + relative
            if not previous < at <= len(image) - 4 or not 0 < length <= 4 * 1024 * 1024 or checksum > 255 * length:
                break
            if image[at:at + 4] not in RECORD_TAGS or (previous == offset and at != end):
                break
            previous = at
        else:
            return root
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    for index, match in enumerate(SIGNATURE.finditer(image)):
        check()
        if index >= 128:
            break
        offset = match.start()
        if offset % 4 or not (record := _record(image, offset)):
            continue
        data, end = record
        if (root := _directory(image, offset, data, end)) is None or not (doc := _document(data, check)):
            continue
        language, speakers, scenes = doc
        assets.append(dict(offset=offset, size=end - offset, kind='strings', media='metadata', confidence='validated',
                           label=f'{language} dialogue script', layout='dialogue-script', resource_type='dialogue',
                           directory_offset=root, dialogue=dict(language=language, speakers=speakers,
                               scenes=[dict(name=s['name'], caption=s['caption'], lines=len(s['lines'])) for s in scenes]),
                           reason='The directory size and byte sum, scene tags, cue IDs, and script terminator agree.',
                           preview_settings=dict(format='auto', source='rom', offset=offset)))
    return assets


def preview(image, asset, selection):
    record = _record(image, asset['offset'])
    if record is None or not (doc := _document(record[0])):
        raise AssetError('The dialogue script changed. Rescan ROM Explorer.')
    language, speakers, scenes = doc
    chosen = integer(selection.get('dialogue_scene', 0), 'Scene', 0, len(scenes))
    speaker = selection.get('dialogue_speaker', '')
    if not isinstance(speaker, str) or (speaker and speaker not in speakers):
        raise AssetError('Choose a speaker from the script.')
    source = scenes[chosen - 1:chosen] if chosen else scenes
    lines = [line for scene in source for line in scene['lines'] if not speaker or line['speaker_code'] == speaker]
    columns = ['index', 'scene', 'cue_id', 'speaker', 'text']
    title = source[0]['name'] if chosen else 'All dialogue cues'
    records = table(title, columns, len(lines), lambda i: lines[i], selection)
    audio = asset.get('cue_audio', {})
    for row in records['rows']:
        if row['cue_id'] in audio:
            row['audio_offset'] = audio[row['cue_id']]
    return dict(media='metadata', title=f'{language} dialogue script',
                table=records, settings=dict(format='auto', source='rom', offset=asset['offset'],
                                            dialogue_scene=chosen, dialogue_speaker=speaker))
