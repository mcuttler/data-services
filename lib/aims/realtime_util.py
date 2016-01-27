#/usr/bin/env python
""" set of tools to
- parse AIMS RSS feed web pages
- create a list of monthly timestamps to download
- generate URL to download (with regards to what has already been downloaded
- unzip and modify NetCDF files so they pass both CF and IMOS checker

data.aims.gov.au/gbroosdata/services/rss/netcdf/level0/1    -> FAIMMS
data.aims.gov.au/gbroosdata/services/rss/netcdf/level0/100  -> SOOP TRV
data.aims.gov.au/gbroosdata/services/rss/netcdf/level0/300  -> NRS DARWIN YONGALA BEAGLE

author Laurent Besnard, laurent.besnard@utas.edu.au
"""

import urllib2, urllib
import xml.etree.ElementTree as ET
import tempfile
import zipfile
import logging
import pickle
import os, sys
import subprocess, shlex
import shutil
from netCDF4 import num2date, date2num, Dataset
import time
from time import gmtime, strftime
from datetime import date, datetime
import re

#####################
# Logging Functions #
#####################
def logging_aims():
    """ start logging using logging python library
    output:
       logger - similar to a file handler
    """
    logging.basicConfig(level = logging.INFO)

    wip_path = os.environ.get('data_wip_path')
    # this is used for unit testing as data_wip_path env would not be set
    if wip_path is None:
        wip_path = tempfile.mkdtemp()

    logger  = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # create a file handler
    handler = logging.FileHandler(os.path.join(wip_path, 'aims.log'))
    handler.setLevel(logging.INFO)

    # create a logging format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # add the handlers to the logger
    logger.addHandler(handler)
    return logger

def close_logger(logger):
    """ close logging
    input:
       logger : logging handler generated by logging_aims()
    """
    #closes the handlers of the specified logger only
    x = list(logger.handlers)
    for i in x:
        logger.removeHandler(i)
        i.flush()
        i.close()

####################
# Pickle Functions #
####################
def _pickle_filename(level_qc):
    """ returns the pickle filepath according to the QC level being processed
    input:
        level_qc(int) : 0 or 1
    output:
        picleQc_file(str) : pickle file path
    """
    wip_path = os.environ.get('data_wip_path')

    if level_qc == 0:
        pickle_qc_file = os.path.join(wip_path, 'aims_qc0.pickle')
    elif level_qc == 1:
        pickle_qc_file = os.path.join(wip_path, 'aims_qc1.pickle')

    return pickle_qc_file

from retrying import retry
@retry(urllib2.URLError, tries=10, delay=3, backoff=2)
def urlopen_with_retry(url):
    """ it will retry a maximum of 10 times, with an exponential backoff delay
    doubling each time, e.g. 3 seconds, 6 seconds, 12 seconds
    """
    return urllib2.urlopen(url)

def save_channel_info(channel_id, aims_xml_info, level_qc, *last_downloaded_date_channel):
    """
     if channel_id has been successfuly processed, we write about it in a pickle file
     we write the last downloaded data date for each channel
     input:
        channel_id(str)       : channel_id to save information
        aims_xml_info(tupple) : generated by parser_aims_xml
        level_qc(int)         : 0 or 1
        last_downloaded_date_channel is a variable argument, not used by soop trv
    """
    pickle_file = _pickle_filename(level_qc)

    # condition in case the pickle file already exists or not. In the first case,
    # aims_xml_info comes from the pickle, file, otherwise comes from the function arg
    if os.path.isfile(pickle_file):
        with open(pickle_file, 'rb') as p_read:
            aims_xml_info = pickle.load(p_read)

        channel_id_index     = aims_xml_info[0].index(channel_id) # value important to write last_downloaded_date to correct index
        last_downloaded_date = aims_xml_info[-1]
    else:
        last_downloaded_date = [None] * len(aims_xml_info[0]) # initialise array
        channel_id_index     = aims_xml_info[0].index(channel_id)

    channel_id_info                        = get_channel_info(channel_id, aims_xml_info)

    if not last_downloaded_date_channel:
        # soop trv specific, vararg
        last_downloaded_date[channel_id_index] = channel_id_info[2] # fromDate
    else:
        last_downloaded_date_channel = ''.join(last_downloaded_date_channel) # convert varargs tupple argument to string
        last_downloaded_date[channel_id_index] = last_downloaded_date_channel

    pickle_db                              = aims_xml_info[0:-1] + (last_downloaded_date,) # add to tupple

    with open(pickle_file, 'wb') as p_write:
        pickle.dump(pickle_db, p_write)

