"""Nintendo 64 asset recognisers. Each one accepts a candidate only when its whole structure checks out.

- textures.py: indexed texture banks (CI4/CI8, RGBA32, the six-level RGBA16 mipmap layout), raw or RNC-packed.
- constructed_resource_textures.py: indexed packed textures identified by loader and drawing code.
- rnc_textures.py: descriptor-table texture banks inside byte-sum RNC blocks.
- rnc_segmented_resources.py: display lists, textures and vertices in checked consecutive RNC blocks.
- rnc_inline_meshes.py: local display-list meshes in checked RNC blocks with inline vertices.
- texture_packs.py: texture packs with a trailing count, inside archives.
- relative_directory.py, relative_textures.py: compressed resource tables and display-list textures.
- display_lists.py: textures that uncompressed display lists load, in files placed by their vertices and pointers.
- fla2.py: texture banks packed with FLA2, the LZ variant of a platformer about a magic glove.
- ffs.py: I64 images in an FFS filesystem packed as one chunked RNC stream.
- runtime_audio.py: sound-table evidence from relocated control graphs in RAM.
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
- rnc_control_audio.py: checked compressed controls and a uniquely corroborated sample table.
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
        adjacent_display_models,
        aki_models,
        aki_textures,
        archived_models,
        arithmetic_assets,
        arithmetic_descriptors,
        audio,
        b1_speech,
        be_iwad_audio,
        be_iwad_images,
        be_iwad_maps,
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
        chunked_polygon_meshes,
        chunked_zlib,
        compact_mio_models,
        compact_mio_textures,
        constructed_resource_textures,
        dean_audio,
        deflate_catalog,
        deflate_catalog_models,
        deflate_level_models,
        deflate_segment_models,
        deflate_sprites,
        deflated_texture_table,
        dialogue,
        dialogue_links,
        diet_audio,
        display_lists,
        ead_direct_audio,
        early_ial_audio,
        embedded_ci8,
        embedded_geometry,
        emsh_links,
        eurocom,
        exs_images,
        exs_models,
        f3dex_tiles,
        fat_models,
        fat_textures,
        ffs,
        ffs_models,
        fla2,
        fla2_models,
        flag_lz_graphics,
        float_model_banks,
        fonts,
        graphbin,
        grid_tile_meshes,
        gzip_meshes,
        ia_font_textures,
        iain,
        iguana_audio,
        iguana_skin_models,
        iguana_textures,
        img_textures,
        indexed_archive_models,
        indexed_be_textures,
        indexed_deflate_models,
        indexed_pic_images,
        indexed_resource_models,
        indexed_resource_textures,
        indexed_sprite_banks,
        inline_meshes,
        inline_tiles,
        iwad_maps,
        iwad_sprites,
        legacy_level_models,
        legacy_level_world,
        legacy_reloc_objects,
        level_bytecode,
        level_logos,
        level_world,
        level_world_models,
        libmus_song,
        ljam_models,
        ljam_textures,
        lz_banks,
        lz_indexed_images,
        lz_section_meshes,
        lz_standard_midi,
        lz_texture_directories,
        lzo_models,
        lzss_archive_images,
        lzss_archive_models,
        mainfs,
        mainfs_models,
        mio0_graphics,
        models,
        mort_streams,
        mwo_graphics,
        named_adpcm,
        named_cmp_textures,
        named_file_effects,
        named_file_models,
        named_file_textures,
        named_prm_models,
        named_resource_images,
        named_resource_models,
        named_tim_archives,
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
        paired_rle_images,
        paired_rle_models,
        parallel_midi,
        prefixed_texture_catalog,
        prefixed_texture_models,
        ptr_audio,
        ptr_audio_v1,
        rare_assets,
        rare_audio,
        rare_models,
        raw_deflate_lists,
        refpack_first_cache,
        refpack_midx,
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
        reloc_level_objects,
        resources,
        rgba_runtime_headers,
        rle_font_atlas,
        rle_texture_tables,
        rnc_adpcm,
        rnc_chunk_models,
        rnc_control_audio,
        rnc_indexed_sprites,
        rnc_inline_meshes,
        rnc_pgd_models,
        rnc_quad_models,
        rnc_reloc_display,
        rnc_rgba_tiles,
        rnc_segmented_resources,
        rnc_shpn_images,
        rnc_tiled_images,
        rnx,
        romdisk_art,
        romdisk_speech,
        runtime_textures,
        rzip_audio,
        rzip_catalog,
        rzip_models,
        sdf2_audio,
        sdf2_music,
        segmented_model_resources,
        segmented_node_models,
        shpn_images,
        siff_models,
        sized_archive_audio,
        sized_lz_catalog,
        sn64,
        sprite_constructor,
        sprite_sheets,
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
        vol_textures,
        wad_audio,
        wad_models,
        wad_resources,
        yay0_atlases,
        yay0_scenes,
        zip_object_models,
        zip_object_textures,
        zlib_indexed_images,
        zlib_meshes,
        zlib_poly_models,
        zlib_textures,
    )
    display_meshes = []
    sound_banks = audio.regions(image,context=context,**kwargs)
    pointer_banks = ptr_audio.regions(image,**kwargs)
    known=(textures.regions(image,**kwargs)+texture_packs.regions(image,**kwargs)+display_lists.regions(image,models=display_meshes,**kwargs)
           +ffs.regions(image,**kwargs)+ffs_models.regions(image,**kwargs)+rare_models.regions(image,**kwargs)+rare_assets.regions(image,**kwargs)+uv_textures.regions(image,**kwargs)+blast_textures.regions(image,**kwargs)+reloc_files.regions(image,**kwargs)+mainfs.regions(image,**kwargs)+mainfs_models.regions(image,**kwargs)+fla2.regions(image,**kwargs)
           +sound_banks+rare_audio.regions(image,**kwargs)+paired_audio.regions(image,**kwargs)
           +pointer_banks+ptr_audio.sequences(image,**kwargs)+models.regions(image,**kwargs)
           +archived_models.regions(image,**kwargs)+rnx.regions(image,**kwargs)+dean_audio.regions(image,**kwargs)+dialogue.regions(image,**kwargs))
    known.extend(indexed_deflate_models.regions(image, **kwargs))
    known.extend(indexed_be_textures.regions(image, **kwargs))
    known.extend(indexed_deflate_models.texture_regions(image, **kwargs))
    known.extend(cartridge_scores.regions(image, sound_banks, **kwargs))
    known.extend(sprite_constructor.regions(image, context=context, **kwargs))
    known.extend(lzo_models.regions(image, **kwargs))
    known.extend(fla2_models.regions(image, **kwargs))
    known.extend(ptr_audio_v1.regions(image, **kwargs))
    known.extend(romdisk_speech.regions(image, **kwargs))
    known.extend(legacy_level_world.regions(image, **kwargs))
    known.extend(legacy_level_models.regions(image, **kwargs))
    known.extend(legacy_reloc_objects.regions(image, **kwargs))
    known.extend(level_logos.regions(image, **kwargs))
    known.extend(level_world.regions(image, **kwargs))
    known.extend(level_world_models.regions(image, **kwargs))
    known.extend(indexed_archive_models.regions(image, **kwargs))
    known.extend(indexed_pic_images.regions(image, **kwargs))
    known.extend(embedded_ci8.regions(image, **kwargs))
    known.extend(embedded_geometry.regions(image, **kwargs))
    known.extend(grid_tile_meshes.regions(image, **kwargs))
    known.extend(indexed_sprite_banks.regions(image, **kwargs))
    known.extend(segmented_node_models.regions(image, **kwargs))
    known.extend(deflated_texture_table.regions(image, **kwargs))
    known.extend(vol_textures.regions(image, **kwargs))
    known.extend(reloc_level_objects.regions(image, **kwargs))
    known.extend(romdisk_art.regions(image, **kwargs))
    known.extend(b1_speech.regions(image,**kwargs))
    known.extend(display_meshes)
    known.extend(bind.regions(image,**kwargs))
    known.extend(diet_audio.regions(image,**kwargs))
    known.extend(relative_textures.regions(image,**kwargs))
    known.extend(compact_mio_textures.regions(image,**kwargs))
    known.extend(compact_mio_models.regions(image,**kwargs))
    known.extend(flag_lz_graphics.regions(image,**kwargs))
    known.extend(float_model_banks.regions(image,**kwargs))
    known.extend(relative_models.regions(image,**kwargs))
    known.extend(relative_objects.regions(image,**kwargs))
    known.extend(relative_audio.regions(image,**kwargs))
    known.extend(deflate_catalog.regions(image,**kwargs))
    known.extend(deflate_catalog_models.regions(image,**kwargs))
    known.extend(deflate_level_models.regions(image,**kwargs))
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
    known.extend(rnc_adpcm.regions(image,**kwargs))
    known.extend(rnc_quad_models.regions(image,**kwargs))
    known.extend(rnc_reloc_display.regions(image,**kwargs))
    known.extend(rnc_reloc_display.image_regions(image,**kwargs))
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
    known.extend(rnc_shpn_images.regions(image,**kwargs))
    known.extend(ljam_textures.regions(image,**kwargs))
    known.extend(ljam_models.regions(image,**kwargs))
    known.extend(rnc_pgd_models.regions(image,**kwargs))
    known.extend(named_tim_archives.regions(image,**kwargs))
    known.extend(named_cmp_textures.regions(image,**kwargs))
    known.extend(named_prm_models.regions(image,**kwargs))
    known.extend(refpack_triangles.regions(image,**kwargs))
    known.extend(refpack_stadium.regions(image,**kwargs))
    known.extend(refpack_opcodes.regions(image,**kwargs))
    known.extend(refpack_midx.regions(image,**kwargs))
    known.extend(refpack_first_cache.regions(image,**kwargs))
    known.extend(ead_direct_audio.regions(image,**kwargs))
    known.extend(early_ial_audio.regions(image,**kwargs))
    known.extend(bnkb_audio.regions(image,**kwargs))
    known.extend(exs_images.regions(image,**kwargs))
    known.extend(exs_models.regions(image,**kwargs))
    mio0_images = []
    known.extend(mio0_graphics.regions(image,images=mio0_images,**kwargs))
    known.extend(mio0_images)
    known.extend(ia_font_textures.regions(image,**kwargs))
    known.extend(be_iwad_audio.regions(image,**kwargs))
    known.extend(be_iwad_images.regions(image,**kwargs))
    known.extend(be_iwad_maps.regions(image,**kwargs))
    known.extend(named_file_textures.regions(image,**kwargs))
    known.extend(named_file_models.regions(image,**kwargs))
    known.extend(iwad_sprites.regions(image,**kwargs))
    known.extend(iwad_maps.regions(image,**kwargs))
    known.extend(indexed_resource_models.regions(image,**kwargs))
    known.extend(indexed_resource_textures.regions(image,**kwargs))
    known.extend(sized_lz_catalog.regions(image,**kwargs))
    known.extend(siff_models.regions(image,**kwargs))
    known.extend(segmented_model_resources.regions(image,**kwargs))
    known.extend(rnc_segmented_resources.regions(image,**kwargs))
    known.extend(rnc_inline_meshes.regions(image,**kwargs))
    chunked = chunked_zlib.regions(image,**kwargs)
    known.extend(chunked_polygon_meshes.regions(image,chunked,**kwargs))
    known.extend(chunked)
    known.extend(aki_textures.regions(image,**kwargs))
    known.extend(img_textures.regions(image,**kwargs))
    known.extend(sprite_sheets.regions(image,**kwargs))
    known.extend(aki_models.regions(image,**kwargs))
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
    known.extend(rnc_chunk_models.regions(image,**kwargs))
    known.extend(rnc_rgba_tiles.regions(image,**kwargs))
    known.extend(rgba_runtime_headers.regions(image,**kwargs))
    known.extend(adjacent_display_models.regions(image,**kwargs))
    known.extend(compressed_meshes)
    known.extend(gzip_meshes.regions(image,**kwargs))
    known.extend(zlib_textures.regions(image,**kwargs))
    known.extend(zlib_indexed_images.regions(image,**kwargs))
    known.extend(zlib_meshes.regions(image,**kwargs))
    known.extend(zlib_poly_models.regions(image,**kwargs))
    known.extend(mort_streams.regions(image,**kwargs))
    known.extend(inline_meshes.regions(image,**kwargs))
    known.extend(mwo_graphics.regions(image,context=context,**kwargs))
    known.extend(lz_indexed_images.regions(image,**kwargs))
    known.extend(lz_section_meshes.regions(image,**kwargs))
    known.extend(libmus_song.regions(image,pointer_banks,check=kwargs.get('check',lambda:None)))
    known.extend(named_file_effects.regions(image,pointer_banks,check=kwargs.get('check',lambda:None)))
    borg_rows = borg.entries(image, kwargs.get('check', lambda: None))
    known.extend(borg.regions(image,rows=borg_rows,**kwargs))
    known.extend(borg_models.regions(image,borg_rows,**kwargs))
    borg_samples = borg_audio.regions(image,borg_rows,**kwargs)
    known.extend(borg_samples)
    known.extend(borg_dcm.regions(image,borg_rows,borg_samples,**kwargs))
    known.extend(eurocom.regions(image,**kwargs))
    known.extend(uso_textures.regions(image,**kwargs))
    iguana_models = []
    from . import chunked_lz_images
    known.extend(chunked_lz_images.regions(image,**kwargs))
    known.extend(paired_resources.regions(image,**kwargs))
    known.extend(constructed_resource_textures.regions(image,context=context,**kwargs))
    known.extend(runtime_textures.regions(image, (context or {}).get("runtime_snapshots", ()), check=kwargs.get("check", lambda: None)))
    known.extend(paired_rle_images.regions(image,**kwargs))
    known.extend(paired_rle_models.regions(image,**kwargs))
    known.extend(iain.regions(image,**kwargs))
    known.extend(iguana_textures.regions(image,models=iguana_models,**kwargs))
    known.extend(iguana_models)
    known.extend(iguana_audio.regions(image,**kwargs))
    known.extend(iguana_skin_models.regions(image,**kwargs))
    known.extend(sized_archive_audio.regions(image,**kwargs))
    known.extend(rnc_control_audio.regions(image,**kwargs))
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
        aki_models,
        aki_textures,
        archived_models,
        arithmetic_assets,
        arithmetic_descriptors,
        audio,
        b1_speech,
        be_iwad_images,
        be_iwad_maps,
        big_audio,
        big_models,
        big_sam_audio,
        big_tagged_models,
        big_tagged_textures,
        big_textures,
        bind_models,
        bind_textures,
        blast_textures,
        block16_graphics,
        bnkb_audio,
        bolt,
        borg,
        borg_audio,
        borg_dcm,
        borg_models,
        bounded_lz_models,
        cartridge_scores,
        chunked_package_images,
        chunked_polygon_meshes,
        chunked_zlib,
        compact_mio_models,
        compact_mio_textures,
        constructed_resource_textures,
        dean_audio,
        deflate_catalog,
        deflate_catalog_models,
        deflate_level_models,
        deflate_segment_models,
        deflate_sprites,
        deflated_texture_table,
        dialogue,
        diet_audio,
        display_meshes,
        ead_direct_audio,
        early_ial_audio,
        embedded_ci8,
        embedded_geometry,
        eurocom,
        exs_images,
        exs_models,
        f3dex_tiles,
        fat_models,
        fat_textures,
        ffs,
        ffs_models,
        fla2,
        fla2_models,
        flag_lz_graphics,
        float_model_banks,
        fonts,
        graphbin,
        grid_tile_meshes,
        gzip_meshes,
        ia_font_textures,
        iain_models,
        iain_textures,
        iguana_audio,
        iguana_models,
        iguana_skin_models,
        iguana_textures,
        img_textures,
        indexed_archive_models,
        indexed_be_textures,
        indexed_deflate_models,
        indexed_pic_images,
        indexed_resource_models,
        indexed_resource_textures,
        indexed_sprite_banks,
        inline_tiles,
        iwad_maps,
        iwad_sprites,
        legacy_level_models,
        legacy_level_world,
        legacy_reloc_objects,
        level_bytecode,
        level_logos,
        level_world,
        level_world_models,
        libmus_song,
        ljam_models,
        ljam_textures,
        lz_banks,
        lz_directory_models,
        lz_indexed_images,
        lz_section_meshes,
        lz_standard_midi,
        lz_texture_directories,
        lzo_models,
        lzss_archive_images,
        lzss_archive_models,
        mainfs,
        mainfs_models,
        mio0_graphics,
        models,
        mort_streams,
        mwo_graphics,
        named_adpcm,
        named_cmp_textures,
        named_file_models,
        named_file_textures,
        named_prm_models,
        named_resource_images,
        named_resource_models,
        named_tim_archives,
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
        paired_rle_images,
        paired_rle_models,
        parallel_midi,
        prefixed_texture_catalog,
        prefixed_texture_models,
        ptr_audio,
        ptr_audio_v1,
        rare_assets,
        rare_models,
        raw_deflate_lists,
        refpack_first_cache,
        refpack_midx,
        refpack_opcodes,
        refpack_stadium,
        refpack_triangles,
        relative_audio,
        relative_models,
        relative_objects,
        relative_textures,
        reloc_files,
        reloc_level_objects,
        resources,
        rgba_runtime_headers,
        ring12_graphics,
        rle_font_atlas,
        rle_texture_tables,
        rnc_adpcm,
        rnc_chunk_models,
        rnc_control_audio,
        rnc_display_models,
        rnc_indexed_sprites,
        rnc_inline_meshes,
        rnc_meshes,
        rnc_pgd_models,
        rnc_quad_models,
        rnc_reloc_display,
        rnc_rgba_tiles,
        rnc_segmented_resources,
        rnc_shpn_images,
        rnc_textures,
        rnc_tiled_images,
        rnx,
        rnx_atlas,
        romdisk_art,
        romdisk_speech,
        runtime_direct_models,
        runtime_packed_graphics,
        runtime_textures,
        runtime_tiled_textures,
        runtime_zip_models,
        rzip_audio,
        rzip_catalog,
        rzip_models,
        scene_records,
        sdf2_audio,
        sdf2_music,
        segmented_model_resources,
        segmented_node_models,
        shpn_images,
        siff_models,
        sized_lz_catalog,
        sn64,
        sn64_music,
        sprite_constructor,
        sprite_sheets,
        stage_banks,
        stage_meshes,
        striped_images,
        table_lz_graphics,
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
        vol_textures,
        wad_audio,
        wad_models,
        wad_resources,
        yay0_atlases,
        yay0_scenes,
        zip_object_models,
        zip_object_textures,
        zlib_indexed_images,
        zlib_meshes,
        zlib_poly_models,
        zlib_textures,
    )
    if asset.get('layout','').startswith('eurocom-') or asset.get('layout')=='edl-stream':
        return eurocom.preview(data,asset,selection)
    if asset.get('layout')=='uso-sequence-directory':return uso_audio_directory.preview(data,asset,selection)
    if asset.get('layout')=='uso-music':return uso_audio.music_preview(data,asset,selection)
    if asset.get('layout')=='uso-audio':return uso_audio.preview(data,asset,selection)
    if asset.get('layout')=='uso-polygon-models':return uso_models.preview(data,asset,selection)
    if asset.get('layout') == rnc_control_audio.LAYOUT:return rnc_control_audio.preview(data,asset,selection)
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
    if asset.get('layout') == big_tagged_textures.LAYOUT:return big_tagged_textures.preview(data,asset,selection)
    if asset.get('layout') == big_tagged_models.LAYOUT:return big_tagged_models.preview(data,asset,selection)
    if asset.get('layout') == big_models.LAYOUT:return big_models.preview(data,asset,selection)
    if asset.get('layout') == graphbin.LAYOUT:return graphbin.preview(data,asset,selection)
    if asset.get('layout') in (tagged_deflate.IMAGE,tagged_deflate.MODEL):return tagged_deflate.preview(data,asset,selection)
    if asset.get('layout') in (rnc_tiled_images.LAYOUT,rnc_tiled_images.BANK,rnc_display_models.LAYOUT):return rnc_tiled_images.preview(data,asset,selection)
    if asset.get('layout')==striped_images.LAYOUT:return striped_images.preview(data,asset,selection)
    if asset.get('layout')==paired_rle_images.LAYOUT:return paired_rle_images.preview(data,asset,selection)
    if asset.get('layout')==paired_rle_models.LAYOUT:return paired_rle_models.preview(data,asset,selection)
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
    if asset.get('layout')==iguana_skin_models._LAYOUT:return iguana_skin_models.preview(data,asset,selection)
    if asset.get('layout')==iain_models.LAYOUT:return iain_models.preview(data,asset,selection)
    from . import chunked_lz_images
    if asset.get('layout')==chunked_lz_images.LAYOUT:return chunked_lz_images.preview(data,asset,selection)
    if asset.get('layout')==paired_resource_models.LAYOUT:return paired_resource_models.preview(data,asset,selection)
    if asset.get('layout')==paired_resource_textures.LAYOUT:return paired_resource_textures.preview(data,asset,selection)
    if asset.get('layout')==constructed_resource_textures.LAYOUT:return constructed_resource_textures.preview(data,asset,selection)
    if asset.get('layout')==runtime_textures.LAYOUT:return runtime_textures.preview(data,asset,selection)
    if asset.get('layout')==runtime_tiled_textures.LAYOUT:return runtime_tiled_textures.preview(data,asset,selection)
    if asset.get('layout')==iain_textures.LAYOUT:return iain_textures.preview(data,asset,selection)
    if asset.get('layout') == f3dex_tiles.LAYOUT:return f3dex_tiles.preview(data,asset,selection)
    if asset.get('layout') == bounded_lz_models.LAYOUT:return bounded_lz_models.preview(data,asset,selection)
    if asset.get('layout') == terminated_rgba_tiles.LAYOUT:return terminated_rgba_tiles.preview(data,asset,selection)
    if asset.get('layout') == rnc_indexed_sprites.LAYOUT:return rnc_indexed_sprites.preview(data,asset,selection)
    if asset.get('layout') == named_adpcm.LAYOUT:return named_adpcm.preview(data,asset,selection)
    if asset.get('layout') == rnc_quad_models.LAYOUT:return rnc_quad_models.preview(data,asset,selection)
    if asset.get('layout') == rnc_adpcm.LAYOUT:return rnc_adpcm.preview(data,asset,selection)
    if asset.get('layout') == b1_speech.LAYOUT:return b1_speech.preview(data,asset,selection)
    if asset.get('layout') == sprite_constructor.LAYOUT:return sprite_constructor.preview(data,asset,selection)
    if asset.get('layout') == lzo_models.LAYOUT:return lzo_models.preview(data,asset,selection)
    if asset.get('layout') == fla2_models.LAYOUT:return fla2_models.preview(data,asset,selection)
    if asset.get('layout') == ptr_audio_v1.LAYOUT:return ptr_audio_v1.preview(data,asset,selection)
    if asset.get('layout') == romdisk_speech.LAYOUT:return romdisk_speech.preview(data,asset,selection)
    if asset.get('layout') == legacy_level_world.IMAGE:return legacy_level_world.preview(data,asset,selection)
    if asset.get('layout') == legacy_level_models.LAYOUT:return legacy_level_models.preview(data,asset,selection)
    if asset.get('layout') in (legacy_reloc_objects.IMAGE, legacy_reloc_objects.MODEL):return legacy_reloc_objects.preview(data,asset,selection)
    if asset.get('layout') == level_logos.LAYOUT:return level_logos.preview(data,asset,selection)
    if asset.get('layout') == level_world.IMAGE:return level_world.preview(data,asset,selection)
    if asset.get('layout') == level_world_models.LAYOUT:return level_world_models.preview(data,asset,selection)
    if asset.get('layout') == vol_textures.LAYOUT:return vol_textures.preview(data,asset,selection)
    if asset.get('layout') == deflated_texture_table.LAYOUT:return deflated_texture_table.preview(data,asset,selection)
    if asset.get('layout') == segmented_node_models.LAYOUT:return segmented_node_models.preview(data,asset,selection)
    if asset.get('layout') == indexed_sprite_banks.LAYOUT:return indexed_sprite_banks.preview(data,asset,selection)
    if asset.get('layout') == grid_tile_meshes.LAYOUT:return grid_tile_meshes.preview(data,asset,selection)
    if asset.get('layout') == indexed_archive_models.LAYOUT:return indexed_archive_models.preview(data,asset,selection)
    if asset.get('layout') in (reloc_level_objects.LAYOUT, reloc_level_objects.IMAGE):return reloc_level_objects.preview(data,asset,selection)
    if asset.get('layout') in (romdisk_art.IMAGE, romdisk_art.MODEL):return romdisk_art.preview(data,asset,selection)
    if asset.get('layout') == rnc_reloc_display.LAYOUT:return rnc_reloc_display.preview(data,asset,selection)
    if asset.get('layout') == rnc_reloc_display.IMAGE:return rnc_reloc_display.image_preview(data,asset,selection)
    if asset.get('layout')=='iguana-indexed-bitmaps':return iguana_textures.preview(data,asset,selection)
    if asset.get('layout')=='uso-ci8-bank':return uso_textures.preview(data,asset,selection)
    if asset.get('layout') in (diet_audio.BANK,diet_audio.SONG):return diet_audio.preview(data,asset,selection)
    if asset.get('layout')==bind_models.LAYOUT:return bind_models.preview(data,asset,selection)
    if asset.get('layout')==bind_textures.LAYOUT:return bind_textures.preview(data,asset,selection)
    if asset.get('layout') == lzss_archive_models.LAYOUT:return lzss_archive_models.preview(data,asset,selection)
    if asset.get('layout') == 'ring-lzss-model-images':return lzss_archive_models.preview_image(data,asset,selection)
    if asset.get('layout') in (shpn_images.LAYOUT, shpn_images.RAW_LAYOUT):return shpn_images.preview(data,asset,selection)
    if asset.get('layout') == rnc_shpn_images.LAYOUT:return rnc_shpn_images.preview(data,asset,selection)
    if asset.get('layout') in (ljam_textures.LAYOUT,ljam_textures.BMP_LAYOUT):return ljam_textures.preview(data,asset,selection)
    if asset.get('layout') == ljam_models.LAYOUT:return ljam_models.preview(data,asset,selection)
    if asset.get('layout') == rnc_pgd_models.LAYOUT:return rnc_pgd_models.preview(data,asset,selection)
    if asset.get('layout') == named_tim_archives.LAYOUT:return named_tim_archives.preview(data,asset,selection)
    if asset.get('layout') == named_cmp_textures.LAYOUT:return named_cmp_textures.preview(data,asset,selection)
    if asset.get('layout') == named_prm_models.LAYOUT:return named_prm_models.preview(data,asset,selection)
    if asset.get('layout') == refpack_triangles.LAYOUT:return refpack_triangles.preview(data,asset,selection)
    if asset.get('layout') == refpack_stadium.LAYOUT:return refpack_stadium.preview(data,asset,selection)
    if asset.get('layout') == refpack_opcodes.LAYOUT:return refpack_opcodes.preview(data,asset,selection)
    if asset.get('layout') in (refpack_midx.LAYOUT, refpack_midx.RAW_LAYOUT):return refpack_midx.preview(data,asset,selection)
    if asset.get('layout') == refpack_first_cache.LAYOUT:return refpack_first_cache.preview(data,asset,selection)
    if asset.get('layout') == ead_direct_audio.LAYOUT:return ead_direct_audio.preview(data,asset,selection)
    if asset.get('layout') == early_ial_audio.LAYOUT:return early_ial_audio.preview(data,asset,selection)
    if asset.get('layout') == bnkb_audio.LAYOUT:return bnkb_audio.preview(data,asset,selection)
    if asset.get('layout') == mio0_graphics.MODEL:return mio0_graphics.preview(data,asset,selection)
    if asset.get('layout') == mio0_graphics.IMAGE:return mio0_graphics.preview_image(data,asset,selection)
    if asset.get('layout') == exs_models.LAYOUT:return exs_models.preview(data,asset,selection)
    if asset.get('layout') == exs_images.LAYOUT:return exs_images.preview(data,asset,selection)
    if asset.get('layout') == lzss_archive_images.LAYOUT:return lzss_archive_images.preview(data,asset,selection)
    if asset.get('layout') == level_bytecode.LAYOUT:return level_bytecode.preview(data,asset,selection)
    if asset.get('layout')=='fla2-texbank':return fla2.preview(data,asset,selection)
    if asset.get('layout')=='mainfs':return mainfs.preview(data,asset,selection)
    if asset.get('layout')==mainfs_models.LAYOUT:return mainfs_models.preview(data,asset,selection)
    if asset.get('layout')==offset_models.LAYOUT:return offset_models.preview(data,asset,selection)
    if asset.get('layout')==offset_textures.LAYOUT:return offset_textures.preview(data,asset,selection)
    if asset.get('layout')==fat_models.LAYOUT:return fat_models.preview(data,asset,selection)
    if asset.get('layout')==fat_textures.LAYOUT:return fat_textures.preview(data,asset,selection)
    if asset.get('layout')=='reloc-file':return reloc_files.preview(data,asset,selection)
    if asset.get('layout') in (lz_banks.BANK, lz_banks.SONGS):return lz_banks.preview(data,asset,selection)
    if asset.get('layout') == zlib_meshes.LAYOUT:return zlib_meshes.preview(data,asset,selection)
    if asset.get('layout') == zlib_poly_models.LAYOUT:return zlib_poly_models.preview(data,asset,selection)
    if asset.get('layout') == rnc_chunk_models.LAYOUT:return rnc_chunk_models.preview(data,asset,selection)
    if asset.get('layout') == rnc_rgba_tiles.LAYOUT:return rnc_rgba_tiles.preview(data,asset,selection)
    if asset.get('layout') == rgba_runtime_headers.LAYOUT:return rgba_runtime_headers.preview(data,asset,selection)
    if asset.get('layout') == mort_streams.LAYOUT:return mort_streams.preview(data,asset,selection)
    if asset.get('layout') == paged_textures.LAYOUT:return paged_textures.preview(data,asset,selection)
    if asset.get('layout') == zlib_textures.LAYOUT:return zlib_textures.preview(data,asset,selection)
    if asset.get('layout') == zlib_indexed_images.LAYOUT:return zlib_indexed_images.preview(data,asset,selection)
    if asset.get('layout') == relative_textures.LAYOUT:return relative_textures.preview(data,asset,selection)
    if asset.get('layout') == compact_mio_textures.LAYOUT:return compact_mio_textures.preview(data,asset,selection)
    if asset.get('layout') == compact_mio_models.LAYOUT:return compact_mio_models.preview(data,asset,selection)
    if asset.get('layout') in (flag_lz_graphics.TEXTURES, flag_lz_graphics.MODELS):return flag_lz_graphics.preview(data,asset,selection)
    if asset.get('layout') == float_model_banks.LAYOUT:return float_model_banks.preview(data,asset,selection)
    if asset.get('layout') == relative_models.LAYOUT:return relative_models.preview(data,asset,selection)
    if asset.get('layout') == relative_objects.LAYOUT:return relative_objects.preview(data,asset,selection)
    if asset.get('layout') in (relative_audio.BANK, relative_audio.SONG):return relative_audio.preview(data,asset,selection)
    if asset.get('layout') == deflate_catalog.TEXTURE:return deflate_catalog.preview(data,asset,selection)
    if asset.get('layout') == deflate_catalog_models.MODEL:return deflate_catalog_models.preview(data,asset,selection)
    if asset.get('layout') == deflate_level_models.LAYOUT:return deflate_level_models.preview(data,asset,selection)
    if asset.get('layout') in (raw_deflate_lists.TEXTURE, raw_deflate_lists.MODEL):
        return raw_deflate_lists.preview(data,asset,selection)
    if asset.get('layout') == rzip_catalog.TEXTURE:return rzip_catalog.preview(data,asset,selection)
    if asset.get('layout') == rzip_models.MODEL:return rzip_models.preview(data,asset,selection)
    if asset.get('layout') == rzip_audio.LAYOUT:return rzip_audio.preview(data,asset,selection)
    if asset.get('layout') == prefixed_texture_catalog.LAYOUT:return prefixed_texture_catalog.preview(data,asset,selection)
    if asset.get('layout') == prefixed_texture_models.LAYOUT:return prefixed_texture_models.preview(data,asset,selection)
    if asset.get('layout') == ia_font_textures.LAYOUT:return ia_font_textures.preview(data,asset,selection)
    if asset.get('layout') == be_iwad_maps.LAYOUT:return be_iwad_maps.preview(data,asset,selection)
    if asset.get('layout') == embedded_geometry.LAYOUT:return embedded_geometry.preview(data,asset,selection)
    if asset.get('layout') == embedded_ci8.LAYOUT:return embedded_ci8.preview(data,asset,selection)
    if asset.get('layout') == indexed_pic_images.LAYOUT:return indexed_pic_images.preview(data,asset,selection)
    if asset.get('layout') == named_file_models.LAYOUT:return named_file_models.preview(data,asset,selection)
    if asset.get('layout') == named_file_textures.LAYOUT:return named_file_textures.preview(data,asset,selection)
    if asset.get('layout') == be_iwad_images.LAYOUT:return be_iwad_images.preview(data,asset,selection)
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
    if asset.get('layout') == aki_models.LAYOUT:return aki_models.preview(data,asset,selection)
    if asset.get('layout') == chunked_polygon_meshes.LAYOUT:return chunked_polygon_meshes.preview(data,asset,selection)
    if asset.get('layout') == chunked_zlib.LAYOUT:return chunked_zlib.preview(data,asset,selection)
    if asset.get('layout') in (aki_textures.LAYOUT, aki_textures.COMPRESSED):return aki_textures.preview(data,asset,selection)
    if asset.get('layout') == img_textures.LAYOUT:return img_textures.preview(data,asset,selection)
    if asset.get('layout') == sprite_sheets.LAYOUT:return sprite_sheets.preview(data,asset,selection)
    if asset.get('layout') == rnc_inline_meshes.LAYOUT:return rnc_inline_meshes.preview(data,asset,selection)
    if asset.get('layout') in (rnc_segmented_resources.MODEL,rnc_segmented_resources.TEXTURE):return rnc_segmented_resources.preview(data,asset,selection)
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
    if asset.get('layout')==lz_indexed_images.LAYOUT:return lz_indexed_images.preview(data,asset,selection)
    if asset.get('layout')==lz_section_meshes.LAYOUT:return lz_section_meshes.preview(data,asset,selection)
    if asset.get('layout')=='borg-audio':return borg_audio.preview(data,asset,selection)
    if asset.get('layout')=='borg-model':return borg_models.preview(data,asset,selection)
    if asset.get('layout')=='borg-texture':return borg.preview(data,asset,selection)
    if asset.get('layout')=='uv-model':return uv_models.preview(data,asset,selection)
    if asset.get('layout')==inline_tiles.LAYOUT:return inline_tiles.preview(data,asset,selection)
    if asset.get('layout')=='uv-texture':return uv_textures.preview(data,asset,selection)
    if asset.get('layout')=='ffs-i64':return ffs.preview(data,asset,selection)
    if asset.get('layout')==ffs_models.LAYOUT:return ffs_models.preview(data,asset,selection)
    if asset.get('layout') == runtime_packed_graphics.MODEL:return runtime_packed_graphics.preview_model(data,asset,selection)
    from . import runtime_deflate_models
    if asset.get('layout') == runtime_deflate_models.LAYOUT:return runtime_deflate_models.preview(data,asset,selection)
    from . import runtime_chunked_models
    if asset.get('layout') == runtime_chunked_models.LAYOUT:return runtime_chunked_models.preview(data,asset,selection)
    if asset.get('layout') == runtime_direct_models.LAYOUT:return runtime_direct_models.preview(data,asset,selection)
    if asset.get('layout') == runtime_zip_models.LAYOUT:return runtime_zip_models.preview(data,asset,selection)
    if asset.get('layout') in (table_lz_graphics.TEXTURES,ring12_graphics.TEXTURES,runtime_packed_graphics.MIO_TEXTURES,runtime_packed_graphics.ERZ_TEXTURES,runtime_packed_graphics.RNC_TEXTURES,runtime_packed_graphics.DEFLATE_TEXTURES,block16_graphics.TEXTURES):return table_lz_graphics.preview(data,asset,selection)
    if asset.get('layout') == indexed_deflate_models.LAYOUT:return indexed_deflate_models.preview(data,asset,selection)
    if asset.get('layout') == indexed_be_textures.LAYOUT:return indexed_be_textures.preview(data,asset,selection)
    if asset.get('layout') == indexed_deflate_models.TEXTURE:return indexed_deflate_models.preview_texture(data,asset,selection)
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
