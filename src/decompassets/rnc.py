"""RNC method 1 containers: bounded Huffman/LZ unpacking of code held in a cartridge image.

Control bits are little-endian words interleaved with literal bytes. The reader must discard prefetched literal
bytes after each run, keeping only the unused control bits. Both container checksums are checked before code is used.
"""

from __future__ import annotations

import functools
import struct
from dataclasses import dataclass

HEADER_BYTES = 18
MAX_OUTPUT = 4 << 20
MAX_CODE_BITS = 16


class RncError(ValueError):
    pass


@functools.cache
def _crc_table() -> tuple[int, ...]:
    table = []
    for value in range(256):
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
        table.append(value)
    return tuple(table)


def crc16(data: bytes) -> int:
    value = 0
    table = _crc_table()
    for byte in data:
        value = (value >> 8) ^ table[(value ^ byte) & 0xFF]
    return value


@dataclass
class Literal:
    packed: int
    output: int
    size: int


class _Bits:
    def __init__(self, payload: bytes):
        # A final control value can prefetch another word past the payload. Keep
        # that lookahead separate from take()'s physical input-bit bound.
        self.data = payload + bytes(4)
        self.end = len(payload)
        self.pos = 0
        self.buffer = self.word(0)
        self.left = 0

    def word(self, pos: int) -> int:
        if pos + 2 > len(self.data):
            raise RncError("truncated RNC control bits")
        return self.data[pos] | self.data[pos + 1] << 8

    def take(self, count: int) -> int:
        if not 0 <= count <= 30:
            raise RncError("invalid RNC bit count")
        if count > 16:
            return self.take(16) | self.take(count - 16) << 16
        if not count:
            return 0
        if self.pos * 8 - self.left + count > self.end * 8:
            raise RncError("truncated RNC control bits")
        value = self.buffer & ((1 << count) - 1)
        if count > self.left:
            self.buffer >>= self.left
            self.pos += 2
            self.buffer |= self.word(self.pos) << 16
            count -= self.left
            self.left = 16
        self.buffer >>= count
        self.left -= count
        return value

    def literal(self, count: int) -> bytes:
        if count < 0 or self.pos + count > self.end:
            raise RncError("truncated RNC literal run")
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        self.buffer &= (1 << self.left) - 1
        self.buffer |= self.word(self.pos) << self.left
        return result


def _table(bits: _Bits) -> list[tuple[int, int, int, int]]:
    lengths = [bits.take(4) for _ in range(bits.take(5))]
    entries = []
    code = 0
    for width in range(1, MAX_CODE_BITS + 1):
        for symbol, length in enumerate(lengths):
            if length != width:
                continue
            if code >= 1 << width:
                raise RncError("oversubscribed RNC Huffman tree")
            reversed_code = int(f"{code:0{width}b}"[::-1], 2)
            entries.append(((1 << width) - 1, reversed_code, width, symbol))
            code += 1
        code <<= 1
    return entries


def _value(bits: _Bits, table: list[tuple[int, int, int, int]]) -> int:
    for mask, code, width, symbol in table:
        if bits.buffer & mask == code:
            bits.take(width)
            return symbol if symbol < 2 else (1 << (symbol - 1)) | bits.take(symbol - 1)
    raise RncError("RNC stream has no matching Huffman code")


def _method1(payload: bytes, size: int, *, literals: list[Literal] | None = None, max_chunks: int = 255) -> bytearray:
    """Decode one method-1 bit stream to exactly `size` bytes; the container's checks are the caller's."""
    bits = _Bits(payload)
    if bits.take(2):
        raise RncError("encrypted or locked RNC streams are unsupported")
    out = bytearray()
    chunks = 0
    while len(out) < size:
        raw, distance, length = _table(bits), _table(bits), _table(bits)
        count = bits.take(16)
        if not count:
            raise RncError("empty RNC chunk")
        for index in range(count):
            n = _value(bits, raw)
            if len(out) + n > size:
                raise RncError("RNC literal run exceeds declared output")
            if n:
                if literals is not None:
                    literals.append(Literal(HEADER_BYTES + bits.pos, len(out), n))
                out += bits.literal(n)
            if index + 1 < count:
                offset, n = _value(bits, distance) + 1, _value(bits, length) + 2
                if offset > len(out) or len(out) + n > size:
                    raise RncError("RNC back-reference is outside its output")
                for _ in range(n):
                    out.append(out[-offset])  # a run can overlap its own already-decoded bytes
        chunks += 1
        if chunks > max_chunks:
            raise RncError("too many RNC chunks")
    return out