def get_last_downloaded_date_channel(channel_id, level_qc, from_date):
    """ Retrieve the last date sucessfully downloaded for a channel """
    pickle_file = _pickle_filename(level_qc) # different pickle per QC
    if os.path.isfile(pickle_file):
        with open(pickle_file, 'rb') as p_read:
            pickle_db = pickle.load(p_read)

        if channel_id in pickle_db[0]: # check the channel is in the pickle file
            channel_id_index = pickle_db[0].index(channel_id)

            if pickle_db[-1][channel_id_index] is not None: # check the last downloaded_date field
                return pickle_db[-1][channel_id_index]

    return from_date

def has_channel_already_been_downloaded(channel_id, level_qc):
    pickle_file = _pickle_filename(level_qc) # different pickle per QC
    if os.path.isfile(pickle_file):
        with open(pickle_file, 'rb') as p_read:
            pickle_db = pickle.load(p_read)

        if channel_id in pickle_db[0]: # check the channel is in the pickle file
            channel_id_index = pickle_db[0].index(channel_id)

            if pickle_db[-1][channel_id_index] is not None: # check the last downloaded_date field
                return True
            else:
                return False
        else:
            return False

    else:
        return False

def create_list_of_dates_to_download(channel_id, level_qc, from_date, thru_date):
    """ generate a list of monthly start dates and end dates to download FAIMMS and NRS data """

    from dateutil import rrule
    from datetime import datetime, timedelta
    from dateutil.relativedelta import relativedelta

    last_downloaded_date = get_last_downloaded_date_channel(channel_id, level_qc, from_date)
    start_dates          = []
    end_dates            = []

    from_date            = datetime.strptime(from_date, "%Y-%m-%dT%H:%M:%SZ")
    thru_date            = datetime.strptime(thru_date, "%Y-%m-%dT%H:%M:%SZ")
    last_downloaded_date = datetime.strptime(last_downloaded_date, "%Y-%m-%dT%H:%M:%SZ")

    if last_downloaded_date < thru_date:
        for dt in rrule.rrule(rrule.MONTHLY, dtstart=datetime(last_downloaded_date.year, last_downloaded_date.month, 1), until=thru_date):
            start_dates.append(dt)
            end_dates.append(datetime(dt.year, dt.month , 1) + relativedelta(months=1))

        end_dates[-1] = thru_date

    return start_dates, end_dates

def md5(fname):
    """ return a md5 checksum of a file """
    import hashlib

    hash = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash.update(chunk)
    return hash.hexdigest()

######################
# XML Info Functions #
######################
def parse_aims_xml(xml_url):
    """ Download and parse the AIMS XML rss feed """
    logger          = logging_aims()
    logger.info('parse AIMS xml : %s' % (xml_url))
    response        = urllib2.urlopen(xml_url)
    html            = response.read()
    root            = ET.fromstring(html)

    next_item_exist = True
    n_item          = 3 # start number for AIMS xml file

    title           = []
    link            = []
    metadata_uuid   = []
    uom             = []
    from_date       = []
    thru_date       = []
    platform_name   = []
    site_name       = []
    channel_id      = []
    parameter       = []
    parameter_type  = []
    trip_id         = [] # soop trv only

    while next_item_exist:
        title         .append(root[0][n_item][0].text)
        link          .append(root[0][n_item][1].text)
        metadata_uuid .append(root[0][n_item][6].text)
        uom           .append(root[0][n_item][7].text)
        from_date     .append(root[0][n_item][8].text)
        thru_date     .append(root[0][n_item][9].text)
        platform_name .append(root[0][n_item][10].text)
        site_name     .append(root[0][n_item][11].text)
        channel_id    .append(root[0][n_item][12].text)
        parameter     .append(root[0][n_item][13].text)
        parameter_type.append(root[0][n_item][14].text)

        # in case there is no trip id defined by AIMS, we create a fake one, used by SOOP TRV only
        try:
            trip_id   .append(root[0][n_item][15].text)
        except IndexError:
            dateObject   = time.strptime(root[0][n_item][8].text,"%Y-%m-%dT%H:%M:%SZ")
            trip_id_fake = str(dateObject.tm_year) + str(dateObject.tm_mon).zfill(2) + str(dateObject.tm_mday).zfill(2)
            trip_id.append(trip_id_fake)

        n_item += 1
        # test if next item in XML file exists
        try:
            root[0][n_item +1]
            next_item_exist = True
        except IndexError:
            next_item_exist = False

    response.close()
    close_logger(logger)
    return channel_id, from_date, thru_date, metadata_uuid, uom, platform_name, site_name, parameter, parameter_type, trip_id

