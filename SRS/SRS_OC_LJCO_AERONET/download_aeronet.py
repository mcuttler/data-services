#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Tue Oct  7 11:45:44 2014
This script downloads a lev20 file (CSV) and unzip it in the IMOS public folder
/SRS/SRS-OC-LJCO/AERONET

@author: lbesnard
laurent.besnard@utas.edu.au
"""

import sys
import os
sys.path.insert(0, os.path.join(os.environ.get('DATA_SERVICES_DIR'), 'lib'))
from python.imos_logging import IMOSLogging
from BeautifulSoup import BeautifulSoup
import urllib2
import re
import zipfile
from tempfile import mkdtemp, mkstemp
from urllib import urlopen
from StringIO import StringIO
import glob
import shutil

NASA_LEV2_URL = "http://aeronet.gsfc.nasa.gov/cgi-bin/print_warning_opera_v2_new?site=Lucinda&year=110&month=6&day=1&year2=110&month2=6&day2=30&LEV20=1&AVG=10"

def download_ljco_aeronet(download_dir):
    logger.info('Open NASA webpage')
    htmlPage     = urllib2.urlopen(NASA_LEV2_URL)
    htmlPageSoup = BeautifulSoup(htmlPage)

    # scrap webpage to find zip file address
    webpageBase, value = NASA_LEV2_URL.split("/cgi-bin", 1)
    for link in htmlPageSoup.findAll('a', attrs={'href': re.compile("^.zip")}):
        dataWebLink = webpageBase + link.get('href')

    logger.info('Downloading AERONET data')
    url_data_object = urlopen(dataWebLink)
    temp_dir        = mkdtemp()

    with zipfile.ZipFile(StringIO(url_data_object.read())) as zip_data:
        zip_data.extractall(temp_dir)

    data_file    = glob.glob('%s/*Lucinda.lev20' % temp_dir)[0]

    logger.info('Cleaning AERONET data')
    f        = open(data_file, 'r')
    filedata = f.read()
    f.close()

    replaced_data = filedata.replace("N/A", "")

    f = open(data_file, 'w')
    f.write(replaced_data)
    f.close()

    if os.path.exists(download_dir):
        shutil.move(data_file, os.path.join(download_dir, 'Lucinda.lev20'))
    else:
        logger.error('%s does not exists' % download_dir)

    shutil.rmtree(temp_dir)


if __name__ == "__main__":
    logging = IMOSLogging()
    log_file = [mkstemp()]
    global logger
    logger = logging.logging_start(log_file[0][1])

    try:
        download_ljco_aeronet(sys.argv[1])
    except Exception, e:
        print e

    logging.logging_stop()
    os.close(log_file[0][0])
    os.remove(log_file[0][1])