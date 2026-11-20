"""Inspect indexed Eurocom model archives and their neighboring resource tables."""

import base64
import math
import re
import struct
from collections import Counter
from itertools import islice

from .. import formats
from . import edl, eurocom_mesh, mort, musyx, musyx_project, musyx_render, musyx_song
from .resource_inspection import table

WORD = struct.Struct('>I')
INDEX = struct.Struct('>4I')
ENTRY = struct.Struct('>12I')
TEX = struct.Struct('>BxHH2xI')
SAMPLE = struct.Struct('>HHIIHHIII')
ANIMATION = struct.Struct('>HHI6f')
GROUP = struct.Struct('>IHH')
SONG = struct.Struct('>IIHH')
PAL = struct.Struct('>B3xI')
EDL_TAG = re.compile(rb'EDL[\x00-\x02\x80-\x82]')
INDEX_START = re.compile(rb'(?=(?:\x00(?!\x00{3})...\x00{10}..){4})', re.S)


def _word(image, at):
    return WORD.unpack_from(image, at)[0]


def _entries(image, index, base):
    entries = []
    seen = set()
    for at in range(index, min(base, index + 2049 * INDEX.size), INDEX.size):
        offset, reserved, cache, nodes = INDEX.unpack_from(image, at)
        if not (offset or reserved or cache or nodes):
            return entries if len(entries) >= 4 else None
        header = base + offset
        if (reserved or cache or not 0 < nodes <= 8192 or header % 4
                or not base <= header <= len(image) - ENTRY.size or header in seen):
            return None
        fields = ENTRY.unpack_from(image, header)
        for pos, stride in enumerate((68, 28, 8, 12, 1, 1)):
            off, count = fields[2*pos:2*pos+2]
            if count and (off + count * stride > header - base or (not off and pos < 4)):
                return None
        entries.append((header, nodes, fields))
        seen.add(header)
    return None


def _find_archive(image, blocks, check):
    # In this layout the first EDL component starts the archive. The program's
    # index is a separate array of relative offsets and empty RAM cache fields.
    for base in islice(blocks, 8):
        for match in INDEX_START.finditer(image, max(0, base - 8 * 1024 * 1024), base):
            check()
            index = match.start()
            if index % 4:
                continue
            entries = _entries(image, index, base)
            if entries and len(entries) >= 8 and sum(
                base + f[j] in blocks for _, _, f in entries for j in (8, 10)
            ) >= len(entries):
                return index, base, entries
    return None


def _blob(image, blocks, base, offset, length):
    at = base + offset
    stored = blocks.get(at) or edl.header(image, at)
    if stored is None:
        return image[at:at + length]
    if length != stored[1]:
        raise formats.AssetError('An EDL archive component has a mismatched extent.')
    return edl.unpack(image, at)


def _textures(image, base, fields, blocks):
    _, _, _, _, ptable, palettes, ttable, textures, pb, pn, tb, tn = fields
    p = PAL.iter_unpack(image[base + ptable:base + ptable + palettes * PAL.size])
    t = TEX.iter_unpack(image[base + ttable:base + ttable + textures * TEX.size])
    psize = (blocks.get(base + pb) or edl.header(image, base + pb) or (0, pn, pn))[2]
    tsize = (blocks.get(base + tb) or edl.header(image, base + tb) or (0, tn, tn))[2]
    rows = []
    for index, (flags, w, h, offset) in enumerate(t):
        width, height = w + 1, h + 1
        ci8 = flags & 1
        length = width * height if ci8 else (width * height + 1) // 2
        if width > 2048 or height > 2048 or offset + length > tsize:
            return []
        palette = next(p, None)
        if palette and 2 * (palette[0] + 1 + palette[1]) > psize:
            return []
        if palette and palette[0] in (15, 255):
            rows.append((index, flags, width, height, offset, length, palette))
    return rows


def _asset(offset, size, label, layout, kind='container', **facts):
    return dict(offset=offset, size=size, label=label, layout=layout, kind=kind, media='metadata',
                confidence='validated', reason='Resource offsets and record extents agree.',
                preview_settings=dict(source='rom', format='auto', offset=offset), **facts)