def get_channel_info(channel_id, aims_xml_info):
    """ returns all the informations found in the parsed AIMS xml file for one channel only
    input:
        channel_id(int) : channel_id to return info from
        aims_xml_info   : generated by parse_aims_xml
    output:
        similar as parse_aims_xml
    """

    channel_id_index = aims_xml_info[0].index(channel_id)
    from_date        = aims_xml_info[1][channel_id_index]
    thru_date        = aims_xml_info[2][channel_id_index]
    metadata_uuid    = aims_xml_info[3][channel_id_index]
    uom              = aims_xml_info[4][channel_id_index]
    platform_name    = aims_xml_info[5][channel_id_index]
    site_name        = aims_xml_info[6][channel_id_index]
    parameter        = aims_xml_info[7][channel_id_index]
    parameter_type   = aims_xml_info[8][channel_id_index]

    try:
        trip_id          = aims_xml_info[9][channel_id_index]
        is_trip_id_exist = True
    except:
        is_trip_id_exist = False

    if is_trip_id_exist is True:
        trip_id = aims_xml_info[9][channel_id_index]
        return channel_id, from_date, thru_date, metadata_uuid, uom, platform_name, site_name, parameter, parameter_type, trip_id
    else:
        return channel_id, from_date, thru_date, metadata_uuid, uom, platform_name, site_name, parameter, parameter_type

##########################################
# Channel Process/Download/Mod Functions #
##########################################
def download_channel(channel_id, from_date, thru_date, level_qc):
    """ generated the data link to download, and extract the zip file into a temp file
    input:
        channel_id(str) : channel_id to download
        from_date(str)  : str containing the first time to start the download from written in this format 2009-04-21_t10:43:54Z
        thru_date(str)  : same as above but for the last date
        level_qc(int)   : 0 or 1
    """
    logger            = logging_aims()
    tmp_zip_file      = tempfile.mkstemp()
    netcdf_tmp_path   = tempfile.mkdtemp()
    url_data_download = 'http://data.aims.gov.au/gbroosdata/services/data/rtds/%s/level%s/raw/raw/%s/%s/netcdf/2' % (channel_id, str(level_qc), from_date, thru_date)
    urllib.urlretrieve(url_data_download, tmp_zip_file[1])
    zip               = zipfile.ZipFile(tmp_zip_file[1])

    for name in zip.namelist():
        zip.extract(name, netcdf_tmp_path)
        netcdf_file_path = os.path.join(netcdf_tmp_path, name)

    zip.close()
    os.close(tmp_zip_file[0])
    os.remove(tmp_zip_file[1]) #file object needs to be closed or can end up with too many open files

    logger.info('     %s downloaded successfuly' %url_data_download)
    close_logger(logger)
    return netcdf_file_path

####################################
# Functions to modify NetCDF files #
# AIMS NetCDF file specific only   #
####################################
def is_no_data_found(netcdf_file_path):
    """ Check if the unzipped file is a 'NO_DATA_FOUND' file instead of a netCDF file
    this behaviour is correct for FAIMMS and NRS, as it means no data for the selected
    time period. However it doesn't make sense for SOOP TRV
    """
    return os.path.basename(netcdf_file_path) == 'NO_DATA_FOUND'

def rename_netcdf_attribute(object_, old_attribute_name, new_attribute_name):
    """ Rename global attribute from netcdf4 dataset object
      object             = Dataset(netcdf_file, 'a', format='NETCDF4')
      old_attribute_name = current gatt name to modify
      new_attribute_name = new gatt name
    """
    setattr(object_, new_attribute_name, getattr(object_, old_attribute_name))
    delattr(object_, old_attribute_name)

def is_time_var_empty(netcdf_file_path):
    """ check if the yet unmodified file (time instead of TIME) has values in its time variable """
    netcdf_file_obj = Dataset(netcdf_file_path, 'r', format='NETCDF4')
    var_obj         = netcdf_file_obj.variables['time']

    if var_obj.shape[0] == 0:
        return True

    var_values = var_obj[:]
    netcdf_file_obj.close()

    return not var_values.any()

