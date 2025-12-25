# [99boundaries](https://99boundaries.com)

[![PyPI version](https://badge.fury.io/py/nintynine-boundaries.svg)](https://badge.fury.io/py/nintynine-boundaries)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<img width="920" alt="Indonesia Maritime and Land Boundaries" src="https://user-images.githubusercontent.com/10322094/169665541-701d6de6-7bf9-4e8b-b098-c5a17206eb0b.png">

A simple command line utility to generate administrative boundaries from [OpenStreetMap](http://openstreetmap.org) via [Overpass](http://overpass-api.de/) and [OSM Land Polygons](https://osmdata.openstreetmap.de/data/land-polygons.html).

## Features

- Generate maritime and land boundaries for any country
- Multiple output formats: GeoJSON, ESRI Shapefile, GeoPackage, CSV (WKT), MapInfo
- Batch processing for multiple countries at once
- Uses OpenStreetMap data via Overpass API
- High-quality land boundary generation with OSM land polygons

## Installation

### For Users

Install via pip:

```bash
pip install nintynine-boundaries
```

### For Development

Please make sure you have installed [poetry](https://python-poetry.org/docs/) locally. Then clone this repository and run `poetry install` from the root folder.

To activate the virtual environment:

```bash
eval $(poetry env activate)
```

### Prerequisites

- Python 3.10 or higher
- GDAL/GEOS libraries (installed automatically with geopandas on most systems)
- Optional: [OSM Land Polygons](https://osmdata.openstreetmap.de/data/land-polygons.html) for generating land boundaries
  - Download the [WGS84 split variant](https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip) (~600MB) for faster processing
  - Unzip to a local directory and reference with `--land_data_dir` flag 


## Usage & Examples

```sh
make_boundary --help
usage: make_boundary [-h] -a ALPHA2 [ALPHA2 ...] -f FORMATS [FORMATS ...] [-l ADMIN_LEVEL] [-d LAND_DATA_DIR]
                     [--debug] [--no-debug]

required arguments:
  -a ALPHA2 [ALPHA2 ...], --alpha2 ALPHA2 [ALPHA2 ...]
                        List of ISO-3166-1 alpha2 country codes, e.g. ES FR DE
  -f FORMATS [FORMATS ...], --formats FORMATS [FORMATS ...]
                        Output formats, one or multiple of shp, gpkg, csv, geojson, mapinfo

optional arguments:
  -l ADMIN_LEVEL, --admin_level ADMIN_LEVEL
                        OSM administrative level, currently only level 2 supported. Read more at
                        https://wiki.openstreetmap.org/wiki/Key:admin_level
  -d LAND_DATA_DIR, --land_data_dir LAND_DATA_DIR
                        Path to the OSM land data polygons folder, read more and download from
                        https://osmdata.openstreetmap.de/data/land-polygons.html
  --debug
  --no-debug
```

Depending on the selected country the processing time will vary. While the maritime boundaries will take a few seconds to be generated, the land boundaries will take longer due superior spatial detail. Land boundaries for countries with with greater coverage, e.g. the United States, Canada or France, can take up to 45 minutes to be generated and will require up to 8g of memory. The reasons are resource hungry geopandas overlay operations intersecting the maritime boundaries with the OSM land polygons dataset.

#### Generate the maritime boundary as GeoJSON for Australia:

`make_boundary --alpha2 AU --formats geojson`

#### Generate the maritime and land boundary as GeoJSON, GeoPackage and ESRI Shapefile for Spain:

`make_boundary --alpha2 ES --formats geojson shp gpkg --land_data_dir /path/to/land-polygons-split-4326`

#### Generate the maritime and land boundaries as CSV (geometry as WKT) for France and Canada:

`make_boundary --alpha2 FR CA --formats csv --land_data_dir /path/to/land-polygons-split-4326`

The file output formats can either be ESRI Shapefile, GeoJSON, CSV, GeoPackage or MapInfo and will be saved as archives into the `data` within this repository.

## Output

Generated files are saved as ZIP archives in the `data` folder with the naming pattern:

- `{country_code}_admin_level_{level}_maritime.{format}.zip` - Maritime boundaries only
- `{country_code}_admin_level_{level}_land.{format}.zip` - Land boundaries (if `--land_data_dir` is provided)

Each archive contains the boundary data in the requested format with attributes including country code, name, and administrative level.

## Known Limitations

- Currently only supports admin level 2 (country-level boundaries)
- Land boundary generation for countries with large territories (US, Canada, France, Russia) can take 30-45 minutes and require up to 8GB of memory
- Requires active internet connection to query Overpass API

## Troubleshooting

**Memory errors for large countries:**
- The land boundary intersection process is memory-intensive for countries with extensive coastlines
- Consider processing one country at a time
- Ensure you have at least 8GB of available RAM

**Missing GDAL/GEOS libraries:**
- On Ubuntu/Debian: `sudo apt-get install gdal-bin libgdal-dev libgeos-dev`
- On macOS: `brew install gdal geos`
- On Windows: Install via conda or use OSGeo4W

**Overpass API timeouts:**
- The Overpass API may be slow or timeout for very large queries
- Try again later or use the `--debug` flag to see detailed error messages

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request to the [GitHub repository](https://github.com/timmccauley/nintynine-boundaries).

## Future Work

The plan is to include further administrative levels for individual countries at a later stage.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
