#!/usr/bin/env python3
"""
CryoEM_Collector.py — Metadata collector for cryosparc_projs
=============================================================
Recorre ~/cryosparc_projs (o el path dado con --base) y encuentra todas
las colecciones cryo-EM excluyendo CS-edwin. Extrae pixel size, voltaje,
magnificacion, dosis, defocus, fracciones, fechas de inicio/fin, etc.

Funciona automáticamente con colecciones nuevas colocadas en la base.

Uso:
    python3 CryoEM_Collector.py
    python3 CryoEM_Collector.py --base /ruta/a/cryosparc_projs
    python3 CryoEM_Collector.py --format json
    python3 CryoEM_Collector.py -o reporte.txt
"""
import re
import json
import argparse
from datetime import datetime
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def find_first(pattern, text, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def fmt_px(px_str):
    if not px_str: return ""
    try: return f"{float(px_str) * 1e10:.5f} Å"
    except: return ""


def fmt_kv(kv, unit=""):
    if kv is None or kv == "N/A": return "N/A"
    try: return f"{float(kv):.2f} {unit}".strip()
    except: return str(kv)

def fmt_date_short(dt_str):
    if not dt_str or dt_str == "N/A": return "N/A"
    try:
        dt = datetime.fromisoformat(dt_str).strftime("%Y-%m-%d %H:%M")
        return dt
    except:
        return dt_str[:16] if len(dt_str) >= 16 else dt_str

# ── data extraction from XMLs ───────────────────────────────────────────────

def extract_custom_data(xml_content):
    """Extract key-value pairs from CustomData (MicroscopeImage format)."""
    data = {}
    for m in re.finditer(
        r'<a:Key>([^<]+)</a:Key>\s*<a:Value[^>]*>([^<]+)<',
        xml_content, re.DOTALL
    ):
        data[m.group(1)] = m.group(2)
    return data


def parse_foilhole_xml(xml_path):
    """Extract all metadata from a FoilHole XML (movie/optics, non-Fractions)."""
    try:
        content = xml_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    info = {}

    # Pixel size
    px = find_first(r"<pixelSize>.*?<numericValue>([0-9.eE+-]+)<", content, re.DOTALL)
    if px: info["pixel_size_m"] = px

    # Voltage and magnification
    vl = find_first(r"<AccelerationVoltage[^>]*>([0-9]+)<", content, re.IGNORECASE)
    if vl: info["voltage_v"] = vl

    mg = find_first(r"<NominalMagnification>([0-9]+)<", content, re.IGNORECASE)
    if mg: info["magnification"] = mg

    # Custom data: defocus, dose, exposure time
    custom = extract_custom_data(content)
    df = custom.get("AppliedDefocus")
    if df:
        try: info["defocus_um"] = round(float(df) * 1e6, 2)
        except: pass

    dose = custom.get("DoseOnCamera") or custom.get("Detectors[BM-Falcon].TotalDose")
    if dose:
        try: info["dose_on_camera_e_A2"] = round(float(dose), 2)
        except: pass

    dr = custom.get("Detectors[BM-Falcon].DoseRate") or custom.get("DoseRate")
    if dr:
        try: info["dose_rate_setpoint_e_A2_s"] = round(float(dr), 2)
        except: pass

    exp = custom.get("Detectors[BM-Falcon].ExposureTime") or find_first(
        r"<ExposureTime>([0-9.]+)<", content)
    if exp:
        try: info["exposure_time_s"] = round(float(exp), 3)
        except: pass

    # Detector name
    det = custom.get("DetectorCommercialName")
    if det: info["detector"] = det

    # Acquisition datetime
    acq = find_first(r"acquisitionDateTime>([^<]+)<", content)
    if acq: info["acq_datetime"] = acq

    # Number of fractions (modern EPU 3.15+: FractionationSettings)
    nfr = find_first(r"(?:<b:)?NumberOffractions>([0-9]+)<", content)
    if nfr: info["num_fractions"] = int(nfr)

    return info


def parse_fractions_xml(xml_path):
    """Extract fractions-related metadata from _Fractions.xml."""
    try:
        content = xml_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    info = {}

    ef = find_first(r"<ExpectedNumberOfFractions>(\d+)<", content)
    if ef: info["expected_fractions"] = int(ef)

    rf = find_first(r"<RecordedNumberOfFractions>(\d+)<", content)
    if rf: info["recorded_fractions"] = int(rf)

    det = find_first(r"<CommercialName>([^<]+)<", content)
    if det: info["detector"] = det
    else:
        det = find_first(r"<Detector>([^<]+)<", content)
        if det: info["detector"] = det

    ec = find_first(r"<ElectronCounting>([^<]+)<", content)
    if ec: info["electron_counting"] = ec

    et = find_first(r"<ExposureTime>([0-9.]+)<", content)
    if et:
        try: info["frac_exposure_time_s"] = round(float(et), 3)
        except: pass

    dt = find_first(r"<DateTimeWithTimeZone>([^<]+)<", content)
    if dt: info["frac_datetime"] = dt

    # Sensor pixel size (specimen-level, calibrated) — fallback pixel source
    sps = find_first(r"<SensorPixelSize>\s*<Width>([0-9.eE+-]+)</Width>", content)
    if sps:
        try: info["sensor_pixel_size_m"] = float(sps)
        except: pass

    # Per-fraction dose statistics (only <SampleType>DoseFraction</SampleType> blocks)
    doses, rates, exposures = [], [], []
    for blk in re.findall(r"<Fraction>(.*?)</Fraction>", content, re.DOTALL):
        st = find_first(r"<SampleType>([^<]+)</SampleType>", blk)
        if st and st.strip() != "DoseFraction":
            continue
        td = find_first(r"<TotalDose>([0-9.eE+-]+)<", blk)
        dr = find_first(r"<DoseRate>([0-9.eE+-]+)<", blk)
        ex = find_first(r"<ExposureTime>([0-9.eE+-]+)<", blk)
        try:
            if td is not None: doses.append(float(td))
            if dr is not None: rates.append(float(dr))
            if ex is not None: exposures.append(float(ex))
        except: pass

    if doses:
        info["n_dose_fractions"] = len(doses)
        info["total_dose_frac_sum_e_A2"] = round(sum(doses), 2)
        info["dose_per_fraction_e_A2"] = round(sum(doses) / len(doses), 3)
        info["fraction_dose_range_e_A2"] = [round(min(doses), 3), round(max(doses), 3)]
    if rates:
        info["avg_dose_rate_e_A2_s"] = round(sum(rates) / len(rates), 3)
    if exposures:
        info["frac_exposure_time_s"] = round(exposures[0], 3)
        info["total_exposure_s"] = round(sum(exposures), 2)

    return info


# ── metadata extraction per session ─────────────────────────────────────────

def extract_metadata(session_path):
    """Extract all metadata for a session (modern EPU or legacy)."""
    p = Path(session_path)
    meta = {}

    # ── Find FoilHole XMLs for pixel size, defocus, dose ───────────────────
    # Modern EPU: Images-Disc*/GridSquare*/Data/FoilHole_*.xml (non-Fractions)
    # Legacy: FoilHole_*.xml in session root (non-Fractions)
    foilhole_xml = None
    for xml in sorted(p.glob("**/FoilHole_*.xml")):
        if "_Fractions" not in xml.name:
            foilhole_xml = xml
            break
    if not foilhole_xml:
        # Legacy: non-Fractions in root
        for xml in sorted(p.glob("FoilHole_*.xml")):
            if "_Fractions" not in xml.name:
                foilhole_xml = xml
                break

    if foilhole_xml:
        meta.update(parse_foilhole_xml(foilhole_xml))

    # ── Find Fractions XML for fractions count, detector, datetime ─────────
    frac_xml = None
    for xml in sorted(p.glob("**/*_Fractions.xml")):
        frac_xml = xml
        break
    if frac_xml:
        meta.update(parse_fractions_xml(frac_xml))

    # ── Resolve pixel size: main XML first, else SensorPixelSize ────────────
    if not meta.get("pixel_size_m") and meta.get("sensor_pixel_size_m"):
        meta["pixel_size_m"] = meta["sensor_pixel_size_m"]
        meta["pixel_size_source"] = "SensorPixelSize"

    # ── Resolve dose: sum of fraction TotalDose preferred; DoseOnCamera as
    #    fallback and as an independent reference value ─────────────────────
    if "total_dose_frac_sum_e_A2" in meta:
        meta["total_dose_e_A2"] = meta["total_dose_frac_sum_e_A2"]
        meta["dose_source"] = f"sum of {meta.get('n_dose_fractions', '?')} fractions"
    elif "dose_on_camera_e_A2" in meta:
        meta["total_dose_e_A2"] = meta["dose_on_camera_e_A2"]
        meta["dose_source"] = "DoseOnCamera (movie XML)"
    if "avg_dose_rate_e_A2_s" in meta:
        meta["dose_rate_e_A2_s"] = meta["avg_dose_rate_e_A2_s"]

# ── Session start date + defocus range from EpuSession.dm ─────────────
    dm_file = p / "EpuSession.dm"
    if dm_file.exists():
        try:
            dm = dm_file.read_text(encoding="utf-8", errors="replace")
            sd = find_first(r"<StartDateTime>([^<]+)<", dm)
            if sd: meta["session_start"] = sd
            name = find_first(r"<Name[^>]*>([^<]+)<", dm)
            if name: meta["session_name"] = name

            # Extract defocus range from Defocus blocks in DM
            dc_vals = []
            for m in re.finditer(r"<Defocus[^>]*>(.*?)</Defocus>", dm):
                doubles = re.findall(r"<a:double>([^<]+)</a:double>", m.group(1))
                dc_vals.extend([float(d) for d in doubles])
            if dc_vals:
                meta["defocus_range_um"] = (
                    round(min(dc_vals) * 1e6, 2),
                    round(max(dc_vals) * 1e6, 2),
                )
                meta["defocus_values_um"] = sorted(
                    set(round(v * 1e6, 2) for v in dc_vals)
                )
        except: pass

    # ── Legacy: scan FoilHole XMLs for actual defocus range ────────────────
    if "defocus_range_um" not in meta:
        dvals = set()
        for xml in (list(p.glob("FoilHole_*.xml")) or list(p.glob("**/FoilHole_*.xml")))[:50]:
            if "_Fractions" in xml.name:
                continue
            try:
                c = xml.read_text(encoding="utf-8", errors="replace")
                df = find_first(r"<a:Key>AppliedDefocus</a:Key>\s*<a:Value[^>]*>([^<]+)<", c)
                if df:
                    dvals.add(round(float(df) * 1e6, 2))
            except: pass
        if dvals:
            meta["defocus_values_um"] = sorted(dvals)
            meta["defocus_range_um"] = (min(dvals), max(dvals))

    # ── Collection start/end dates from FoilHole XMLs ──────────────────────
    # Use filename timestamp pattern (YYYYMMDD_HHMMSS) for sorting, then
    # parse the actual datetime from XML content of first/last files
    all_fhs = [
        f for f in p.glob("**/FoilHole_*.xml")
        if "_Fractions" not in f.name
    ]
    if not all_fhs:
        all_fhs = [
            f for f in p.glob("FoilHole_*.xml")
            if "_Fractions" not in f.name
        ]

    if all_fhs:
        # Sort by timestamp extracted from filename (faster than reading all)
        def fname_ts(f):
            m = re.search(r"_(\d{8})_(\d{6})\.", f.name)
            return m.group(1) + m.group(2) if m else f.name

        all_fhs.sort(key=fname_ts)

        # Sample first 5 and last 5 for date range (robust + fast)
        sample = all_fhs[:5] + all_fhs[-5:]
        dates = []
        for fh in sample:
            try:
                c = fh.read_text(encoding="utf-8", errors="replace")
                d = find_first(r"acquisitionDateTime>([^<]+)<", c)
                if d: dates.append(d)
            except: pass

        if dates:
            # ISO format strings sort correctly
            meta["first_acq"] = min(dates)
            meta["last_acq"] = max(dates)

    # Legacy: get dates from Fractions XMLs if no acquisition datetime
    if "first_acq" not in meta:
        all_ffs = sorted(p.glob("*_Fractions.xml"))
        if not all_ffs:
            all_ffs = sorted(p.glob("**/*_Fractions.xml"))
        if all_ffs:
            ff_dates = []
            for ff in all_ffs[:5] + all_ffs[-5:]:
                try:
                    c = ff.read_text(encoding="utf-8", errors="replace")
                    d = find_first(r"<DateTimeWithTimeZone>([^<]+)<", c)
                    if d: ff_dates.append(d)
                except: pass
            if ff_dates:
                meta["first_acq"] = min(ff_dates)
                meta["last_acq"] = max(ff_dates)

    return meta


# ── discovery ───────────────────────────────────────────────────────────────

def discover_collections(base):
    """Find all cryo-EM collections, excluding CS-edwin. Auto-detects new."""
    collections = []

    # Modern EPU: has EpuSession.dm
    for dm in base.glob("**/EpuSession.dm"):
        if "CS-edwin" in str(dm):
            continue
        d = dm.parent
        gs = sum(1 for disc in d.glob("Images-Disc*") for sd in disc.iterdir()
                 if sd.is_dir() and sd.name.startswith("GridSquare"))
        fh = len([f for f in d.glob("**/FoilHole_*.xml") if "_Fractions" not in f.name])
        fx = len(list(d.glob("**/*_Fractions.xml")))
        collections.append({
            "path": str(d),
            "rel_path": str(d.relative_to(base)),
            "type": "modern_epu",
            "grid_squares": gs,
            "foil_holes": fh,
            "fractions_xml": fx,
        })

    # Legacy: flat *_Fractions.xml in session root (no EpuSession.dm)
    # Check top-level dirs
    for p in sorted(base.iterdir()):
        if not p.is_dir() or p.name == "CS-edwin":
            continue
        has_dm = (p / "EpuSession.dm").exists()
        if has_dm:
            continue
        fx = len(list(p.glob("*_Fractions.xml")))
        if fx > 0:
            collections.append({
                "path": str(p),
                "rel_path": str(p.relative_to(base)),
                "type": "legacy",
                "grid_squares": 0,
                "foil_holes": 0,
                "fractions_xml": fx,
            })

    # Check PAD4/ subdir
    pad4 = base / "PAD4"
    if pad4.is_dir():
        for p in sorted(pad4.iterdir()):
            if not p.is_dir():
                continue
            has_dm = (p / "EpuSession.dm").exists()
            if has_dm:
                continue
            fx = len(list(p.glob("*_Fractions.xml")))
            if fx > 0:
                # Avoid duplicates
                rel = str(p.relative_to(base))
                if not any(c["rel_path"] == rel for c in collections):
                    collections.append({
                        "path": str(p),
                        "rel_path": rel,
                        "type": "legacy",
                        "grid_squares": 0,
                        "foil_holes": 0,
                        "fractions_xml": fx,
                    })

    return collections


# ── report generation ───────────────────────────────────────────────────────

def generate_report(base, fmt="text"):
    base = Path(base).expanduser().resolve()
    collections = discover_collections(base)

    # Extract metadata for each
    for c in collections:
        c["meta"] = extract_metadata(c["path"])

    if fmt == "json":
        return _json_report(base, collections)
    return _text_report(base, collections)


def _text_report(base, collections):
    lines = []
    div = "=" * 120
    lines += [div,
              "  Cryo-EM COLLECTIONS REPORT — cryosparc_projs (excl. CS-edwin)",
              f"  Base: {base}",
              f"  Generated: {datetime.now().isoformat()}",
              div, ""]

    # Summary table
    hdr = (f"{'#':<3} {'Collection':<58} {'Type':<7} {'Movies':<7} {'GS':<5} "
           f"{'Pixel':<11} {'Detector':<14} {'kV':<4} {'Fracs':<6} {'Defocus':<9} "
           f"{'Dose':<12} {'StartDate':<12} {'EndDate':<12}")
    lines.append(hdr)
    lines.append("-" * 120)

    for i, c in enumerate(collections, 1):
        m = c["meta"]
        px = fmt_px(m.get("pixel_size_m", ""))
        volt = f"{int(m['voltage_v'])/1000:.0f}" if m.get("voltage_v") else "-"
        det = m.get("detector", "N/A") or "N/A"
        movies = c["fractions_xml"] if c["fractions_xml"] > 0 else c["foil_holes"]
        gs = str(c["grid_squares"]) if c["grid_squares"] > 0 else "-"
        fracs = m.get("recorded_fractions") or m.get("num_fractions")
        fracs_str = str(fracs) if fracs is not None else "-"
        if m.get("defocus_range_um"):
            dmn, dmx = m["defocus_range_um"]
            defocus = f"{dmn:.1f} to {dmx:.1f} µm" if dmn != dmx else f"{dmn:.1f} µm"
        elif m.get("defocus_um"):
            defocus = f"{m['defocus_um']} µm"
        else:
            defocus = "N/A"
        dose = f"{m.get('total_dose_e_A2', 'N/A')}" if "total_dose_e_A2" in m else "N/A"
        if m.get("total_dose_e_A2"): dose = f"{m['total_dose_e_A2']} e/Å²"
        start = fmt_date_short(m.get("session_start") or m.get("first_acq", ""))[:16]
        end = fmt_date_short(m.get("last_acq", ""))[:16]
        lines.append(
            f"{i:<3} {c['rel_path']:<58} {c['type'][:7]:<7} {str(movies):<7} {gs:<5} "
            f"{px:<11} {det:<14} {volt:<4} {fracs_str:<6} {defocus:<9} {dose:<12} "
            f"{start:<12} {end:<12}"
        )

    # Details
    lines += ["", div, "", "DETAILS:", ""]

    for i, c in enumerate(collections, 1):
        m = c["meta"]
        lines.append(f"[{i}] {c['rel_path']}")
        lines.append(f"     Type: {'Modern EPU' if c['type'] == 'modern_epu' else 'Legacy (flat XMLs)'}")
        lines.append(f"     GridSquares: {c['grid_squares'] if c['grid_squares'] > 0 else '-'} | "
                     f"FoilHoles: {c['foil_holes']} | Fractions XML: {c['fractions_xml']}")

        px = fmt_px(m.get("pixel_size_m", ""))
        if px:
            src = " (SensorPixelSize)" if m.get("pixel_size_source") == "SensorPixelSize" else ""
            lines.append(f"     Pixel size: {px}{src}")
        if m.get("magnification"): lines.append(f"     Magnification: {m['magnification']}x")
        if m.get("voltage_v"): lines.append(f"     Voltage: {int(m['voltage_v'])/1000:.0f} kV")
        if m.get("detector"): lines.append(f"     Detector: {m['detector']}")
        if m.get("electron_counting"): lines.append(f"     Electron counting: {m['electron_counting']}")

        fracs = m.get("recorded_fractions", m.get("num_fractions"))
        if fracs: lines.append(f"     Fractions/movie: {fracs}")
        if m.get("defocus_range_um"):
            dmn, dmx = m["defocus_range_um"]
            dr_str = f"{dmn:.1f} to {dmx:.1f} µm" if dmn != dmx else f"{dmn:.1f} µm"
            lines.append(f"     Defocus range: {dr_str}")
            if m.get("defocus_values_um") and len(m["defocus_values_um"]) > 1:
                lines.append(f"     Defocus values: {m['defocus_values_um']} µm")
        elif m.get("defocus_um"):
            lines.append(f"     Applied defocus: {m['defocus_um']} µm")
        if m.get("total_dose_e_A2"):
            src = m.get("dose_source")
            lines.append(f"     Total dose: {m['total_dose_e_A2']} e⁻/Å²" + (f" ({src})" if src else ""))
        if m.get("dose_per_fraction_e_A2") and m.get("fraction_dose_range_e_A2"):
            dmin, dmax = m["fraction_dose_range_e_A2"]
            rng = f", range {dmin} – {dmax}" if dmin != dmax else ""
            lines.append(f"     Dose per fraction: avg {m['dose_per_fraction_e_A2']}{rng} e⁻/Å²")
        if m.get("dose_rate_e_A2_s"):
            rate_src = "avg over fractions" if "avg_dose_rate_e_A2_s" in m else "movie XML"
            lines.append(f"     Dose rate: {m['dose_rate_e_A2_s']} e⁻/Å²/s ({rate_src})")
        if m.get("dose_on_camera_e_A2") and m.get("dose_on_camera_e_A2") != m.get("total_dose_e_A2"):
            lines.append(f"     DoseOnCamera (ref): {m['dose_on_camera_e_A2']} e⁻/Å²")
        if m.get("frac_exposure_time_s"): lines.append(f"     Exposure per fraction: {m['frac_exposure_time_s']} s")
        if m.get("total_exposure_s"): lines.append(f"     Total exposure: {m['total_exposure_s']} s")
        elif m.get("exposure_time_s"): lines.append(f"     Exposure time: {m['exposure_time_s']} s")

        if m.get("session_start"):
            lines.append(f"     Session start: {fmt_date_short(m['session_start'])}")
        if m.get("first_acq"):
            lines.append(f"     First movie: {fmt_date_short(m['first_acq'])}")
        if m.get("last_acq"):
            lines.append(f"     Last movie: {fmt_date_short(m['last_acq'])}")

        lines.append("")

    lines += [div,
              f"  Total: {len(collections)} collections "
              f"({sum(1 for c in collections if c['type']=='modern_epu')} modern EPU + "
              f"{sum(1 for c in collections if c['type']=='legacy')} legacy)",
              div]
    return "\n".join(lines)


def _json_report(base, collections):
    js = []
    for c in collections:
        m = c["meta"]
        js.append({
            "name": Path(c["path"]).name,
            "rel_path": c["rel_path"],
            "type": c["type"],
            "grid_squares": c["grid_squares"],
            "foil_holes": c["foil_holes"],
            "fractions_xml": c["fractions_xml"],
            "pixel_size_A": round(float(m.get("pixel_size_m", 0)) * 1e10, 5) if m.get("pixel_size_m") else None,
            "pixel_size_source": m.get("pixel_size_source"),
            "voltage_kV": int(m["voltage_v"]) / 1000 if m.get("voltage_v") else None,
            "magnification": int(m["magnification"]) if m.get("magnification") else None,
            "detector": m.get("detector"),
            "electron_counting": m.get("electron_counting"),
            "fractions_per_movie": m.get("recorded_fractions", m.get("num_fractions")),
            "defocus_um": m.get("defocus_um"),
            "defocus_range_um": m.get("defocus_range_um"),
            "defocus_values_um": m.get("defocus_values_um"),
            "total_dose_e_A2": m.get("total_dose_e_A2"),
            "dose_source": m.get("dose_source"),
            "dose_on_camera_e_A2": m.get("dose_on_camera_e_A2"),
            "dose_per_fraction_e_A2": m.get("dose_per_fraction_e_A2"),
            "fraction_dose_range_e_A2": m.get("fraction_dose_range_e_A2"),
            "n_dose_fractions": m.get("n_dose_fractions"),
            "dose_rate_e_A2_s": m.get("dose_rate_e_A2_s"),
            "exposure_time_s": m.get("exposure_time_s"),
            "total_exposure_s": m.get("total_exposure_s"),
            "session_start": m.get("session_start"),
            "first_acq": m.get("first_acq"),
            "last_acq": m.get("last_acq"),
        })
    return json.dumps(js, indent=2, ensure_ascii=False)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Collects cryo-EM metadata from cryosparc_projs (excl. CS-edwin)"
    )
    parser.add_argument("--base", "-b", default="~/cryosparc_projs",
                        help="Base directory (default: ~/cryosparc_projs)")
    parser.add_argument("--format", "-f", choices=["json", "text"], default="text",
                        help="Output format (default: text)")
    parser.add_argument("--output", "-o", help="Write output to file")
    args = parser.parse_args()

    result = generate_report(args.base, args.format)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"[INFO] Saved: {args.output}")
    else:
        print(result)


if __name__ == "__main__":
    main()