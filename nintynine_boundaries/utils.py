import os
import warnings
from logging import DEBUG, INFO, Formatter, Logger, StreamHandler, getLogger
from pathlib import Path
from shutil import rmtree
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union
from zipfile import ZIP_DEFLATED, ZipFile

warnings.simplefilter(action="ignore", category=UserWarning)
warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*of field tags has been truncated to 254 characters*")

import time

import requests
from geopandas import GeoDataFrame
from osm2geojson import json2geojson, overpass_call
from pandas import DataFrame
from tqdm.auto import tqdm

driver_lookup: dict[str, str] = {
    "GPKG": "GPKG",
    "GEOJSON": "GeoJSON",
    "CSV": "CSV",
    "SHP": "SHP",
    "MAPINFO": "MapInfo File",
    "KML": "KML",
    "FGB": "FlatGeobuf",
    "PGDUMP": "PGDUMP",
    "PARQUET": "Parquet",
}


class Node(TypedDict):
    id: int
    lon_lat: Tuple[float, float]
    way_id: int


class TqdmLoggingHandler(StreamHandler):
    """Custom logging handler that writes through tqdm.write() to avoid conflicts with progress bars"""

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


def setup_custom_logger(name: str, debug: bool) -> Logger:
    """Sets up a custom logger

    Parameters
    ----------
    name : str
        the name of the logger
    debug : bool
        whether debug is enabled or not

    Returns
    -------
    Logger
        the python Logger instance
    """
    formatter = Formatter(fmt="%(asctime)s - %(levelname)s - %(module)s - %(message)s")
    handler = TqdmLoggingHandler()
    handler.setFormatter(formatter)

    logger = getLogger(name)
    if debug:
        logger.setLevel(DEBUG)
    else:
        logger.setLevel(INFO)
    logger.addHandler(handler)

    return logger