def _method1_header(data, max_output):
    if len(data) < HEADER_BYTES or data[:4] != b"RNC\x01":
        raise RncError("not an RNC method-1 container")
    size, packed = struct.unpack_from(">II", data, 4)
    if not 0 < size <= max_output or packed < 2 or HEADER_BYTES + packed > len(data):
        raise RncError("invalid RNC sizes")
    return size, packed


def unpack_sum32(data: bytes, *, max_output: int = MAX_OUTPUT) -> bytes:
    """Decode the method-1 variant with a big-endian sum of the output bytes."""
    size, packed = _method1_header(data, max_output)
    checksum, _, chunks = struct.unpack_from(">IBB", data, 12)
    if not chunks or checksum > 255 * size:
        raise RncError("invalid RNC byte-sum header")
    out = _method1(data[HEADER_BYTES:HEADER_BYTES + packed], size, max_chunks=chunks)
    if sum(out) != checksum:
        raise RncError("RNC unpacked byte sum differs")
    return bytes(out)


def unpack(data: bytes, *, max_output: int = MAX_OUTPUT, literals: list[Literal] | None = None) -> bytes:
    """Unpack a checksummed method-1 block. Optional literal locations support a verified compression template."""
    size, packed = _method1_header(data, max_output)
    unpacked_crc, packed_crc = struct.unpack_from(">HH", data, 12)
    payload = data[HEADER_BYTES:HEADER_BYTES + packed]
    if crc16(payload) != packed_crc:
        raise RncError("RNC packed checksum differs")
    out = _method1(payload, size, literals=literals)
    if crc16(out) != unpacked_crc:
        raise RncError("RNC unpacked checksum differs")
    return bytes(out)


def repack_like(output: bytes, template: bytes) -> bytes:
    """Reuse a valid stream's coding decisions, deriving its literal bytes from newly built output.

    This is a matching-build operation, not a general compressor. Edits incompatible with the template's LZ
    references are rejected by decoding the result and comparing every output byte.
    """
    locations: list[Literal] = []
    original = unpack(template, literals=locations)
    if len(output) != len(original):
        raise RncError("RNC template requires the original output size")
    packed = int.from_bytes(template[8:12], "big")
    result = bytearray(template[:HEADER_BYTES + packed])
    for span in locations:
        result[span.packed:span.packed + span.size] = output[span.output:span.output + span.size]
    struct.pack_into(">HH", result, 12, crc16(output), crc16(result[HEADER_BYTES:]))
    if unpack(result) != output:
        raise RncError("new output is incompatible with RNC template references")
    return bytes(result)


def rebuild_cartridge(analysis: bytes, original: bytes, blocks: list[dict]) -> bytes:
    """Replace packed code with literals derived from a linked analysis image; preserve rebuilt prefix bytes."""
    if len(analysis) < len(original):
        raise RncError("analysis image is shorter than the cartridge")
    result = bytearray(analysis[:len(original)])
    for block in blocks:
        offset, start, size = block['rom'], block['analysis'], block['size']
        if not 0 <= offset <= len(original) - HEADER_BYTES or not len(original) <= start <= len(analysis) - size:
            raise RncError("compressed-block mapping is outside its images")
        packed = repack_like(analysis[start:start + size], original[offset:])
        result[offset:offset + len(packed)] = packed
    return bytes(result)


