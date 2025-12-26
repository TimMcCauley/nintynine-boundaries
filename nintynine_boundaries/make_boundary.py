import logging
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from geopandas import GeoDataFrame, read_file
from osm2geojson import json2geojson, overpass_call

from nintynine_boundaries.utils import (
    clean_data_dir,
    make_overpass_query,
    setup_custom_logger,
    to_files,
)


def cmdline_args() -> Namespace:
    parser = ArgumentParser()

    parser._action_groups.pop()
    required = parser.add_argument_group("required arguments")
    optional = parser.add_argument_group("optional arguments")

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
        help="Output formats, one or multiple of shp, gpkg, csv, geojson, mapinfo, kml, fgb, pgdump",
    )
    optional.add_argument(
        "-l",
        "--max_admin_level",
        type=int,
        help="Highest OSM administrative level to process. Processes levels 2 through max_admin_level. Read more at https://wiki.openstreetmap.org/wiki/Key:admin_level",
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
    optional.add_argument("--clean", action="store_true", help="Clean the data directory before processing")
    optional.add_argument("--no-clean", dest="clean", action="store_false", help="Skip cleaning the data directory")
    optional.set_defaults(clean=True)

    return parser.parse_args()


def main() -> None:
    """This function first makes a query to overpass to fetch the country relation
    which includes maritime boundaries.
    The result is exported to a geodataframe and saved to a set of files.
    If openstreetmap land polygons are downloaded and provided these are then intersected
    with the country relation to obtain the more detailed coastal boundaries."""

    try:
        args: Namespace = cmdline_args()
        alpha2_list: List[str] = args.alpha2
        max_admin_level: int = args.max_admin_level
        land_data_dir: Optional[Path] = args.land_data_dir
        formats: List[str] = args.formats
        debug: bool = args.debug
        clean: bool = args.clean
        setup_custom_logger("du", debug)
        logger: logging.Logger = logging.getLogger("du")

        # Clean data directory before processing if requested
        if clean:
            clean_data_dir()
            logger.info("Cleaned data directory")

    except:
        print("\nTry $make_boundary --alpha2 ES")
        sys.exit(1)

    for alpha2 in alpha2_list:
        # Process admin levels from 2 to max_admin_level
        for current_admin_level in range(2, max_admin_level + 1):

            logger.info(f"processing {alpha2} admin level {current_admin_level}...")

            overpass_query: str = make_overpass_query(alpha2, current_admin_level, parent_admin_level=2)
            data: Dict[str, Any] = json2geojson(overpass_call(overpass_query))
            if len(data["features"]) > 0:

                logger.info(f"overpass returned {len(data['features'])} features")

                gdf_maritime: GeoDataFrame = GeoDataFrame.from_features(features=data, crs="epsg:4326")
                # we only want to keep polygons
                gdf_maritime = gdf_maritime[gdf_maritime["geometry"].apply(lambda x: x.type != "Point")].explode(
                    index_parts=False
                )

                if not set(gdf_maritime.geom_type).isdisjoint(("MultiPolygon", "Polygon")):
                    to_files(
                        current_admin_level,
                        alpha2,
                        gdf_maritime,
                        formats,
                        include_maritime=True,
                    )

                    logger.info(f"saved {alpha2} admin level {current_admin_level} maritime boundary")

                    # we use the land data and intersect with the maritime
                    # administritive boundaries to obtain the coastal land boundaries
                    if land_data_dir:
                        bbox: Tuple[float, float, float, float] = tuple(gdf_maritime.total_bounds)
                        gdf_osm_land: GeoDataFrame = read_file(
                            land_data_dir,
                            bbox=bbox,
                        )

                        # Process each maritime feature individually to preserve attributes
                        land_features: List[Dict[str, Any]] = []

                        for _, maritime_row in gdf_maritime.iterrows():
                            # Create a GeoDataFrame for this single maritime feature
                            gdf_single_maritime: GeoDataFrame = GeoDataFrame([maritime_row], crs=gdf_maritime.crs)

                            # Intersect with land polygons
                            gdf_single_intersection: GeoDataFrame = gdf_osm_land.overlay(gdf_single_maritime, how="intersection")

                            if not gdf_single_intersection.empty:
                                # Dissolve this feature's land polygons into one
                                gdf_single_intersection["dissolve_column"] = 0
                                gdf_single_dissolved: GeoDataFrame = gdf_single_intersection.dissolve(by="dissolve_column")

                                # Extract the dissolved geometry
                                dissolved_geom = gdf_single_dissolved.geometry.iloc[0]

                                # Create a feature dict preserving the original maritime attributes
                                feature_dict = maritime_row.to_dict()
                                feature_dict["geometry"] = dissolved_geom
                                land_features.append(feature_dict)

                        if land_features:
                            gdf_intersection: GeoDataFrame = GeoDataFrame(land_features, crs="epsg:4326")

                            logger.info(f"Overlaying land polygons complete - processed {len(land_features)} features")

                            to_files(
                                current_admin_level,
                                alpha2,
                                gdf_intersection,
                                formats,
                                include_maritime=False,
                            )

                            logger.info(f"saved {alpha2} admin level {current_admin_level} land boundary\n")
                        else:
                            logger.warning(f"No land intersection features found for {alpha2} admin level {current_admin_level}")


if __name__ == "__main__":
    main()
