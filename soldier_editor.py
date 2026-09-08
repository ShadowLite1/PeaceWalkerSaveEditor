from __future__ import annotations

import json
import shutil
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

try:
    import winsound
except ImportError:  # pragma: no cover - the editor is distributed for Windows
    winsound = None

from edit_save import update_internal_checks
from save_cipher import derive_state, filename_checksum, transform


SAVE_SIZE = 0x4F950
ROSTER_BASE = 0x1FA80
ROSTER_COUNT_OFFSET = ROSTER_BASE - 0x10
RECORD_SIZE = 0xA0
RECORD_COUNT = 350
SOLDIER_EXPORT_MAGIC = b"PWSOLDIER\x01"
DESCRIPTION_KEY_OFFSET = 0x14
DESCRIPTION_KEY_SIZE = 4
NAME_OFFSET = 0x20
NAME_SIZE = 16
ASSIGNMENT_OFFSET = 0x30
PORTRAIT_FACE_OFFSET = 0x3C
PORTRAIT_SET_OFFSET = 0x3E
SOLDIER_TYPE_OFFSET = 0x31
SERVICE_TYPE_OFFSET = 0x18
SEX_OFFSET = 0x34
UNIT_TITLE_OFFSET = 0x32
VOICE_OFFSET = 0x33
CONDITION_FLAGS_OFFSET = 0x36
HOSTILITY_OFFSET = 0x7E
MORALE_OFFSET = 0x82
ACQUISITION_METHOD_OFFSET = 0x8C
SKILLS_OFFSET = 0x98
SKILLS_SIZE = 8
VISIBLE_SKILLS = 4
GMP_OFFSET = 0x38
LIFE_CURRENT_OFFSET = 0x42
LIFE_MAX_OFFSET = 0x44
PSYCHE_CURRENT_OFFSET = 0x4A
PSYCHE_MAX_OFFSET = 0x4C

# Aptitudes are little-endian 16-bit scores. Combat is calculated from the
# eight battle aptitudes and has no separate stored score.
TEAM_GRADE_OFFSETS = {
    "R&D": 0x6C,
    "Mess Hall": 0x64,
    "Medical": 0x68,
    "Intel": 0x70,
}
BATTLE_GRADE_OFFSETS = {
    "Shoot": 0x58,
    "Reload": 0x5A,
    "Throw": 0x5C,
    "Place": 0x5E,
    "Walk": 0x54,
    "Run": 0x52,
    "Fight": 0x56,
    "Defend": 0x60,
}
GRADE_NAMES = {0: "E", 1: "D", 2: "C", 3: "B", 4: "A", 5: "S"}
RANK_CHOICES = [GRADE_NAMES[value] for value in range(5, -1, -1)]
GRADE_CHOICES = [f"{value:02X} — {GRADE_NAMES[value]}" for value in range(5, -1, -1)] + ["-- — -"]
TEAM_GRADE_MINIMUM_SCORES = {-1: 0, 0: 1, 1: 100, 2: 200, 3: 500, 4: 750, 5: 1001}
BATTLE_GRADE_MINIMUM_SCORES = {0: 0, 1: 209, 2: 417, 3: 626, 4: 834, 5: 1042}
BATTLE_SCORE_MAX = 1250
VITAL_STAT_MAX = 9999
RELATION_STAT_MAX = 999
CUSTOM_QUOTE_SIDECAR_SUFFIX = ".pwquotes.json"
CUSTOM_QUOTE_MAX_BYTES = 511

KNOWN_SKILLS = {
    0x00: "None",
    0x01: "Sidekick",
    0x02: "Radio Technology",
    0x03: "SWAT",
    0x04: "Rescue",
    0x05: "Decoy",
    0x06: "Engineering",
    0x08: "Channeler",
    0x09: "Voice Actor",
    0x0C: "Green Beret",
    0x0E: "Pro Wrestling Maniac",
    0x10: "Three-Star Chef",
    0x11: "Four-Star Chef",
    0x12: "Five-Star Chef",
    0x13: "Pharmacist",
    0x14: "Expert Pharmacist",
    0x16: "Counselor",
    0x18: "Physician",
    0x19: "Surgeon",
    0x1B: "Gunsmith (Handguns)",
    0x1C: "Gunsmith (Shotguns)",
    0x1D: "Gunsmith (Assault Rifles)",
    0x1E: "Gunsmith (Machine Guns)",
    0x1F: "Gunsmith (Sniper Rifles)",
    0x23: "Bipedal Weapons Design",
    0x27: "Gung Ho",
    0x2A: "Optical Technology",
    0x2B: "FSLN Comandante",
    0x2C: "AI Development Technology",
    0x2D: "Bird Watcher",
    0x2E: "Home Cooking",
    0x2F: "Mother Base Deputy Commander",
    0x30: "Gunsmith (Submachine Guns)",
    0x31: "Patriot",
    0x32: "Japanese Patriot",
    0x33: "Anti-tank Rifle Design",
    0x34: "M134 Design",
    0x35: "EM Weapons Design",
    0x36: "Metamaterials Technology",
}
SKILL_DESCRIPTIONS = {
    0x00: "No special effect.",
    0x01: "Praises allies when they neutralize enemies, restoring some Psyche. Using the praise effect prevents an S-rank mission result.",
    0x02: "May block enemy calls for reinforcements and improves requested support. The effect grows with additional staff who have this skill.",
    0x03: "Improves CQC and limb damage, enables knockdowns with rolls, and shortens Snake Sync preparation time.",
    0x04: "Improves the effectiveness of recovery and rescue actions during missions.",
    0x05: "Draws enemy attention, restores Psyche while targeted, reduces incoming damage, and improves shield protection.",
    0x06: "Improves attacks against vehicles and AI weapons, speeds placement of weapons, and improves vehicle repairs when assigned to R&D.",
    0x08: "Reveals the locations of certain items and special targets on the mission map.",
    0x09: "Strengthens the effects of certain voiced CO-OPS communications.",
    0x0C: "Raises weapon critical rate, CQC power, and natural Life recovery. The effect grows with additional staff who have this skill.",
    0x0E: "Improves CQC throws and other close-combat actions.",
    0x10: "Improves Mess Hall performance as a three-star chef.",
    0x11: "Improves Mess Hall performance as a four-star chef.",
    0x12: "Provides the strongest chef bonus to Mess Hall performance.",
    0x13: "Improves medical item development and Medical Team effectiveness.",
    0x14: "Provides an enhanced bonus to medical item development and Medical Team effectiveness.",
    0x16: "Improves Psyche recovery and Medical Team effectiveness.",
    0x18: "Improves Life recovery and Medical Team effectiveness.",
    0x19: "Provides an enhanced medical and surgical bonus when assigned to the Medical Team.",
    0x1B: "Reduces the GMP required to develop handguns while assigned to R&D.",
    0x1C: "Reduces the GMP required to develop shotguns while assigned to R&D.",
    0x1D: "Reduces the GMP required to develop assault rifles while assigned to R&D.",
    0x1E: "Reduces the GMP required to develop machine guns while assigned to R&D.",
    0x1F: "Reduces the GMP required to develop sniper rifles while assigned to R&D.",
    0x23: "Enables development of Metal Gear ZEKE when assigned to R&D.",
    0x27: "Increases combat effectiveness and resilience during missions.",
    0x2A: "Enables development of equipment and weapons that use optical technology when assigned to R&D.",
    0x2B: "Provides the special command ability associated with the FSLN commander.",
    0x2C: "Enables installation and development of AI technology for ZEKE when assigned to R&D.",
    0x2D: "Helps locate birds and related collectibles during missions.",
    0x2E: "Improves Mess Hall performance through home cooking.",
    0x2F: "Raises the morale of staff on the team to which this soldier is assigned.",
    0x30: "Reduces the GMP required to develop submachine guns while assigned to R&D.",
    0x31: "Provides the special combat effect associated with the Patriot skill.",
    0x32: "Provides the special combat effect associated with the Japanese Patriot skill.",
    0x33: "Enables development of anti-tank rifles when assigned to R&D.",
    0x34: "Enables development of the M134 Gatling gun when assigned to R&D.",
    0x35: "Enables development of electromagnetic weapons when assigned to R&D.",
    0x36: "Enables development of the Stealth Mat and Stealth Camouflage when assigned to R&D.",
}
RESERVED_SKILLS = {
    0x07, 0x0A, 0x0B, 0x0D, 0x0F, 0x15, 0x17, 0x1A,
    0x20, 0x21, 0x22, 0x24, 0x25, 0x26, 0x28, 0x29,
}

