import datetime
import logging
import os
import re
import tempfile
import zipfile

import pandas as pd
import requests
from BeautifulSoup import BeautifulSoup
from dateutil import parser
from pykml import parser as kml_parser
from retrying import retry

logger = logging.getLogger(__name__)
AWAC_KML_URL = 'https://s3-ap-southeast-2.amazonaws.com/transport.wa/DOT_OCEANOGRAPHIC_SERVICES/AWAC_V2/AWAC.kml'
README_URL = 'https://s3-ap-southeast-2.amazonaws.com/transport.wa/DOT_OCEANOGRAPHIC_SERVICES/AWAC/AWAC_READ_ME/AWAC_READ_ME.htm'

NC_ATT_CONFIG = os.path.join(os.path.dirname(__file__), 'generate_nc_file_att')


def retry_if_urlerror_error(exception):
    """Return True if we should retry (in this case when it's an URLError), False otherwise"""
    return isinstance(exception, requests.ConnectionError)


@retry(retry_on_exception=retry_if_urlerror_error, stop_max_attempt_number=10)
def retrieve_sites_info_awac_kml(kml_url=AWAC_KML_URL):
    """
    downloads a kml from dept_of_transport WA. retrieve informations to create a dictionary of site info(lat, lon, data url ...
    :param kml_url: string url kml to parse
    :return: dictionary
    """

    logger.info('Parsing {url}'.format(url=kml_url))
    try:
        fileobject = requests.get(kml_url).content
    except:
        logger.error('{url} not reachable. Retry'.format(url=kml_url))
        raise requests.ConnectionError

    root = kml_parser.fromstring(fileobject)
    doc = root.Document.Folder

    sites_info = dict()
    for pm in doc.Placemark:

        coordinates = pm.Point.coordinates.pyval
        latitude = float(coordinates.split(',')[1])
        longitude = float(coordinates.split(',')[0])
        water_depth = float(coordinates.split(',')[2])

        description = pm.description.text

        snippet = pm.snippet.pyval
        time_start = snippet.split(' - ')[0]
        time_end = snippet.split(' - ')[1]
        time_start = datetime.datetime.strptime(time_start, '%Y-%m-%d')
        time_end = datetime.datetime.strptime(time_end, '%Y-%m-%d')

        name = pm.name.text
        soup = BeautifulSoup(description)
        text_zip_url = soup.findAll('a', attrs={'href': re.compile("^http(s|)://.*_Text.zip")})[0].attrMap['href']

        m = re.search('<b>AWAC LOCATION ID:</b>(.*)<br>', description)
        site_code = m.group(1).lstrip()
        logger.info('{site} available for download'.format(site=site_code))
        site_info = {'site_name': name,
                     'lat_lon': [latitude, longitude],
                     'timezone': 8,
                     'latitude': latitude,
                     'longitude': longitude,
                     'water_depth': water_depth,
                     'time_start': time_start,
                     'time_end': time_end,
                     'text_zip_url': text_zip_url,
                     'site_code': site_code}
        sites_info[site_code] = site_info

    return sites_info


@retry(retry_on_exception=retry_if_urlerror_error, stop_max_attempt_number=20)
def download_site_data(site_info):
    """
    download to a temporary directory the data
    :param site_info: a sub-dictionary of site information from retrieve_sites_info_awac_kml function
    :return:
    """
    temp_dir = tempfile.mkdtemp()

    logger.info('downloading data for {site_code} to {temp_dir}'.format(site_code=site_info['site_code'],
                                                                        temp_dir=temp_dir))

    try:
        r = requests.get(site_info['text_zip_url'])
    except:
        logger.error('{url} not reachable. Retry'.format(url=site_info['text_zip_url']))
        raise requests.ConnectionError

    zip_file_path = os.path.join(temp_dir, os.path.basename(site_info['text_zip_url']))

    with open(zip_file_path, 'wb') as f:
        f.write(r.content)

    zip_ref = zipfile.ZipFile(zip_file_path, 'r')
    zip_ref.extractall(temp_dir)
    zip_ref.close()
    os.remove(zip_file_path)

    site_path = os.listdir(temp_dir)[0]
    if site_path.endswith('_Text'):
        return os.path.join(temp_dir, site_path)


def param_mapping_parser(filepath):
    """
    parser of mapping csv file
    :param filepath: path to csv file containing mapping information between AWAC parameters and IMOS/CF parameters
    :return: pandas dataframe of filepath
    """
    if not filepath:
        logger.error('No PARAMETER MAPPING file available')
        exit(1)

    df = pd.read_table(filepath, sep=r",",
                       engine='python')
    df.set_index('ORIGINAL_VARNAME', inplace=True)
    return df


