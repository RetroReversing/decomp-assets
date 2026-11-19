"""Nintendo 64 asset recognisers. Each one accepts a candidate only when its whole structure checks out.

- textures.py: indexed texture banks (CI4/CI8, RGBA32, the six-level RGBA16 mipmap layout), raw or RNC-packed.
- rnc_textures.py: descriptor-table texture banks inside byte-sum RNC blocks.
- texture_packs.py: texture packs with a trailing count, inside archives.
- display_lists.py: textures that uncompressed display lists load, in files placed by their vertices and pointers.
- fla2.py: texture banks packed with FLA2, the LZ variant of a platformer about a magic glove.
- ffs.py: I64 images in an FFS filesystem packed as one chunked RNC stream.
- rare_models.py: model textures in a deflated asset table.
- blast_textures.py: textures packed with a demolition game's own codecs, listed in its texture table.
- mainfs.py: image packs and model bitmaps in a party-game series' main filesystem (three packings).
- sno.py: sno unpacking and its texture sheets, read where a caller knows a stream's start and size.
- reloc_files.py: textures and sprites in a table of relocatable files, some VPK0-packed (vpk0.py).
- uv_textures.py: textures in a UV filesystem of FORM files, drawn by each file's own display list.
- audio.py: libultra B1 sound banks, their sample tables and mono VADPCM previews.
- ptr_audio.py: libmus PtrTablesV2 banks, marked wave tables and sequences.
- models.py: indexed geometry with byte-plane vertices and cache-relative polygons.
- archived_models.py, model_links.py, model_scenery.py: models inside archives, their texture links and scenery.
- animation.py: three-bit shared-header animation ADPCM and node tracks.
- resources.py, resource_inspection.py: an indexed cartridge directory and its records.
- fonts.py: I4 glyph tables a named text writer points at.
- native_scene.py: links a directory's objects to their models, textures and animations.
"""

from ..formats import AssetError


def regions(image, *, context=None, **kwargs):
    """Every asset found in `image`, as dicts with `offset`, `size`, `kind`, `label`, `confidence` and `reason`.

    `context` is optional evidence from the game's code: `functions` and `symbols` (name, address, ROM offset),
    `segments`, `gp`, and `read_code`, a reader of MIPS code that turns a function into its calls and constant
    arguments. Fonts are found from the function that draws them (`functions`); audio banks find their sample
    tables from the constant arguments of alBnkfNew calls (`read_code`). `check` (called often,
    raise to stop) and `progress` (given a dict) are passed to each recogniser.
    """
    from . import (
        archived_models,
        audio,
        blast_textures,
        display_lists,
        ffs,
        fla2,
        fonts,
        mainfs,
        models,
        native_scene,
        ptr_audio,
        rare_models,
        reloc_files,
        resources,
        texture_packs,
        textures,
        uv_textures,
    )
    known=(textures.regions(image,**kwargs)+texture_packs.regions(image,**kwargs)+display_lists.regions(image,**kwargs)
           +ffs.regions(image,**kwargs)+rare_models.regions(image,**kwargs)+uv_textures.regions(image,**kwargs)+blast_textures.regions(image,**kwargs)+reloc_files.regions(image,**kwargs)+mainfs.regions(image,**kwargs)+fla2.regions(image,**kwargs)
           +audio.regions(image,context=context,**kwargs)
           +ptr_audio.regions(image,**kwargs)+ptr_audio.sequences(image,**kwargs)+models.regions(image,**kwargs)
           +archived_models.regions(image,**kwargs))
    assets=known+resources.regions(image,known=known,**kwargs)
    native_scene.link(assets)
    return assets+fonts.regions(image,context=context,known=assets,**kwargs)


def preview(data, asset, selection):
    """A preview of one asset `regions` found: an image, a sound, a model or a table, chosen by `selection`."""
    from . import (
        archived_models,
        audio,
        blast_textures,
        ffs,
        fla2,
        fonts,
        mainfs,
        models,
        ptr_audio,
        rare_models,
        reloc_files,
        resources,
        rnc_textures,
        texture_packs,
        textures,
        uv_textures,
    )
    if asset.get('layout')=='fla2-texbank':return fla2.preview(data,asset,selection)
    if asset.get('layout')=='mainfs':return mainfs.preview(data,asset,selection)
    if asset.get('layout')=='reloc-file':return reloc_files.preview(data,asset,selection)
    if asset.get('layout')=='blast':return blast_textures.preview(data,asset,selection)
    if asset.get('layout')=='uv-texture':return uv_textures.preview(data,asset,selection)
    if asset.get('layout')=='ffs-i64':return ffs.preview(data,asset,selection)
    if asset.get('layout')=='rare-model':return rare_models.preview(data,asset,selection)
    if asset.get('font_layout')=='native-i4-pointer-glyphs':return fonts.preview(data,asset,selection)
    if asset.get('audio_kind') in ('libmus sample bank','libmus sequence'):return ptr_audio.preview(data,asset,selection)
    if asset.get('layout')=='archived-pd3v-model':return archived_models.preview(data,asset,selection)
    if asset.get('layout')=='rnc-sum32-texture-bank':return rnc_textures.preview(data,asset,selection)
    if asset.get('layout')=='trailer-count-texture-pack':return texture_packs.preview(data,asset,selection)
    return {'audio':audio.preview,'model':models.preview,'metadata':resources.preview}.get(asset.get('media'),textures.preview)(data,asset,selection)


def scene(image, asset, selection, assets):
    """An object from a resource directory with its linked model, textures and animation."""
    from . import native_scene
    from .models import ModelError
    from .resources import SchemaError
    try:return native_scene.preview(image,asset,selection,assets)
    except (ModelError,SchemaError) as exc:raise AssetError(str(exc)+' Rescan and choose another resource.') from None
