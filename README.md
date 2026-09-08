# Peace Walker Soldier Editor — PTB

A Windows save editor for the PC release of **METAL GEAR SOLID: Peace Walker — Master Collection Version**.

PTB means public test build. Back up your save before editing it.

## Features

- Opens and saves encrypted PC `STW` save files.
- Edits soldier names, assignments, portraits, classes, recruitment categories, sex, unit title, voice profile, acquisition method, Life, Psyche, GMP+, Hostility, Morale, Combat, R&D, Mess Hall, Medical, Intel, skills, and Details Quotes.
- Automatically caps Life and Psyche at the game's maximum value of 9,999.
- Automatically caps Hostility and Morale at the soldier-record maximum of 999.
- Shows skill descriptions.
- Provides a Play button for each voice profile when its authentic preview WAV is included.
- Filters and searches the staff roster, including unique characters.
- Exports a soldier and imports one into an empty roster slot from the right-click menu.
- Supports persistent per-soldier custom Details Quotes through an optional ASI plugin.
- Includes the portrait pack used by the PTB release.

## Use the editor

1. Close Peace Walker before editing a save.
2. Make a backup copy of the save.
3. Start `PeaceWalkerSoldierEditor_PTB.exe`.
4. Select **Open Save** and choose the encrypted PC `STW` file.
5. Select a soldier, make changes, and choose **Apply Soldier Changes**.
6. Choose **Save As** and write the edited file to a new location first.
7. After confirming the edited save works, replace the original if desired.

For soldier transfers, right-click a populated roster entry and select **Export Soldier**. To import it, right-click an empty slot and select **Import Soldier**.

The **Details Quote** selector copies only the four-byte quote identifier from the selected donor soldier. It does not copy the donor's separate identity data.

The condition indicator is intentionally read-only. The save contains a compact condition flag used by sick or wounded staff, but its individual bit meanings are not yet safe to edit.

### Voice previews

Choose a Voice Profile and select **Play** to hear its bundled sample. Authentic preview files use the names `voice_01.wav` through `voice_09.wav` in the `voice_previews` folder. If a profile has not been captured yet, the editor reports that the preview is unavailable.

### Custom Details Quotes

1. Select a soldier and type text into **Custom Details Quote (optional)**.
2. Choose **Apply Soldier Changes**, then **Save As**.
3. Keep the generated `.pwquotes.json` file beside the edited save. It stores the custom text because arbitrary quote text cannot be embedded directly in the normal soldier record.
4. Choose **Install Custom Quote Support** once and select the real Peace Walker executable. MGSPatriotFix or another compatible ASI loader must already be installed.
5. Close the editor and start Peace Walker normally. The game-side plugin loads the matching companion file automatically.

The save remains a standard Peace Walker save. If the companion file or plugin is missing, the game falls back to the selected donor quote. The plugin is specific to the supported PC executable and may need an update if a game patch changes its code layout.

## Build from source

Requirements:

- Windows 10 or 11
- Python 3.11 or newer
- Visual Studio 2022 with the **Python development** workload
- Visual Studio 2022 **Desktop development with C++** workload when rebuilding the optional quote plugin

### Visual Studio 2022

1. Open **Visual Studio Installer**.
2. Select **Modify** for your Visual Studio installation.
3. Install the **Python development** workload.
4. In Visual Studio, select **File > Open > Folder** and open this repository.
5. Open **View > Terminal** and run the build commands below.

From a PowerShell window in this repository:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
quote_plugin\build_plugin.bat
.venv\Scripts\python -m PyInstaller --clean --noconfirm PeaceWalkerSoldierEditor.spec
```

The standalone application will be created under:

```text
dist\PeaceWalkerSoldierEditor_PTB\PeaceWalkerSoldierEditor_PTB.exe
```

The included portrait files are bundled automatically by the PyInstaller specification.

## Source layout

- `soldier_editor.py` — graphical editor and soldier-record handling
- `save_cipher.py` — PC save encryption/decryption support
- `edit_save.py` — internal save checksum updates
- `portrait_assets/` — portrait images bundled with the PTB release
- `quote_plugin/` — source and build script for persistent game-side custom quote support
- `third_party/minhook/` — MinHook source used by the optional ASI plugin
- `PeaceWalkerSoldierEditor.spec` — standalone Windows build configuration

## Important notes

- This build is intended for the PC Master Collection release. Other releases may use a different save layout.
- Never edit the only copy of a save.
- The application does not need Python or separate DLL/PYC files when built with the included PyInstaller specification.
- The standalone folder must be kept intact; do not move only the `.exe` out of it.
- Antivirus products may scrutinize newly compiled unsigned executables. Publishing the source and reproducible build steps lets users inspect and build the program themselves.

This is an unofficial fan-made utility and is not affiliated with or endorsed by Konami.