def unpack_m2(data: bytes, *, max_output: int = MAX_OUTPUT) -> bytes:
    """Bounded method-2 assets; code rebuilding continues to use method 1 only.

    Token grammar reference: ScummVM common/compression/rnc_deco.cpp,
    unpackM2 (ScummVM developers, GPL-3.0-or-later). Sizes, reads, both CRCs
    and every back-reference are checked here before any asset is exposed.
    """
    if len(data)<HEADER_BYTES or data[:4]!=b'RNC\x02':raise RncError('not an RNC method-2 container')
    size,packed,out_crc,in_crc=struct.unpack_from('>IIHH',data,4)
    if not 0<size<=max_output or not 1<=packed<=len(data)-HEADER_BYTES:raise RncError('invalid RNC sizes')
    payload=data[HEADER_BYTES:HEADER_BYTES+packed]
    if crc16(payload)!=in_crc:raise RncError('RNC packed checksum differs')
    cursor=buffer=left=0

    def byte():
        nonlocal cursor
        if cursor>=len(payload):raise RncError('truncated RNC token')
        value=payload[cursor];cursor+=1
        return value

    def bit():
        nonlocal buffer,left
        if not left:buffer=byte();left=8
        left-=1
        return (buffer>>left)&1

    out=bytearray()

    def literal(count):
        if len(out)+count>size:raise RncError('RNC literal exceeds output')
        for _ in range(count):out.append(byte())

    if bit() or bit():raise RncError('encrypted or locked RNC streams are unsupported')
    # Empty continuation chunks still consume input, so truncated streams terminate.
    while True:
        while not bit():literal(1)
        length=2;high=0;distance=False
        if not bit():
            length=4+bit()
            if bit():
                length=(length-1)*2+bit()
                if length==9:
                    count=0
                    for _ in range(4):count=count*2+bit()
                    literal((count+3)*4)
                    continue
            distance=True
        elif bit():
            length=3
            if bit():
                length=byte()
                if not length:
                    if bit():continue
                    break
                length+=8
            distance=True
        if distance and bit():
            high=bit()
            if bit():
                high=(high*2+bit())|4
                if not bit():high=high*2+bit()
            elif not high:high=2+bit()
        offset=high*256+byte()+1
        if offset>len(out) or len(out)+length>size:raise RncError('RNC back-reference is outside output')
        for _ in range(length):out.append(out[-offset])
    if len(out)!=size or crc16(out)!=out_crc:raise RncError('RNC unpacked size or checksum differs')
    return bytes(out)


CHUNK_BYTES = 4096
MAX_CHUNKED = 64 << 20


def chunked(image: bytes, offset: int) -> dict | None:
    """A chunked stream's layout: method byte 0x81, then a table of each 4 KB chunk's packed size.

    Each chunk is a method-1 stream of its own, so any part of the output can be read without the rest; a
    chunk starts on an even offset. Its checksum fields don't use the method-1 CRC, so a stream is accepted
    only when every chunk table entry is plausible and all of them fit inside the image."""
    if image[offset:offset+4] != b"RNC\x81" or offset + HEADER_BYTES > len(image):
        return None
    size, packed = struct.unpack_from(">II", image, offset + 4)
    count = -(-size // CHUNK_BYTES)
    table = offset + HEADER_BYTES
    if not 0 < size <= MAX_CHUNKED or table + 2*count > len(image):
        return None
    sizes = struct.unpack_from(f">{count}H", image, table)
    starts, at = [], table + 2*count
    for packed_size in sizes:
        if not 2 <= packed_size <= 2*CHUNK_BYTES:
            return None
        starts.append(at)
        at += packed_size + (packed_size & 1)
    if at > len(image):
        return None
    return dict(offset=offset, size=size, chunks=list(zip(starts, sizes)), end=at)


def unpack_chunked(image: bytes, layout: dict, start: int = 0, end: int | None = None, *, check=lambda: None) -> bytes:
    """Output bytes `start` to `end` of a chunked stream, decoding only the chunks that hold them."""
    end = layout["size"] if end is None else end
    if not 0 <= start <= end <= layout["size"]:
        raise RncError("range is outside the chunked stream")
    first, last = start // CHUNK_BYTES, max(start, end - 1) // CHUNK_BYTES
    out = bytearray()
    for index in range(first, last + 1):
        check()
        at, packed = layout["chunks"][index]
        want = min(CHUNK_BYTES, layout["size"] - index*CHUNK_BYTES)
        out += _method1(image[at:at + packed], want)
    base = first * CHUNK_BYTES
    return bytes(out[start - base:end - base])
