"""The library on its own: no decompdecomp, and the calls other projects use."""
import importlib
import pathlib
import pkgutil

import decompassets
from decompassets import n64
from decompassets.n64 import audio

from .test_native_audio import fixture as audio_fixture
from .test_native_textures import bank

SOURCE = pathlib.Path(decompassets.__file__).parent


def test_every_module_imports_and_none_reaches_back_into_decompdecomp():
    names = [m.name for m in pkgutil.walk_packages(decompassets.__path__, 'decompassets.')]
    assert 'decompassets.n64.textures' in names and 'decompassets.rnc' in names
    for name in names:
        importlib.import_module(name)
    for path in SOURCE.rglob('*.py'):
        assert 'decompnet' not in path.read_text(), path


def test_regions_and_preview_find_a_bank_with_no_offsets_given():
    image = bytes(64) + bank() + bytes(64)
    found = n64.regions(image)
    textures = [a for a in found if a['label'] == 'Texture bank']
    assert len(textures) == 1 and textures[0]['offset'] == 64 and textures[0]['confidence'] == 'validated'
    preview = n64.preview(image, textures[0], {})
    assert preview['details']['frame'] == 0


def test_loader_evidence_comes_from_the_callers_code_reader():
    image, context, base = audio_fixture()
    # Without a reader of MIPS code the library uses no loader evidence, and says nothing it can't prove.
    assert audio.loader_tables(image, context) == {}
    calls = []

    def read_code(vram, code, *, gp=0, check=lambda: None):
        calls.append(vram)
        if vram != 0x80000000:
            return {'events': []}
        argument = {'kind': 'constant', 'value': base}
        return {'events': [{'kind': 'call', 'target': 0x80000040, 'instruction': 0x80000008,
                            'args': [None, argument]}]}

    tables = audio.loader_tables(image, {**context, 'read_code': read_code})
    assert list(tables) == [base] and tables[base][0]['function'] == 'audio_loader'
    assert 0x80000000 in calls
    bank_found = audio.regions(image, context={**context, 'read_code': read_code})[0]
    assert bank_found['table_offset'] == base and len(bank_found['samples']) == 2
