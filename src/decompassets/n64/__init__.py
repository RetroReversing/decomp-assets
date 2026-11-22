"""Nintendo 64 asset recognisers. Each one accepts a candidate only when its whole structure checks out.

- textures.py: indexed texture banks (CI4/CI8, RGBA32, the six-level RGBA16 mipmap layout), raw or RNC-packed.
- rnc_textures.py: descriptor-table texture banks inside byte-sum RNC blocks.
- texture_packs.py: texture packs with a trailing count, inside archives.
- relative_directory.py, relative_textures.py: compressed resource tables and display-list textures.
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
- big_pages.py, big_models.py, big_textures.py, big_audio.py, big_sam_audio.py: paged resource archives, their meshes and indexed images.
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
        big_models,
        bind,
        blast_textures,
        bnkb_audio,
        bolt,
        borg,
        borg_audio,
        borg_dcm,
        borg_models,
        bounded_lz_models,
        cartridge_scores,
        chunked_package_images,
        dean_audio,
        deflate_catalog,
        deflate_catalog_models,
        deflate_segment_models,
        deflate_sprites,
        dialogue,
        dialogue_links,
        diet_audio,
        display_lists,
        ead_direct_audio,
        emsh_links,
        eurocom,
        exs_images,
        exs_models,
        f3dex_tiles,
        fat_models,
        fat_textures,
        ffs,
        fla2,
        fonts,
        graphbin,
        gzip_meshes,
        ia_font_textures,
        iain,
        iguana_audio,
        iguana_textures,
        indexed_resource_models,
        indexed_resource_textures,
        inline_meshes,
        inline_tiles,
        iwad_maps,
        iwad_sprites,
        level_bytecode,
        libmus_song,
        lz_banks,
        lz_standard_midi,
        lz_texture_directories,
        lzss_archive_images,
        lzss_archive_models,
        mainfs,
        mio0_graphics,
        models,
        mwo_graphics,
        named_adpcm,
        named_resource_images,
        named_resource_models,
        native_scene,
        nested_scenes,
        offset_models,
        offset_textures,
        packed_anim,
        packed_model_tables,
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
        refpack_opcodes,
        refpack_stadium,
        refpack_triangles,
        relative_audio,
        relative_materials,
        relative_meshes,
        relative_models,
        relative_objects,
        relative_textures,
        reloc_files,
        resources,
        rle_font_atlas,
        rle_texture_tables,
        rnc_indexed_sprites,
        rnc_quad_models,
        rnc_tiled_images,
        rnx,
        rzip_audio,
        rzip_catalog,
        rzip_models,
        sdf2_audio,
        sdf2_music,
        segmented_model_resources,
        shpn_images,
        siff_models,
        sized_lz_catalog,
        sn64,
        stage_banks,
        stage_meshes,
        striped_images,
        tagged_deflate,
        terminated_rgba_tiles,
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
        zip_object_models,
        zip_object_textures,
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
    known.extend(relative_textures.regions(image,**kwargs))
    known.extend(relative_models.regions(image,**kwargs))
    known.extend(relative_objects.regions(image,**kwargs))
    known.extend(relative_audio.regions(image,**kwargs))
    known.extend(deflate_catalog.regions(image,**kwargs))
    known.extend(deflate_catalog_models.regions(image,**kwargs))
    known.extend(raw_deflate_lists.regions(image,**kwargs))
    known.extend(rzip_catalog.regions(image,**kwargs))
    known.extend(rzip_models.regions(image,**kwargs))
    known.extend(rzip_audio.regions(image,**kwargs))
    known.extend(prefixed_texture_catalog.regions(image,**kwargs))
    known.extend(prefixed_texture_models.regions(image,**kwargs))
    known.extend(rle_font_atlas.regions(image,**kwargs))
    known.extend(fat_textures.regions(image,**kwargs))
    known.extend(bounded_lz_models.regions(image,**kwargs))
    known.extend(terminated_rgba_tiles.regions(image,**kwargs))
    known.extend(rnc_indexed_sprites.regions(image,**kwargs))
    known.extend(named_adpcm.regions(image,**kwargs))
    known.extend(rnc_quad_models.regions(image,**kwargs))
    known.extend(f3dex_tiles.regions(image,**kwargs))
    known.extend(fat_models.regions(image,**kwargs))
    known.extend(wad_resources.regions(image,**kwargs))
    known.extend(wad_models.regions(image,**kwargs))
    known.extend(wad_audio.regions(image,**kwargs))
    known.extend(zip_object_models.regions(image,**kwargs))
    known.extend(zip_object_textures.regions(image,**kwargs))
    known.extend(offset_textures.regions(image,**kwargs))
    known.extend(offset_models.regions(image,**kwargs))
    known.extend(shpn_images.regions(image,**kwargs))
    known.extend(refpack_triangles.regions(image,**kwargs))
    known.extend(refpack_stadium.regions(image,**kwargs))
    known.extend(refpack_opcodes.regions(image,**kwargs))
    known.extend(ead_direct_audio.regions(image,**kwargs))
    known.extend(bnkb_audio.regions(image,**kwargs))
    known.extend(exs_images.regions(image,**kwargs))
    known.extend(exs_models.regions(image,**kwargs))
    mio0_images = []
    known.extend(mio0_graphics.regions(image,images=mio0_images,**kwargs))
    known.extend(mio0_images)
    known.extend(ia_font_textures.regions(image,**kwargs))
    known.extend(iwad_sprites.regions(image,**kwargs))
    known.extend(iwad_maps.regions(image,**kwargs))
    known.extend(indexed_resource_models.regions(image,**kwargs))
    known.extend(indexed_resource_textures.regions(image,**kwargs))
    known.extend(sized_lz_catalog.regions(image,**kwargs))
    known.extend(siff_models.regions(image,**kwargs))
    known.extend(segmented_model_resources.regions(image,**kwargs))
    stages = stage_banks.regions(image, **kwargs)
    known.extend(stages)
    known.extend(stage_meshes.regions(image, stages, kwargs.get("check", lambda: None)))
    known.extend(level_bytecode.regions(image,**kwargs))
    known.extend(lz_banks.regions(image,**kwargs))
    known.extend(lzss_archive_images.regions(image,**kwargs))
    mixed_images = []
    known.extend(lzss_archive_models.regions(image,images=mixed_images,**kwargs))
    known.extend(mixed_images)
    known.extend(bolt.regions(image,**kwargs))
    known.extend(arithmetic_assets.regions(image,context=context,**kwargs))
    known.extend(arithmetic_descriptors.regions(image,context=context,**kwargs))
    known.extend(relative_materials.regions(image,**kwargs))
    known.extend(relative_meshes.regions(image,**kwargs))
    known.extend(yay0_atlases.regions(image,context=context,**kwargs))
    known.extend(yay0_scenes.regions(image,**kwargs))
    known.extend(inline_tiles.regions(image,**kwargs))
    known.extend(sn64.regions(image,**kwargs))
    known.extend(sdf2_audio.regions(image,**kwargs))
    known.extend(sdf2_music.regions(image,**kwargs))
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
    known.extend(rle_texture_tables.regions(image,context=context,**kwargs))
    known.extend(packed_model_tables.regions(image,context=context,**kwargs))
    known.extend(chunked_package_images.regions(image,**kwargs))
    big_images, big_sounds = [], []
    known.extend(big_models.regions(image,images=big_images,audio=big_sounds,**kwargs))
    known.extend(big_images)
    known.extend(big_sounds)
    known.extend(graphbin.regions(image,**kwargs))
    known.extend(deflate_sprites.regions(image,**kwargs))
    known.extend(deflate_segment_models.regions(image,**kwargs))
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
        big_audio,
        big_models,
        big_sam_audio,
        big_textures,
        bind_models,
        bind_textures,
        blast_textures,
        bnkb_audio,
        bolt,
        borg,
        borg_audio,
        borg_dcm,
        borg_models,
        bounded_lz_models,
        cartridge_scores,
        chunked_package_images,
        dean_audio,
        deflate_catalog,
        deflate_catalog_models,
        deflate_segment_models,
        deflate_sprites,
        dialogue,
        diet_audio,
        display_meshes,
        ead_direct_audio,
        eurocom,
        exs_images,
        exs_models,
        f3dex_tiles,
        fat_models,
        fat_textures,
        ffs,
        fla2,
        fonts,
        graphbin,
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
        iwad_maps,
        iwad_sprites,
        level_bytecode,
        libmus_song,
        lz_banks,
        lz_directory_models,
        lz_standard_midi,
        lz_texture_directories,
        lzss_archive_images,
        lzss_archive_models,
        mainfs,
        mio0_graphics,
        models,
        mwo_graphics,
        named_adpcm,
        named_resource_images,
        named_resource_models,
        nested_scenes,
        offset_models,
        offset_textures,
        packed_anim,
        packed_model_tables,
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
        refpack_opcodes,
        refpack_stadium,
        refpack_triangles,
        relative_audio,
        relative_models,
        relative_objects,
        relative_textures,
        reloc_files,
        resources,
        rle_font_atlas,
        rle_texture_tables,
        rnc_display_models,
        rnc_indexed_sprites,
        rnc_meshes,
        rnc_quad_models,
        rnc_textures,
        rnc_tiled_images,
        rnx,
        rnx_atlas,
        rzip_audio,
        rzip_catalog,
        rzip_models,
        scene_records,
        sdf2_audio,
        sdf2_music,
        segmented_model_resources,
        shpn_images,
        siff_models,
        sized_lz_catalog,
        sn64,
        sn64_music,
        stage_banks,
        stage_meshes,
        striped_images,
        tagged_deflate,
        terminated_rgba_tiles,
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
        zip_object_models,
        zip_object_textures,
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
    if asset.get('layout') == packed_model_tables.LAYOUT:return packed_model_tables.preview(data,asset,selection)
    if asset.get('layout') == rle_texture_tables.LAYOUT:return rle_texture_tables.preview(data,asset,selection)
    if asset.get('layout') == sdf2_music.LAYOUT:return sdf2_music.preview(data,asset,selection)
    if asset.get('layout') == sdf2_audio.LAYOUT:return sdf2_audio.preview(data,asset,selection)
    if asset.get('layout') == deflate_segment_models.LAYOUT:return deflate_segment_models.preview(data,asset,selection)
    if asset.get('layout') == deflate_sprites.LAYOUT:return deflate_sprites.preview(data,asset,selection)
    if asset.get('layout') == chunked_package_images.LAYOUT:return chunked_package_images.preview(data,asset,selection)
    if asset.get('layout') == big_sam_audio.LAYOUT:return big_sam_audio.preview(data,asset,selection)
    if asset.get('layout') == big_audio.LAYOUT:return big_audio.preview(data,asset,selection)
    if asset.get('layout') == big_textures.LAYOUT:return big_textures.preview(data,asset,selection)
    if asset.get('layout') == big_models.LAYOUT:return big_models.preview(data,asset,selection)
    if asset.get('layout') == graphbin.LAYOUT:return graphbin.preview(data,asset,selection)
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
    if asset.get('layout')=='sn64-sequences':
        return sn64_music.preview(data,asset,selection) if asset.get('samples') else sn64.preview_directory(data,asset,selection)
    if asset.get('layout')==cartridge_scores.LAYOUT:return cartridge_scores.preview(data,asset,selection)
    if asset.get('layout')==paired_audio.SEQUENCE_LAYOUT:return paired_audio.preview(data,asset,selection)
    if asset.get('layout')=='iguana-qmesh':return iguana_models.preview(data,asset,selection)
    if asset.get('layout')==iain_models.LAYOUT:return iain_models.preview(data,asset,selection)
    if asset.get('layout')==paired_resource_models.LAYOUT:return paired_resource_models.preview(data,asset,selection)
    if asset.get('layout')==paired_resource_textures.LAYOUT:return paired_resource_textures.preview(data,asset,selection)
    if asset.get('layout')==iain_textures.LAYOUT:return iain_textures.preview(data,asset,selection)
    if asset.get('layout') == f3dex_tiles.LAYOUT:return f3dex_tiles.preview(data,asset,selection)
    if asset.get('layout') == bounded_lz_models.LAYOUT:return bounded_lz_models.preview(data,asset,selection)
    if asset.get('layout') == terminated_rgba_tiles.LAYOUT:return terminated_rgba_tiles.preview(data,asset,selection)
    if asset.get('layout') == rnc_indexed_sprites.LAYOUT:return rnc_indexed_sprites.preview(data,asset,selection)
    if asset.get('layout') == named_adpcm.LAYOUT:return named_adpcm.preview(data,asset,selection)
    if asset.get('layout') == rnc_quad_models.LAYOUT:return rnc_quad_models.preview(data,asset,selection)
    if asset.get('layout')=='iguana-indexed-bitmaps':return iguana_textures.preview(data,asset,selection)
    if asset.get('layout')=='uso-ci8-bank':return uso_textures.preview(data,asset,selection)
    if asset.get('layout') in (diet_audio.BANK,diet_audio.SONG):return diet_audio.preview(data,asset,selection)
    if asset.get('layout')==bind_models.LAYOUT:return bind_models.preview(data,asset,selection)
    if asset.get('layout')==bind_textures.LAYOUT:return bind_textures.preview(data,asset,selection)
    if asset.get('layout') == lzss_archive_models.LAYOUT:return lzss_archive_models.preview(data,asset,selection)
    if asset.get('layout') == 'ring-lzss-model-images':return lzss_archive_models.preview_image(data,asset,selection)
    if asset.get('layout') == shpn_images.LAYOUT:return shpn_images.preview(data,asset,selection)
    if asset.get('layout') == refpack_triangles.LAYOUT:return refpack_triangles.preview(data,asset,selection)
    if asset.get('layout') == refpack_stadium.LAYOUT:return refpack_stadium.preview(data,asset,selection)
    if asset.get('layout') == refpack_opcodes.LAYOUT:return refpack_opcodes.preview(data,asset,selection)
    if asset.get('layout') == ead_direct_audio.LAYOUT:return ead_direct_audio.preview(data,asset,selection)
    if asset.get('layout') == bnkb_audio.LAYOUT:return bnkb_audio.preview(data,asset,selection)
    if asset.get('layout') == mio0_graphics.MODEL:return mio0_graphics.preview(data,asset,selection)
    if asset.get('layout') == mio0_graphics.IMAGE:return mio0_graphics.preview_image(data,asset,selection)
    if asset.get('layout') == exs_models.LAYOUT:return exs_models.preview(data,asset,selection)
    if asset.get('layout') == exs_images.LAYOUT:return exs_images.preview(data,asset,selection)
    if asset.get('layout') == lzss_archive_images.LAYOUT:return lzss_archive_images.preview(data,asset,selection)
    if asset.get('layout') == level_bytecode.LAYOUT:return level_bytecode.preview(data,asset,selection)
    if asset.get('layout')=='fla2-texbank':return fla2.preview(data,asset,selection)
    if asset.get('layout')=='mainfs':return mainfs.preview(data,asset,selection)
    if asset.get('layout')==offset_models.LAYOUT:return offset_models.preview(data,asset,selection)
    if asset.get('layout')==offset_textures.LAYOUT:return offset_textures.preview(data,asset,selection)
    if asset.get('layout')==fat_models.LAYOUT:return fat_models.preview(data,asset,selection)
    if asset.get('layout')==fat_textures.LAYOUT:return fat_textures.preview(data,asset,selection)
    if asset.get('layout')=='reloc-file':return reloc_files.preview(data,asset,selection)
    if asset.get('layout') in (lz_banks.BANK, lz_banks.SONGS):return lz_banks.preview(data,asset,selection)
    if asset.get('layout') == zlib_meshes.LAYOUT:return zlib_meshes.preview(data,asset,selection)
    if asset.get('layout') == paged_textures.LAYOUT:return paged_textures.preview(data,asset,selection)
    if asset.get('layout') == zlib_textures.LAYOUT:return zlib_textures.preview(data,asset,selection)
    if asset.get('layout') == relative_textures.LAYOUT:return relative_textures.preview(data,asset,selection)
    if asset.get('layout') == relative_models.LAYOUT:return relative_models.preview(data,asset,selection)
    if asset.get('layout') == relative_objects.LAYOUT:return relative_objects.preview(data,asset,selection)
    if asset.get('layout') in (relative_audio.BANK, relative_audio.SONG):return relative_audio.preview(data,asset,selection)
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
    if asset.get('layout') in (iwad_sprites.LAYOUT, iwad_sprites.TEXTURE):return iwad_sprites.preview(data,asset,selection)
    if asset.get('layout') == iwad_maps.LAYOUT:return iwad_maps.preview(data,asset,selection)
    if asset.get('layout') == zip_object_textures.LAYOUT:return zip_object_textures.preview(data,asset,selection)
    if asset.get('layout') == zip_object_models.LAYOUT:return zip_object_models.preview(data,asset,selection)
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
