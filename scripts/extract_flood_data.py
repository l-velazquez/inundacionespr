#!/usr/bin/env python3
"""
Extract and enrich Puerto Rico flood hazard GeoJSON data.

Adds computed fields to each feature:
  RISK_SCORE  - continuous 0-10 risk value
  RISK_NORM   - 0-1 normalized risk
  HAZARD_TIER - 1-5 categorical tier (for binning)
  IS_FLOODWAY - boolean floodway flag
  DEPTH_CLEAN - flood depth (None when not available)
  BFE_CLEAN   - base flood elevation (None when not available)

Usage:
  python3 scripts/extract_flood_data.py
"""

import json
import math
import statistics
from pathlib import Path

# Paths
ROOT = Path(__file__).parent.parent
INPUT_FILE  = ROOT / "data" / "puerto_rico_alto_riesgo_simplified.json"
OUTPUT_FILE = ROOT / "data" / "puerto_rico_alto_riesgo_enriched.json"

# Base risk score by flood zone
ZONE_BASE_SCORE = {
    "VE":  9.5,   # Coastal storm high hazard
    "AE":  7.5,   # 1% annual chance – detailed study
    "AO":  7.0,   # 1% annual chance – shallow overflow
    "AH":  6.5,   # 1% annual chance – shallow ponding
    "A":   6.0,   # 1% annual chance – approximate
    "A99": 4.5,   # 1% annual chance – protected
    "X":   1.5,   # Moderate / minimal (base; subtype adjusts)
    "D":   2.0,   # Future conditions undetermined
}

SUBTYPE_BONUS = {
    "FLOODWAY":                              2.0,
    "RIVERINE FLOODWAY SHOWN IN COASTAL ZONE": 1.5,
    "0.2 PCT ANNUAL CHANCE FLOOD HAZARD":    1.5,   # for X zones
    "AREA OF MINIMAL FLOOD HAZARD":         -0.5,
}

SENTINEL = -9999.0   # FEMA "not applicable" sentinel value


def clean_numeric(value):
    """Return None for sentinel / non-numeric, else float."""
    try:
        v = float(value)
        return None if v <= SENTINEL + 1 else v
    except (TypeError, ValueError):
        return None


def compute_risk_score(props):
    """Compute a 0-10 risk score from all available fields."""
    zone    = (props.get("FLD_ZONE") or "").strip().upper()
    subtype = (props.get("ZONE_SUBTY") or "").strip().upper()
    depth   = clean_numeric(props.get("DEPTH"))
    bfe     = clean_numeric(props.get("STATIC_BFE"))

    # Base score from zone type
    score = ZONE_BASE_SCORE.get(zone, 2.0)

    # Subtype modifier
    for key, bonus in SUBTYPE_BONUS.items():
        if key in subtype:
            score += bonus
            break

    # Depth bonus: 0–2 pts from actual flood depth
    if depth is not None and depth > 0:
        score += min(depth * 0.4, 2.0)

    # BFE bonus: areas with documented high elevation flood surfaces
    if bfe is not None and bfe > 0:
        score += min(bfe * 0.02, 0.5)

    return round(min(max(score, 0.0), 10.0), 3)


def hazard_tier(score):
    """Map 0-10 score → 1-5 categorical tier."""
    if score >= 8.5:   return 5   # Extreme (VE / Floodway)
    if score >= 6.5:   return 4   # High
    if score >= 4.5:   return 3   # Elevated
    if score >= 2.5:   return 2   # Moderate
    return 1                       # Low / minimal


def enrich_feature(feature):
    """Add computed fields to a single GeoJSON feature."""
    props = feature.get("properties", {})

    zone    = (props.get("FLD_ZONE") or "").strip().upper()
    subtype = (props.get("ZONE_SUBTY") or "").strip().upper()
    depth   = clean_numeric(props.get("DEPTH"))
    bfe     = clean_numeric(props.get("STATIC_BFE"))

    score = compute_risk_score(props)

    props["RISK_SCORE"]  = score
    props["HAZARD_TIER"] = hazard_tier(score)
    props["IS_FLOODWAY"] = "FLOODWAY" in subtype
    props["DEPTH_CLEAN"] = depth
    props["BFE_CLEAN"]   = bfe

    feature["properties"] = props
    return feature


def print_stats(features):
    """Print a summary of all extracted fields."""
    scores  = [f["properties"]["RISK_SCORE"]  for f in features]
    tiers   = [f["properties"]["HAZARD_TIER"] for f in features]
    depths  = [f["properties"]["DEPTH_CLEAN"] for f in features if f["properties"]["DEPTH_CLEAN"] is not None]
    bfes    = [f["properties"]["BFE_CLEAN"]   for f in features if f["properties"]["BFE_CLEAN"]   is not None]

    zones   = {}
    subtypes = {}
    for f in features:
        z = f["properties"].get("FLD_ZONE", "?")
        s = f["properties"].get("ZONE_SUBTY") or "(none)"
        zones[z]    = zones.get(z, 0) + 1
        subtypes[s] = subtypes.get(s, 0) + 1

    print("\n" + "="*55)
    print("  Puerto Rico Flood Hazard — Enrichment Summary")
    print("="*55)

    print(f"\nFeatures processed : {len(features):,}")
    print(f"Floodway zones     : {sum(1 for f in features if f['properties']['IS_FLOODWAY']):,}")
    print(f"With depth data    : {len(depths):,}")
    print(f"With BFE data      : {len(bfes):,}")

    print("\n--- FLD_ZONE breakdown ---")
    for z, count in sorted(zones.items(), key=lambda x: -x[1]):
        print(f"  {z:<8} {count:>6,}")

    print("\n--- ZONE_SUBTY breakdown ---")
    for s, count in sorted(subtypes.items(), key=lambda x: -x[1]):
        print(f"  {s[:45]:<45} {count:>6,}")

    print(f"\n--- RISK_SCORE (0–10) ---")
    print(f"  min    {min(scores):.2f}")
    print(f"  max    {max(scores):.2f}")
    print(f"  mean   {statistics.mean(scores):.2f}")
    print(f"  median {statistics.median(scores):.2f}")

    print(f"\n--- HAZARD_TIER distribution ---")
    for t in range(1, 6):
        count = tiers.count(t)
        bar = "█" * (count // 20)
        print(f"  Tier {t}  {count:>6,}  {bar}")

    if depths:
        print(f"\n--- DEPTH_CLEAN (feet, n={len(depths)}) ---")
        print(f"  min {min(depths):.2f}  max {max(depths):.2f}  mean {statistics.mean(depths):.2f}")

    if bfes:
        print(f"\n--- BFE_CLEAN (feet, n={len(bfes)}) ---")
        print(f"  min {min(bfes):.2f}  max {max(bfes):.2f}  mean {statistics.mean(bfes):.2f}")

    print()


def main():
    print(f"Reading  {INPUT_FILE} …")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    features = geojson.get("features", [])
    print(f"Loaded {len(features):,} features.")

    enriched = [enrich_feature(feat) for feat in features]
    geojson["features"] = enriched

    print_stats(enriched)

    print(f"Writing  {OUTPUT_FILE} …")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(geojson, f, separators=(",", ":"))

    size_mb = OUTPUT_FILE.stat().st_size / 1_048_576
    print(f"Done. Output: {OUTPUT_FILE.name}  ({size_mb:.1f} MB)\n")


if __name__ == "__main__":
    main()
