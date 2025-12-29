import os
import warnings
from logging import DEBUG, INFO, Formatter, Logger, StreamHandler, getLogger
from pathlib import Path
from shutil import rmtree
from typing import List, Optional, Tuple, TypedDict, Union
from zipfile import ZIP_DEFLATED, ZipFile

warnings.simplefilter(action="ignore", category=UserWarning)
warnings.simplefilter(action="ignore", category=FutureWarning)
# warnings.filterwarnings("ignore", message=".*of field tags has been truncated to 254 characters*")

from geopandas import GeoDataFrame
from pandas import DataFrame

driver_lookup: dict[str, str] = {
    "GPKG": "GPKG",
    "GEOJSON": "GeoJSON",
    "CSV": "CSV",
    "SHP": "SHP",
    "MAPINFO": "MapInfo File",
    "KML": "KML",
    "FGB": "FlatGeobuf",
    "PGDUMP": "PGDUMP",
}


class Node(TypedDict):
    id: int
    lon_lat: Tuple[float, float]
    way_id: int


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
    handler = StreamHandler()
    handler.setFormatter(formatter)

    logger = getLogger(name)
    if debug:
        logger.setLevel(DEBUG)
    else:
        logger.setLevel(INFO)
    logger.addHandler(handler)

    return logger


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

    # Process each feature individually to ensure consistent folder naming
    for position, (_, row) in enumerate(gdf.iterrows()):
        feature_name_clean = get_feature_filename(row, position)

        p: Path = output_path / country / str(admin_level) / feature_name_clean

        p.mkdir(parents=True, exist_ok=True)

        filename = feature_name_clean
        if not include_maritime:
            filename = f"{filename}_land"

        feature_gdf = GeoDataFrame([row], crs=gdf.crs)

        for driver in formats:
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
