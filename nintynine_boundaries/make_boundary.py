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
        help="List of ISO-3166-1 alpha2 country codes, e.g. ES FR DE",
    )
    required.add_argument(
        "-f",
        "--formats",
        nargs="+",
        default=[],
        required=True,
        help="Output formats, one or multiple of shp, gpkg, csv, geojson, mapinfo",
    )
    optional.add_argument(
        "-l",
        "--admin_level",
        type=int,
        help="OSM administrative level, currently only level 2 supported. Read more at https://wiki.openstreetmap.org/wiki/Key:admin_level",
        default=2,
    )
    optional.add_argument(
        "-d",
        "--land_data_dir",
        type=Path,
        help="Path to the OSM land data polygons folder, read more and download from https://osmdata.openstreetmap.de/data/land-polygons.html",
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
    with the country relation to obtain the more detailed coastal boundaries."""

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
                gdf_maritime = gdf_maritime.drop(columns=["tags"])
                # we only want polygons
                gdf_maritime = gdf_maritime[
                    gdf_maritime["geometry"].apply(lambda x: x.type != "Point")
                ].explode(index_parts=False)

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
                        gdf_intersection = gdf_osm_land.overlay(
                            gdf_maritime, how="intersection"
                        )
                        # a small hack
                        # https://gis.stackexchange.com/questions/296663/dissolve-not-based-on-attribute-in-geopandas
                        gdf_intersection["dissolve_column"] = 0
                        gdf_intersection = gdf_intersection.dissolve(
                            by="dissolve_column"
                        )
                        # can be single or multipart geometries
                        if hasattr(gdf_intersection.geometry.iloc[0], "geoms"):
                            geometries = [
                                geom for geom in gdf_intersection.geometry.iloc[0].geoms
                            ]
                        else:
                            geometries = [gdf_intersection.geometry.iloc[0]]

                        gdf_intersection = GeoDataFrame(
                            geometry=GeoSeries(geometries, crs="epsg:4326")
                        )

                        logger.debug(f"overlaying land polygons complete")

                        to_files(
                            admin_level,
                            alpha2,
                            gdf_intersection,
                            formats,
                            include_maritime=False,
                        )

                        logger.debug(f"saved {alpha2} land boundary\n")


if __name__ == "__main__":
    main()
