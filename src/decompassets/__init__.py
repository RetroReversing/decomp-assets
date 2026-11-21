"""Find and preview game assets inside a cartridge or disc image by their structure, never by known offsets.

- formats.py: the readers every console shares: raw pixel layouts, palettes, PCM, VAG, PNG/JPEG/WAVE checks
  and browser previews. `AssetError` is the one error a caller shows.
- archives.py: zip members inside a game image, bounded.
- rnc.py: Rob Northen ProPack (RNC methods 1 and 2) unpacking, checksums and repacking.
- n64/: Nintendo 64 recognisers (textures, audio banks, models, animation, fonts, resource directories);
  `decompassets.n64.regions` runs them all.

Everything here reads bytes and returns plain dicts. It never writes a game file, runs a tool or downloads.
"""

__version__ = "0.39.0"
