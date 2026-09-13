# Peace Walker Soldier Editor

Executable: `dist/PeaceWalkerSoldierEditor_v8.exe`

## Supported save type

- Master Collection PC `STW` saves (`0x4F950` bytes).
- The editor decrypts the primary save payload automatically.
- Save As rebuilds the known internal checks, encrypts the payload, and
  calculates the filename checksum required by the game.

## Confirmed editable fields

- Codename: staff record `+0x20`, 16-byte storage (15 ASCII characters plus
  terminator).
- Assignment byte: record `+0x30`. This byte changes when moving a soldier to
  the Waiting Room, but its complete enum is not yet labeled.
- Portrait/special-identity byte: record `+0x19`.
- Recruitment category: record `+0x18`. Confirmed values are `04` special/no
  category, `06` Former Prisoner, `07` Volunteer Soldier, and `08` Military
  Soldier.
- Soldier class: record `+0x31`. The dropdown contains every class confirmed
  against the in-game staff-details screen; unknown values already present in
  a save remain selectable and are preserved as unmapped values.
- Life current/maximum: record `+0x42/+0x44` (little-endian 16-bit). The editor
  displays the maximum, matching the in-game staff-details screen, and writes
  an edited value to both fields.
- Psyche current/maximum: record `+0x4A/+0x4C` (little-endian 16-bit). The
  editor likewise displays the maximum and writes both fields.
- Base GMP+: record `+0x38` (little-endian 16-bit). The number displayed by
  the game can be higher when staff bonuses are active.
- R&D, Mess Hall, Medical, Intel, and the eight battle aptitudes are stored as
  little-endian 16-bit scores. Their displayed grades use the confirmed score
  bands: a zero score displays `-`, E starts at 1, D at 100, C at 200, B at
  500, A at 750, and S at 1001. Unchanged scores are preserved exactly.
- Combat is the grade of the weakest of the eight battle aptitudes. In the
  editor its dropdown sets all eight at once; each can subsequently be changed
  alone.
- Eight-byte zero-terminated skill-ID list: record `+0x98..+0x9F`.
- Complete `0xA0` raw staff record for controlled research.

## PS3 cross-format validation

The decrypted PS3 advanced-save roster was compared with its PC round-trip.
All 350 staff records (`350 × 0xA0` bytes) matched byte-for-byte. The PS3 and PC
formats therefore use the same soldier-record layout and the same four skill
IDs; conversion relocates the roster block but does not translate its fields.

Cross-checked examples include HIDEO's four-skill sequence
`03 08 0C 0E` (SWAT, Channeler, Green Beret, Pro Wrestling Maniac), Miller's
`2F`, Amanda's `2B`, Huey's `23`, Paz's `2E`, and Strangelove's `2C`.

## Confirmed soldier-class table

| ID | In-game class | ID | In-game class |
|---:|---|---:|---|
| `01` | Infantry | `02` | Sharpshooter |
| `03` | Commando | `04` | Scout |
| `05` | Guerrilla | `06` | Elite Commando |
| `07` | Mechanic | `08` | Researcher |
| `09` | Doctor | `0A` | Nurse |
| `0B` | Cook | `0C` | Medic |
| `0D` | Engineer | `0E` | Supply Soldier |
| `0F` | Industrial Spy | `10` | Spy |
| `11` | Food Technician | `12` | Nutritionist |
| `13` | Medical Researcher | `15` | High School Student (Paz) |
| `16` | MSF Subcommander (Miller) | `18` | AI Researcher (Strangelove) |
| `19` | Child Soldier (Chico) | `1A` | FSLN Commander (Amanda) |
| `1B` | Bipedal Weapons Developer (Huey) | `1C` | Ornithologist (Cécile) |
| `24` | Commander | `31` | Actress |
| `55` | Veteran Voice Actor | `56` | New Voice Actor |
| `57` | Game Designer (Hideo) |  |  |

## Exact Master Collection English skill table

The following names were read directly from the English in-game staff-details
screen using a controlled ten-soldier verification save:

| ID | In-game English name | ID | In-game English name |
|---:|---|---:|---|
| `01` | Sidekick | `02` | Radio Technology |
| `03` | SWAT | `04` | Rescue |
| `05` | Decoy | `06` | Engineering |
| `08` | Channeler | `09` | Voice Actor |
| `0C` | Green Beret | `0E` | Pro Wrestling Maniac |
| `10` | Three-Star Chef | `11` | Four-Star Chef |
| `12` | Five-Star Chef | `13` | Pharmacist |
| `14` | Expert Pharmacist | `16` | Counselor |
| `18` | Physician | `19` | Surgeon |
| `1B` | Gunsmith (Handguns) | `1C` | Gunsmith (Shotguns) |
| `1D` | Gunsmith (Assault Rifles) | `1E` | Gunsmith (Machine Guns) |
| `1F` | Gunsmith (Sniper Rifles) | `23` | Bipedal Weapons Design |
| `27` | Gung Ho | `2A` | Optical Technology |
| `2B` | FSLN Comandante | `2C` | AI Development Technology |
| `2D` | Bird Watcher | `2E` | Home Cooking |
| `2F` | Mother Base Deputy Commander | `30` | Gunsmith (Submachine Guns) |
| `31` | Patriot | `32` | Japanese Patriot |
| `33` | Anti-tank Rifle Design | `34` | M134 Design |
| `35` | EM Weapons Design | `36` | Metamaterials Technology |

## Safety

- Prefer Save As to a testing folder.
- If the original path is deliberately selected, the editor creates a
  `.backup` copy first.
- Use the checksum filename shown by the editor before putting the save into
  the game's save directory.
- Raw-record editing can create unsupported identities, skills, or invalid
  staff state even when the overall save remains structurally valid.
