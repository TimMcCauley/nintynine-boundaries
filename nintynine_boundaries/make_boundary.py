import logging
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional

from geopandas import GeoDataFrame, read_file
from tqdm.auto import tqdm

from nintynine_boundaries.utils import (
    apply_overlap_filter,
    clean_data_dir,
    make_overpass_query,
    make_overpass_query_fallback,
    overpass_call_with_retry,
    setup_custom_logger,
    suppress_pygrio_warnings,
    to_files,
)

# Constants
PROGRESS_BAR_COLOR = "#00FF00"
DEFAULT_CRS = "epsg:4326"
PARENT_ADMIN_LEVEL = 2


def cmdline_args() -> Namespace:
    """Parse command line arguments for the boundary generation tool.

    Returns
    -------
    Namespace
        Parsed command line arguments including alpha2 country codes, formats,
        max_admin_level, land_data_dir, debug flag, clean flag, and output_path
    """
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
        help="Output formats, one or multiple of shp, gpkg, csv, geojson, mapinfo, kml, fgb, pgdump, parquet",
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
    optional.add_argument("--suppress-warnings", dest="suppress_warnings", action="store_true", help="Suppress PyGRIO/GDAL warnings")
    optional.add_argument("--no-suppress-warnings", dest="suppress_warnings", action="store_false", help="Show PyGRIO/GDAL warnings")
    optional.set_defaults(suppress_warnings=True)
    optional.add_argument(
        "-o",
        "--output_path",
        type=Path,
        help="Output directory path for generated boundary files",
        default=Path(__file__).absolute().parent / "data",
    )

    return parser.parse_args()


def get_progress_bar_config(**kwargs) -> Dict[str, Any]:
    """Get default progress bar configuration with optional overrides.

    Parameters
    ----------
    **kwargs
        Optional progress bar parameters to override defaults

    Returns
    -------
    Dict[str, Any]
        Progress bar configuration dictionary
    """
    defaults = {"colour": PROGRESS_BAR_COLOR, "leave": False, "initial": 0}
    return {**defaults, **kwargs}


def intersect_maritime_with_land(
    gdf_maritime: GeoDataFrame,
    gdf_osm_land: GeoDataFrame,
    logger: logging.Logger
) -> List[Dict[str, Any]]:
    """Intersect maritime features with land polygons to create land boundaries.

    Parameters
    ----------
    gdf_maritime : GeoDataFrame
        Maritime boundary features to intersect with land
    gdf_osm_land : GeoDataFrame
        OSM land polygon features
    logger : logging.Logger
        Logger instance for debug messages

    Returns
    -------
    List[Dict[str, Any]]
        List of feature dictionaries with land geometries and preserved maritime attributes
    """
    land_features: List[Dict[str, Any]] = []
    total_maritime_features = len(gdf_maritime)
    logger.debug(f"Intersecting {total_maritime_features} maritime features with land polygons...")

    for idx, (_, maritime_row) in tqdm(
        enumerate(gdf_maritime.iterrows(), 1),
        total=total_maritime_features,
        desc="Intersecting with land polygons",
        unit="feature",
        position=2,
        **get_progress_bar_config(initial=1)
    ):
        logger.debug(f"Processing maritime feature {idx}/{total_maritime_features}")

        # Create a GeoDataFrame for this single maritime feature
        gdf_single_maritime: GeoDataFrame = GeoDataFrame([maritime_row], crs=gdf_maritime.crs)

        maritime_geom = maritime_row.geometry
        # Query spatial index to find candidate land polygons
        candidate_indices = gdf_osm_land.sindex.query(maritime_geom, predicate="intersects")
        gdf_land_subset = gdf_osm_land.iloc[candidate_indices]

        # Intersect with the filtered land polygons
        gdf_single_intersection: GeoDataFrame = gdf_land_subset.overlay(
            gdf_single_maritime, how="intersection"
        )

        if not gdf_single_intersection.empty:
            # Dissolve this feature's land polygons into one
            gdf_single_intersection["dissolve_column"] = 0
            gdf_single_dissolved: GeoDataFrame = gdf_single_intersection.dissolve(
                by="dissolve_column"
            )

            # Extract the dissolved geometry
            dissolved_geom = gdf_single_dissolved.geometry.iloc[0]

            # Create a feature dict preserving the original maritime attributes
            feature_dict = maritime_row.to_dict()
            feature_dict["geometry"] = dissolved_geom
            land_features.append(feature_dict)

    return land_features