def metadata_parser(filepath):
    """
    parser of location metadata file
    :param filepath: txt file path of metadata file
    :return: pandas dataframe of data metadata, pandas dataframe of metadata
    """

    try:
        df = pd.read_csv(filepath, sep=r"(\s{2})+", skiprows=8,
                         skipinitialspace=True,
                         date_parser=lambda x: pd.strip().datetime.strptime(x, '%d/%m/%Y'),
                         header=None,
                         engine='python')

        df_default = True

        # cleaning manually since df.dropna(axis=1, how='all') doesn't work
        # move by 1 the index since using inplace option
        for col_idx in [1, 2, 3, 4, 5]:
            try:
                df.drop(df.columns[col_idx], axis=1, inplace=True)
            except Exception, e:
                logger.info('No comment data in metadata file. {err}'.format(err=e))
    except:
        df = pd.read_csv(filepath, sep=r"\s{2}", skiprows=8,
                         skipinitialspace=True,
                         index_col=False,
                         header=None,
                         engine='python')
        df.dropna(axis=1, how='all', inplace=True)
        df_default = False

    if df.shape[1] == 6:
        df.columns = ['deployment_name', 'start_date', 'end_date', 'instrument_maker', 'instrument_model', 'comment']
    elif df.shape[1] == 5:  # means comment column is empty
        df.columns = ['deployment_name', 'start_date', 'end_date', 'instrument_maker', 'instrument_model']
        df["comment"] = ""
    elif df.shape[1] > 5:
        df['comment'] = df[df.columns[5:]].apply(lambda x: ','.join(x.astype(str)), axis=1)  # merging last columns into a comment
        df.drop(df.columns[5: df.shape[1]-1], axis=1, inplace=True)
        df.columns = ['deployment_name', 'start_date', 'end_date', 'instrument_maker', 'instrument_model', 'comment']

    df.set_index('deployment_name', inplace=True)

    # strip leading/trailing spaces from values
    for col in df.columns:
        df[col] = df[col].str.strip()

    if not df_default:
        df['start_date'] = pd.to_datetime(df['start_date'].map(lambda x: x.strip()), format='%d/%m/%Y')
        df['end_date'] = pd.to_datetime(df['end_date'].map(lambda x: x.strip()), format='%d/%m/%Y')

    timezone = pd.read_csv(filepath, skiprows=1, nrows=1, header=None)[0][0].strip(
        '#Time Zone: Australian Western Standard Time  (UTC +').rstrip(')')
    timezone = parser.parse(timezone[:]).time()

    lat_lon_str = pd.read_csv(filepath, skiprows=2, nrows=1, header=None)[0][0]
    lat_lon_vals = re.findall(r"[-+]?\d*\.\d+|\d+", pd.read_csv(filepath, skiprows=2, nrows=1, header=None)[0][0])
    lat_lon_vals = [float(s) for s in lat_lon_vals]

    water_depth_str = pd.read_csv(filepath, skiprows=3, nrows=1, header=None)[0][0]
    water_depth_val = re.findall(r"[-+]?\d*\.\d+|\d+", water_depth_str)
    water_depth_val = [float(s) for s in water_depth_val]

    station_name_str = pd.read_csv(filepath, nrows=1, header=None)[0][0].strip('#Station metadata at ')
    site_code = os.path.basename(os.path.normpath(filepath)).split('_')[0]

    return df, {'site_name': station_name_str,
                'site_code' : site_code,
                'water_depth': water_depth_val,
                'lat_lon': lat_lon_vals,
                'timezone': timezone.hour + timezone.minute/60
                }


def ls_txt_files(path):
    """
    list text files from path
    :param path: path to find txt files extension in
    :return: list of txt files
    """
    return ls_ext_files(path, '.txt')


def ls_ext_files(path, extension):
    """
    list text files from path
    :param path: path to find txt files extension in
    :param extension: ".txt", ".csv" ...
    :return: list of files matching extension
    """
    file_ls = []
    for file in os.listdir(path):
        if file.endswith(extension):
            file_ls.append(os.path.join(path, file))

    return file_ls


