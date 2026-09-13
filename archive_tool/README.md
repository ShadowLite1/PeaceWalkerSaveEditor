# Peace Walker Archive Tool

Manifest-based extractor and repacker for the Windows PC release of Metal Gear
Solid: Peace Walker - Master Collection Version.

Run `pwarchive_gui.py` for the Windows interface, or build the standalone
version with `build_gui.bat`. The command-line interface remains available in
`pwarchive.py` for scripting and batch extraction.

Supported formats:

- `STAGEDAT.PDT`: extract and fixed-allocation repack
- `SLOT.DAT` + `SLOT.KEY`: extract and fixed-allocation repack
- `DAR`: extract and rebuild
- `QAR`: extract and rebuild using the PC release's bundled archive alignment

The Master Collection PC resource cipher, hashed filenames, HD `SLOT.KEY`
records, 0x1000-byte sectors, and per-page cipher resets are handled
automatically. The original archive is never modified. Repacking preserves
unchanged pages byte-for-byte and only rebuilds pages whose extracted payload
was edited.

Each SLOT page is also unpacked into a matching `_files` folder containing its
actual hashed resources (textures, language data, models, scripts, audio, and
other known types). Repack reads edits from those folders and inserts them back
into the page. An inner replacement cannot exceed its original fixed allocation.

PC STAGEDAT extraction reads the widened lookup records and each stage's
`data.cnf`, recovering the real name and extension of every resource instead of
leaving anonymous `.bin` files. The manifest retains the owning stage and name.

Examples:

```powershell
python pwarchive.py inspect 009645fa.PDT
python pwarchive.py extract stage STAGEDAT.PDT extracted-stage
python pwarchive.py extract slot SLOT.DAT extracted-slot --key SLOT.KEY
python pwarchive.py extract dar cache.dar extracted-dar
python pwarchive.py extract qar cache.qar extracted-qar
python pwarchive.py repack extracted-stage STAGEDAT-mod.PDT
```

Every extraction writes `pwarchive-manifest.json`. Repacking reads that
manifest and never modifies the source archive. Stage and Slot replacements
must compress to fit the original allocation.
