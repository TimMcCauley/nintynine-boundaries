# [99boundaries](https://99boundaries.com)

Command line utility to generate administrative boundaries from [OpenStreetMap](http://openstreetmap.org) via [Overpass](http://overpass-api.de/) and [OSM Land Polygons](https://osmdata.openstreetmap.de/data/land-polygons.html).

## Installation & Resource Consumption

Clone this repository and run `poetry install` from the root folder. In order to generate not only maritime but also land (coastal) boundaries, you will need to download land polygons derived from OpenStreetMap and generiously hosted [here](https://osmdata.openstreetmap.de/data/land-polygons.html). To decrease the computation time please download the [WGS84 split variant](https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip). 

Countries with greater coverage, such as Russia, Canada or France will require at least 8GB of memory to extract the land polygons. 

## Usage

1. Generate the maritime boundary as GeoJSON for Australia:

`make_boundary --alpha2 AU --formats geojson`

2. Generate the maritime and land boundary as GeoJSON and ESRI Shapefile for Spain:

`make_boundary --alpha2 ES --formats geojson shp --land_data_dir /path/to/land-polygons-split-4326`

3. Generate the maritime and land boundaries as CSV (geometry as WKT) for France and Canada:

`make_boundary --alpha2 FR CA --formats csv --land_data_dir /path/to/land-polygons-split-4326`

The file output formats can either be ESRI Shapefile, GeoJSON, CSV, GeoPackage or MapInfo and will be saved as archives into the `data` folder residing in `path/to/nintynine-boundaries/nintynine_boundaries`.

## Future Work

The plan is to include further admin levels for individual countries at a later stage.