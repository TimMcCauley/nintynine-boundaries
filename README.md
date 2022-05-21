# [99boundaries](https://99boundaries.com)

<img width="920" alt="Indonesia Maritime and Land Boundaries" src="https://user-images.githubusercontent.com/10322094/169665541-701d6de6-7bf9-4e8b-b098-c5a17206eb0b.png">

A simple command line utility to generate administrative boundaries from [OpenStreetMap](http://openstreetmap.org) via [Overpass](http://overpass-api.de/) and [OSM Land Polygons](https://osmdata.openstreetmap.de/data/land-polygons.html).

## Installation

Clone this repository and run `poetry install` from the root folder. In order to generate not only maritime but also land (coastal) boundaries, you will need to download land polygons derived from OpenStreetMap and generiously hosted [here](https://osmdata.openstreetmap.de/data/land-polygons.html). To decrease the computation time please download the [WGS84 split variant](https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip). 


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

The file output formats can either be ESRI Shapefile, GeoJSON, CSV, GeoPackage or MapInfo and will be saved as archives into the `data` folder residing in `path/to/nintynine-boundaries/nintynine_boundaries`.

## Future Work

The plan is to include further administrative levels for individual countries at a later stage.
