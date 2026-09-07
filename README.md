# Peace Walker Soldier Editor — PTB

A Windows save editor for the PC release of **METAL GEAR SOLID: Peace Walker — Master Collection Version**.

PTB means public test build. Back up your save before editing it.

## Features

- Opens and saves encrypted PC `STW` save files.
- Edits soldier names, assignments, portraits, classes, recruitment categories, sex, Life, Psyche, GMP+, Combat, R&D, Mess Hall, Medical, Intel, skills, and Details Quotes.
- Shows skill descriptions.
- Filters and searches the staff roster, including unique characters.
- Exports a soldier and imports one into an empty roster slot from the right-click menu.
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

## Build from source

Requirements:

- Windows 10 or 11
- Python 3.11 or newer
- Visual Studio 2022 with the **Python development** workload when building through Visual Studio

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
- `PeaceWalkerSoldierEditor.spec` — standalone Windows build configuration

## Important notes

- This build is intended for the PC Master Collection release. Other releases may use a different save layout.
- Never edit the only copy of a save.
- The application does not need Python or separate DLL/PYC files when built with the included PyInstaller specification.
- Antivirus products may scrutinize newly compiled unsigned executables. Publishing the source and reproducible build steps lets users inspect and build the program themselves.

This is an unofficial fan-made utility and is not affiliated with or endorsed by Konami.
