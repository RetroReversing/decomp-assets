import struct

from decompassets.n64 import arithmetic_assets


def test_directory_requires_zero_padding_and_ordered_aligned_offsets():
    bank = struct.pack('>4I', 2, 16, 24, 0) + b'A' * 8 + b'B' * 8
    assert arithmetic_assets.directory(bank) == [(16, 24), (24, 32)]
    assert arithmetic_assets.directory(bank[:-1]) is None
    assert arithmetic_assets.directory(bank[:15] + b'\xff' + bank[16:]) is None
    assert arithmetic_assets.directory(bank[:11] + b'\x10' + bank[12:]) is None


def test_indexed_pointer_requires_the_loaded_directory_and_palette_commands():
    pc, bank = 0x80001000, 0x80204000
    # Palette count, its opcode, global load into t1, entry 2, then
    # texture address in a1 with the palette skip in the call delay slot.
    words = (0x3c07073f, 0x34e7c000, 0x3c02f000, 0x8c894000,
             0x8d25000c, 0x00a92821, 0x0c001000, 0x24a50200)
    code = struct.pack('>8I', *words)
    load = dict(kind='load', width=4, instruction=pc+12, place=dict(kind='constant', value=bank))
    draw = dict(instruction=pc+24)
    assert arithmetic_assets._palette_member(code, pc, [load], draw, bank) == 2
    assert arithmetic_assets._palette_member(code, pc, [load], draw, bank+4) is None
    assert arithmetic_assets._palette_member(code, pc, [load], dict(instruction=pc+20), bank) is None
