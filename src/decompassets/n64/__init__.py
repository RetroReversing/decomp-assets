"""Nintendo 64 asset recognisers. Each one accepts a candidate only when its whole structure checks out.

- textures.py: indexed texture banks (CI4/CI8, RGBA32, the six-level RGBA16 mipmap layout), raw or RNC-packed.
- rnc_textures.py: descriptor-table texture banks inside byte-sum RNC blocks.
- texture_packs.py: texture packs with a trailing count, inside archives.
- display_lists.py: textures that uncompressed display lists load, in files placed by their vertices and pointers.
- fla2.py: texture banks packed with FLA2, the LZ variant of a platformer about a magic glove.
- ffs.py: I64 images in an FFS filesystem packed as one chunked RNC stream.
- rare_models.py: model textures in a deflated asset table.
- zlib_meshes.py: packed vertex batches and triangles in checked zlib members.
- zlib_textures.py: RGBA sprites and textures with dimensions recorded inside zlib members.
- gzip_meshes.py: geometry in paired gzip vertex and Fast3D display-list members.
- blast_textures.py: textures packed with a demolition game's own codecs, listed in its texture table.
- mainfs.py: image packs and model bitmaps in a party-game series' main filesystem (three packings).
- sno.py: sno unpacking and its texture sheets, read where a caller knows a stream's start and size.
- reloc_files.py: textures and sprites in a table of relocatable files, some VPK0-packed (vpk0.py).
- uv_models.py: local geometry from UVMD models.
- uv_textures.py: textures in a UV filesystem of FORM files, drawn by each file's own display list.
- rnx.py: chained byte-sum pages and checked resource payloads.
- lz_standard_midi.py: S1 song directories of LZ-packed Standard MIDI files.
- lz_directory_models.py: local F3DEX2 geometry and LODs in indexed LZ object banks.
- lz_texture_directories.py: named textures and RDP strips inside indexed LZ banks.
- packed_tim.py: TIM sprites in adaptive Huffman-compressed BAM3 banks.
- dialogue.py: scene headings, cue text and speaker keys in indexed RAW! scripts.
- dean_audio.py: DEAN stream directories and audio metadata.
- audio.py: libultra B1 sound banks, their sample tables and mono VADPCM previews.
- ptr_audio.py: libmus PtrTablesV2 banks, marked wave tables and sequences.
- rnc_meshes.py: EMsh polygon tables and delta-encoded positions in byte-sum RNC blocks.
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
        arithmetic_assets,
        arithmetic_descriptors,
        audio,
        bind,
        blast_textures,
        bolt,
        borg,
        borg_audio,
        borg_dcm,
        borg_models,
        cartridge_scores,
        dean_audio,
        deflate_catalog,
        deflate_catalog_models,
        dialogue,
        dialogue_links,
        diet_audio,
        display_lists,
        emsh_links,
        eurocom,
        ffs,
        fla2,
        fonts,
        gzip_meshes,
        ia_font_textures,
        iain,
        iguana_audio,
        iguana_textures,
        indexed_resource_models,
        indexed_resource_textures,
        inline_meshes,
        inline_tiles,
        libmus_song,
        lz_banks,
        lz_standard_midi,
        lz_texture_directories,
        mainfs,
        models,
        mwo_graphics,
        named_resource_images,
        named_resource_models,
        native_scene,
        nested_scenes,
        packed_anim,
        packed_tim,
        paged_lz_models,
        paged_models,
        paged_textures,
        paired_audio,
        paired_resources,
        parallel_midi,
        prefixed_texture_catalog,
        prefixed_texture_models,
        ptr_audio,
        rare_assets,
        rare_audio,
        rare_models,
        raw_deflate_lists,
        relative_materials,
        relative_meshes,
        reloc_files,
        resources,
        rle_font_atlas,
        rnc_tiled_images,
        rnx,
        rzip_audio,
        rzip_catalog,
        rzip_models,
        segmented_model_resources,
        siff_models,
        sized_lz_catalog,
        sn64,
        stage_banks,
        stage_meshes,
        striped_images,
        tagged_deflate,
        texture_packs,
        textures,
        uso_audio,
        uso_models,
        uso_textures,
        uv_models,
        uv_sequences,
        uv_textures,
        wad_audio,
        wad_models,
        wad_resources,
        yay0_atlases,
        yay0_scenes,
        zlib_meshes,
        zlib_textures,
    )
    display_meshes = []
    sound_banks = audio.regions(image,context=context,**kwargs)
    pointer_banks = ptr_audio.regions(image,**kwargs)
    known=(textures.regions(image,**kwargs)+texture_packs.regions(image,**kwargs)+display_lists.regions(image,models=display_meshes,**kwargs)
           +ffs.regions(image,**kwargs)+rare_models.regions(image,**kwargs)+rare_assets.regions(image,**kwargs)+uv_textures.regions(image,**kwargs)+blast_textures.regions(image,**kwargs)+reloc_files.regions(image,**kwargs)+mainfs.regions(image,**kwargs)+fla2.regions(image,**kwargs)
           +sound_banks+rare_audio.regions(image,**kwargs)+paired_audio.regions(image,**kwargs)
           +pointer_banks+ptr_audio.sequences(image,**kwargs)+models.regions(image,**kwargs)
           +archived_models.regions(image,**kwargs)+rnx.regions(image,**kwargs)+dean_audio.regions(image,**kwargs)+dialogue.regions(image,**kwargs))
    known.extend(cartridge_scores.regions(image, sound_banks, **kwargs))
    known.extend(display_meshes)
    known.extend(bind.regions(image,**kwargs))
    known.extend(diet_audio.regions(image,**kwargs))
    known.extend(deflate_catalog.regions(image,**kwargs))
    known.extend(deflate_catalog_models.regions(image,**kwargs))
    known.extend(raw_deflate_lists.regions(image,**kwargs))
    known.extend(rzip_catalog.regions(image,**kwargs))
    known.extend(rzip_models.regions(image,**kwargs))
    known.extend(rzip_audio.regions(image,**kwargs))
    known.extend(prefixed_texture_catalog.regions(image,**kwargs))
    known.extend(prefixed_texture_models.regions(image,**kwargs))
    known.extend(rle_font_atlas.regions(image,**kwargs))
    known.extend(wad_resources.regions(image,**kwargs))
    known.extend(wad_models.regions(image,**kwargs))
    known.extend(wad_audio.regions(image,**kwargs))
    known.extend(ia_font_textures.regions(image,**kwargs))
    known.extend(indexed_resource_models.regions(image,**kwargs))
    known.extend(indexed_resource_textures.regions(image,**kwargs))
    known.extend(sized_lz_catalog.regions(image,**kwargs))
    known.extend(siff_models.regions(image,**kwargs))
    known.extend(segmented_model_resources.regions(image,**kwargs))
    stages = stage_banks.regions(image, **kwargs)
    known.extend(stages)
    known.extend(stage_meshes.regions(image, stages, kwargs.get("check", lambda: None)))
    known.extend(lz_banks.regions(image,**kwargs))
    known.extend(bolt.regions(image,**kwargs))
    known.extend(arithmetic_assets.regions(image,context=context,**kwargs))
    known.extend(arithmetic_descriptors.regions(image,context=context,**kwargs))
    known.extend(relative_materials.regions(image,**kwargs))
    known.extend(relative_meshes.regions(image,**kwargs))
    known.extend(yay0_atlases.regions(image,context=context,**kwargs))
    known.extend(yay0_scenes.regions(image,**kwargs))
    known.extend(inline_tiles.regions(image,**kwargs))
    known.extend(sn64.regions(image,**kwargs))
    known.extend(packed_anim.regions(image,**kwargs))
    known.extend(paged_models.regions(image,**kwargs))
    known.extend(paged_textures.regions(image,**kwargs))
    known.extend(paged_lz_models.regions(image,**kwargs))
    known.extend(nested_scenes.regions(image,**kwargs))
    known.extend(named_resource_images.regions(image,**kwargs))
    known.extend(packed_tim.regions(image,**kwargs))
    indexed_models = []
    known.extend(lz_texture_directories.regions(image,models=indexed_models,**kwargs))
    known.extend(indexed_models)
    known.extend(named_resource_models.regions(image,**kwargs))
    known.extend(tagged_deflate.regions(image,**kwargs))
    known.extend(striped_images.regions(image,**kwargs))
    compressed_meshes = []
    known.extend(rnc_tiled_images.regions(image,models=compressed_meshes,**kwargs))
    known.extend(compressed_meshes)
    known.extend(gzip_meshes.regions(image,**kwargs))
    known.extend(zlib_textures.regions(image,**kwargs))
    known.extend(zlib_meshes.regions(image,**kwargs))
    known.extend(inline_meshes.regions(image,**kwargs))
    known.extend(mwo_graphics.regions(image,context=context,**kwargs))
    known.extend(libmus_song.regions(image,pointer_banks,check=kwargs.get('check',lambda:None)))
    borg_rows = borg.entries(image, kwargs.get('check', lambda: None))
    known.extend(borg.regions(image,rows=borg_rows,**kwargs))
    known.extend(borg_models.regions(image,borg_rows,**kwargs))
    borg_samples = borg_audio.regions(image,borg_rows,**kwargs)
    known.extend(borg_samples)
    known.extend(borg_dcm.regions(image,borg_rows,borg_samples,**kwargs))
    known.extend(eurocom.regions(image,**kwargs))
    known.extend(uso_textures.regions(image,**kwargs))
    iguana_models = []
    known.extend(paired_resources.regions(image,**kwargs))
    known.extend(iain.regions(image,**kwargs))
    known.extend(iguana_textures.regions(image,models=iguana_models,**kwargs))
    known.extend(iguana_models)
    known.extend(iguana_audio.regions(image,**kwargs))
    known.extend(uso_models.regions(image,**kwargs))
    known.extend(uv_models.regions(image,**kwargs))
    known.extend(uv_sequences.regions(image,sound_banks=sound_banks,**kwargs))
    known.extend(parallel_midi.regions(image, **kwargs))
    known.extend(lz_standard_midi.regions(image,sound_banks=sound_banks,**kwargs))
    known.extend(uso_audio.regions(image,**kwargs))
    assets=known+resources.regions(image,known=known,**kwargs)
    native_scene.link(assets)
    dialogue_links.link(image,assets,kwargs.get('check',lambda:None))
    emsh_links.link(image,assets,kwargs.get('check',lambda:None))
    return assets+fonts.regions(image,context=context,known=assets,**kwargs)


def preview(data, asset, selection):
    """A preview of one asset `regions` found: an image, a sound, a model or a table, chosen by `selection`."""
    from . import (
        archived_models,
        arithmetic_assets,
        arithmetic_descriptors,
        audio,
        bind_models,
        bind_textures,
        blast_textures,
        bolt,
        borg,
        borg_audio,
        borg_dcm,
        borg_models,
        cartridge_scores,
        dean_audio,
        deflate_catalog,
        deflate_catalog_models,
        dialogue,
        diet_audio,
        display_meshes,
        eurocom,
        ffs,
        fla2,
        fonts,
        gzip_meshes,
        ia_font_textures,
        iain_models,
        iain_textures,
        iguana_audio,
        iguana_models,
        iguana_textures,
        indexed_resource_models,
        indexed_resource_textures,
        inline_tiles,
        libmus_song,
        lz_banks,
        lz_directory_models,
        lz_standard_midi,
        lz_texture_directories,
        mainfs,
        models,
        mwo_graphics,
        named_resource_images,
        named_resource_models,
        nested_scenes,
        packed_anim,
        packed_tim,
        paged_lz_models,
        paged_models,
        paged_textures,
        paired_audio,
        paired_resource_models,
        paired_resource_textures,
        parallel_midi,
        prefixed_texture_catalog,
        prefixed_texture_models,
        ptr_audio,
        rare_assets,
        rare_models,
        raw_deflate_lists,
        reloc_files,
        resources,
        rle_font_atlas,
        rnc_display_models,
        rnc_meshes,
        rnc_textures,
        rnc_tiled_images,
        rnx,
        rnx_atlas,
        rzip_audio,
        rzip_catalog,
        rzip_models,
        scene_records,
        segmented_model_resources,
        siff_models,
        sized_lz_catalog,
        sn64,
        stage_banks,
        stage_meshes,
        striped_images,
        tagged_deflate,
        texture_packs,
        textures,
        uso_audio,
        uso_audio_directory,
        uso_models,
        uso_textures,
        uv_models,
        uv_sequences,
        uv_textures,
        wad_audio,
        wad_models,
        wad_resources,
        yay0_atlases,
        yay0_scenes,
        zlib_meshes,
        zlib_textures,
    )
    if asset.get('layout','').startswith('eurocom-') or asset.get('layout')=='edl-stream':
        return eurocom.preview(data,asset,selection)
    if asset.get('layout')=='uso-sequence-directory':return uso_audio_directory.preview(data,asset,selection)
    if asset.get('layout')=='uso-music':return uso_audio.music_preview(data,asset,selection)
    if asset.get('layout')=='uso-audio':return uso_audio.preview(data,asset,selection)
    if asset.get('layout')=='uso-polygon-models':return uso_models.preview(data,asset,selection)
    if asset.get('layout') in ('iguana-dean','iguana-compact-midi'):return iguana_audio.preview(data,asset,selection)
    if asset.get('layout') in (tagged_deflate.IMAGE,tagged_deflate.MODEL):return tagged_deflate.preview(data,asset,selection)
    if asset.get('layout') in (rnc_tiled_images.LAYOUT,rnc_tiled_images.BANK,rnc_display_models.LAYOUT):return rnc_tiled_images.preview(data,asset,selection)
    if asset.get('layout')==striped_images.LAYOUT:return striped_images.preview(data,asset,selection)
    if asset.get('layout')==named_resource_images.LAYOUT:return named_resource_images.preview(data,asset,selection)
    if asset.get('layout')==packed_tim.LAYOUT:return packed_tim.preview(data,asset,selection)
    if asset.get('layout')==lz_texture_directories.LAYOUT:return lz_texture_directories.preview(data,asset,selection)
    if asset.get('layout')==lz_directory_models.LAYOUT:return lz_directory_models.preview(data,asset,selection)
    if asset.get('layout')==named_resource_models.LAYOUT:return named_resource_models.preview(data,asset,selection)
    if asset.get('layout') in (nested_scenes.IMAGE,nested_scenes.MODEL):return nested_scenes.preview(data,asset,selection)
    if asset.get('layout')==paged_lz_models.LAYOUT:return paged_lz_models.preview(data,asset,selection)
    if asset.get('layout')==paged_models.LAYOUT:return paged_models.preview(data,asset,selection)
    if asset.get('layout')==packed_anim.LAYOUT:return packed_anim.preview(data,asset,selection)
    if asset.get('layout')=='sn64-sequences':return sn64.preview_directory(data,asset,selection)
    if asset.get('layout')==cartridge_scores.LAYOUT:return cartridge_scores.preview(data,asset,selection)
    if asset.get('layout')==paired_audio.SEQUENCE_LAYOUT:return paired_audio.preview(data,asset,selection)
    if asset.get('layout')=='iguana-qmesh':return iguana_models.preview(data,asset,selection)
    if asset.get('layout')==iain_models.LAYOUT:return iain_models.preview(data,asset,selection)
    if asset.get('layout')==paired_resource_models.LAYOUT:return paired_resource_models.preview(data,asset,selection)
    if asset.get('layout')==paired_resource_textures.LAYOUT:return paired_resource_textures.preview(data,asset,selection)
    if asset.get('layout')==iain_textures.LAYOUT:return iain_textures.preview(data,asset,selection)
    if asset.get('layout')=='iguana-indexed-bitmaps':return iguana_textures.preview(data,asset,selection)
    if asset.get('layout')=='uso-ci8-bank':return uso_textures.preview(data,asset,selection)
    if asset.get('layout') in (diet_audio.BANK,diet_audio.SONG):return diet_audio.preview(data,asset,selection)
    if asset.get('layout')==bind_models.LAYOUT:return bind_models.preview(data,asset,selection)
    if asset.get('layout')==bind_textures.LAYOUT:return bind_textures.preview(data,asset,selection)
    if asset.get('layout')=='fla2-texbank':return fla2.preview(data,asset,selection)
    if asset.get('layout')=='mainfs':return mainfs.preview(data,asset,selection)
    if asset.get('layout')=='reloc-file':return reloc_files.preview(data,asset,selection)
    if asset.get('layout') in (lz_banks.BANK, lz_banks.SONGS):return lz_banks.preview(data,asset,selection)
    if asset.get('layout') == zlib_meshes.LAYOUT:return zlib_meshes.preview(data,asset,selection)
    if asset.get('layout') == paged_textures.LAYOUT:return paged_textures.preview(data,asset,selection)
    if asset.get('layout') == zlib_textures.LAYOUT:return zlib_textures.preview(data,asset,selection)
    if asset.get('layout') == deflate_catalog.TEXTURE:return deflate_catalog.preview(data,asset,selection)
    if asset.get('layout') == deflate_catalog_models.MODEL:return deflate_catalog_models.preview(data,asset,selection)
    if asset.get('layout') in (raw_deflate_lists.TEXTURE, raw_deflate_lists.MODEL):
        return raw_deflate_lists.preview(data,asset,selection)
    if asset.get('layout') == rzip_catalog.TEXTURE:return rzip_catalog.preview(data,asset,selection)
    if asset.get('layout') == rzip_models.MODEL:return rzip_models.preview(data,asset,selection)
    if asset.get('layout') == rzip_audio.LAYOUT:return rzip_audio.preview(data,asset,selection)
    if asset.get('layout') == prefixed_texture_catalog.LAYOUT:return prefixed_texture_catalog.preview(data,asset,selection)
    if asset.get('layout') == prefixed_texture_models.LAYOUT:return prefixed_texture_models.preview(data,asset,selection)
    if asset.get('layout') == ia_font_textures.LAYOUT:return ia_font_textures.preview(data,asset,selection)
    if asset.get('layout') == wad_audio.LAYOUT:return wad_audio.preview(data,asset,selection)
    if asset.get('layout') == wad_models.LAYOUT:return wad_models.preview(data,asset,selection)
    if asset.get('layout') == wad_resources.TEXTURE:return wad_resources.preview(data,asset,selection)
    if asset.get('layout') == rle_font_atlas.LAYOUT:return rle_font_atlas.preview(data,asset,selection)
    if asset.get('layout') == indexed_resource_models.LAYOUT:return indexed_resource_models.preview(data,asset,selection)
    if asset.get('layout') == indexed_resource_textures.LAYOUT:return indexed_resource_textures.preview(data,asset,selection)
    if asset.get('layout') == sized_lz_catalog.TEXTURE:return sized_lz_catalog.preview(data,asset,selection)
    if asset.get('layout') == stage_banks.TEXTURE:return stage_banks.preview(data,asset,selection)
    if asset.get('layout') == stage_meshes.MODEL:return stage_meshes.preview(data,asset,selection)
    if asset.get('layout') == segmented_model_resources.LAYOUT:return segmented_model_resources.preview(data,asset,selection)
    if asset.get('layout') in (siff_models.MODEL,siff_models.TEXTURE):return siff_models.preview(data,asset,selection)
    if asset.get('layout') == gzip_meshes.LAYOUT:return gzip_meshes.preview(data,asset,selection)
    if asset.get('layout')=='blast':return blast_textures.preview(data,asset,selection)
    if asset.get('layout')=='uv-sequence-directory':return uv_sequences.preview(data,asset,selection)
    if asset.get('layout')==parallel_midi.LAYOUT:return parallel_midi.preview(data,asset,selection)
    if asset.get('layout')==lz_standard_midi.LAYOUT:return lz_standard_midi.preview(data,asset,selection)
    if asset.get('layout')=='f3dex-mesh':return display_meshes.preview(data,asset,selection)
    if asset.get('layout') in ('libmus-raw-song','libmus-binary-song','libmus-binary-effects'):return libmus_song.preview(data,asset,selection)
    if asset.get('layout')=='borg-dcm':return borg_dcm.preview(data,asset,selection)
    if asset.get('layout') in (bolt.TEXTURE,bolt.MODEL,'bolt-vox'):return bolt.preview(data,asset,selection)
    if asset.get('layout')==arithmetic_assets.TEXTURES:return arithmetic_assets.preview(data,asset,selection)
    if asset.get('layout')==arithmetic_descriptors.LAYOUT:return arithmetic_descriptors.preview(data,asset,selection)
    if asset.get('layout') in (yay0_scenes.IMAGE,yay0_scenes.MODEL):return yay0_scenes.preview(data,asset,selection)
    if asset.get('layout')==yay0_atlases.LAYOUT:return yay0_atlases.preview(data,asset,selection)
    if asset.get('layout') in (mwo_graphics.TEXTURES,mwo_graphics.MODELS):return mwo_graphics.preview(data,asset,selection)
    if asset.get('layout')=='borg-audio':return borg_audio.preview(data,asset,selection)
    if asset.get('layout')=='borg-model':return borg_models.preview(data,asset,selection)
    if asset.get('layout')=='borg-texture':return borg.preview(data,asset,selection)
    if asset.get('layout')=='uv-model':return uv_models.preview(data,asset,selection)
    if asset.get('layout')==inline_tiles.LAYOUT:return inline_tiles.preview(data,asset,selection)
    if asset.get('layout')=='uv-texture':return uv_textures.preview(data,asset,selection)
    if asset.get('layout')=='ffs-i64':return ffs.preview(data,asset,selection)
    if asset.get('layout') in (rare_assets.TEXTURES, rare_assets.MESH):return rare_assets.preview(data,asset,selection)
    if asset.get('layout') in ('rare-model', rare_assets.SEQUEL_MESH):return rare_models.preview(data,asset,selection)
    if asset.get('font_layout')=='native-i4-pointer-glyphs':return fonts.preview(data,asset,selection)
    if asset.get('audio_kind') in ('libmus sample bank','libmus sequence'):return ptr_audio.preview(data,asset,selection)
    if asset.get('layout')=='archived-pd3v-model':return archived_models.preview(data,asset,selection)
    if asset.get('layout')=='rnx-ci4-atlas':return rnx_atlas.preview(data,asset,selection)
    if asset.get('layout')=='rnx-stream':return rnx.preview(data,asset)
    if asset.get('layout')=='scene-records':return scene_records.preview(data,asset,selection)
    if asset.get('layout')=='dialogue-script':return dialogue.preview(data,asset,selection)
    if asset.get('audio_kind')=='dean stream':return dean_audio.preview(data,asset,selection)
    if asset.get('layout')=='emsh-v010':return rnc_meshes.preview(data,asset,selection)
    if asset.get('layout')=='rnc-sum32-texture-bank':return rnc_textures.preview(data,asset,selection)
    if asset.get('layout')=='trailer-count-texture-pack':return texture_packs.preview(data,asset,selection)
    return {'audio':audio.preview,'model':models.preview,'metadata':resources.preview}.get(asset.get('media'),textures.preview)(data,asset,selection)


def scene(image, asset, selection, assets):
    """An object from a resource directory with its linked model, textures and animation."""
    from . import native_scene, rnc_meshes
    from .models import ModelError
    from .resources import SchemaError
    if asset.get('layout')=='emsh-v010' and (link:=asset.get('emsh_texture_bank')):
        bank=next((a for a in assets if a['offset']==link['offset'] and a.get('layout')=='rnc-sum32-texture-bank'),None)
        if bank is not None:
            return rnc_meshes.preview(native_scene.raw(image,asset),asset,selection,
                                      (native_scene.raw(image,bank),bank['offset']))
    try:return native_scene.preview(image,asset,selection,assets)
    except (ModelError,SchemaError) as exc:raise AssetError(str(exc)+' Rescan and choose another resource.') from None
