# MO_MODEL_VIEWER

Standalone Peace Walker MDP and Master Collection PC MDPX model viewer and
early-stage editor for Windows. It does not require the game or Noesis. Open an
extracted `.mdp`, orbit with the left mouse button, zoom with the wheel, toggle
meshes and the skeleton, or export visible meshes to Wavefront OBJ.

Select one or more meshes to translate, rotate, or scale them. Transform edits
support Undo/Redo (`Ctrl+Z` and `Ctrl+Y`). **Save MDP Copy** patches edited
vertex positions into a copy of the original MDP/MDPX container while preserving
the original file structure and all unedited data. It intentionally refuses to
overwrite the source model.

Matching `.txp` files are loaded automatically when they sit beside the model,
or can be selected with OPEN TXP. Indexed 4-bit and 8-bit PSP textures,
palettes, PC 64-bit TXP tables, and Master Collection format `0x06` embedded
DDS/DXT textures are supported. OPEN MTAR loads the animation list;
PLAY animates the skeleton at the game's 30 FPS rate.

The initial viewer supports conventional MDP vertex buffers 01-04 and 09-0E.
Metadata-only MDPX copies whose vertex-buffer offsets are zero are reported
clearly. Another archive page may contain a full copy with the same model hash.

Portable Ops is not yet enabled. Its model container and vertex layouts must be
verified independently before write support can be considered safe.