def has_valid_polygons(gdf: GeoDataFrame) -> bool:
    """Check if GeoDataFrame contains Polygon or MultiPolygon geometries.

    Parameters
    ----------
    gdf : GeoDataFrame
        GeoDataFrame to check

    Returns
    -------
    bool
        True if GeoDataFrame contains Polygon or MultiPolygon geometries
    """
    return bool(set(gdf.geom_type).intersection({"MultiPolygon", "Polygon"}))


def process_admin_level(
    alpha2: str,
    current_admin_level: int,
    gdf_country_reference: Optional[GeoDataFrame],
    land_data_dir: Optional[Path],
    formats: List[str],
    output_path: Path,
    logger: logging.Logger
) -> Optional[GeoDataFrame]:
    """Process a single admin level for a country.

    Parameters
    ----------
    alpha2 : str
        ISO-3166-1 alpha2 country code
    current_admin_level : int
        Current OSM administrative level to process
    gdf_country_reference : Optional[GeoDataFrame]
        Reference GeoDataFrame for admin level 2 boundary (for overlap filtering)
    land_data_dir : Optional[Path]
        Path to OSM land data polygons folder
    formats : List[str]
        Output formats to generate
    output_path : Path
        Output directory path
    logger : logging.Logger
        Logger instance

    Returns
    -------
    Optional[GeoDataFrame]
        GeoDataFrame of admin level 2 boundary if current_admin_level == 2, otherwise None
    """
    logger.debug(f"processing {alpha2} admin level {current_admin_level}...")

    overpass_query: str = make_overpass_query(alpha2, current_admin_level, parent_admin_level=PARENT_ADMIN_LEVEL)
    data: Dict[str, Any] = overpass_call_with_retry(overpass_query, logger=logger)

    # If no results and admin level > 2, try fallback query using area-based search
    if len(data["features"]) == 0 and current_admin_level > PARENT_ADMIN_LEVEL:
        logger.debug(
            f"No results from parent-child query, trying area-based fallback query for {alpha2} admin level {current_admin_level}..."
        )
        overpass_query = make_overpass_query_fallback(alpha2, current_admin_level)
        data = overpass_call_with_retry(overpass_query, logger=logger)

    if len(data["features"]) == 0:
        return None

    logger.debug(f"overpass returned {len(data['features'])} features")

    gdf_maritime: GeoDataFrame = GeoDataFrame.from_features(features=data, crs=DEFAULT_CRS)
    logger.debug(
        f"Before filtering: {len(gdf_maritime)} features, geometry types: {gdf_maritime.geom_type.value_counts().to_dict()}"
    )

    # we only want to keep polygons
    gdf_maritime = gdf_maritime[gdf_maritime["geometry"].apply(lambda x: x.geom_type != "Point")]
    logger.debug(f"After removing points: {len(gdf_maritime)} features")

    gdf_maritime = gdf_maritime.explode(index_parts=False)
    logger.debug(
        f"After explode: {len(gdf_maritime)} polygon features, geometry types: {gdf_maritime.geom_type.value_counts().to_dict()}"
    )

    # Store admin level 2 boundary as reference for filtering higher levels
    reference_gdf = None
    if current_admin_level == PARENT_ADMIN_LEVEL:
        reference_gdf = gdf_maritime.copy()

    # Filter admin level 3+ by 50% overlap with country boundary to exclude neighboring countries
    gdf_maritime = apply_overlap_filter(
        gdf_maritime, current_admin_level, gdf_country_reference, logger, "maritime"
    )

    if not has_valid_polygons(gdf_maritime):
        return reference_gdf

    to_files(
        current_admin_level,
        alpha2,
        gdf_maritime,
        formats,
        include_maritime=True,
        output_path=output_path,
    )

    logger.debug(f"saved {alpha2} admin level {current_admin_level} maritime boundary")

    # we use the land data and intersect with the maritime
    # administritive boundaries to obtain the coastal land boundaries
    if land_data_dir:
        logger.debug(f"Processing land polygons for {alpha2} admin level {current_admin_level}...")
        bbox = tuple(gdf_maritime.total_bounds)

        logger.debug(f"Reading land polygons from {land_data_dir}...")
        gdf_osm_land: GeoDataFrame = read_file(
            land_data_dir,
            bbox=bbox,
        )
        logger.debug(f"Loaded {len(gdf_osm_land)} land polygon features within bounding box")

        # Process each maritime feature individually to preserve attributes
        land_features = intersect_maritime_with_land(gdf_maritime, gdf_osm_land, logger)

        if land_features:
            gdf_intersection: GeoDataFrame = GeoDataFrame(land_features, crs=DEFAULT_CRS)

            logger.debug(f"Overlaying land polygons complete - processed {len(land_features)} features")

            # Filter land boundaries by 50% overlap for admin level 3+ as well
            gdf_intersection = apply_overlap_filter(
                gdf_intersection, current_admin_level, gdf_country_reference, logger, "land"
            )

            to_files(
                current_admin_level,
                alpha2,
                gdf_intersection,
                formats,
                include_maritime=False,
                output_path=output_path,
            )

            logger.debug(f"saved {alpha2} admin level {current_admin_level} land boundary\n")
        else:
            logger.debug(
                f"No land intersection features found for {alpha2} admin level {current_admin_level}"
            )

    return reference_gdf


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
        suppress_warnings: bool = args.suppress_warnings
        output_path: Path = args.output_path

        # Suppress PyGRIO/GDAL warnings if requested
        if suppress_warnings:
            suppress_pygrio_warnings()

        setup_custom_logger("du", debug)
        logger: logging.Logger = logging.getLogger("du")

        # Warn if land data directory is not provided or doesn't exist
        if land_data_dir is None:
            logger.warning(
                "⚠️  No land data directory provided. Only maritime boundaries will be generated. "
                "To generate land boundaries with detailed coastlines, download OSM land polygons from "
                "https://osmdata.openstreetmap.de/data/land-polygons.html and provide the path with --land_data_dir"
            )
        elif not land_data_dir.exists():
            logger.warning(
                f"⚠️  Land data directory does not exist: {land_data_dir}. "
                "Only maritime boundaries will be generated. "
                "Please download OSM land polygons from https://osmdata.openstreetmap.de/data/land-polygons.html"
            )

        # Clean data directory before processing if requested
        if clean:
            clean_data_dir(output_path)
            logger.debug("Cleaned data directory")

    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        print(f"Error: {e}")
        print("\nTry $make_boundary --alpha2 ES")
        sys.exit(1)

    for alpha2 in tqdm(
        alpha2_list,
        desc="Processing countries",
        unit="country",
        position=0,
        **get_progress_bar_config()
    ):
        # Store the admin level 2 boundary for overlap filtering
        gdf_country_reference: Optional[GeoDataFrame] = None

        # Process admin levels from 2 to max_admin_level
        admin_levels = range(PARENT_ADMIN_LEVEL, max_admin_level + 1)
        for current_admin_level in tqdm(
            admin_levels,
            desc=f"Processing {alpha2} admin levels",
            unit="level",
            position=1,
            **get_progress_bar_config()
        ):
            reference_gdf = process_admin_level(
                alpha2,
                current_admin_level,
                gdf_country_reference,
                land_data_dir,
                formats,
                output_path,
                logger
            )

            # Update the reference GeoDataFrame if this was admin level 2
            if reference_gdf is not None:
                gdf_country_reference = reference_gdf


if __name__ == "__main__":
    main()