def convert_time_cf_to_imos(netcdf_file_path):
    """  convert a CF time into an IMOS one forced to be 'days since 1950-01-01 00:00:00'
    the variable HAS to be 'TIME'
    """
    try:
        netcdf_file_obj = Dataset(netcdf_file_path, 'a', format='NETCDF4')
        time            = netcdf_file_obj.variables['TIME']
        dtime           = num2date(time[:], time.units, time.calendar) # this gives an array of datetime objects
        time.units      = 'days since 1950-01-01 00:00:00 UTC'
        time[:]         = date2num(dtime, time.units, time.calendar) # conversion to IMOS recommended time
        netcdf_file_obj.close()
        return True
    except:
        return False

def strictly_increasing(list):
    """ check monotocity of list of values"""
    return all(x<y for x, y in zip(list, list[1:]))

def is_time_monotonic(netcdf_file_path):
    netcdf_file_obj = Dataset(netcdf_file_path, 'r', format='NETCDF4')
    time            = netcdf_file_obj.variables['TIME'][:]
    netcdf_file_obj.close()
    if not strictly_increasing(time):
        return False
    return True

def modify_aims_netcdf(netcdf_file_path, channel_id_info):
    """ Modify the downloaded netCDF file so it passes both CF and IMOS checker
    input:
       netcdf_file_path(str)    : path of netcdf file to modify
       channel_id_index(tupple) : information from xml for the channel
    """
    netcdf_file_obj                 = Dataset(netcdf_file_path, 'a', format='NETCDF4')

    # add gatts to NetCDF
    netcdf_file_obj.aims_channel_id = int(channel_id_info[0])

    if not (channel_id_info[3] == 'Not Available'):
        netcdf_file_obj.metadata_uuid = channel_id_info[3]

    if not netcdf_file_obj.instrument_serial_number:
        del(netcdf_file_obj.instrument_serial_number)

    # add CF gatts, values stored in lib/netcdf/netcdf-cf-imos-compliance.sh
    netcdf_file_obj.Conventions            = os.environ.get('CONVENTIONS')
    netcdf_file_obj.data_centre_email      = os.environ.get('DATA_CENTRE_EMAIL')
    netcdf_file_obj.data_centre            = os.environ.get('DATA_CENTRE')
    netcdf_file_obj.project                = os.environ.get('PROJECT')
    netcdf_file_obj.acknowledgement        = os.environ.get('ACKNOWLEDGEMENT')
    netcdf_file_obj.distribution_statement = os.environ.get('DISTRIBUTION_STATEMENT')

    netcdf_file_obj.date_created           = strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())
    netcdf_file_obj.quality_control_set    = 1
    imos_qc_convention                     = 'IMOS standard set using the IODE flags'
    netcdf_file_obj.author                 = 'laurent besnard'
    netcdf_file_obj.author_email           = 'laurent.besnard@utas.edu.au'

    rename_netcdf_attribute(netcdf_file_obj, 'geospatial_LAT_max', 'geospatial_lat_max')
    rename_netcdf_attribute(netcdf_file_obj, 'geospatial_LAT_min', 'geospatial_lat_min')
    rename_netcdf_attribute(netcdf_file_obj, 'geospatial_LON_max', 'geospatial_lon_max')
    rename_netcdf_attribute(netcdf_file_obj, 'geospatial_LON_min', 'geospatial_lon_min')

    # variables modifications
    time           = netcdf_file_obj.variables['time']
    time.calendar  = 'gregorian'
    time.axis      = 'T'
    time.valid_min = 0.0
    time.valid_max = 9999999999.0
    netcdf_file_obj.renameDimension('time','TIME')
    netcdf_file_obj.renameVariable('time','TIME')

    netcdf_file_obj.time_coverage_start = num2date(time[:], time.units, time.calendar).min().strftime('%Y-%m-%dT%H:%M:%SZ')
    netcdf_file_obj.time_coverage_end   = num2date(time[:], time.units, time.calendar).max().strftime('%Y-%m-%dT%H:%M:%SZ')

    # latitude longitude
    latitude                  = netcdf_file_obj.variables['LATITUDE']
    latitude.axis             = 'Y'
    latitude.valid_min        = -90.0
    latitude.valid_max        = 90.0
    latitude.reference_datum  = 'geographical coordinates, WGS84 projection'
    latitude.standard_name    = 'latitude'
    latitude.long_name        = 'latitude'

    longitude                 = netcdf_file_obj.variables['LONGITUDE']
    longitude.axis            = 'X'
    longitude.valid_min       = -180.0
    longitude.valid_max       = 180.0
    longitude.reference_datum = 'geographical coordinates, WGS84 projection'
    longitude.standard_name   = 'longitude'
    longitude.long_name       = 'longitude'

    # Change variable name, standard name, longname, untis ....
    if 'Seawater_Intake_Temperature' in netcdf_file_obj.variables.keys():
        var                     = netcdf_file_obj.variables['Seawater_Intake_Temperature']
        var.units               = 'Celsius'
        netcdf_file_obj.renameVariable('Seawater_Intake_Temperature', 'TEMP')
        netcdf_file_obj.renameVariable('Seawater_Intake_Temperature_quality_control', 'TEMP_quality_control')
        var.ancillary_variables = 'TEMP_quality_control'

    if 'PSAL' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.variables['PSAL'].units = '1e-3'

    if 'TURB' in netcdf_file_obj.variables.keys():
        var                                                             = netcdf_file_obj.variables['TURB']
        var.units                                                       = '1'
        var.standard_name                                               = 'sea_water_turbidity'
        netcdf_file_obj.variables['TURB_quality_control'].standard_name = 'sea_water_turbidity status_flag'

    if 'DOWN_PHOTOSYNTH_FLUX' in netcdf_file_obj.variables.keys():
        var       = netcdf_file_obj.variables['DOWN_PHOTOSYNTH_FLUX']
        var.units = 'W m-2'


    def clean_no_cf_variables(var, netcdf_file_obj):
        """
        remove standard name of main variable and of its ancillary qc var if exists
        """
        if var in netcdf_file_obj.variables.keys():
            if hasattr(netcdf_file_obj.variables[var], 'standard_name'):
               del(netcdf_file_obj.variables[var].standard_name)
        var_qc = '%s_quality_control' %var
        if var_qc in netcdf_file_obj.variables.keys():
            if hasattr(netcdf_file_obj.variables[var_qc], 'standard_name'):
                del(netcdf_file_obj.variables[var_qc].standard_name)
            if hasattr(netcdf_file_obj.variables[var], 'ancillary_variables'):
                netcdf_file_obj.variables[var].ancillary_variables = var_qc

    if 'fluorescence' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.renameVariable('fluorescence','CPHL')
        netcdf_file_obj.variables['CPHL'].long_name = 'mass_concentration_of_inferred_chlorophyll_from_relative_fluorescence_units_in_sea_water_concentration_of_chlorophyll_in_sea_water'
        if 'fluorescence_quality_control' in  netcdf_file_obj.variables.keys():
            netcdf_file_obj.renameVariable('fluorescence_quality_control','CPHL_quality_control')
            netcdf_file_obj.variables['CPHL_quality_control'].long_name = 'mass_concentration_of_inferred_chlorophyll_from_relative_fluorescence_units_in_sea_waterconcentration_of_chlorophyll_in_sea_water status_flag'
        clean_no_cf_variables('CPHL', netcdf_file_obj)

    if 'WDIR_10min' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.variables['WDIR_10min'].units = 'degree'

    if 'WDIR_30min' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.variables['WDIR_30min'].units = 'degree'

    if 'R_sigma_30min' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.variables['R_sigma_30min'].units = 'degree'
        clean_no_cf_variables('R_sigma_30min', netcdf_file_obj)

    if 'WDIR_sigma_10min' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.variables['WDIR_sigma_10min'].units = 'degree'
        clean_no_cf_variables('WDIR_sigma_10min', netcdf_file_obj)

    if 'WDIR_sigma_30min' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.variables['WDIR_sigma_30min'].units = 'degree'
        clean_no_cf_variables('WDIR_sigma_30min', netcdf_file_obj)

    if 'ATMP' in netcdf_file_obj.variables.keys():
        netcdf_file_obj.variables['ATMP'].units = 'hPa'

    if 'RAIN_DURATION' in netcdf_file_obj.variables.keys():
        clean_no_cf_variables('RAIN_DURATION', netcdf_file_obj)

    if 'HAIL_DURATION' in netcdf_file_obj.variables.keys():
        clean_no_cf_variables('HAIL_DURATION', netcdf_file_obj)

    if 'HAIL_HIT' in netcdf_file_obj.variables.keys():
        clean_no_cf_variables('HAIL_HIT', netcdf_file_obj)
        netcdf_file_obj.variables['HAIL_HIT'].comment = netcdf_file_obj.variables['HAIL_HIT'].units
        netcdf_file_obj.variables['HAIL_HIT'].units = '1'

    if 'HAIL_INTENSITY_10min' in netcdf_file_obj.variables.keys():
        clean_no_cf_variables('HAIL_INTENSITY_10min', netcdf_file_obj)
        netcdf_file_obj.variables['HAIL_INTENSITY_10min'].comment = netcdf_file_obj.variables['HAIL_INTENSITY_10min'].units
        netcdf_file_obj.variables['HAIL_INTENSITY_10min'].units = '1'

    # add qc conventions to qc vars
    variables = netcdf_file_obj.variables.keys()
    qc_vars = [s for s in variables if '_quality_control' in s]
    if qc_vars != []:
        for var in qc_vars:
            netcdf_file_obj.variables[var].quality_control_conventions = imos_qc_convention

    # clean longnames, force lower case, remove space, remove double underscore
    for var in variables:
        if hasattr(netcdf_file_obj.variables[var], 'long_name'):
            netcdf_file_obj.variables[var].long_name = netcdf_file_obj.variables[var].long_name.replace('__','_')
            netcdf_file_obj.variables[var].long_name = netcdf_file_obj.variables[var].long_name.replace(' _','_')
            netcdf_file_obj.variables[var].long_name = netcdf_file_obj.variables[var].long_name.lower()

    netcdf_file_obj.close()

