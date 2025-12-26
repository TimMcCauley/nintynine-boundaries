import os
import warnings
from logging import DEBUG, INFO, Formatter, Logger, StreamHandler, getLogger
from pathlib import Path
from shutil import rmtree
from typing import List, Tuple, TypedDict
from zipfile import ZIP_DEFLATED, ZipFile

warnings.simplefilter(action="ignore", category=UserWarning)
warnings.simplefilter(action="ignore", category=FutureWarning)
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


def zipdir(path: str, ziph: ZipFile) -> None:
    """Zips a directory

    Parameters
    ----------
    path : str
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

    # Drop tags column to avoid truncation warnings and reduce file size
    if "tags" in gdf.columns:
        gdf = gdf.drop(columns=["tags"])

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


def clean_data_dir() -> None:
    """Removes the data directory if it exists to ensure a clean run"""
    data_dir: Path = Path(__file__).absolute().parent / "data"
    if data_dir.exists():
        rmtree(data_dir)


def to_files(
    admin_level: int,
    country: str,
    gdf: GeoDataFrame,
    formats: List[str],
    include_maritime: bool,
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
    """

    if admin_level == 2:
        p: Path = Path(__file__).absolute().parent / "data" / str(admin_level) / country
        p.mkdir(parents=True, exist_ok=True)

        filename: str
        if include_maritime:
            filename = f"{country}_{admin_level}"
        else:
            filename = f"{country}_{admin_level}_land"

        for driver in formats:
            gpd_to_file(driver_lookup[driver.upper()], p, filename, gdf)

    else:

        # For higher admin levels, create separate files for each feature
        # Structure: data/2/country/admin_level/feature_name/
        for idx, row in gdf.iterrows():
            feature_name = None

            if "tags" in row and isinstance(row["tags"], dict):
                feature_name = f"{row["tags"].get("name")}"

            feature_id = f"feature_{row.get('id', idx)}"

            feature_name_clean = str(f"{feature_id}_{feature_name}").lower().replace(" ", "_")
            feature_name_clean = "".join(c if c.isalnum() or c == "_" else "_" for c in feature_name_clean)

            p: Path = Path(__file__).absolute().parent / "data" / "2" / country / str(admin_level) / feature_name_clean

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
