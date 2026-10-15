![MetaFix](docs/assets/banner.svg)

MetaFix is a desktop utility for bulk-repairing date and time metadata on photos and videos. It uses [ExifTool](https://exiftool.org/) under the hood and wraps it in a clean dark GUI built with Python, Flask, and pywebview.

Built for the common situation where photos come off a phone, cloud service, or old backup with wrong, missing, or inconsistent timestamps across their metadata fields.

---

## Features

- **Three edit modes** — set a manual date, copy one field into others, or shift dates by years/months/days/hours/minutes
- **Before/after columns** — see exactly what will change before you commit
- **Field source indicator** — the Current date column shows which EXIF field the date was read from (e.g. `2026:06:06 21:34:15 (CreateDate)`)
- **Copy source hint** — the copy mode dropdown auto-selects the most common source field across your loaded files and annotates each option with a file count
- **Filter by source field** — filter the file list to show only files whose date comes from a specific field, then select all of them with one click
- **Selection-aware actions** — preview and apply only affect ticked files; unticked files are never touched
- **Drag and drop** — drop files or folders directly onto the window
- **Recursive folder scan** — optional, toggled per session
- **Rename to timestamp** — renames files to `YYYY-MM-DD_HH-MM-SS_originalname.ext` after writing metadata, with `(1)`, `(2)` duplicate protection
- **BACKUPS folder** — originals are backed up to a `BACKUPS/` subfolder in the same directory before any changes are made
- **Undo** — restores the last batch from the BACKUPS folder
- **Clean backups** — deletes the BACKUPS folders once you're satisfied
- **ExifTool path memory** — set once, remembered in `data/config.json` forever
- **Non-destructive** — only metadata headers are modified; pixel data, video codec, and quality are never touched

---

## Supported formats

| Type | Extensions |
|------|-----------|
| Photos | `.jpg` `.jpeg` `.png` `.heic` `.webp` `.tiff` |
| Videos | `.mov` `.mp4` `.m4v` `.avi` `.mkv` `.3gp` `.gif` |

---

## Requirements

- **Windows** (tested on Windows 10/11)
- **Python 3.10+**
- **ExifTool** — download the Windows executable from [exiftool.org](https://exiftool.org/) and place it anywhere on your machine

---

## Installation

```bash
git clone https://github.com/yourname/MetaFix
cd MetaFix
pip install -r requirements.txt
python MetaFix.py
```

On first launch, click the path bar at the top of the window and point it to your `exiftool.exe`. This is saved in `data/config.json` and never needs to be set again.

---

## Packaging

The legacy PyInstaller spec is in the ignored `Meta/` directory and has not been updated for the package layout. It still refers to `app.py` and the old asset directories; the previous build command is not currently supported.

## Usage

### 1 — Load files

Drag and drop photos or videos directly onto the window, or use the **add files** and **add folder** buttons in the toolbar. Enable **Recursive folders** before adding a folder to scan all subfolders.

Files appear in the table with their current metadata date and the field it was read from. The priority order for field selection is:

```
DateTimeOriginal → ContentCreateDate → CreateDate → MediaCreateDate
→ TrackCreateDate → TrackModifyDate → ModifyDate → FileCreateDate → FileModifyDate
```

### 2 — Choose a mode

**Manual** — Pick a specific date and time. That exact value will be written to all selected destination fields. Use this when you know the correct date (e.g. you scanned old photos and want to tag them with the day they were taken).

**Copy** — Copies the value from one source field into all selected destination fields on the same file. Useful when one field has the correct date and the others don't. The dropdown auto-selects the most common source field across your loaded files and shows the count per field so you can confirm you're picking the right one.

**Shift** — Moves every date forward or backward by a relative offset. Enter negative values to go backwards. Useful for correcting timezone errors (e.g. camera was set to the wrong timezone) or systematic clock drift.

### 3 — Select files

Check individual rows or use the header checkbox to select all visible rows. The toolbar shows a **gold pill** with the current selection count.

Use the **filter by source field** dropdown to narrow the table to files that share a particular source field. A **select all filtered** button appears when a filter is active, letting you select exactly that subset in one click.

### 4 — Select destination fields

The sidebar shows all writable EXIF/metadata fields. All are ticked by default. Untick any you don't want written.

| Field | Used by |
|-------|---------|
| `DateTimeOriginal` | Most photo apps, Lightroom, Immich, Google Photos |
| `CreateDate` | Photos and videos broadly |
| `ModifyDate` | General modification timestamp |
| `MediaCreateDate` | QuickTime/MP4 video containers |
| `TrackCreateDate` | Individual tracks within video files |
| `TrackModifyDate` | Track-level modification time |

**Update filesystem date** writes `FileModifyDate` in addition, which affects what Windows Explorer shows in the "Date modified" column.

### 5 — Preview

Click **⊙ preview** to populate the After column without writing anything. The After column highlights in gold where the value will change, and stays dim where it won't. Unselected files show no After value.

### 6 — Apply

Click **▶ apply changes**. The status bar shows exactly how many files were processed and reports any errors inline. ExifTool creates a `BACKUPS/` folder in each affected directory containing original copies of every file it touched.

### 7 — Undo and cleanup

**↩ undo last** restores the last batch of files from the BACKUPS folder. It copies the backup back over the modified file. Undo covers the most recent apply only.

**🗑 clean backups** permanently deletes the BACKUPS folder(s) for all directories containing currently loaded files. Do this once you're happy with the results.

---

## What ExifTool cannot change

**Windows "Date created"** (`FileCreateDate`) is a filesystem property set by the OS, not an EXIF field. ExifTool cannot modify it via normal file APIs on Windows. To update it you need a PowerShell command:

```powershell
(Get-Item "C:\path\to\file.jpg").CreationTime = "2024-05-01 14:32:00"
```

"Date modified" (`FileModifyDate`) and "Date taken" (`DateTimeOriginal`) are writable by ExifTool normally and handled by MetaFix.

---

## File safety

MetaFix never modifies pixel data, video codec data, audio, or compression. It only rewrites metadata headers. The BACKUPS folder gives you a full byte-for-byte copy of every file before it was touched.

---

## Project structure

```text
MetaFix/
├── MetaFix.py                 Desktop entry point (used by MetaFix.bat)
├── metafix/
│   ├── __init__.py            Flask application factory
│   ├── desktop.py             Window, server lifecycle, native drag-and-drop
│   ├── routes.py              HTTP endpoints and native file dialogs
│   ├── config.py              Configuration and shared session state
│   ├── fields.py              Supported formats and metadata fields
│   ├── dates.py               Date calculations and Windows timestamps
│   ├── metadata.py            Metadata reading and source selection
│   ├── exiftool.py            ExifTool subprocess wrapper
│   ├── ffmpeg.py              AVI metadata reading and remuxing
│   ├── operations.py          Preview, apply, undo, and cleanup workflows
│   ├── backups.py             Backup paths and sidecar placement
│   ├── files.py               Loaded-file collection and renaming
│   ├── templates/index.html   Interface markup
│   └── static/
        ├── css/app.css        Interface styles
        └── js/app.js          Interface logic
├── docs/assets/banner.svg     README banner
├── requirements.txt
└── README.md
```

The interface calls Flask routes, which delegate batch work to `operations.py`.
Metadata adapters run ExifTool or FFmpeg; native window integration lives in
`desktop.py`. Flask resolves templates and static assets relative to the package.

`data/config.json` is stored relative to the app directory, independently of the
working directory. In a packaged build, it lives beside the executable in `data/`.
The directory is created automatically when settings are saved and is ignored by Git.
Loaded files and the last batch remain in memory.

Ignored `Meta/`, `venv/`, and `MetaFix.bat` are maintained separately and were left
unchanged during restructuring.

---

## Tech stack

| Component | Library |
|-----------|---------|
| GUI shell | [pywebview](https://pywebview.flowrl.com/) (Qt backend) |
| Web server | [Flask](https://flask.palletsprojects.com/) |
| Metadata | [ExifTool](https://exiftool.org/) (subprocess) |
| Date maths | [python-dateutil](https://dateutil.readthedocs.io/) |
| Packaging | [PyInstaller](https://pyinstaller.org/) |
| UI fonts | Inter + IBM Plex Mono |

---

## Dependencies

```
flask
pywebview[qt]
python-dateutil
```

Install with:

```bash
pip install -r requirements.txt
```