def set_glob_attr(nc_file_obj, data, metadata, site_info):
    """
    Set generic global attributes in netcdf file object
    :param nc_file_obj: NetCDF4 object already opened
    :param data:
    :param metadata:
    :return:
    """
    deployment_code = metadata[1]['deployment_code']
    setattr(nc_file_obj, 'data_collected_readme_url', README_URL)
    setattr(nc_file_obj, 'instrument_maker', metadata[0].loc[deployment_code]['instrument_maker'])
    setattr(nc_file_obj, 'instrument_model', metadata[0].loc[deployment_code]['instrument_model'])
    if metadata[0].loc[deployment_code]['comment']:
        setattr(nc_file_obj, 'comment', metadata[0].loc[deployment_code]['comment'])
    setattr(nc_file_obj, 'deployment_code', deployment_code)
    setattr(nc_file_obj, 'site_code', metadata[1]['site_code'])
    setattr(nc_file_obj, 'site_name', metadata[1]['site_name'])
    setattr(nc_file_obj, 'water_depth', metadata[1]['water_depth'])
    setattr(nc_file_obj, 'geospatial_lat_min', metadata[1]['lat_lon'][0])
    setattr(nc_file_obj, 'geospatial_lat_max', metadata[1]['lat_lon'][0])
    setattr(nc_file_obj, 'geospatial_lon_min', metadata[1]['lat_lon'][1])
    setattr(nc_file_obj, 'geospatial_lon_max', metadata[1]['lat_lon'][1])
    setattr(nc_file_obj, 'time_coverage_start',
            data.datetime.dt.strftime('%Y-%m-%dT%H:%M:%SZ').values.min())
    setattr(nc_file_obj, 'time_coverage_end',
            data.datetime.dt.strftime('%Y-%m-%dT%H:%M:%SZ').values.max())
    setattr(nc_file_obj, 'date_created', pd.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    setattr(nc_file_obj, 'local_time_zone', metadata[1]['timezone'])
    setattr(nc_file_obj, 'original_data_url', site_info['text_zip_url'])


def set_var_attr(nc_file_obj, var_mapping, nc_varname, df_varname_mapped_equivalent, dtype):
    """
    set variable attributes of an already opened NetCDF file
    :param nc_file_obj:
    :param var_mapping:
    :param nc_varname:
    :param df_varname_mapped_equivalent:
    :param dtype:
    :return:
    """

    setattr(nc_file_obj[nc_varname], 'units', var_mapping.loc[df_varname_mapped_equivalent]['UNITS'])

    if not pd.isnull(var_mapping.loc[df_varname_mapped_equivalent]['LONG_NAME']):
        setattr(nc_file_obj[nc_varname], 'long_name', var_mapping.loc[df_varname_mapped_equivalent]['LONG_NAME'])
    else:
        setattr(nc_file_obj[nc_varname], 'long_name',
                var_mapping.loc[df_varname_mapped_equivalent]['STANDARD_NAME'].replace('_', ' '))

    if not pd.isnull(var_mapping.loc[df_varname_mapped_equivalent]['STANDARD_NAME']):
        setattr(nc_file_obj[nc_varname], 'standard_name', var_mapping.loc[df_varname_mapped_equivalent]['STANDARD_NAME'])

    if not pd.isnull(var_mapping.loc[df_varname_mapped_equivalent]['VALID_MIN']):
        setattr(nc_file_obj[nc_varname], 'valid_min', var_mapping.loc[df_varname_mapped_equivalent]['VALID_MIN'].astype(dtype))

    if not pd.isnull(var_mapping.loc[df_varname_mapped_equivalent]['VALID_MAX']):
        setattr(nc_file_obj[nc_varname], 'valid_max', var_mapping.loc[df_varname_mapped_equivalent]['VALID_MAX'].astype(dtype))

    if not pd.isnull(var_mapping.loc[df_varname_mapped_equivalent]['ANCILLARY_VARIABLES']):
        setattr(nc_file_obj[nc_varname], 'ancillary_variables',
                var_mapping.loc[df_varname_mapped_equivalent]['ANCILLARY_VARIABLES'])

    if not pd.isnull(var_mapping.loc[df_varname_mapped_equivalent]['REFERENCE_DATUM']):
        setattr(nc_file_obj[nc_varname], 'reference_datum',
                var_mapping.loc[df_varname_mapped_equivalent]['REFERENCE_DATUM'])

    if not pd.isnull(var_mapping.loc[df_varname_mapped_equivalent]['POSITIVE']):
        setattr(nc_file_obj[nc_varname], 'positive', var_mapping.loc[df_varname_mapped_equivalent]['POSITIVE'])