BG = "#d8d5bd"
INK = "#171914"
PANEL = "#292b27"
RED = "#ef3029"
ORANGE = "#ff6519"
CREAM = "#f2f0da"


def skill_label(value: int) -> str:
    if value in KNOWN_SKILLS:
        return KNOWN_SKILLS[value]
    if value in RESERVED_SKILLS:
        return f'Reserved skill ({value:02X})'
    return f"Unknown skill ({value:02X})"


SKILL_CHOICES = [skill_label(value) for value in KNOWN_SKILLS]

SOLDIER_TYPES = {
    0x01: "Infantry",
    0x02: "Sharpshooter",
    0x03: "Commando",
    0x04: "Scout",
    0x05: "Guerrilla",
    0x06: "Elite Commando",
    0x07: "Mechanic",
    0x08: "Researcher",
    0x09: "Doctor",
    0x0A: "Nurse",
    0x0B: "Cook",
    0x0C: "Medic",
    0x0D: "Engineer",
    0x0E: "Supply Soldier",
    0x0F: "Industrial Spy",
    0x10: "Spy",
    0x11: "Food Technician",
    0x12: "Nutritionist",
    0x13: "Medical Researcher",
    0x24: "Commander",
    0x31: "Actress",
    0x56: "New Voice Actor",
}
SERVICE_TYPES = {
    0x04: "None / Special Character",
    0x06: "Former Prisoner",
    0x07: "Volunteer Soldier",
    0x08: "Military Soldier",
}
SEXES = {0x10: "Female", 0x11: "Male"}
UNIT_TITLES = {value: f"Title {value}" for value in range(1, 7)}
VOICES = {value: f"Voice {value}" for value in range(1, 10)}
ACQUISITION_METHODS = {value: f"Method {value}" for value in range(10)}
ASSIGNMENTS = {
    0x00: "Unassigned",
    0x01: "Waiting Room",
    0x02: "Combat Unit",
    0x03: "R&D Team",
    0x04: "Medical Team",
    0x05: "Mess Hall Team",
    0x06: "Intel Team",
    0x07: "Trade Waiting Room",
    0x08: "Brig",
    0x09: "Sickbay",
}


def enum_label(value: int, names: dict[int, str]) -> str:
    return names.get(value, f"Unknown value ({value:02X})")


def enum_value(label: str, field: str) -> int:
    for names in (ASSIGNMENTS, SOLDIER_TYPES, SERVICE_TYPES, SEXES, UNIT_TITLES, VOICES, ACQUISITION_METHODS):
        for value, name in names.items():
            if label == name:
                return value
    if "(" in label and label.endswith(")"):
        return parse_hex_byte(label.rsplit("(", 1)[1][:-1], field)
    return parse_hex_byte(label.split("—", 1)[0].strip(), field)


def skill_value(label: str, field: str) -> int:
    for value, name in KNOWN_SKILLS.items():
        if label == name:
            return value
    if "(" in label and label.endswith(")"):
        return parse_hex_byte(label.rsplit("(", 1)[1][:-1], field)
    return parse_hex_byte(label.split("—", 1)[0].strip(), field)


def grade_label(value: int) -> str:
    if value < 0:
        return "-- — -"
    value = max(0, min(5, value))
    return f"{value:02X} — {GRADE_NAMES[value]}"


def team_score_grade(score: int) -> int:
    if score == 0:
        return -1
    for grade in range(5, -1, -1):
        if score >= TEAM_GRADE_MINIMUM_SCORES[grade]:
            return grade
    return 0


def battle_score_grade(score: int) -> int:
    for grade in range(5, -1, -1):
        if score >= BATTLE_GRADE_MINIMUM_SCORES[grade]:
            return grade
    return 0


def parse_battle_score(value: str, label: str) -> int:
    try:
        number = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be a whole number") from exc
    if number < 0:
        raise ValueError(f"{label} cannot be negative")
    return min(number, BATTLE_SCORE_MAX)


def grade_value(label: str, field: str) -> int:
    if label.startswith("--"):
        return -1
    value = parse_hex_byte(label.split("—", 1)[0].strip(), field)
    if value > 5:
        raise ValueError(f"{field} must be between E and S")
    return value


def parse_stat(value: str, label: str, maximum: int = 9999) -> int:
    try:
        number = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be a whole number") from exc
    if not 0 <= number <= maximum:
        raise ValueError(f"{label} must be between 0 and {maximum}")
    return number


def capped_vital_text(value: str) -> str:
    """Clamp numeric Life/Psyche input without interfering with normal editing."""
    stripped = value.strip()
    if stripped.isdecimal() and int(stripped) > VITAL_STAT_MAX:
        return str(VITAL_STAT_MAX)
    return value


def capped_relation_text(value: str) -> str:
    """Clamp Morale/Hostility to the record's observed 0-999 range."""
    stripped = value.strip()
    if stripped.isdecimal() and int(stripped) > RELATION_STAT_MAX:
        return str(RELATION_STAT_MAX)
    return value


