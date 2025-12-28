#!/usr/bin/env python3
"""
Generate boundary catalog JSON from the output folder structure.

Scans the misc folder and generates a JSON catalog with download links,
metadata, and OSM relation information for each boundary.
"""

import os
import json
import re
from pathlib import Path
from typing import List, Dict, Optional


def parse_folder_name(folder_name: str) -> Optional[Dict[str, str]]:
    """
    Parse folder name to extract relation ID and name.

    Expected format: relation_<id>_<name>
    Example: relation_50046_denmark

    Returns dict with 'relation_id' and 'name' or None if parse fails
    """
    match = re.match(r'relation_(\d+)_(.+)', folder_name)
    if match:
        return {
            'relation_id': match.group(1),
            'name': match.group(2).replace('_', ' ').title()
        }
    return None


def get_country_name_from_iso(iso_code: str) -> str:
    """
    Map ISO codes to country names.
    This is a basic mapping - extend as needed.
    """
    country_map = {
        'DE': 'Germany',
        'FR': 'France',
        'US': 'United States of America',
        'GB': 'United Kingdom',
        'JP': 'Japan',
        'CA': 'Canada',
        'AU': 'Australia',
        'BR': 'Brazil',
        'IN': 'India',
        'ES': 'Spain',
        'IT': 'Italy',
        'DK': 'Denmark',
        'AT': 'Austria',
        'CH': 'Switzerland',
        'LU': 'Luxembourg',
    }
    return country_map.get(iso_code, iso_code)


def scan_output_folder(base_path: str = "misc") -> List[Dict]:
    """
    Scan the output folder and generate boundary catalog entries.

    Folder structure expected:
    misc/
      <ISO_CODE>/
        <admin_level>/
          relation_<id>_<name>/
            relation_<id>_<name>.geojson.zip
            relation_<id>_<name>.shp.zip
            relation_<id>_<name>_land.geojson.zip  (optional)
            relation_<id>_<name>_land.shp.zip      (optional)
    """
    catalog = []
    base_path = Path(base_path)

    if not base_path.exists():
        print(f"Warning: {base_path} does not exist")
        return catalog

    # Iterate through ISO code folders
    for iso_folder in sorted(base_path.iterdir()):
        if not iso_folder.is_dir():
            continue

        iso_code = iso_folder.name
        parent_country = get_country_name_from_iso(iso_code)

        # Iterate through admin level folders
        for admin_level_folder in sorted(iso_folder.iterdir()):
            if not admin_level_folder.is_dir():
                continue

            try:
                admin_level = int(admin_level_folder.name)
            except ValueError:
                continue

            # Iterate through relation folders
            for relation_folder in sorted(admin_level_folder.iterdir()):
                if not relation_folder.is_dir():
                    continue

                parsed = parse_folder_name(relation_folder.name)
                if not parsed:
                    continue

                relation_id = parsed['relation_id']
                name = parsed['name']

                # Check for maritime and land variants
                base_name = relation_folder.name
                has_geojson = (relation_folder / f"{base_name}.geojson.zip").exists()
                has_shp = (relation_folder / f"{base_name}.shp.zip").exists()
                has_land_geojson = (relation_folder / f"{base_name}_land.geojson.zip").exists()
                has_land_shp = (relation_folder / f"{base_name}_land.shp.zip").exists()

                # URLs mirror the exact directory structure
                # e.g., LU/6/relation_123_folder/relation_123_folder.geojson.zip

                # Generate maritime entry if files exist
                if has_geojson or has_shp:
                    catalog.append({
                        "parent": parent_country,
                        "iso_code": iso_code,
                        "admin_level": admin_level,
                        "geojson_dl_link": f"https://files.99boundaries.com/{iso_code}/{admin_level}/{base_name}/{base_name}.geojson.zip",
                        "shp_dl_link": f"https://files.99boundaries.com/{iso_code}/{admin_level}/{base_name}/{base_name}.shp.zip",
                        "name": name,
                        "osm_relation_link_id": f"https://www.openstreetmap.org/relation/{relation_id}",
                        "polygon_type": "maritime"
                    })

                # Generate land entry if land files exist
                if has_land_geojson or has_land_shp:
                    catalog.append({
                        "parent": parent_country,
                        "iso_code": iso_code,
                        "admin_level": admin_level,
                        "geojson_dl_link": f"https://files.99boundaries.com/{iso_code}/{admin_level}/{base_name}/{base_name}_land.geojson.zip",
                        "shp_dl_link": f"https://files.99boundaries.com/{iso_code}/{admin_level}/{base_name}/{base_name}_land.shp.zip",
                        "name": name,
                        "osm_relation_link_id": f"https://www.openstreetmap.org/relation/{relation_id}",
                        "polygon_type": "land"
                    })

    return catalog


def main():
    """Main function to generate and save the catalog."""
    # Generate catalog
    catalog = scan_output_folder("misc")

    # Save to JSON file
    output_file = "boundary_catalog.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=4, ensure_ascii=False)

    print(f"Generated catalog with {len(catalog)} entries")
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    main()
