import os
import warnings
from pathlib import Path
from shutil import rmtree
from typing import Tuple, TypedDict, List
from zipfile import ZIP_DEFLATED, ZipFile
from logging import Logger, getLogger, StreamHandler, Formatter, DEBUG, INFO

warnings.simplefilter(action="ignore", category=UserWarning)
warnings.simplefilter(action="ignore", category=FutureWarning)
from geopandas import GeoDataFrame
from pandas import DataFrame


class Node(TypedDict):
    id: int
    lon_lat: Tuple[int, int]
    way_id: int


# flake8: noqa
import logging


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


def zipdir(path: str, ziph: ZipFile):
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


def gpd_to_file(driver: str, p: Path, filename: str, gdf: GeoDataFrame):
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
    folder = p / driver.replace(" ", "")
    folder.mkdir(exist_ok=True)

    local_file = folder / f"{filename}.{driver.lower().replace(' ', '')}"
    zipped_file = p / f"{filename}.{driver.lower().replace(' ', '')}.zip"

    if driver == "CSV":
        DataFrame(
            gdf.assign(geometry=gdf["geometry"].apply(lambda param: param.wkt))
        ).to_csv(local_file)

    elif driver == "SHP":
        gdf.to_file(filename=local_file)

    elif driver == "MapInfo File":
        if "id" in gdf:
            gdf["id"] = gdf["id"].astype("float")
        gdf.to_file(filename=local_file, driver=driver)

    else:
        # gdf = gdf.drop(columns=["tags"])
        if "tags" in gdf:
            gdf["tags"] = gdf["tags"].astype("str")
        gdf.to_file(filename=local_file, driver=driver)

    with ZipFile(zipped_file, "w", ZIP_DEFLATED) as zipf:
        zipdir(folder, zipf)

    rmtree(folder)


def to_files(
    admin_level: int,
    country: str,
    gdf: GeoDataFrame,
    formats: List,
    include_maritime: bool,
):
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
    p = Path(__file__).absolute().parent / "data" / str(admin_level) / country
    p.mkdir(parents=True, exist_ok=True)

    if include_maritime:
        filename = f"{country}_{admin_level}"
    else:
        filename = f"{country}_{admin_level}_land"

    driver_lookup = {
        "GPKG": "GPKG",
        "GEOJSON": "GeoJSON",
        "CSV": "CSV",
        "SHP": "SHP",
        "MAPINFO": "MapInfo File",
        "KML": "KML",
        "FGB": "FlatGeobuf",
        "PGDUMP": "PGDUMP",
    }

    for driver in formats:
        gpd_to_file(driver_lookup[driver.upper()], p, filename, gdf)


def make_overpass_query(alpha2: str, admin_level: int) -> str:
    """Returns the overpass query for a certain admin level and country code

    Parameters
    ----------
    alpha2 : int
        ISO 3166-1 alpha-2 country code
    admin_level : str
        the administrative level
    """

    if admin_level == 2:

        return f"""
        [timeout:600][out:json];
        relation["boundary"="administrative"]["admin_level"="2"]["ISO3166-1"="{alpha2}"];
        (._;>;);
        out;
        """