def parse_hex_byte(value: str, label: str) -> int:
    text = value.strip().removeprefix("0x").removeprefix("0X")
    try:
        number = int(text, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be a hexadecimal byte") from exc
    if not 0 <= number <= 0xFF:
        raise ValueError(f"{label} must be between 00 and FF")
    return number


class SoldierEditor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Peace Walker Soldier Editor")
        self.geometry("1280x860")
        self.minsize(1080, 720)
        self.configure(bg=BG)
        self.data: bytearray | None = None
        self.source_path: Path | None = None
        self.header_index: int | None = None
        self.selected_slot: int | None = None
        self.description_slots: dict[str, int] = {}
        self.custom_quotes: dict[int, str] = {}
        self.portrait_files: dict[int, Path] = {}
        self.portrait_files_by_code: dict[tuple[int, int], list[tuple[int, Path]]] = {}
        self.portrait_photo = None
        self.dirty = False

        self.resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        app_icon = self.resource_root / "app_icon.ico"
        if app_icon.is_file():
            try:
                self.iconbitmap(default=str(app_icon))
            except tk.TclError:
                pass
        portrait_roots = [
            self.resource_root / "portrait_assets",
            self.resource_root / "extracted_runtime_txp" / "008ad7dc",
        ]
        for portrait_root in portrait_roots:
            if portrait_root.is_dir():
                for path in portrait_root.glob("*.png"):
                    try:
                        resource_hash = int(path.stem.rsplit("_", 1)[1], 16)
                        self.portrait_files[resource_hash] = path
                        portrait_set = (resource_hash >> 16) & 0xFF
                        face = resource_hash & 0xFF
                        family = (resource_hash >> 8) & 0xFF
                        self.portrait_files_by_code.setdefault((portrait_set, face), []).append(
                            (family, path)
                        )
                    except (IndexError, ValueError):
                        pass
                if self.portrait_files:
                    break

        portrait_pairs = sorted(self.portrait_files_by_code)
        self.portrait_choices = {
            f"Portrait {index + 1}": pair for index, pair in enumerate(portrait_pairs)
        }
        self.portrait_choice_by_code = {
            pair: label for label, pair in self.portrait_choices.items()
        }

        self._build_menu()
        self._build_style()
        self._build_ui()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("PW.TFrame", background=BG)
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("TEntry", font=("Segoe UI", 10))
        style.configure("TCombobox", font=("Segoe UI", 10))
        style.configure("PW.TLabel", background=BG, foreground=INK, font=("Segoe UI", 11))
        style.configure("Title.TLabel", background=BG, foreground=INK, font=("Segoe UI", 22))
        style.configure("Sub.TLabel", background=BG, foreground=INK, font=("Segoe UI", 13))
        style.configure("Panel.TLabel", background=PANEL, foreground=CREAM, font=("Segoe UI", 11))
        style.configure("Red.TLabel", background=RED, foreground="white", font=("Segoe UI", 12, "bold"))
        style.configure("Orange.TLabel", background=ORANGE, foreground="white", font=("Segoe UI", 12, "bold"))
        style.configure("PW.TButton", font=("Segoe UI", 10, "bold"), padding=7)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open PC Save…", command=self.open_save)
        file_menu.add_command(label="Save As…", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menu.add_cascade(label="File", menu=file_menu)
        self.config(menu=menu)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12, style="PW.TFrame")
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer, style="PW.TFrame")
        left.pack(side="left", fill="y")
        ttk.Label(left, text="STAFF", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="350 roster records", style="PW.TLabel").pack(anchor="w")
        ttk.Label(left, text="FILTERS", style="Sub.TLabel").pack(anchor="w", pady=(7, 1))
        self.assignment_filter_var = tk.StringVar(value="All assignments")
        filter_specs = (
            ("Team / assignment", self.assignment_filter_var, "assignment_filter_box"),
        )
        for label, variable, attribute in filter_specs:
            ttk.Label(left, text=label, style="PW.TLabel").pack(anchor="w")
            box = ttk.Combobox(left, textvariable=variable, state="readonly", width=31)
            box.pack(fill="x", pady=(0, 3))
            box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_list())
            setattr(self, attribute, box)
        ttk.Button(left, text="CLEAR FILTERS", command=self.clear_filters).pack(fill="x", pady=(2, 5))
        ttk.Label(left, text="Name or slot search", style="PW.TLabel").pack(anchor="w")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self.refresh_list())
        search = ttk.Entry(left, textvariable=self.search_var, width=34)
        search.pack(fill="x", pady=(4, 6))

        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True)
        self.roster = tk.Listbox(list_frame, width=38, exportselection=False)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.roster.yview)
        self.roster.configure(yscrollcommand=scroll.set)
        self.roster.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.roster.bind("<<ListboxSelect>>", self.select_soldier)
        self.roster.bind("<Button-3>", self._show_roster_menu)
        self.roster_menu = tk.Menu(self, tearoff=False)
        self.roster_menu.add_command(label="Export soldier...", command=self.export_soldier)
        self.roster_menu.add_command(label="Import soldier...", command=self.import_soldier)

        right = ttk.Frame(outer, padding=(18, 0, 0, 0), style="PW.TFrame")
        right.pack(side="left", fill="both", expand=True)
        self.status_var = tk.StringVar(value="Open an encrypted PC STW save to begin.")
        ttk.Label(right, textvariable=self.status_var, style="PW.TLabel").pack(anchor="w", pady=(0, 8))

        card = ttk.Frame(right, style="PW.TFrame")
        card.pack(fill="x")
        portrait = tk.Frame(card, bg="#11120f", width=230, height=230, highlightbackground="#77776b", highlightthickness=2)
        portrait.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 16))
        portrait.grid_propagate(False)
        self.portrait_text = tk.Label(portrait, text="PORTRAIT", bg="#11120f", fg="#dad8c3", font=("Segoe UI", 18), justify="center")
        self.portrait_text.place(x=0, y=0, relwidth=1, relheight=1)
        self.portrait_code = tk.Label(portrait, text="Portrait", bg="#11120f", fg="#dad8c3", font=("Segoe UI", 11), padx=8, pady=3)
        self.portrait_code.place(relx=.5, rely=1, anchor="s")

        identity = ttk.Frame(card, style="PW.TFrame")
        identity.grid(row=0, column=1, sticky="ew")
        self.name_var = tk.StringVar()
        self.assignment_var = tk.StringVar()
        self.portrait_choice_var = tk.StringVar()
        self.soldier_type_var = tk.StringVar()
        self.service_type_var = tk.StringVar()
        self.sex_var = tk.StringVar()
        self.unit_title_var = tk.StringVar()
        self.voice_var = tk.StringVar()
        self.acquisition_method_var = tk.StringVar()
        self.condition_var = tk.StringVar(value="Normal")
        self.description_var = tk.StringVar()
        ttk.Entry(identity, textvariable=self.name_var, width=28, font=("Segoe UI", 18)).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(identity, text="Assignment", style="PW.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.assignment_box = ttk.Combobox(identity, textvariable=self.assignment_var, width=20, state="readonly")
        self.assignment_box.grid(row=2, column=0, sticky="w")
        ttk.Label(identity, text="Portrait", style="PW.TLabel").grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(8, 0))
        portrait_box = ttk.Combobox(
            identity,
            textvariable=self.portrait_choice_var,
            values=list(self.portrait_choices),
            width=18,
            state="readonly",
        )
        portrait_box.grid(row=2, column=1, sticky="w", padx=(14, 0))
        portrait_box.bind("<<ComboboxSelected>>", lambda _event: self.update_portrait_preview())

        metadata = ttk.Frame(card, style="PW.TFrame")
        metadata.grid(row=1, column=1, sticky="ew", pady=(14, 0))
        ttk.Label(metadata, text="Soldier class", style="PW.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(metadata, text="Recruitment category", style="PW.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(metadata, text="Sex", style="PW.TLabel").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.soldier_type_box = ttk.Combobox(metadata, textvariable=self.soldier_type_var, width=23, state="readonly")
        self.soldier_type_box.grid(row=1, column=0, sticky="w")
        self.service_type_box = ttk.Combobox(metadata, textvariable=self.service_type_var, width=23, state="readonly")
        self.service_type_box.grid(row=1, column=1, sticky="w", padx=(10, 0))
        self.sex_box = ttk.Combobox(metadata, textvariable=self.sex_var, width=15, state="readonly")
        self.sex_box.grid(row=1, column=2, sticky="w", padx=(10, 0))

        ttk.Label(metadata, text="Details Quote donor", style="PW.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.description_box = ttk.Combobox(metadata, textvariable=self.description_var, width=58, state="readonly")
        self.description_box.grid(row=3, column=0, columnspan=3, sticky="ew")
        ttk.Label(metadata, text="Unit title", style="PW.TLabel").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Label(metadata, text="Voice profile", style="PW.TLabel").grid(row=4, column=1, sticky="w", padx=(10, 0), pady=(10, 0))
        ttk.Label(metadata, text="Acquisition method", style="PW.TLabel").grid(row=4, column=2, sticky="w", padx=(10, 0), pady=(10, 0))
        self.unit_title_box = ttk.Combobox(
            metadata, textvariable=self.unit_title_var, values=list(UNIT_TITLES.values()), width=23, state="readonly"
        )
        self.unit_title_box.grid(row=5, column=0, sticky="w")
        voice_controls = ttk.Frame(metadata, style="PW.TFrame")
        voice_controls.grid(row=5, column=1, sticky="w", padx=(10, 0))
        self.voice_box = ttk.Combobox(
            voice_controls, textvariable=self.voice_var, values=list(VOICES.values()), width=15, state="readonly"
        )
        self.voice_box.pack(side="left")
        ttk.Button(
            voice_controls,
            text="▶",
            width=2,
            style="PW.TButton",
            command=self.play_voice_preview,
        ).pack(side="left", padx=(5, 0))
        self.acquisition_method_box = ttk.Combobox(
            metadata,
            textvariable=self.acquisition_method_var,
            values=list(ACQUISITION_METHODS.values()),
            width=15,
            state="readonly",
        )
        self.acquisition_method_box.grid(row=5, column=2, sticky="w", padx=(10, 0))
        ttk.Label(metadata, textvariable=self.condition_var, style="PW.TLabel").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(5, 0)
        )
        stats = tk.Frame(card, bg=PANEL, padx=8, pady=8)
        stats.grid(row=2, column=1, sticky="ew", pady=(16, 0))
        self.life_var = tk.StringVar()
        self.psyche_var = tk.StringVar()
        self.gmp_var = tk.StringVar()
        self.hostility_var = tk.StringVar()
        self.morale_var = tk.StringVar()
        self.life_var.trace_add("write", lambda *_args: self._cap_vital_stat(self.life_var))
        self.psyche_var.trace_add("write", lambda *_args: self._cap_vital_stat(self.psyche_var))
        self.hostility_var.trace_add("write", lambda *_args: self._cap_relation_stat(self.hostility_var))
        self.morale_var.trace_add("write", lambda *_args: self._cap_relation_stat(self.morale_var))
        for row, (label, variable) in enumerate((("LIFE", self.life_var), ("PSYCHE", self.psyche_var))):
            tk.Label(stats, text=label, bg=RED, fg="white", width=10, anchor="w", padx=7,
                     font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="ew", pady=1)
            ttk.Entry(stats, textvariable=variable, width=9, justify="right").grid(row=row, column=1, padx=(2, 12), pady=1)
        tk.Label(stats, text="STORED BASE GMP+", bg=PANEL, fg=CREAM, font=("Segoe UI", 10, "bold")).grid(row=0, column=2)
        ttk.Entry(stats, textvariable=self.gmp_var, width=10, justify="right").grid(row=1, column=2)
        for column, (label, variable) in enumerate(
            (("HOSTILITY", self.hostility_var), ("MORALE", self.morale_var)), start=3
        ):
            tk.Label(stats, text=label, bg=PANEL, fg=CREAM, font=("Segoe UI", 10, "bold")).grid(
                row=0, column=column, padx=(14, 0)
            )
            ttk.Entry(stats, textvariable=variable, width=8, justify="right").grid(
                row=1, column=column, padx=(14, 0)
            )

        parameters = tk.Frame(right, bg=BG)
        parameters.pack(fill="x", pady=(12, 0))
        ttk.Label(parameters, text="PARAMETERS", style="Sub.TLabel").pack(anchor="w")
        basic = tk.Frame(parameters, bg=BG)
        basic.pack(fill="x", pady=(3, 3))
        battle = tk.Frame(parameters, bg=BG)
        self.combat_score_var = tk.StringVar()
        self.combat_rank_var = tk.StringVar()
        self.team_score_vars = {name: tk.StringVar() for name in TEAM_GRADE_OFFSETS}
        self.team_rank_vars = {name: tk.StringVar() for name in TEAM_GRADE_OFFSETS}
        self.battle_score_vars = {name: tk.StringVar() for name in BATTLE_GRADE_OFFSETS}
        self.battle_rank_vars = {name: tk.StringVar() for name in BATTLE_GRADE_OFFSETS}
        self._battle_score_box(basic, 0, "Combat", self.combat_score_var, self.combat_rank_var, None)
        for column, (name, variable) in enumerate(self.team_score_vars.items(), start=1):
            self._team_score_box(basic, column, name, variable, self.team_rank_vars[name])
        for column, (name, variable) in enumerate(self.battle_score_vars.items()):
            self._battle_score_box(battle, column, name, variable, self.battle_rank_vars[name], name)

        skills = tk.Frame(right, bg=PANEL, padx=10, pady=10)
        skills.pack(fill="x", pady=(14, 0))
        tk.Label(skills, text="SKILLS", bg=PANEL, fg=CREAM, font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self.skill_vars = [tk.StringVar() for _ in range(VISIBLE_SKILLS)]
        for index, variable in enumerate(self.skill_vars):
            box = ttk.Combobox(skills, textvariable=variable, values=SKILL_CHOICES, state="readonly", width=34)
            box.grid(row=1 + index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 8, 0), pady=3)
            box.bind("<<ComboboxSelected>>", lambda _event, item=index: self._show_skill_description(item))
            box.bind("<FocusIn>", lambda _event, item=index: self._show_skill_description(item))
        skills.columnconfigure(0, weight=1)
        skills.columnconfigure(1, weight=1)
        self.skill_description_var = tk.StringVar(value="Select a skill to see what it does.")
        self.skill_description = tk.Label(
            skills,
            textvariable=self.skill_description_var,
            bg="#1f211e",
            fg=CREAM,
            font=("Segoe UI", 10),
            justify="left",
            anchor="nw",
            padx=10,
            pady=8,
            wraplength=900,
        )
        self.skill_description.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 2))

        # Keep custom quote editing visually separate from the skill controls.
        tk.Frame(right, bg=RED, height=3).pack(fill="x", pady=(10, 0))
        custom_quotes = tk.Frame(right, bg=PANEL, padx=10, pady=10)
        custom_quotes.pack(fill="x")
        tk.Label(
            custom_quotes,
            text="CUSTOM DETAILS QUOTE (OPTIONAL)",
            bg=PANEL,
            fg=CREAM,
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        self.custom_description_text = tk.Text(
            custom_quotes,
            height=5,
            wrap="word",
            undo=True,
            font=("Segoe UI", 11),
            bg="#f4f3ee",
            fg="#11120f",
            insertbackground="#11120f",
            relief="sunken",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        self.custom_description_text.pack(fill="x")
        tk.Label(
            custom_quotes,
            text="Stored beside the save and loaded automatically by the optional Custom Quote plugin.",
            bg=PANEL,
            fg=CREAM,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", pady=(3, 0))
        ttk.Button(custom_quotes, text="APPLY SOLDIER CHANGES", style="PW.TButton", command=self.apply_fields).pack(anchor="w", pady=(8, 0))

        # Kept as an internal buffer for record loading; the PTB interface does
        # not expose raw save bytes.
        raw = ttk.Frame(right)
        self.raw_text = tk.Text(raw, height=5, wrap="none", font=("Consolas", 9), bg="#20221f", fg="#eeeeea", insertbackground="white")

        bottom = ttk.Frame(right)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="OPEN SAVE", style="PW.TButton", command=self.open_save).pack(side="left")
        ttk.Button(bottom, text="SAVE AS", style="PW.TButton", command=self.save_as).pack(side="left", padx=8)
        ttk.Button(
            bottom,
            text="INSTALL CUSTOM QUOTE SUPPORT",
            style="PW.TButton",
            command=self.install_custom_quote_support,
        ).pack(side="left", padx=8)

    @staticmethod
    def _row(parent, row: int, label: str, widget) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 14))
        widget.grid(row=row, column=1, sticky="w", pady=5)

    @staticmethod
    def _cap_vital_stat(variable: tk.StringVar) -> None:
        value = variable.get()
        capped = capped_vital_text(value)
        if capped != value:
            variable.set(capped)

    @staticmethod
    def _cap_relation_stat(variable: tk.StringVar) -> None:
        value = variable.get()
        capped = capped_relation_text(value)
        if capped != value:
            variable.set(capped)

    def _show_skill_description(self, index: int = 0) -> None:
        if not 0 <= index < len(self.skill_vars):
            return
        label = self.skill_vars[index].get()
        try:
            value = skill_value(label, "Skill")
        except ValueError:
            self.skill_description_var.set("No description is available for this skill value.")
            return
        name = KNOWN_SKILLS.get(value, "Unknown skill")
        description = SKILL_DESCRIPTIONS.get(value, "No verified description is available for this skill.")
        self.skill_description_var.set(f"{name}: {description}")

    def play_voice_preview(self) -> None:
        """Play the bundled sample corresponding to the selected voice profile."""
        try:
            voice = enum_value(self.voice_var.get(), "Voice profile")
        except ValueError as exc:
            messagebox.showerror("Voice preview", str(exc))
            return
        preview = self.resource_root / "voice_previews" / f"voice_{voice:02d}.wav"
        if not preview.is_file():
            messagebox.showinfo(
                "Voice preview unavailable",
                f"The authentic preview sample for Voice {voice} has not been captured yet.",
            )
            return
        if winsound is None:
            messagebox.showerror("Voice preview", "Voice previews require Windows audio support.")
            return
        try:
            winsound.PlaySound(
                str(preview),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except RuntimeError as exc:
            messagebox.showerror("Voice preview", f"The preview could not be played.\n\n{exc}")

    def _grade_box(self, parent, column: int, label: str, variable: tk.StringVar, callback=None) -> None:
        panel = tk.Frame(parent, bg=RED, padx=5, pady=4)
        panel.grid(row=0, column=column, sticky="ew", padx=(0, 3))
        parent.columnconfigure(column, weight=1)
        tk.Label(panel, text=label, bg=RED, fg="white", font=("Segoe UI", 9, "bold")).pack()
        box = ttk.Combobox(panel, textvariable=variable, values=GRADE_CHOICES, state="readonly", width=10)
        box.pack(fill="x")
        if callback:
            box.bind("<<ComboboxSelected>>", callback)

    def _battle_score_box(self, parent, column: int, label: str, score_variable: tk.StringVar,
                          rank_variable: tk.StringVar, battle_name: str | None) -> None:
        panel = tk.Frame(parent, bg=RED, padx=5, pady=4)
        panel.grid(row=0, column=column, sticky="ew", padx=(0, 3))
        parent.columnconfigure(column, weight=1)
        tk.Label(panel, text=label, bg=RED, fg="white", font=("Segoe UI", 9, "bold")).pack()
        row = tk.Frame(panel, bg=RED)
        row.pack(fill="x")
        if battle_name is None:
            # The PTB exposes one friendly Combat control and keeps the eight
            # underlying battle aptitudes synchronized behind the scenes.
            rank = ttk.Combobox(row, textvariable=rank_variable, values=RANK_CHOICES,
                                state="readonly", width=3)
            entry = ttk.Entry(row, textvariable=score_variable, width=7, justify="right")
            rank.bind("<<ComboboxSelected>>", self._combat_rank_changed)
            entry.bind("<KeyRelease>", self._combat_score_changed)
            entry.bind("<Return>", self._combat_score_changed)
            entry.bind("<FocusOut>", self._combat_score_changed)
        else:
            rank = ttk.Combobox(row, textvariable=rank_variable, values=RANK_CHOICES,
                                state="readonly", width=3)
            entry = ttk.Entry(row, textvariable=score_variable, width=7, justify="right")
            rank.bind("<<ComboboxSelected>>", lambda _event, name=battle_name: self._battle_rank_changed(name))
            entry.bind("<KeyRelease>", self._battle_score_changed)
            entry.bind("<Return>", self._battle_score_changed)
            entry.bind("<FocusOut>", self._battle_score_changed)
        rank.pack(side="left")
        entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _team_score_box(self, parent, column: int, label: str, score_variable: tk.StringVar,
                        rank_variable: tk.StringVar) -> None:
        panel = tk.Frame(parent, bg=RED, padx=5, pady=4)
        panel.grid(row=0, column=column, sticky="ew", padx=(0, 3))
        parent.columnconfigure(column, weight=1)
        tk.Label(panel, text=label, bg=RED, fg="white", font=("Segoe UI", 9, "bold")).pack()
        row = tk.Frame(panel, bg=RED)
        row.pack(fill="x")
        rank = ttk.Combobox(row, textvariable=rank_variable, values=RANK_CHOICES + ["-"],
                            state="readonly", width=3)
        rank.pack(side="left")
        entry = ttk.Entry(row, textvariable=score_variable, width=7, justify="right")
        entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        rank.bind("<<ComboboxSelected>>", lambda _event, name=label: self._team_rank_changed(name))
        entry.bind("<KeyRelease>", self._team_score_changed)
        entry.bind("<Return>", self._team_score_changed)
        entry.bind("<FocusOut>", self._team_score_changed)

    def _team_rank_changed(self, name: str) -> None:
        rank = self.team_rank_vars[name].get()
        if rank == "-":
            score = 0
        else:
            grade = next((value for value, grade_name in GRADE_NAMES.items() if grade_name == rank), 0)
            score = BATTLE_GRADE_MINIMUM_SCORES[grade]
        self.team_score_vars[name].set(str(score))

    def _team_score_changed(self, _event=None) -> None:
        for name, variable in self.team_score_vars.items():
            text = variable.get().strip()
            if not text:
                self.team_rank_vars[name].set("")
                continue
            try:
                score = parse_battle_score(text, name)
            except ValueError:
                self.team_rank_vars[name].set("")
                continue
            if text != str(score):
                variable.set(str(score))
            self.team_rank_vars[name].set("-" if score == 0 else GRADE_NAMES[battle_score_grade(score)])

    def _battle_rank_changed(self, name: str) -> None:
        rank = self.battle_rank_vars[name].get()
        grade = next((value for value, grade_name in GRADE_NAMES.items() if grade_name == rank), None)
        if grade is None:
            return
        self.battle_score_vars[name].set(str(BATTLE_GRADE_MINIMUM_SCORES[grade]))
        self._battle_score_changed()

    def _combat_rank_changed(self, _event=None) -> None:
        rank = self.combat_rank_var.get()
        grade = next((value for value, grade_name in GRADE_NAMES.items() if grade_name == rank), None)
        if grade is None:
            return
        score = BATTLE_GRADE_MINIMUM_SCORES[grade]
        for variable in self.battle_score_vars.values():
            variable.set(str(score))
        self._battle_score_changed()

    def _combat_score_changed(self, _event=None) -> None:
        text = self.combat_score_var.get().strip()
        if not text:
            self.combat_rank_var.set("")
            return
        try:
            score = parse_battle_score(text, "Combat")
        except ValueError:
            self.combat_rank_var.set("")
            return
        if text != str(score):
            self.combat_score_var.set(str(score))
        for variable in self.battle_score_vars.values():
            variable.set(str(score))
        self._battle_score_changed()

    def _battle_score_changed(self, _event=None) -> None:
        scores = []
        for name, variable in self.battle_score_vars.items():
            try:
                score = parse_battle_score(variable.get(), name)
            except ValueError:
                self.battle_rank_vars[name].set("")
                continue
            if variable.get().strip() != str(score):
                variable.set(str(score))
            scores.append(score)
            self.battle_rank_vars[name].set(GRADE_NAMES[battle_score_grade(score)])
        if len(scores) == len(self.battle_score_vars):
            weakest = min(scores)
            self.combat_score_var.set(str(weakest))
            self.combat_rank_var.set(GRADE_NAMES[battle_score_grade(weakest)])

    def open_save(self) -> None:
        path_text = filedialog.askopenfilename(title="Open Peace Walker PC STW save")
        if not path_text:
            return
        path = Path(path_text)
        try:
            encrypted = bytearray(path.read_bytes())
            if len(encrypted) != SAVE_SIZE:
                raise ValueError(f"Expected {SAVE_SIZE} bytes; file contains {len(encrypted)}")
            index, *_ = derive_state(encrypted)
            transform(encrypted, index)
            if encrypted[0x40:0x44] != b"oEbN":
                raise ValueError("The file did not decrypt as a PC Peace Walker STW save")
        except Exception as exc:
            messagebox.showerror("Cannot open save", str(exc))
            return
        self.data = encrypted
        self.source_path = path
        self.header_index = index
        self.selected_slot = None
        self.dirty = False
        self._load_custom_quotes(path)
        self._refresh_metadata_choices()
        self.refresh_list()
        self.status_var.set(f"Opened {path.name} — header index {index}")

    def record_start(self, slot: int) -> int:
        return ROSTER_BASE + slot * RECORD_SIZE

    def ensure_roster_includes(self, slot: int) -> None:
        """Extend the game's active-roster boundary to include a populated slot."""
        assert self.data is not None
        current = int.from_bytes(self.data[ROSTER_COUNT_OFFSET : ROSTER_COUNT_OFFSET + 4], "little")
        required = slot + 1
        if required > current:
            self.data[ROSTER_COUNT_OFFSET : ROSTER_COUNT_OFFSET + 4] = required.to_bytes(4, "little")

    def soldier_name(self, slot: int) -> str:
        assert self.data is not None
        start = self.record_start(slot) + NAME_OFFSET
        raw = bytes(self.data[start : start + NAME_SIZE]).split(b"\0", 1)[0]
        return raw.decode("ascii", errors="replace") or "<empty>"

    def _show_roster_menu(self, event) -> None:
        if self.data is None or self.roster.size() == 0:
            return
        index = self.roster.nearest(event.y)
        bounds = self.roster.bbox(index)
        if bounds is None or not bounds[1] <= event.y < bounds[1] + bounds[3]:
            return
        self.roster.selection_clear(0, "end")
        self.roster.selection_set(index)
        self.roster.activate(index)
        self.select_soldier()
        empty = self.selected_slot is not None and self.soldier_name(self.selected_slot) == "<empty>"
        self.roster_menu.entryconfigure("Export soldier...", state="disabled" if empty else "normal")
        self.roster_menu.entryconfigure("Import soldier...", state="normal" if empty else "disabled")
        try:
            self.roster_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.roster_menu.grab_release()

    def export_soldier(self) -> None:
        if self.data is None or self.selected_slot is None:
            return
        slot = self.selected_slot
        name = self.soldier_name(slot)
        if name == "<empty>":
            messagebox.showinfo("Empty slot", "Select a populated soldier to export.")
            return
        safe_name = "".join(character if character.isalnum() or character in "-_" else "_" for character in name)
        path_text = filedialog.asksaveasfilename(
            title="Export Peace Walker soldier",
            initialfile=f"{safe_name}.pwsoldier",
            defaultextension=".pwsoldier",
            filetypes=(("Peace Walker soldier", "*.pwsoldier"), ("All files", "*.*")),
        )
        if not path_text:
            return
        start = self.record_start(slot)
        record = bytes(self.data[start : start + RECORD_SIZE])
        Path(path_text).write_bytes(SOLDIER_EXPORT_MAGIC + record)
        self.status_var.set(f"Exported {name} to {Path(path_text).name}.")

    def import_soldier(self) -> None:
        if self.data is None or self.selected_slot is None:
            return
        slot = self.selected_slot
        if self.soldier_name(slot) != "<empty>":
            messagebox.showinfo("Slot occupied", "Soldiers can only be imported into an empty slot.")
            return
        path_text = filedialog.askopenfilename(
            title="Import Peace Walker soldier",
            filetypes=(("Peace Walker soldier", "*.pwsoldier"), ("All files", "*.*")),
        )
        if not path_text:
            return
        try:
            payload = Path(path_text).read_bytes()
            if not payload.startswith(SOLDIER_EXPORT_MAGIC):
                raise ValueError("This is not a Peace Walker Soldier Editor export file.")
            record = payload[len(SOLDIER_EXPORT_MAGIC):]
            if len(record) != RECORD_SIZE:
                raise ValueError(f"The exported soldier record must contain exactly {RECORD_SIZE} bytes.")
            imported_name = record[NAME_OFFSET : NAME_OFFSET + NAME_SIZE].split(b"\0", 1)[0].decode("ascii")
            if not imported_name:
                raise ValueError("The exported record does not contain a soldier name.")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            messagebox.showerror("Cannot import soldier", str(exc))
            return
        start = self.record_start(slot)
        self.data[start : start + RECORD_SIZE] = record
        self.ensure_roster_includes(slot)
        self.dirty = True
        self._refresh_metadata_choices()
        self.assignment_filter_var.set("All assignments")
        self.search_var.set("")
        self.refresh_list()
        self._select_slot(slot)
        self.status_var.set(f"Imported {imported_name} into slot {slot + 1}; use Save As to write it.")

    def _refresh_metadata_choices(self) -> None:
        assert self.data is not None
        assignment_values = sorted(
            set(ASSIGNMENTS)
            | {self.data[self.record_start(i) + ASSIGNMENT_OFFSET] for i in range(RECORD_COUNT)}
        )
        type_values = sorted(set(SOLDIER_TYPES) | {self.data[self.record_start(i) + SOLDIER_TYPE_OFFSET] for i in range(RECORD_COUNT)})
        service_values = sorted(set(SERVICE_TYPES) | {self.data[self.record_start(i) + SERVICE_TYPE_OFFSET] for i in range(RECORD_COUNT)})
        sex_values = sorted({self.data[self.record_start(i) + SEX_OFFSET] for i in range(RECORD_COUNT)})
        self.soldier_type_box.configure(values=[enum_label(v, SOLDIER_TYPES) for v in type_values])
        self.service_type_box.configure(values=[enum_label(v, SERVICE_TYPES) for v in service_values])
        self.sex_box.configure(values=[enum_label(v, SEXES) for v in sex_values])
        self.assignment_box.configure(values=[enum_label(value, ASSIGNMENTS) for value in assignment_values])
        self.assignment_filter_box.configure(
            values=["All assignments"] + [enum_label(value, ASSIGNMENTS) for value in assignment_values]
        )
        self.description_slots = {
            f"{slot + 1:03d} — {self.soldier_name(slot)}": slot
            for slot in range(RECORD_COUNT)
            if self.soldier_name(slot) != "<empty>"
        }
        self.description_box.configure(values=list(self.description_slots))

    def clear_filters(self) -> None:
        self.assignment_filter_var.set("All assignments")
        self.search_var.set("")
        self.refresh_list()

    def refresh_list(self) -> None:
        self.roster.delete(0, "end")
        if self.data is None:
            return
        needle = self.search_var.get().casefold().strip()
        for slot in range(RECORD_COUNT):
            name = self.soldier_name(slot)
            start = self.record_start(slot)
            if needle and needle not in name.casefold() and needle not in str(slot + 1):
                continue
            assignment_filter = self.assignment_filter_var.get()
            # A typed name/slot search is global. This keeps story characters
            # and other special assignments from being hidden by a team filter.
            if not needle and assignment_filter != "All assignments" and self.data[start + ASSIGNMENT_OFFSET] != enum_value(assignment_filter, "Assignment filter"):
                continue
            self.roster.insert("end", f"{slot + 1:03d}  {name}")
        if needle and self.roster.size() == 1:
            self.roster.selection_set(0)
            self.roster.see(0)
            self.select_soldier()

    def update_portrait_preview(self) -> None:
        choice = self.portrait_choice_var.get()
        if choice not in self.portrait_choices:
            return
        portrait_set, face = self.portrait_choices[choice]
        resource_hash = (portrait_set << 16) | 0x4C00 | face
        path = self.portrait_files.get(resource_hash)
        if path is None:
            # Named/story characters use the BC portrait family rather than the
            # regular-soldier 4C family.  Match by the two codes stored in the
            # roster record and prefer known portrait families.
            candidates = self.portrait_files_by_code.get((portrait_set, face), [])
            if candidates:
                family_priority = {0x4C: 0, 0xBC: 1}
                path = min(candidates, key=lambda item: family_priority.get(item[0], 99))[1]
        if path is None:
            self.portrait_photo = None
            self.portrait_text.configure(image="", text="PORTRAIT")
            self.portrait_code.configure(text=choice)
            return
        try:
            image = Image.open(path).convert("RGBA")
            alpha = image.getchannel("A")
            # DXT5 leaves faint non-zero alpha in otherwise empty padding.
            # Ignore that compression noise when finding the visible portrait.
            visible_alpha = alpha.point(lambda value: 255 if value >= 4 else 0)
            bounds = visible_alpha.getbbox()
            if bounds:
                image = image.crop(bounds)
            cropped_alpha = image.getchannel("A")
            face_mask = cropped_alpha.point(lambda value: 255 if value >= 4 else 0).crop(
                (
                    0,
                    int(image.height * 0.25),
                    image.width,
                    max(1, int(image.height * 0.70)),
                )
            )
            head_bounds = face_mask.getbbox()
            left_padding = 0
            right_padding = 0
            if head_bounds:
                head_center = (head_bounds[0] + head_bounds[2]) // 2
                imbalance = image.width - 2 * head_center
                if imbalance > 0:
                    left_padding = imbalance
                elif imbalance < 0:
                    right_padding = -imbalance
            if left_padding or right_padding:
                centered = Image.new(
                    "RGBA", (image.width + left_padding + right_padding, image.height), (0, 0, 0, 0)
                )
                centered.alpha_composite(image, (left_padding, 0))
                image = centered
            scale = min(226 / image.width, 226 / image.height)
            fitted_size = (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
            image = image.resize(fitted_size, Image.Resampling.LANCZOS)
            paper = Image.new("RGB", (226, 226), "#c9c9b3")
            ink = Image.new("RGB", image.size, "#292a25")
            resized_alpha = image.getchannel("A")
            position = ((226 - image.width) // 2, (226 - image.height) // 2)
            paper.paste(ink, position, resized_alpha)
            self.portrait_photo = ImageTk.PhotoImage(paper)
            self.portrait_text.configure(
                image=self.portrait_photo,
                text="",
            )
            self.portrait_code.configure(text=choice)
        except (OSError, ValueError):
            self.portrait_photo = None
            self.portrait_text.configure(image="", text="PORTRAIT")
            self.portrait_code.configure(text=choice)

    def select_soldier(self, _event=None) -> None:
        selection = self.roster.curselection()
        if not selection or self.data is None:
            return
        line = self.roster.get(selection[0])
        slot = int(line[:3]) - 1
        self.selected_slot = slot
        start = self.record_start(slot)
        record = self.data[start : start + RECORD_SIZE]
        self.name_var.set(self.soldier_name(slot).replace("<empty>", ""))
        self.assignment_var.set(enum_label(record[ASSIGNMENT_OFFSET], ASSIGNMENTS))
        portrait_pair = (record[PORTRAIT_SET_OFFSET], record[PORTRAIT_FACE_OFFSET])
        self.portrait_choice_var.set(self.portrait_choice_by_code.get(portrait_pair, "Portrait unavailable"))
        self.soldier_type_var.set(enum_label(record[SOLDIER_TYPE_OFFSET], SOLDIER_TYPES))
        self.service_type_var.set(enum_label(record[SERVICE_TYPE_OFFSET], SERVICE_TYPES))
        self.sex_var.set(enum_label(record[SEX_OFFSET], SEXES))
        self.unit_title_var.set(enum_label(record[UNIT_TITLE_OFFSET], UNIT_TITLES))
        self.voice_var.set(enum_label(record[VOICE_OFFSET], VOICES))
        self.acquisition_method_var.set(
            enum_label(record[ACQUISITION_METHOD_OFFSET], ACQUISITION_METHODS)
        )
        condition_flags = record[CONDITION_FLAGS_OFFSET]
        self.condition_var.set(
            "Condition: Normal (read-only)"
            if condition_flags == 0
            else "Condition: Sick/wounded state detected (read-only)"
        )
        own_description = f"{slot + 1:03d} — {self.soldier_name(slot)}"
        self.description_var.set(own_description)
        self.custom_description_text.delete("1.0", "end")
        self.custom_description_text.insert("1.0", self.custom_quotes.get(slot, ""))
        self.update_portrait_preview()
        self.life_var.set(str(int.from_bytes(record[LIFE_MAX_OFFSET:LIFE_MAX_OFFSET + 2], "little")))
        self.psyche_var.set(str(int.from_bytes(record[PSYCHE_MAX_OFFSET:PSYCHE_MAX_OFFSET + 2], "little")))
        self.gmp_var.set(str(int.from_bytes(record[GMP_OFFSET:GMP_OFFSET + 2], "little")))
        self.hostility_var.set(str(int.from_bytes(record[HOSTILITY_OFFSET:HOSTILITY_OFFSET + 2], "little")))
        self.morale_var.set(str(int.from_bytes(record[MORALE_OFFSET:MORALE_OFFSET + 2], "little")))
        self.loaded_team_scores = {}
        for name, variable in self.team_score_vars.items():
            offset = TEAM_GRADE_OFFSETS[name]
            score = int.from_bytes(record[offset:offset + 2], "little")
            self.loaded_team_scores[name] = score
            variable.set(str(score))
        self._team_score_changed()
        self.loaded_battle_scores = {}
        for name, variable in self.battle_score_vars.items():
            offset = BATTLE_GRADE_OFFSETS[name]
            score = int.from_bytes(record[offset:offset + 2], "little")
            self.loaded_battle_scores[name] = score
            variable.set(str(score))
        self._battle_score_changed()
        for index, variable in enumerate(self.skill_vars):
            value = record[SKILLS_OFFSET + index]
            label = KNOWN_SKILLS.get(value, "reserved" if value in RESERVED_SKILLS else "")
            variable.set(skill_label(value))
            if index == 0 and label:
                self.status_var.set(f"Slot {slot + 1}: {self.soldier_name(slot)} — first skill: {label}")
        self._show_skill_description(0)
        lines = []
        for offset in range(0, RECORD_SIZE, 16):
            chunk = record[offset : offset + 16]
            lines.append(f"{offset:02X}: " + " ".join(f"{value:02X}" for value in chunk))
        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("1.0", "\n".join(lines))

    def apply_fields(self) -> None:
        if self.data is None or self.selected_slot is None:
            messagebox.showinfo("No soldier selected", "Select a soldier first.")
            return
        try:
            encoded_name = self.name_var.get().encode("ascii")
            if len(encoded_name) > NAME_SIZE - 1:
                raise ValueError("Codename must be at most 15 ASCII characters")
            assignment = enum_value(self.assignment_var.get(), "Assignment")
            portrait_choice = self.portrait_choice_var.get()
            if portrait_choice not in self.portrait_choices:
                raise ValueError("Choose an available portrait")
            portrait_set, portrait_face = self.portrait_choices[portrait_choice]
            soldier_type = enum_value(self.soldier_type_var.get(), "Soldier class")
            service_type = enum_value(self.service_type_var.get(), "Recruitment category")
            sex = enum_value(self.sex_var.get(), "Sex")
            unit_title = enum_value(self.unit_title_var.get(), "Unit title")
            voice = enum_value(self.voice_var.get(), "Voice profile")
            acquisition_method = enum_value(self.acquisition_method_var.get(), "Acquisition method")
            description_slot = self.description_slots[self.description_var.get()]
            custom_description = self.custom_description_text.get("1.0", "end-1c").strip()
            try:
                custom_description_bytes = custom_description.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("Custom Details Quote must be valid UTF-8 text") from exc
            if len(custom_description_bytes) > CUSTOM_QUOTE_MAX_BYTES:
                raise ValueError(
                    f"Custom Details Quote must be no more than {CUSTOM_QUOTE_MAX_BYTES} UTF-8 bytes"
                )
            life = parse_stat(self.life_var.get(), "Life")
            psyche = parse_stat(self.psyche_var.get(), "Psyche")
            gmp = parse_stat(self.gmp_var.get(), "Base GMP+", 0xFFFF)
            hostility = parse_stat(self.hostility_var.get(), "Hostility", RELATION_STAT_MAX)
            morale = parse_stat(self.morale_var.get(), "Morale", RELATION_STAT_MAX)
            team_scores = {
                name: parse_battle_score(variable.get(), name)
                for name, variable in self.team_score_vars.items()
            }
            battle_scores = {
                name: parse_battle_score(variable.get(), name)
                for name, variable in self.battle_score_vars.items()
            }
            skills = bytes(
                skill_value(variable.get(), f"Skill {index + 1}")
                for index, variable in enumerate(self.skill_vars)
            )
        except (UnicodeEncodeError, ValueError) as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        start = self.record_start(self.selected_slot)
        self.data[start + NAME_OFFSET : start + NAME_OFFSET + NAME_SIZE] = (
            encoded_name + b"\0" * (NAME_SIZE - len(encoded_name))
        )
        self.data[start + ASSIGNMENT_OFFSET] = assignment
        self.data[start + PORTRAIT_FACE_OFFSET] = portrait_face
        self.data[start + PORTRAIT_SET_OFFSET] = portrait_set
        self.data[start + SOLDIER_TYPE_OFFSET] = soldier_type
        self.data[start + SERVICE_TYPE_OFFSET] = service_type
        self.data[start + SEX_OFFSET] = sex
        self.data[start + UNIT_TITLE_OFFSET] = unit_title
        self.data[start + VOICE_OFFSET] = voice
        self.data[start + ACQUISITION_METHOD_OFFSET] = acquisition_method
        life_bytes = life.to_bytes(2, "little")
        psyche_bytes = psyche.to_bytes(2, "little")
        self.data[start + LIFE_CURRENT_OFFSET : start + LIFE_CURRENT_OFFSET + 2] = life_bytes
        self.data[start + LIFE_MAX_OFFSET : start + LIFE_MAX_OFFSET + 2] = life_bytes
        self.data[start + PSYCHE_CURRENT_OFFSET : start + PSYCHE_CURRENT_OFFSET + 2] = psyche_bytes
        self.data[start + PSYCHE_MAX_OFFSET : start + PSYCHE_MAX_OFFSET + 2] = psyche_bytes
        self.data[start + GMP_OFFSET : start + GMP_OFFSET + 2] = gmp.to_bytes(2, "little")
        self.data[start + HOSTILITY_OFFSET : start + HOSTILITY_OFFSET + 2] = hostility.to_bytes(2, "little")
        self.data[start + MORALE_OFFSET : start + MORALE_OFFSET + 2] = morale.to_bytes(2, "little")
        for name, score in team_scores.items():
            offset = start + TEAM_GRADE_OFFSETS[name]
            self.data[offset:offset + 2] = score.to_bytes(2, "little")
        for name, score in battle_scores.items():
            offset = start + BATTLE_GRADE_OFFSETS[name]
            self.data[offset:offset + 2] = score.to_bytes(2, "little")
        donor = self.record_start(description_slot) + DESCRIPTION_KEY_OFFSET
        self.data[start + DESCRIPTION_KEY_OFFSET : start + DESCRIPTION_KEY_OFFSET + DESCRIPTION_KEY_SIZE] = self.data[
            donor : donor + DESCRIPTION_KEY_SIZE
        ]
        if custom_description:
            self.custom_quotes[self.selected_slot] = custom_description
        else:
            self.custom_quotes.pop(self.selected_slot, None)
        self.data[start + SKILLS_OFFSET : start + SKILLS_OFFSET + VISIBLE_SKILLS] = skills
        if encoded_name:
            self.ensure_roster_includes(self.selected_slot)
        self.dirty = True
        slot = self.selected_slot
        self.refresh_list()
        self._select_slot(slot)
        self.status_var.set(f"Applied changes to slot {slot + 1}; use Save As to write a new save.")

    def _custom_quote_sidecar(self, save_path: Path) -> Path:
        return save_path.with_name(save_path.name + CUSTOM_QUOTE_SIDECAR_SUFFIX)

    def _load_custom_quotes(self, save_path: Path) -> None:
        self.custom_quotes = {}
        sidecar = self._custom_quote_sidecar(save_path)
        if not sidecar.is_file():
            return
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            records = payload.get("soldiers", {})
            for slot_text, item in records.items():
                slot = int(slot_text) - 1
                text = str(item.get("text", "")).strip()
                if 0 <= slot < RECORD_COUNT and text:
                    self.custom_quotes[slot] = text
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            messagebox.showwarning(
                "Custom quote file",
                f"Could not read {sidecar.name}. The save itself can still be edited.",
            )

    def _runtime_quote_entries(self) -> dict[int, dict[str, object]]:
        if self.data is None:
            return {}
        entries: dict[int, dict[str, object]] = {}
        for slot, text in sorted(self.custom_quotes.items()):
            start = self.record_start(slot)
            selector = bytes(self.data[start + DESCRIPTION_KEY_OFFSET : start + DESCRIPTION_KEY_OFFSET + 4])
            # The current PC build resolves a Details Quote by adding six to
            # the first selector byte before calling the localized text resolver.
            runtime_index = selector[0] + 6
            existing = entries.get(runtime_index)
            if existing is not None and existing["text"] != text:
                raise ValueError(
                    f"Slots {existing['slot']} and {slot + 1} use the same Details Quote donor. "
                    "Choose a different donor for one of them."
                )
            entries[runtime_index] = {
                "slot": slot + 1,
                "name": self.soldier_name(slot),
                "selector": selector.hex(),
                "text": text,
            }
        return entries

    def _write_custom_quote_sidecar(self, save_path: Path) -> Path | None:
        entries = self._runtime_quote_entries()
        sidecar = self._custom_quote_sidecar(save_path)
        if not entries:
            if sidecar.exists():
                sidecar.unlink()
            return None
        soldiers = {
            str(item["slot"]): {
                "name": item["name"],
                "selector": item["selector"],
                "runtime_index": runtime_index,
                "text": item["text"],
            }
            for runtime_index, item in entries.items()
        }
        sidecar.write_text(
            json.dumps({"version": 1, "save": save_path.name, "soldiers": soldiers}, indent=2) + "\n",
            encoding="utf-8",
        )
        return sidecar

    def install_custom_quote_support(self) -> None:
        plugin = self.resource_root / "quote_plugin" / "PeaceWalkerCustomQuotes.asi"
        if not plugin.is_file():
            messagebox.showerror(
                "Custom Quote Support",
                "PeaceWalkerCustomQuotes.asi is missing from this editor build.",
            )
            return
        game_text = filedialog.askopenfilename(
            title="Select METAL GEAR SOLID PEACE WALKER.exe",
            filetypes=(("Peace Walker", "METAL GEAR SOLID PEACE WALKER.exe"), ("Applications", "*.exe")),
        )
        if not game_text:
            return
        game = Path(game_text)
        if game.name.lower() != "metal gear solid peace walker.exe":
            messagebox.showerror("Custom Quote Support", "Select the real Peace Walker game executable.")
            return
        if not (game.parent / "winmm.dll").is_file():
            messagebox.showerror(
                "Custom Quote Support",
                "No compatible ASI loader was found beside the game. Install MGSPatriotFix first.",
            )
            return
        destination = game.parent / "scripts" / plugin.name
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plugin, destination)
        except OSError as exc:
            messagebox.showerror("Custom Quote Support", f"Could not install the plugin.\n\n{exc}")
            return
        messagebox.showinfo(
            "Custom Quote Support Installed",
            "Peace Walker will now load matching .pwquotes.json files automatically.\n\n"
            "Restart the game if it is currently running.",
        )

    def apply_raw(self) -> None:
        if self.data is None or self.selected_slot is None:
            messagebox.showinfo("No soldier selected", "Select a soldier first.")
            return
        text = self.raw_text.get("1.0", "end")
        tokens = []
        for line in text.splitlines():
            payload = line.split(":", 1)[1] if ":" in line else line
            tokens.extend(payload.split())
        try:
            record = bytes(parse_hex_byte(token, "Raw record") for token in tokens)
            if len(record) != RECORD_SIZE:
                raise ValueError(f"Raw record must contain exactly {RECORD_SIZE} bytes")
        except ValueError as exc:
            messagebox.showerror("Invalid raw record", str(exc))
            return
        start = self.record_start(self.selected_slot)
        self.data[start : start + RECORD_SIZE] = record
        if record[NAME_OFFSET : NAME_OFFSET + NAME_SIZE].split(b"\0", 1)[0]:
            self.ensure_roster_includes(self.selected_slot)
        self.dirty = True
        slot = self.selected_slot
        self.refresh_list()
        self._select_slot(slot)
        self.status_var.set(f"Applied raw record to slot {slot}; use Save As to write it.")

    def _select_slot(self, slot: int) -> None:
        for index in range(self.roster.size()):
            if self.roster.get(index).startswith(f"{slot + 1:03d} "):
                self.roster.selection_clear(0, "end")
                self.roster.selection_set(index)
                self.roster.see(index)
                self.select_soldier()
                break

    def save_as(self) -> None:
        if self.data is None or self.source_path is None or self.header_index is None:
            messagebox.showinfo("No save open", "Open a PC STW save first.")
            return
        candidate = bytearray(self.data)
        # The game only scans this many records. Rebuild the boundary at save
        # time as a final safeguard, including soldiers imported by older builds.
        populated_slots = [
            slot
            for slot in range(RECORD_COUNT)
            if candidate[
                self.record_start(slot) + NAME_OFFSET : self.record_start(slot) + NAME_OFFSET + NAME_SIZE
            ].split(b"\0", 1)[0]
        ]
        if populated_slots:
            required_count = max(populated_slots) + 1
            current_count = int.from_bytes(
                candidate[ROSTER_COUNT_OFFSET : ROSTER_COUNT_OFFSET + 4], "little"
            )
            if required_count > current_count:
                candidate[ROSTER_COUNT_OFFSET : ROSTER_COUNT_OFFSET + 4] = required_count.to_bytes(4, "little")
        update_internal_checks(candidate)
        transform(candidate, self.header_index)
        checksum = filename_checksum(candidate)
        suggested = f"STW000000{checksum:04x}01"
        path_text = filedialog.asksaveasfilename(
            title="Save edited Peace Walker file",
            initialdir=str(self.source_path.parent),
            initialfile=suggested,
            defaultextension="",
        )
        if not path_text:
            return
        output = Path(path_text)
        if output.resolve() == self.source_path.resolve():
            backup = self.source_path.with_name(self.source_path.name + ".backup")
            shutil.copy2(self.source_path, backup)
        output.write_bytes(candidate)
        try:
            sidecar = self._write_custom_quote_sidecar(output)
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Custom Details Quotes",
                f"The save was written, but its custom quote file could not be written.\n\n{exc}",
            )
            return
        self.dirty = False
        messagebox.showinfo(
            "Save written",
            f"Saved {output.name}"
            + (f"\nCustom quotes: {sidecar.name}" if sidecar is not None else "")
            + f"\n\nRequired checksum filename: {suggested}\n"
            "If you chose another name, rename the file before loading it in game.",
        )
        self.status_var.set(f"Saved {output}")


if __name__ == "__main__":
    SoldierEditor().mainloop()