def has_var_only_fill_value(netcdf_file_path, var):
    """ some channels have only _Fillvalues in their main variable. This is not correct and need
    to be tested
    var is a string of the variable to test
    """
    netcdf_file_obj = Dataset(netcdf_file_path, 'r', format='NETCDF4')
    var_obj         = netcdf_file_obj.variables[var]
    var_values      = var_obj[:]
    netcdf_file_obj.close()

    # if no fill value in variable, no mask attribute
    if hasattr(var_values,'mask'):
        return all(var_values.mask)
    else:
        return False

def remove_dimension_from_netcdf(netcdf_file_path):
    """ DIRTY, calling bash. need to write in Python, or part of the NetCDF4 module
    need to remove the 'single' dimension name from DEPTH or other dim. Unfortunately can't seem to find a way to do it easily with netCDF4 module
    """
    subprocess.check_call(['ncwa', '-O', '-a', 'single', netcdf_file_path, netcdf_file_path])

def remove_end_date_from_filename(netcdf_filename):
    """ remove the _END-* part of the file, as we download monthly file. This helps
    to overwrite file with new data for the same month
    """
    return re.sub('_END-.*$', '.nc', netcdf_filename)

def pass_netcdf_checker(netcdf_file_path):
    """Calls the netcdf checker and run the IMOS and CF tests.
    Returns True if passes , False otherwise
    """
    if not os.environ.get('NETCDF_CHECKER'):
        raise NameError('NETCDF_CHECKER env not found')

    netcdf_checker_path = os.path.dirname(os.path.realpath(os.environ.get('NETCDF_CHECKER')))
    sys.path.insert(0, netcdf_checker_path)
    import cchecker

    tmp_json_checker_output = tempfile.mkstemp()
    tests                   = ['cf', 'imos']
    return_values           = []
    had_errors              = []
    for test in tests:
        # creation of a tmp json file. Only way (with html) to create an output not displayed to stdin by default
        return_value, errors = cchecker.ComplianceChecker.run_checker(netcdf_file_path, [test] , 'None', 'normal', tmp_json_checker_output[1], 'json')
        had_errors.append(errors)
        return_values.append(return_value)

    os.close(tmp_json_checker_output[0])
    os.remove(tmp_json_checker_output[1]) #file object needs to be closed or can end up with too many open files

    if any(had_errors):
        return False # checker exceptions
    if all(return_values):
        return True # all tests passed
    return False # at least one did not pass

def set_up():
    """
    set up wip facility directories
    """
    wip_path = os.environ.get('data_wip_path')
    if not wip_path:
        logger = logging_aims()
        logger.error('data_wip_path from config.txt is empty')
        close_logger(logger)
        exit(1)

    if not os.path.exists(wip_path):
        os.makedirs(wip_path)

    if not os.path.exists(os.path.join(wip_path,'errors')):
        os.makedirs(os.path.join(wip_path,'errors'))
