import logging
import sys
import time
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from geopandas import GeoDataFrame, read_file
from osm2geojson import json2geojson, overpass_call

from nintynine_boundaries.utils import (
    clean_data_dir,
    filter_by_overlap,
    make_overpass_query,
    make_overpass_query_fallback,
    setup_custom_logger,
    to_files,
)


def overpass_call_with_retry(
    query: str,
    max_retries: int = 3,
    initial_delay: float = 5.0,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """Call Overpass API with retry logic and exponential backoff.

    Parameters
    ----------
    query : str
        The Overpass query string
    max_retries : int
        Maximum number of retry attempts (default: 3)
    initial_delay : float
        Initial delay in seconds before first retry (default: 5.0)
    logger : Optional[logging.Logger]
        Logger instance for logging retry attempts

    Returns
    -------
    Dict[str, Any]
        GeoJSON data from the Overpass API

    Raises
    ------
    requests.exceptions.HTTPError
        If all retry attempts fail
    """
    delay = initial_delay

    for attempt in range(max_retries):
        try:
            result = overpass_call(query)
            return json2geojson(result)
        except requests.exceptions.HTTPError as e:
            if attempt < max_retries - 1:
                if logger:
                    logger.warning(
                        f"Overpass API error (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay:.1f} seconds..."
                    )
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                if logger:
                    logger.error(f"Overpass API failed after {max_retries} attempts: {e}")
                raise
        except Exception as e:
            if logger:
                logger.error(f"Unexpected error during Overpass API call: {e}")
            raise

    # This should never be reached, but just in case
    raise RuntimeError("Unexpected error in overpass_call_with_retry")


def apply_overlap_filter(
    gdf: GeoDataFrame,
    current_admin_level: int,
    gdf_country_reference: Optional[GeoDataFrame],
    logger: logging.Logger,
    boundary_type: str = "maritime"
) -> GeoDataFrame:
    """Apply 50% overlap filtering to admin level 3+ features.

    Parameters
    ----------
    gdf : GeoDataFrame
        The GeoDataFrame to filter
    current_admin_level : int
        Current administrative level being processed
    gdf_country_reference : Optional[GeoDataFrame]
        Reference country boundary (admin level 2)
    logger : logging.Logger
        Logger instance for logging filter results
    boundary_type : str
        Type of boundary being filtered ("maritime" or "land") for logging

    Returns
    -------
    GeoDataFrame
        Filtered GeoDataFrame or original if filtering not applicable
    """
    if current_admin_level > 2 and gdf_country_reference is not None:
        features_before = len(gdf)
        gdf_filtered = filter_by_overlap(gdf, gdf_country_reference, min_overlap_ratio=0.5)
        features_after = len(gdf_filtered)

        if features_before > features_after:
            logger.info(
                f"Filtered out {features_before - features_after} {boundary_type} features "
                f"with <50% overlap (kept {features_after}/{features_before})"
            )

        return gdf_filtered

    return gdf


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
    optional.set_defaults(clean=False)
    optional.add_argument(
        "-o",
        "--output_path",
        type=Path,
        help="Output directory path for generated boundary files",
        default=Path(__file__).absolute().parent / "data",
    )

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
        output_path: Path = args.output_path
        setup_custom_logger("du", debug)
        logger: logging.Logger = logging.getLogger("du")

        # Clean data directory before processing if requested
        if clean:
            clean_data_dir(output_path)
            logger.info("Cleaned data directory")

    except:
        print("\nTry $make_boundary --alpha2 ES")
        sys.exit(1)

    for alpha2 in alpha2_list:
        # Store the admin level 2 boundary for overlap filtering
        gdf_country_reference: Optional[GeoDataFrame] = None

        # Process admin levels from 2 to max_admin_level
        for current_admin_level in range(2, max_admin_level + 1):

            logger.info(f"processing {alpha2} admin level {current_admin_level}...")

            overpass_query: str = make_overpass_query(alpha2, current_admin_level, parent_admin_level=2)
            data: Dict[str, Any] = overpass_call_with_retry(overpass_query, logger=logger)

            # If no results and admin level > 2, try fallback query using area-based search
            if len(data["features"]) == 0 and current_admin_level > 2:
                logger.info(f"No results from parent-child query, trying area-based fallback query for {alpha2} admin level {current_admin_level}...")
                overpass_query = make_overpass_query_fallback(alpha2, current_admin_level)
                data = overpass_call_with_retry(overpass_query, logger=logger)

            if len(data["features"]) > 0:

                logger.info(f"overpass returned {len(data['features'])} features")

                gdf_maritime: GeoDataFrame = GeoDataFrame.from_features(features=data, crs="epsg:4326")
                # we only want to keep polygons
                gdf_maritime = gdf_maritime[gdf_maritime["geometry"].apply(lambda x: x.type != "Point")].explode(
                    index_parts=False
                )

                # Store admin level 2 boundary as reference for filtering higher levels
                if current_admin_level == 2:
                    gdf_country_reference = gdf_maritime.copy()

                # Filter admin level 3+ by 50% overlap with country boundary to exclude neighboring countries
                gdf_maritime = apply_overlap_filter(gdf_maritime, current_admin_level, gdf_country_reference, logger, "maritime")

                if not set(gdf_maritime.geom_type).isdisjoint(("MultiPolygon", "Polygon")):
                    to_files(
                        current_admin_level,
                        alpha2,
                        gdf_maritime,
                        formats,
                        include_maritime=True,
                        output_path=output_path,
                    )

                    logger.info(f"saved {alpha2} admin level {current_admin_level} maritime boundary")

                    # we use the land data and intersect with the maritime
                    # administritive boundaries to obtain the coastal land boundaries
                    if land_data_dir:
                        bbox = tuple(gdf_maritime.total_bounds)
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

                            # Filter land boundaries by 50% overlap for admin level 3+ as well
                            gdf_intersection = apply_overlap_filter(gdf_intersection, current_admin_level, gdf_country_reference, logger, "land")

                            to_files(
                                current_admin_level,
                                alpha2,
                                gdf_intersection,
                                formats,
                                include_maritime=False,
                                output_path=output_path,
                            )

                            logger.info(f"saved {alpha2} admin level {current_admin_level} land boundary\n")
                        else:
                            logger.warning(f"No land intersection features found for {alpha2} admin level {current_admin_level}")


if __name__ == "__main__":
    main()
