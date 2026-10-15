# CryoEM Collector

Metadata collector for cryo-EM data acquisition directories. Automatically discovers and scans all cryo-EM collections under a base directory (default: `~/cryosparc_projs`), extracts key acquisition parameters from EPU XML/DM metadata, and generates structured reports in text or JSON format.

> **Originally migrated from [CEM_data_collection](https://github.com/josedwin19/CEM_data_collection) (archived).** This version has been rewritten to handle **multiple collections** with automatic discovery, supporting both modern EPU and legacy directory layouts.

---

## Key Features

- **Auto-discovery**: Scans a base directory and finds all cryo-EM collections automatically — no need to specify each session individually.
- **Dual layout support**:
  - **Modern EPU** (3.x+): directories with `EpuSession.dm`, `Images-Disc*/GridSquare*/Data/FoilHole_*.xml`
  - **Legacy**: flat `*_Fractions.xml` files in session root (no `EpuSession.dm`)
- **Exclusion filter**: Automatically skips `CS-edwin` project directories.
- **PAD4 support**: Detects collections inside `PAD4/` subdirectory.
- **Rich metadata extraction** per collection:
  - Pixel size (Å, 5 decimals) — from the movie XML, with `SensorPixelSize` from the Fractions XML as fallback
  - Acceleration voltage (kV), nominal magnification
  - Detector name, electron counting status
  - **Dose (validated)**: total dose computed as the **sum of per-fraction `TotalDose`** from the Fractions XML; `DoseOnCamera` from the movie XML is kept as an independent reference
  - Dose rate (e⁻/Å²/s, averaged over fractions), dose per fraction (avg + min/max range, useful QC for uneven fraction schemes)
  - Defocus range and individual defocus values (µm)
  - Fractions per movie (expected vs. recorded), exposure per fraction, total exposure (s)
  - Session start date, first/last acquisition timestamps
  - Grid square count, foil hole count, movie count
- **Two output formats**: human-readable text (with summary table + per-collection details) and machine-readable JSON.
- **No external dependencies**: Pure Python standard library (`re`, `json`, `argparse`, `datetime`, `pathlib`).

---

## Requirements

- **Python 3.8+**
- No third-party libraries required.

---

## Usage

### Default scan (text report to stdout)

```bash
python3 CryoEM_Collector.py
```

Scans `~/cryosparc_projs` and prints a text report.

### Custom base directory

```bash
python3 CryoEM_Collector.py --base /path/to/cryoem_data
```

### Save report to file

```bash
python3 CryoEM_Collector.py -o report.txt
```

### JSON output

```bash
python3 CryoEM_Collector.py --format json -o report.json
```

### All options

| Parameter | Shorthand | Description | Default |
|---|---|---|---|
| `--base` | `-b` | Base directory to scan for collections | `~/cryosparc_projs` |
| `--format` | `-f` | Output format: `text` or `json` | `text` |
| `--output` | `-o` | Write output to file instead of stdout | *(stdout)* |

```bash
python3 CryoEM_Collector.py --help
```

---

## Example Text Report

```
========================================================================================================================
  Cryo-EM COLLECTIONS REPORT — cryosparc_projs (excl. CS-edwin)
  Base: /home/user/cryosparc_projs
  Generated: 2026-07-30T16:14:00
========================================================================================================================

#   Collection                                             Type    Movies  GS    Pixel    Detector      kV   Fracs  Defocus   Dose        StartDate   EndDate
------------------------------------------------------------------------------------------------------------------------
1   ProjectA/session_2026_01                                modern  980     4     0.83 Å   Falcon 4i     300  40     -0.8 to -2.0 µm  45.20 e/Å²  2026-01-15  2026-01-15
2   ProjectB/PAD4/legacy_session                            legacy  320     -     0.89 Å   Falcon 4i     200  32     -1.0 to -2.5 µm  50.10 e/Å²  2025-12-10  2025-12-11

DETAILS:

[1] ProjectA/session_2026_01
     Type: Modern EPU
     GridSquares: 4 | FoilHoles: 1240 | Fractions XML: 980
     Pixel size: 0.87148 Å
     Magnification: 75000x
     Voltage: 300 kV
     Detector: Falcon 3EC
     Electron counting: On
     Fractions/movie: 40
     Defocus range: -0.8 to -2.0 µm
     Defocus values: [-2.0, -1.8, -1.5, -1.2, -1.0, -0.8] µm
     Total dose: 40.35 e⁻/Å² (sum of 40 fractions)
     Dose per fraction: avg 1.009, range 0.879 – 5.559 e⁻/Å²
     Dose rate: 0.993 e⁻/Å²/s (avg over fractions)
     DoseOnCamera (ref): 40.35 e⁻/Å²
     Exposure per fraction: 0.897 s
     Total exposure: 40.87 s
     Session start: 2026-01-15 09:12
     First movie: 2026-01-15 09:12:45
     Last movie: 2026-01-15 14:55:12

[2] ProjectB/PAD4/legacy_session
     ...

========================================================================================================================
  Total: 2 collections (1 modern EPU + 1 legacy)
========================================================================================================================
```

## Example JSON Output

```json
[
  {
    "name": "session_2026_01",
    "rel_path": "ProjectA/session_2026_01",
    "type": "modern_epu",
    "grid_squares": 4,
    "foil_holes": 1240,
    "fractions_xml": 980,
    "pixel_size_A": 0.87148,
    "pixel_size_source": null,
    "voltage_kV": 300.0,
    "magnification": 75000,
    "detector": "Falcon 3EC",
    "electron_counting": "On",
    "fractions_per_movie": 40,
    "defocus_um": -1.5,
    "defocus_range_um": [-2.0, -0.8],
    "defocus_values_um": [-2.0, -1.8, -1.5, -1.2, -1.0, -0.8],
    "total_dose_e_A2": 40.35,
    "dose_source": "sum of 40 fractions",
    "dose_on_camera_e_A2": 40.35,
    "dose_per_fraction_e_A2": 1.009,
    "fraction_dose_range_e_A2": [0.879, 5.559],
    "n_dose_fractions": 40,
    "dose_rate_e_A2_s": 0.993,
    "exposure_time_s": 42.195,
    "total_exposure_s": 40.87,
    "session_start": "2026-01-15T09:12:00",
    "first_acq": "2026-01-15T09:12:45",
    "last_acq": "2026-01-15T14:55:12"
  }
]
```

---

## How It Works

1. **Discovery**: Scans the base directory recursively for `EpuSession.dm` files (modern EPU) and top-level directories with `*_Fractions.xml` (legacy). Skips `CS-edwin`.
2. **Metadata extraction**: For each collection:
   - Reads `EpuSession.dm` for session name, start date, and defocus values.
   - Parses a sample `FoilHole_*.xml` (non-Fractions) for pixel size, voltage, magnification, detector, defocus, and `DoseOnCamera`.
   - Parses a `*_Fractions.xml` for fractions count, electron counting, detector name, `SensorPixelSize`, and **per-fraction dose data** (`TotalDose`, `DoseRate`, `ExposureTime` — only blocks with `SampleType = DoseFraction` are considered).
   - Samples first/last FoilHole files to determine acquisition date range.
3. **Dose calculation**:
   - `total_dose_e_A2` = **sum of all per-fraction `TotalDose`** values (preferred; cross-validated against `DoseOnCamera` from the movie XML, which is reported as an independent reference when it differs).
   - `dose_rate_e_A2_s` = average of per-fraction `DoseRate`.
   - `dose_per_fraction_e_A2` = mean fraction dose, with min–max range — useful to detect uneven fraction schemes (e.g., a longer final fraction).
   - `total_exposure_s` = sum of per-fraction exposure times.
   - If the Fractions XML has no dose data, `DoseOnCamera` is used as fallback and the `dose_source` field indicates it.
4. **Report generation**: Aggregates all collections into a summary table (text) or array of objects (JSON).

---

## License

MIT — see the [toolbox LICENSE](../../LICENSE).