def overpass_call_with_retry(
    query: str, max_retries: int = 3, initial_delay: float = 5.0, logger: Optional[Logger] = None
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
    logger : Optional[Logger]
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
    logger: Logger,
    boundary_type: str = "maritime",
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
    logger : Logger
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
            logger.debug(
                f"Filtered out {features_before - features_after} {boundary_type} features "
                f"with <50% overlap (kept {features_after}/{features_before})"
            )

        return gdf_filtered

    return gdf


def zipdir(path: Union[str, Path], ziph: ZipFile) -> None:
    """Zips a directory

    Parameters
    ----------
    path : Union[str, Path]
        the path to the directory to zip
    ziph : ZipFile
        zip file handler
    """
    for root, dirs, files in os.walk(path):
        for file in files:
            ziph.write(
                os.path.join(root, file),
                os.path.relpath(os.path.join(root, file), os.path.join(path, "..")),
            )


def gpd_to_file(driver: str, p: Path, filename: str, gdf: GeoDataFrame) -> None:
    """Exports a GeoDataFrame to a file with specified format

    Parameters
    ----------
    driver : str
        the OGR driver to be used
    p : Path
        the path to the file to be generated
    filename : str
        the filename to be generated
    gdf : GeoDataFrame
        the GeoDataFrame to be used
    """
    folder: Path = p / driver.replace(" ", "")
    folder.mkdir(exist_ok=True)

    local_file: Path = folder / f"{filename}.{driver.lower().replace(' ', '')}"
    zipped_file: Path = p / f"{filename}.{driver.lower().replace(' ', '')}.zip"

    if driver == "CSV":
        DataFrame(gdf.assign(geometry=gdf["geometry"].apply(lambda param: param.wkt))).to_csv(local_file)

    elif driver == "SHP":
        gdf.to_file(filename=local_file)

    elif driver == "MapInfo File":
        if "id" in gdf:
            gdf["id"] = gdf["id"].astype("float")
        gdf.to_file(filename=local_file, driver=driver)

    elif driver == "Parquet":
        gdf.to_parquet(local_file)

    else:
        gdf.to_file(filename=local_file, driver=driver)

    with ZipFile(zipped_file, "w", ZIP_DEFLATED) as zipf:
        zipdir(folder, zipf)

    rmtree(folder)


def clean_data_dir(output_path: Optional[Path] = None) -> None:
    """Removes the data directory if it exists to ensure a clean run

    Parameters
    ----------
    output_path : Path, optional
        The output directory path. If None, uses default path.
    """
    if output_path is None:
        data_dir: Path = Path(__file__).absolute().parent / "data"
    else:
        data_dir = output_path
    if data_dir.exists():
        rmtree(data_dir)


def get_geometry_coordinate_count(geom) -> int:
    """Calculates the total number of coordinates in a geometry

    Parameters
    ----------
    geom : shapely.geometry
        A shapely geometry object

    Returns
    -------
    int
        Total number of coordinates in the geometry
    """
    coord_count = 0
    if hasattr(geom, "exterior"):
        # Single polygon
        coord_count = len(geom.exterior.coords)
        if hasattr(geom, "interiors"):
            coord_count += sum(len(interior.coords) for interior in geom.interiors)
    elif hasattr(geom, "geoms"):
        # MultiPolygon or GeometryCollection
        for g in geom.geoms:
            if hasattr(g, "exterior"):
                coord_count += len(g.exterior.coords)
                if hasattr(g, "interiors"):
                    coord_count += sum(len(interior.coords) for interior in g.interiors)
    return coord_count


def get_feature_filename(row, idx) -> str:
    """Generates a clean filename for a feature based on its tags and relation ID

    Parameters
    ----------
    row : Series
        A row from the GeoDataFrame containing feature data
    idx : int
        The index of the row (used as fallback for ID)

    Returns
    -------
    str
        A cleaned filename string
    """
    feature_name = None

    if "tags" in row and isinstance(row["tags"], dict):
        feature_name = row["tags"].get("name:en") or row["tags"].get("int_name") or row["tags"].get("name")

    relation_id = f"relation_{row.get('id', idx)}"

    feature_name_clean = str(f"{relation_id}_{feature_name}").lower().replace(" ", "_")
    feature_name_clean = "".join(c if c.isalnum() or c == "_" else "_" for c in feature_name_clean)

    return feature_name_clean


def to_files(
    admin_level: int,
    country: str,
    gdf: GeoDataFrame,
    formats: List[str],
    include_maritime: bool,
    output_path: Path,
) -> None:
    """Helper function looping over all drivers

    Parameters
    ----------
    admin_level : int
        the administrative level
    country : str
        the country name
    gdf : GeoDataFrame
        the geodataframe holding the data
    include_maritime : bool
        whether we are dealing with martime boundaries or not
    output_path : Path
        the output directory path
    """
    import logging

    logger = logging.getLogger("du")

    boundary_type = "maritime" if include_maritime else "land"
    logger.debug(f"Saving {len(gdf)} {boundary_type} features for {country} admin level {admin_level}")

    # Log geometry types present
    geom_types = gdf.geom_type.value_counts().to_dict()
    logger.debug(f"Geometry types: {geom_types}")

    # Union all polygons grouped by relation_id (id column)
    if "id" in gdf.columns and len(gdf) > 0:
        logger.debug(f"Unioning {len(gdf)} polygons grouped by relation_id")

        # Group by relation_id and union geometries within each group
        unioned_features = []
        unique_ids = gdf["id"].unique()

        logger.debug(f"Found {len(unique_ids)} unique relation IDs")

        for relation_id in unique_ids:
            # Get all rows for this relation_id
            relation_rows = gdf[gdf["id"] == relation_id]

            # Get the first row to preserve attributes
            first_row = relation_rows.iloc[0].to_dict()

            # Union all geometries for this relation_id
            unioned_geometry = relation_rows.geometry.union_all()

            # Create a feature with unioned geometry and original attributes
            first_row["geometry"] = unioned_geometry
            unioned_features.append(first_row)

            logger.debug(
                f"Relation {relation_id}: unioned {len(relation_rows)} polygons into {unioned_geometry.geom_type}"
            )

        # Create new GeoDataFrame with unioned features
        gdf = GeoDataFrame(unioned_features, crs=gdf.crs)

        logger.debug(f"Unioned {len(gdf)} relation(s) at admin level {admin_level}")

    # Process each feature individually to ensure consistent folder naming
    for position, (_, row) in tqdm(
        enumerate(gdf.iterrows()),
        total=len(gdf),
        desc=f"Exporting {boundary_type} features",
        unit="feature",
        leave=False,
        position=2,
        colour="#00FF00",
        initial=1,
    ):
        feature_name_clean = get_feature_filename(row, position)

        # Log details about the feature being saved
        relation_id = row.get("id", position)
        geom_type = row.geometry.geom_type if hasattr(row.geometry, "geom_type") else "Unknown"
        logger.debug(
            f"Saving feature {position + 1}/{len(gdf)}: relation_id={relation_id}, name={feature_name_clean}, geom_type={geom_type}"
        )

        p: Path = output_path / country / str(admin_level) / feature_name_clean

        p.mkdir(parents=True, exist_ok=True)

        filename = feature_name_clean
        if not include_maritime:
            filename = f"{filename}_land"

        feature_gdf = GeoDataFrame([row], crs=gdf.crs)

        # Calculate coordinate count to determine if GeoJSON should be skipped
        coord_count = get_geometry_coordinate_count(row.geometry)
        skip_geojson = coord_count > 50000
        if skip_geojson:
            logger.debug(f"Skipping GeoJSON for {feature_name_clean} (too large: {coord_count:,} coordinates)")

        for driver in formats:
            # Skip GeoJSON if geometry is too large
            if skip_geojson and driver.upper() == "GEOJSON":
                continue
            gpd_to_file(driver_lookup[driver.upper()], p, filename, feature_gdf)


def make_overpass_query(alpha2: str, admin_level: int, parent_admin_level: int = 2) -> str:
    """Returns the overpass query for a certain admin level and country code

    Parameters
    ----------
    alpha2 : str
        ISO 3166-1 alpha-2 country code
    admin_level : int
        the administrative level to query
    parent_admin_level : int
        the parent administrative level (default: 2 for country level)

    Raises
    ------
    ValueError
        If admin_level is not supported
    """

    if admin_level == 2:
        return f"""
        [timeout:600][out:json];
        relation["boundary"="administrative"]["admin_level"="2"]["ISO3166-1"="{alpha2}"];
        (._;>;);
        out;
        """
    elif admin_level > 2:
        # Nested query for higher admin levels
        return f"""
        [timeout:600][out:json];
        relation["ISO3166-1"="{alpha2}"]["admin_level"="{parent_admin_level}"]["boundary"="administrative"]->.country;
        (
          relation(r.country)["boundary"="administrative"]["admin_level"="{admin_level}"];
        );
        (._;>;);
        out;
        """
    else:
        raise ValueError(f"Admin level {admin_level} is not supported.")


def make_overpass_query_fallback(alpha2: str, admin_level: int) -> str:
    """Returns a fallback overpass query using area-based search instead of parent-child relationships

    This fallback query searches for all administrative boundaries of a given level within
    the country's area, which is useful when parent-child relationships aren't properly tagged.

    Parameters
    ----------
    alpha2 : str
        ISO 3166-1 alpha-2 country code
    admin_level : int
        the administrative level to query

    Raises
    ------
    ValueError
        If admin_level is not supported
    """

    if admin_level == 2:
        return make_overpass_query(alpha2, admin_level)
    elif admin_level > 2:
        # Area-based query for higher admin levels (fallback)
        return f"""
        [timeout:600][out:json];
        area["ISO3166-1"="{alpha2}"]["admin_level"="2"]->.country;
        (
          relation(area.country)["boundary"="administrative"]["admin_level"="{admin_level}"];
        );
        (._;>;);
        out;
        """
    else:
        raise ValueError(f"Admin level {admin_level} is not supported.")


def filter_by_overlap(gdf: GeoDataFrame, reference_gdf: GeoDataFrame, min_overlap_ratio: float = 0.5) -> GeoDataFrame:
    """Filters a GeoDataFrame to only include features that have at least min_overlap_ratio
    overlap with the reference geometry (typically the parent country boundary).

    This prevents neighboring countries' administrative regions from being included in results.

    Parameters
    ----------
    gdf : GeoDataFrame
        The GeoDataFrame to filter (e.g., admin level 3+ features)
    reference_gdf : GeoDataFrame
        The reference GeoDataFrame (e.g., admin level 2 country boundary)
    min_overlap_ratio : float
        Minimum ratio of overlap required (default: 0.5 for 50%)

    Returns
    -------
    GeoDataFrame
        Filtered GeoDataFrame containing only features with sufficient overlap
    """
    if reference_gdf.empty or gdf.empty:
        return gdf

    # Dissolve reference geometry into a single geometry for comparison
    reference_geom = reference_gdf.geometry.union_all()

    # Filter features based on overlap ratio
    def calculate_overlap_ratio(geometry):
        try:
            intersection = geometry.intersection(reference_geom)
            if intersection.is_empty:
                return 0.0
            overlap_ratio = intersection.area / geometry.area
            return overlap_ratio
        except Exception:
            # If calculation fails, include the feature to be safe
            return 1.0

    gdf["overlap_ratio"] = gdf.geometry.apply(calculate_overlap_ratio)
    filtered_gdf = gdf[gdf["overlap_ratio"] >= min_overlap_ratio].copy()

    # Remove the temporary overlap_ratio column
    filtered_gdf = filtered_gdf.drop(columns=["overlap_ratio"])

    return filtered_gdf
