import logging
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

from geopandas import GeoDataFrame, GeoSeries, read_file
from osm2geojson import json2geojson, overpass_call

from nintynine_boundaries.utils import (
    make_overpass_query,
    setup_custom_logger,
    to_files,
)


def cmdline_args() -> Namespace:
    p = ArgumentParser()

    p._action_groups.pop()
    required = p.add_argument_group("required arguments")
    optional = p.add_argument_group("optional arguments")

    required.add_argument(
        "-a",
        "--alpha2",
        nargs="+",
        default=[],
        required=True,
        help="List of ISO-3166-1 alpha2 codes",
    )
    required.add_argument(
        "-f",
        "--formats",
        nargs="+",
        default=[],
        required=True,
        help="Output formats. One or multiple of SHP, GPKG, CSV, GEOJSON, MAPINFO",
    )
    optional.add_argument(
        "-l",
        "--admin_level",
        type=int,
        help="OpenStreetMap administrative level. Currently only level 2 supportted. Read more at https://wiki.openstreetmap.org/wiki/Key:admin_level",
        default=2,
    )
    optional.add_argument(
        "-d",
        "--land_data_dir",
        type=Path,
        help="Path to OpenStreetMap land data folder, read more and download from https://osmdata.openstreetmap.de/data/land-polygons.html",
    )
    optional.add_argument("--debug", action="store_true")
    optional.add_argument("--no-debug", dest="debug", action="store_false")
    optional.set_defaults(debug=False)

    return p.parse_args()


def main():
    """This function first makes a query to overpass to fetch the country relation
    which includes maritime boundaries.
    The result is exported to a geodataframe and saved to a set of files.
    If openstreetmap land polygons are downloaded and provided these are then intersected
    with the country relation to obtain the detailed coastal boundaries."""

    try:
        args = cmdline_args()
        alpha2_list = args.alpha2
        admin_level = args.admin_level
        land_data_dir = args.land_data_dir
        formats = args.formats
        debug = args.debug
        setup_custom_logger("du", debug)
        logger = logging.getLogger("du")

    except:
        print("\nTry $make_boundary --alpha2 ES")
        sys.exit(1)

    for alpha2 in alpha2_list:
        if admin_level == 2:

            logger.info(f"processing {alpha2}...")

            overpass_query = make_overpass_query(alpha2, admin_level)
            data = json2geojson(overpass_call(overpass_query))
            if len(data["features"]) > 0:

                logger.debug(f"overpass returned {len(data['features'])} features")

                gdf_maritime = GeoDataFrame.from_features(
                    features=data, crs="epsg:4326"
                )

                # we only want boundaries
                gdf_maritime = gdf_maritime[
                    gdf_maritime["geometry"].apply(lambda x: x.type != "Point")
                ]
                if not set(gdf_maritime.geom_type).isdisjoint(
                    ("MultiPolygon", "Polygon")
                ):
                    to_files(
                        admin_level,
                        alpha2,
                        gdf_maritime,
                        formats,
                        include_maritime=True,
                    )

                    logger.debug(f"saved {alpha2} maritime boundary")

                    # we use the land data and intersect with the maritime
                    # administritive boundaries to obtain the coastal land boundaries
                    if land_data_dir:
                        bbox = tuple(gdf_maritime.total_bounds)
                        gdf_osm_land = read_file(
                            land_data_dir,
                            bbox=bbox,
                        )
                        intersection = (gdf_osm_land.unary_union).intersection(
                            gdf_maritime.unary_union
                        )
                        # sometimes the intersection will be a geometry collection
                        # we have to unpack; we dont want that geometry type in the output
                        if hasattr(intersection, "geoms"):
                            intersection = [
                                geometry
                                for geometry in intersection.geoms
                                if geometry.type not in ["Point", "LineString"]
                            ]

                        logger.debug(f"{len(intersection)} intersected land polygons")

                        gdf_land = GeoDataFrame(
                            geometry=GeoSeries(intersection), crs="epsg:4326"
                        )
                        to_files(
                            admin_level,
                            alpha2,
                            gdf_land,
                            formats,
                            include_maritime=False,
                        )

                        logger.debug(f"saved {alpha2} land boundary\n")


if __name__ == "__main__":
    main()