def _mort(image, check):
    for hit in islice(re.finditer(b'MORT', image), 512):
        at = hit.start()
        for count in range(8, min(2048, at // 4 - 1)):
            base = at - count * 4
            if _word(image, base - 4) != count or _word(image, base) != 0x1000000 | (at + 4 - base):
                continue
            clips = []
            for word, in WORD.iter_unpack(image[base:at]):
                check()
                offset = base + (word & 0xffffff) - 4
                if (word >> 24 != 1 or not at <= offset <= len(image) - mort.HEADER.size
                        or clips and offset < clips[-1]['offset'] + clips[-1]['size']):
                    break
                magic, frames, rate, words = mort.HEADER.unpack_from(image, offset)
                size = words * 4
                if (magic != b'MORT' or not frames or not 4000 <= rate <= 48000
                        or size <= mort.HEADER.size or offset + size > len(image)):
                    break
                # Each encoded frame represents 160 mono PCM samples.
                clips.append(dict(offset=offset, size=size, rate=rate, samples=frames * mort.SAMPLES_PER_FRAME,
                                  codec='Factor 5 MORT', label=str(len(clips)), preview_available=size<=formats.MAX_BYTES))
            if len(clips) == count:
                return _asset(base - 4, at - base + 4, 'MORT speech index', 'eurocom-speech',
                              kind='audio', audio_kind='indexed speech', samples=clips) | {'media':'audio'}
    return None


def _scenes(image, index, base, entries):
    first = (entries[-1][0] + ENTRY.size + 15) & ~15
    needle = WORD.pack(first - base)
    for match in re.finditer(re.escape(needle), image[:index]):
        start = match.start()
        if start % 4:
            continue
        previous = first - 1
        offsets = []
        for at in range(start, min(start + 1024, index), 4):
            relative = _word(image, at)
            if not relative and len(offsets) >= 8:
                return _asset(start, len(offsets)*4, 'Scene script index', 'eurocom-scenes', indices=offsets)
            offset = base + relative
            if not previous < offset < min(first + 512 * 1024, len(image)) or offset % 16:
                break
            offsets.append(offset)
            previous = offset
    return None


def _dialogue(image, last_scene):
    # This three-language layout stores equal length indices before a common
    # string pool. The reader has a fixed 272-entry stride for each language.
    count, languages = 272, ('English', 'French', 'German')
    extent = count * 4 * len(languages)
    for root in range(last_scene + 4, min(last_scene + 24 * 1024, len(image) - extent), 4):
        prefix = struct.unpack_from('>4I', image, root)
        if not all(extent <= v < 65536 for v in prefix) or not prefix[0] > prefix[1] > prefix[2] > prefix[3]:
            continue
        values = [v for v, in WORD.iter_unpack(image[root:root+extent])]
        if not all(extent <= v < 65536 and root+v < len(image) for v in values):
            continue
        limit = min(root+65536, len(image))
        ends = [image.find(b'\0', root+v, limit) for v in values]
        if min(ends) < 0 or any(end-root-v>2048 for end,v in zip(ends,values)):
            continue
        if sum(end > root+v and 32 <= image[root+v] < 127 for end,v in zip(ends,values)) < len(values)*0.7:
            continue
        return [_asset(root+i*count*4, count*4, f'{language} dialogue index', 'eurocom-dialogue',
                       kind='strings', directory_offset=root, language=language, data_base=root, count=count)
                for i,language in enumerate(languages)]
    return []


def _animation(image, index, base, check):
    # Skeleton groups are packed consecutively with a 32-byte separator;
    # the first group begins immediately after the animation record table.
    shape = re.compile(rb'(?=(?:\x00...(?:\x00[\x01-\x40])..){8})', re.S)
    for match in shape.finditer(image, index, min(index + 0x20000, base)):
        at = match.start()
        if at % 4:
            continue
        check()
        groups = []
        end_offset = None
        for ptr in range(at, min(at + 256 * GROUP.size, base - GROUP.size), GROUP.size):
            relative, bones, flags = GROUP.unpack_from(image, ptr)
            if relative == bones == flags == 0:
                break
            if not 0 < bones <= 64 or end_offset not in (None, relative):
                groups = []
                break
            groups.append((relative, bones))
            end_offset = relative + 32 * (bones + 1)
        if len(groups) < 8:
            continue
        lower = max(0, base - 512 * 1024)
        for stop in re.finditer(rb'\0\0\xff\xff\0{4}', image[lower:base]):
            end = lower + stop.start()
            start_data = end - groups[0][0]
            if end % 4 or not 0 <= start_data < end or start_data + end_offset > base:
                continue
            count = 0
            for row in range(end - ANIMATION.size, max(start_data, end-4096*ANIMATION.size), -ANIMATION.size):
                frames, flags, relative, *values = ANIMATION.unpack_from(image, row)
                group = flags & 0x7fff
                if not frames or group >= len(groups) or not all(map(math.isfinite, values)):
                    break
                bones = groups[group][1]
                stride = 4*bones + 6*(bones if flags & 0x8000 else 1)
                if start_data + relative + frames*stride > row:
                    break
                count += 1
                if not relative:
                    if count >= 8:
                        return _asset(row, count*ANIMATION.size, 'Skeletal animation index', 'eurocom-animation',
                                      kind='animation', count=count, group_bones=[bones for _,bones in groups],
                                      data_base=start_data)
                    break
    return None


def _music(image, index, archive_end, speech):
    # Song records carry absolute ROM extents and a small group/song ID pair.
    upper = speech['offset']
    for start in range(0, index - 8*SONG.size, 4):
        lo, hi, group, song = SONG.unpack_from(image, start)
        if not archive_end < lo < hi <= upper or not (0 < group < 256 and 0 <= song < 256):
            continue
        songs = []
        for at in range(start, min(index - SONG.size + 1, start+128*SONG.size), SONG.size):
            lo, hi, group, song = SONG.unpack_from(image, at)
            if lo == hi == group == song == 0 and len(songs) >= 8:
                ordered = sorted(songs)
                if all(a[1] <= b[0] for a,b in zip(ordered, ordered[1:])):
                    return _asset(start, len(songs)*SONG.size, 'MusyX song index', 'eurocom-songs',
                                  kind='music sequence', songs=songs)
                break
            if not archive_end < lo < hi <= upper or not (0 < group < 256 and 0 <= song < 256):
                break
            songs.append((lo,hi,group,song))
    return None


def _samples(image, start, end, check):
    # Sorted IDs and runs of sample descriptors lead to an all-ones terminator.
    shape = re.compile(rb'(?=(?:..\0\0....\0{4}\x3c\0..\x03...........){3})', re.S)
    for match in shape.finditer(image, start, min(start+1024*1024, end)):
        at = match.start()
        if at % 4:
            continue
        check()
        rows = []
        previous_id = -1
        for pos in range(at, min(end-SAMPLE.size,at+2048*SAMPLE.size), SAMPLE.size):
            if image[pos:pos+4] == b'\xff'*4 and len(rows) >= 8:
                data_base = (pos + 4 + 15) & ~15
                offsets = sorted({relative for _,relative,*_ in rows})
                if offsets[0] == 0 and data_base+offsets[-1] < end:
                    extents = {a:b-a for a,b in zip(offsets,offsets[1:]+[end-data_base])}
                    samples = [dict(offset=data_base+relative, size=extents[relative], rate=rate,
                                    codec='MusyX ADPCM', label=str(identifier), samples=length, root_key=root_key,
                                    loop_start=loop_start, loop_end=loop_end,
                                    preview_available=musyx.byte_length(length)<=extents[relative])
                               for identifier,relative,rate,length,root_key,loop_start,loop_end in rows]
                    return _asset(at, len(rows)*SAMPLE.size, 'MusyX sample directory', 'eurocom-samples',
                                  kind='audio', data_base=data_base, bank_end=end, count=len(rows),
                                  samples=samples, audio_kind='indexed sample directory') | {'media':'audio'}
                break
            identifier, zero, relative, reserved, tuning, rate, encoded, loop_start, loop_size = SAMPLE.unpack_from(image, pos)
            if (identifier <= previous_id or zero or reserved or not 4000 <= rate <= 48000
                    or encoded >> 24 != 3 or not encoded & 0xffffff):
                break
            length = encoded & 0xffffff
            loop_end = loop_start + loop_size if loop_size and loop_start+loop_size <= length else 0
            rows.append((identifier, relative, rate, length, tuning >> 8, loop_start, loop_end))
            previous_id = identifier
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    blocks = {}
    for match in islice(EDL_TAG.finditer(image), 20000):
        check()
        offset = match.start()
        if offset % 4 == 0 and (info := edl.header(image, offset)):
            blocks[offset] = info[:3]
    if not blocks:
        return []
    found = _find_archive(image, blocks, check)
    if found is None:
        result = []
        expanded = 0
        for offset, (method, size, decoded) in blocks.items():
            if expanded + decoded > 64 * 1024 * 1024:
                break
            expanded += decoded
            check()
            try:
                edl.unpack(image, offset)
            except formats.AssetError:
                continue
            result.append(_asset(offset, size, f'EDL method {method} stream', 'edl-stream',
                                 kind='compressed', expanded_size=decoded))
        return result
    index, base, entries = found
    archive_end = entries[-1][0] + ENTRY.size
    counts = Counter(m for offset,(m,_,_) in blocks.items() if base <= offset < archive_end)
    assets = [_asset(index, len(entries)*INDEX.size, 'EDL model and level archive index', 'eurocom-index',
                     archive_base=base, method_counts=dict(counts))]
    texture_total = 0
    mesh_info = {}
    for i, (offset, nodes, fields) in enumerate(entries):
        check()
        if i % 32 == 0:
            progress(dict(phase='Checking EDL archive entries', done=i, total=len(entries)))
        asset = _asset(offset, ENTRY.size, f'EDL archive entry {i}', 'eurocom-entry',
                       archive_base=base, resource_id=i, nodes=nodes)
        rows = _textures(image, base, fields, blocks)
        if rows:
            _, flags, w, h, _, _, _ = rows[0]
            bank = _asset(base+fields[6], fields[7]*TEX.size, f'EDL textures · entry {i}', 'eurocom-textures',
                          kind='image', archive_base=base, entry_offset=offset)
            bank.update(media='image', texture_count=len(rows), frames=1, palettes=fields[5],
                        texture_groups=[(0, [row[0] for row in rows])])
            bank['preview_settings'].update(width=w, height=h, display_format='ci8' if flags & 1 else 'ci4')
            assets.append(bank)
            texture_total += len(rows)
        placements = base + fields[0]
        meshes = []
        seen = set()
        for row in range(placements,placements+fields[1]*68,68):
            relative = _word(image,row+36)
            if relative in seen:
                continue
            seen.add(relative)
            if relative not in mesh_info:
                found = eurocom_mesh.mesh(image,base,relative)
                mesh_info[relative] = (found[1],len(found[2])) if found else None
            if counts := mesh_info[relative]:
                vertices, triangles = counts
                meshes.append(dict(name=f'Mesh {len(meshes)+1}', descriptor=relative,
                                   vertices=vertices, triangles=triangles))
        if meshes:
            asset.update(layout='eurocom-model', kind='3d model', media='model', meshes=meshes,
                         vertices=sum(m['vertices'] for m in meshes), triangles=sum(m['triangles'] for m in meshes))
        assets.append(asset)
    assets[0]['texture_total'] = texture_total
    # Cover the archive's contiguous payload without creating thousands of
    # duplicate browser cards for its individual compressed components.
    assets.append(dict(offset=base, size=archive_end-base, kind='compressed', label='EDL model and level archive',
                       confidence='validated', reason='The game index resolves to bounded entry headers.'))
    if scenes := _scenes(image, index, base, entries):
        assets.append(scenes)
        assets.extend(_dialogue(image, scenes['indices'][-1]))
    if motion := _animation(image,index,base,check):
        assets.append(motion)
        assets.append(dict(offset=motion['data_base'], size=motion['offset']-motion['data_base'],
                           kind='animation', label='Quantized bone key data', confidence='validated',
                           reason='Animation index frame extents fit the key bank.'))
    if speech := _mort(image, check):
        assets.append(speech)
        first, last = speech['samples'][0], speech['samples'][-1]
        assets.append(dict(offset=first['offset'], size=last['offset']+last['size']-first['offset'],
                           kind='audio', label='Indexed MORT speech payloads', confidence='validated',
                           reason='The ordered speech index resolves to MORT clip markers.'))
        if music := _music(image,index,archive_end,speech):
            assets.append(music)
            if samples := _samples(image,archive_end,min(s[0] for s in music['songs']),check):
                assets.append(samples)
                project = musyx_project.locate(image, samples['offset'], music['songs'], check)
                if project:
                    music['project_offset'] = project['offset']
                    music['project_groups'] = len(project['groups'])
                    required = musyx_project.used_programs(image, music['songs'], project['groups'])
                    if pool := musyx_project.find_pool(image, project['end'], samples['offset'], required):
                        music['pool_offset'] = pool['offset']
                        music['pool_objects'] = sum(len(section) for section in pool['objects'].values())
                        music['used_program_objects'] = len(required)
                        music['sample_index'] = samples['offset']
                        music['media'] = 'audio'
                        music['audio_kind'] = 'indexed sample directory'
                        music['samples'] = [dict(offset=lo, size=hi-lo, codec='MusyX sequence',
                                                 label=str(song), preview_available=True)
                                            for lo,hi,_,song in music['songs']]
                assets.append(dict(offset=samples['data_base'], size=samples['bank_end']-samples['data_base'],
                                   kind='audio', label='MusyX sample payload', confidence='validated',
                                   reason='The ordered sample directory resolves to stored data offsets.'))
    return assets


def _texture_preview(image, asset, selection):
    base = asset['archive_base']
    fields = ENTRY.unpack_from(image, asset['entry_offset'])
    rows = _textures(image, base, fields, {})
    slot = formats.integer(selection.get('texture', 0), 'Texture', 0, len(rows)-1)
    _, flags, width, height, offset, length, (entries, palette_at) = rows[slot]
    raw = _blob(image, {}, base, *fields[10:12])[offset:offset+length]
    palette = _blob(image, {}, base, *fields[8:10])[2*palette_at:2*(palette_at+entries+1)]
    colors = formats._rgba(palette, 'rgba5551-be', entries+1)
    indices = raw if flags & 1 else (idx for byte in raw for idx in (byte & 15, byte >> 4))
    pixels = bytearray()
    for idx in islice(indices, width*height):
        if idx > entries:
            raise formats.AssetError('The texture references an absent EDL palette entry.')
        pixels.extend(colors[4*idx:4*idx+4])
    raw_image = formats.preview(bytes(pixels), dict(format='rgba8888', width=width, height=height, offset=0))
    raw_image['details'].update(format='CI8' if flags & 1 else 'CI4', texture=rows[slot][0],
                                note='Stored palette preview. Runtime intensity and material modes may differ.')
    raw_image['settings'] = dict(format='auto', source='rom', offset=asset['offset'], texture=slot)
    return raw_image


def _records(image, asset):
    layout = asset['layout']
    offset = asset['offset']
    if layout == 'eurocom-index':
        entries = _entries(image, offset, asset['archive_base'])
        if not entries:
            raise formats.AssetError('The archive index changed. Rescan ROM Explorer.')
        rows = [dict(resource_id=i, offset=at, nodes=nodes, placements=fields[1], textures=fields[7])
                for i,(at,nodes,fields) in enumerate(entries)]
        fields = {'EDL streams': sum(asset['method_counts'].values()), 'Texture slots': asset['texture_total']}
    elif layout == 'eurocom-entry':
        fields = ENTRY.unpack_from(image, offset)
        rows = [dict(component=name, rom_offset=asset['archive_base']+at, count=count)
                for name,(at,count) in zip(('Placements','Extra records','Palette descriptors','Texture descriptors',
                                            'Palette payload bytes','Texture payload bytes'),
                                           zip(fields[::2],fields[1::2])) if count]
        fields = {'Render nodes': asset['nodes']}
    elif layout == 'eurocom-dialogue':
        root = asset['data_base']
        rows = []
        for i in range(asset['count']):
            at = root + _word(image, offset+4*i)
            end = image.find(b'\0',at,min(at+2049,len(image)))
            rows.append(dict(text=image[at:end].decode('cp1252', errors='replace').translate(
                {c: None for c in range(32) if c not in (9,10,13)})))
        fields = {'Language': asset['language']}
    elif layout == 'eurocom-animation':
        rows = []
        for i in range(asset['count']):
            frames, flags, relative, *_ = ANIMATION.unpack_from(image,offset+i*ANIMATION.size)
            group = flags & 0x7fff
            rows.append(dict(frames=frames, group=group, bones=asset['group_bones'][group],
                             per_bone_translation=bool(flags & 0x8000), key_offset=asset['data_base']+relative))
        fields = {'Skeleton groups': len(asset['group_bones'])}
    elif layout == 'eurocom-scenes':
        rows = [dict(script_offset=at) for at in asset['indices']]
        fields = {}
    elif layout == 'eurocom-speech':
        rows = [dict(clip_offset=clip['offset'], encoded_bytes=clip['size'], sample_rate=clip['rate'],
                     duration_seconds=round(clip['samples']/clip['rate'],3))
                for clip in asset['samples']]
        if 'indices' in asset:
            rows = [dict(clip_offset=at, duration_seconds=round(struct.unpack_from('>H',image,at)[0]/75,3))
                    for at in asset['indices']]
        fields = {'Codec': 'Factor 5 MORT'}
    elif layout == 'eurocom-songs':
        rows = []
        for start, end, group, song in asset['songs']:
            valid = 0 <= start < end <= len(image) and end-start <= musyx_song.MAX_SONG_BYTES
            data = image[start:end] if valid else b''
            arrangement = musyx_song.arrangement(data)
            streams = [musyx_song.events(data, lo, hi) for lo, hi in arrangement['streams']] if arrangement else []
            rows.append(dict(rom_start=start, rom_end=end, group=group, song=song,
                             bpm=arrangement['tempo'] if arrangement else None,
                             tracks=len(arrangement['tracks']) if arrangement else None,
                             note_events=sum(event['kind']=='note' for stream in streams for event in stream)
                             if streams and all(stream is not None for stream in streams) else None))
        fields = {'Sequencer': 'MusyX'}
        if 'project_groups' in asset:
            fields['Instrument groups'] = asset['project_groups']
        if 'pool_objects' in asset:
            fields['Sound objects'] = asset['pool_objects']
            fields['Sound objects used by notes'] = asset['used_program_objects']
    elif layout == 'eurocom-samples':
        rows = []
        for i in range(asset['count']):
            identifier, _, relative, _, _, rate, encoded, loop_start, loop_size = SAMPLE.unpack_from(
                image,offset+i*SAMPLE.size)
            rows.append(dict(sample_id=identifier, sample_offset=asset['data_base']+relative, rate=rate,
                             samples=encoded & 0xffffff, loop_start=loop_start if loop_size else None,
                             loop_samples=loop_size))
        fields = {'Codec': 'MusyX ADPCM'}
    else:
        return [], {'Decoded bytes': len(edl.unpack(image, offset))}
    return rows, fields


def preview(image, asset, selection):
    if asset['layout'] == 'eurocom-model':
        return eurocom_mesh.preview(image, asset, selection)
    if asset['layout'] == 'eurocom-textures':
        return _texture_preview(image, asset, selection)
    if asset['layout'] == 'eurocom-songs' and 'sample' in selection:
        return _song_preview(image, asset, selection)
    if asset['layout'] in ('eurocom-samples', 'eurocom-speech') and 'sample' in selection:
        return _sample_preview(image, asset, selection)
    rows, fields = _records(image, asset)
    result = dict(media='metadata', title=asset['label'], fields=fields, settings=asset['preview_settings'])
    if rows:
        result['table'] = table(asset['label'], ['index', *rows[0]], len(rows), rows.__getitem__, selection)
    return result


def _sample_preview(image, asset, selection):
    index = formats.integer(selection['sample'], 'Sample', 0, len(asset['samples']) - 1)
    sample = asset['samples'][index]
    if not sample['preview_available']:
        raise formats.AssetError('This sample has no bounded preview. Rescan the ROM to refresh its audio index.')
    rate = sample['rate']
    count = min(sample['samples'], rate * formats.MAX_SECONDS)
    if asset['layout'] == 'eurocom-speech':
        start = sample['offset']
        pcm = mort.decode(image[start:start+sample['size']], count // mort.SAMPLES_PER_FRAME)
        count = len(pcm) // 2
    else:
        pcm = musyx.decode(image, sample['offset'], count)
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', rate=rate, length=len(pcm)))
    details.update(format=sample['codec'], sample=index, original_samples=sample['samples'],
                   truncated=count < sample['samples'], note=asset['reason'])
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,' + base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample': index})


def _song_preview(image, asset, selection):
    index = formats.integer(selection['sample'], 'Song', 0, len(asset['songs'])-1)
    start, end, group, song = asset['songs'][index]
    sample_index = asset.get('sample_index', 0)
    if not 0 < sample_index < start < end <= len(image) or end-start > musyx_song.MAX_SONG_BYTES:
        raise formats.AssetError('This song needs a validated instrument and sample bank. Rescan the ROM.')
    songs = asset['songs']
    bank = _samples(image, sample_index, min(row[0] for row in songs), lambda: None)
    project = musyx_project.locate(image, sample_index, songs)
    required = musyx_project.used_programs(image, songs, project['groups']) if project else None
    pool = musyx_project.find_pool(image, project['end'], sample_index, required) if project else None
    if bank is None or bank['offset'] != sample_index or pool is None:
        raise formats.AssetError('The song instrument tables no longer match the ROM. Rescan the ROM.')
    samples = {int(sample['label']):sample for sample in bank['samples']}
    pcm, stats = musyx_render.render(image, image[start:end], project['groups'][group], song,
                                     pool['objects'], samples)
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2, rate=musyx_render.RATE, length=len(pcm)))
    details.update(stats, format='MusyX sequence', sample=index,
                   note='One-pass sample-backed preview. Runtime effects and macro timing can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,' + base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample': index})
