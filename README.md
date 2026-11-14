# decomp-assets

Find the textures, sound banks, models, animation and fonts inside a game image by their structure, with no list
of offsets for each game or release. Give it the bytes of a cartridge (or a file from a disc). It returns each asset
it is sure of, with the reason it is sure, and previews it: a PNG, a WAVE, a model's vertices or a table.

Tools like splat and Torch extract assets from offsets someone wrote down for one release. This finds them first. A
candidate is only reported when its whole structure agrees: every table entry, every block extent, every palette
size, every checksum. Anything less is left alone, not guessed at.

It never writes a game file, runs an external tool or downloads anything. It only reads bytes you already have.

It started in [decompdecomp](https://github.com/RetroReversing/decompdecomp), whose ROM Explorer uses it. This
repository has kept its history.

## Status

Nintendo 64 first. The shared readers in `formats.py` (pixel layouts, palettes, PCM, VAG, PNG/JPEG/WAVE checks) and
the RNC unpacker work for any console. The interface may change before 1.0.

## Use

```bash
uv add "decompassets @ https://github.com/RetroReversing/decomp-assets/archive/refs/tags/v0.10.0.tar.gz"
```

```python
from decompassets import n64

image = open('game.z64', 'rb').read()
for asset in n64.regions(image):
    print(hex(asset['offset']), asset['label'], asset['confidence'], asset['reason'])

preview = n64.preview(image, asset, {'frame': 0})   # an image, a sound, a model or a table
```

`n64.regions` also takes `context`, evidence from the game's code: `functions` and `symbols` (name, address, ROM
offset), `segments`, `gp`, and `read_code`, a reader of MIPS code that turns a function into its calls and constant
arguments. Fonts are found from the function that draws them (`functions`), and audio banks their sample tables
from the constant arguments of `alBnkfNew` calls (`read_code`). Leave these out and those recognisers report only
what the data proves on its own. `check` (called often; raise to stop) and
`progress` (given a dict) let a long scan be followed and cancelled.

Errors a user can act on are `decompassets.formats.AssetError`, with a sentence saying what to do.

## Layout

- `formats.py`: readers every console shares, and the browser previews.
- `archives.py`: zip members inside a game image, bounded.
- `rnc.py`: Rob Northen ProPack, methods 1 and 2: unpacking, checksums, repacking.
- `n64/`: Nintendo 64 recognisers; its `__init__.py` lists them.

Every recogniser has limits on how much it reads and decodes, so a hostile or damaged image can't make it run long
or use much memory.

## Tests

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
```

The tests build small invented images. They contain no game data, and nothing here should.

## License

GNU Affero General Public License version 3 (LICENSE).
