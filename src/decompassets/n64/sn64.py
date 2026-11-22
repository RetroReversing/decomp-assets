"""SN64 sample banks whose paired SSEQ directory bounds the wave table.

The container fields are cross-checked against the cartridge's loaders and
the published Doom64EX WadGen sound reader.
"""

import re
import struct
from itertools import islice

_HEAD = struct.Struct('>4s8I6H2I')
_SEQUENCE_HEADER = struct.Struct('>4s7I')
_SEQUENCE_ENTRY = struct.Struct('>HHIII')
_TRACK = struct.Struct('>10H')
_WAVE = struct.Struct('>6I')
_LOOP = struct.Struct('>4H')
_BOOK = struct.Struct('>2I256s')
_MAX_ROWS = 2048


def _align(value):
    return (value+15)&~15


def _sequences(image, offset, check):
    if offset+_SEQUENCE_HEADER.size > len(image):
        return None
    magic, version, z1, count, z2, z3, size, z4 = _SEQUENCE_HEADER.unpack_from(image,offset)
    start = offset+_SEQUENCE_HEADER.size
    body = start+size
    if (magic != b'SSEQ' or version != 2 or z1 or z2 or z3 or z4 or not 0 < count <= _MAX_ROWS
            or size != count*_SEQUENCE_ENTRY.size or body>len(image)):
        return None
    rows = []
    total = 0
    for tracks, zero, length, relative, reserved in _SEQUENCE_ENTRY.iter_unpack(image[start:body]):
        check()
        if (zero or reserved or not 0 < tracks <= 32 or not tracks*_TRACK.size <= length <= 0x100000
                or relative < total or body+relative+length > len(image)):
            return None
        rows.append(dict(offset=body+relative,size=length,tracks=tracks))
        total = relative+length
    return _align(body+total), rows


def _samples(image, offset, check):
    if offset+_HEAD.size > len(image):
        return None
    (magic, version, _, version_id, _, _, body_size, _, instruments, patches, patch_size,
     voices, voice_size, count, row_size, _, _) = _HEAD.unpack_from(image,offset)
    if (magic != b'SN64' or version != 2 or version_id != 100 or not 0 < instruments <= 128
            or not 0 < patches <= _MAX_ROWS or not 0 < voices <= _MAX_ROWS or not 0 < count <= _MAX_ROWS
            or (patch_size,voice_size,row_size) != (4,20,_WAVE.size)):
        return None
    control_end = offset+_HEAD.size+body_size
    if control_end > len(image):
        return None
    records = offset+_HEAD.size+patches*patch_size+voices*voice_size
    tables = []
    for padding in (0, 8):
        wave_records = records+padding
        loop = wave_records+count*row_size
        if loop+_LOOP.size > control_end:
            continue
        count1, zero, loops, count2 = _LOOP.unpack_from(image,loop)
        books = loop+_LOOP.size+loops*48
        if count1 == count2 == count and not zero and books+count*_BOOK.size == control_end:
            tables.append((wave_records, loop, loops, books))
    if len(tables) != 1:
        return None
    wave_records, loop, loops, books = tables[0]
    wave_rows = list(_WAVE.iter_unpack(image[wave_records:loop]))
    first = _align(control_end)
    if image[first:first+4] == b'SSEQ':
        sequence = first
        parsed = _sequences(image,sequence,check)
        if not parsed:
            return None
        wave_base, sequences = parsed
        sequence_end = wave_base
    else:
        wave_base = first
        relative, size, *_ = wave_rows[-1]
        sequence = _align(wave_base+relative+size)
        parsed = _sequences(image,sequence,check)
        if not parsed:
            return None
        sequence_end, sequences = parsed
    samples = []
    end = 0
    for index, (relative,size,zero,_,loop_id,reserved) in enumerate(wave_rows):
        check()
        book_at = books+index*_BOOK.size
        order, predictors = struct.unpack_from('>II',image,book_at)
        encoded = size-size%9
        first, last = wave_base+relative, wave_base+relative+encoded
        if (not encoded or relative != end or wave_base+relative+size > len(image)
                or order != 2 or not 0 < predictors <= 8 or zero or reserved or (loop_id >= loops and loop_id != 0xffffffff)
                or any(image[last:wave_base+relative+size])):
            return None
        for at in range(first,last,9):
            if (image[at]&15) >= predictors:
                return None
            if at%4096 < 9:
                check()
        samples.append(dict(label=f'Sample {index+1}',codec='N64 VADPCM',offset=first,
                            size=size,encoded_size=encoded,samples=encoded//9*16,rate=22050,
                            book_offset=book_at+8,predictors=predictors))
        end = relative+size
    return control_end, sequence, sequence_end, wave_base, samples, sequences


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    for hit in islice(re.finditer(rb'SN64\0\0\0\x02',image),64):
        check()
        offset = hit.start()
        parsed = _samples(image,offset,check) if offset%16 == 0 else None
        if not parsed:
            continue
        end, sequence, sequence_end, wave, samples, sequences = parsed
        reason = 'The paired SN64 and SSEQ records bound the sample table and every ADPCM frame selector validates.'
        asset = dict(kind='audio',media='audio',audio_kind='sample bank',layout='sn64-bank',
                     confidence='validated',reason=reason,table_offset=wave)
        assets.append(dict(**asset,offset=offset,size=end-offset,label='SN64 sample bank',samples=samples,
                           preview_settings=dict(format='auto',source='rom',offset=offset)))
        for sample in samples:
            at = sample['offset']
            assets.append(dict(**asset,offset=at,size=sample['size'],label=sample['label'],samples=[sample],
                               preview_settings=dict(format='auto',source='rom',offset=at)))
        assets.append(dict(kind='music sequence',media='metadata',layout='sn64-sequences',confidence='validated',
                           label='SSEQ sequence directory',offset=sequence,size=sequence_end-sequence,sequences=sequences,
                           reason='Each track entry fits the validated sequence directory paired with the wave table.',
                           preview_settings=dict(format='auto',source='rom',offset=sequence)))
    return assets


def preview_directory(image, asset, selection):
    from .resource_inspection import table

    rows = asset['sequences']
    return dict(media='metadata',title=asset['label'],fields={'Sequencer':'SSEQ'},
                table=table(asset['label'],['index','offset','size','tracks'],len(rows),
                            lambda index: rows[index],selection),
                settings=asset['preview_settings'])
