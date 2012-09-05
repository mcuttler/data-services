function [dateforfileSQL] = radar_CODAR_create_current_data(filename, site_code, isQC)
%This subfunction will open NetCDF files and process the data in order to
%create a new netCDF file.
%This new NetCDF file will contain the current data (intensity and
%direction) averaged over an hour on a grid.
%

%see files radar_CODAR_main.m and config.txt for any changes on the
%following global variables
global dfradialdata
global inputdir
global outputdir
global ncwmsdir
global dateFormat

temp = datenum(filename(14:28), dateFormat);
dateforfileSQL = datestr(temp, dateFormat);
yearDF = dateforfileSQL(1:4);
monthDF = dateforfileSQL(5:6);
dayDF = dateforfileSQL(7:8);
clear temp

%ACCESSING THE DATA
filePath = fullfile(dfradialdata, site_code, filename(14:17), filename(18:19), filename(20:21), [filename(1:end-3), '.nc']);
ncid = netcdf.open(filePath, 'NC_NOWRITE');
temp_varid = netcdf.inqVarID(ncid, 'POSITION');
temp = netcdf.getVar(ncid, temp_varid);
POS = temp(:);

dimfile = length(POS);

temp_varid = netcdf.inqVarID(ncid, 'ssr_Surface_Eastward_Sea_Water_Velocity');
temp = netcdf.getVar(ncid, temp_varid);
EAST = temp(:);

temp_varid = netcdf.inqVarID(ncid, 'ssr_Surface_Northward_Sea_Water_Velocity');
temp = netcdf.getVar(ncid, temp_varid);
NORTH = temp(:);

%ACCESSING THE METADATA
meta.Metadata_Conventions   = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'Metadata_Conventions');
meta.title                  = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'title');
meta.id                     = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'id');
meta.geospatial_lat_min     = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'geospatial_lat_min');
meta.geospatial_lat_max     = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'geospatial_lat_max');
meta.geospatial_lon_min     = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'geospatial_lon_min');
meta.geospatial_lon_max     = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'geospatial_lon_max');
meta.time_coverage_start    = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'time_coverage_start');
meta.time_coverage_duration = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'time_coverage_duration');
meta.abstract               = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'abstract');
meta.history                = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'history');
meta.comment                = netcdf.getAtt(ncid, netcdf.getConstant('GLOBAL'), 'comment');
netcdf.close(ncid);

%
%OPEN THE TEXT FILE CONTAINING THE GRID
switch site_code
    case 'TURQ'
        fileGrid = fullfile(inputdir, 'TURQ_grid_for_ncWMS.dat');

        comptlat = 55;
        comptlon = 57;
        
    case 'BONC'
        fileGrid = fullfile(inputdir, 'BONC_grid_for_ncWMS.dat');

        comptlat = 69;
        comptlon = 69;
end

rawdata = importdata(fileGrid); 
% points are listed from bottom left to top right so a complex reshape is
% needed to transform this array in matrix
X = reshape(rawdata(:,1)', comptlon, comptlat)';
Y = reshape(rawdata(:,2)', comptlon, comptlat)';

% let's re-order points from top left to bottom right
I = (comptlat:-1:1)';
X = X(I, :);
Y = Y(I, :);

Zrad = NaN(comptlat, comptlon);
Urad = NaN(comptlat, comptlon);
Vrad = NaN(comptlat, comptlon);
QCrad = NaN(comptlat, comptlon);

% let's find out the i lines and j columns from the POSITION
totalPOS = (1:1:comptlat*comptlon)';
iMember = ismember(totalPOS, POS);

totalEAST = NaN(comptlat*comptlon, 1);
totalNORTH = NaN(comptlat*comptlon, 1);

totalEAST(iMember) = EAST;
totalNORTH(iMember) = NORTH;

% data is ordered from bottom left to top right so a complex reshape is
% needed
Zrad = reshape(sqrt(totalEAST .^2 + totalNORTH .^2)', comptlon, comptlat)';
Urad = reshape(totalEAST', comptlon, comptlat)';
Vrad = reshape(totalNORTH', comptlon, comptlat)';
if isQC
    % for now there is no QC info
end

% let's re-order data from top left to bottom right
Urad = Urad(I, :);
Vrad = Vrad(I, :);
Zrad = Zrad(I, :);
if isQC
    QCrad = QCrad(I, :);
end

%
%NetCDF file creation
Urad(isnan(Urad))   = 9999;
Vrad(isnan(Vrad))   = 9999;
Zrad(isnan(Zrad))   = 9999;

timestart = [1950, 1, 1, 0, 0, 0];
timefin = [str2double(filename(14:17)), str2double(filename(18:19)), str2double(filename(20:21)), ...
    str2double(filename(23:24)), str2double(filename(25:26)), str2double(filename(27:28))];

% time in averaged netCDF file is first file date
timenc = (etime(timefin, timestart))/(60*60*24);

timeStr = datestr(timenc(1) + datenum(timestart), 'yyyy-mm-ddTHH:MM:SSZ');

switch site_code
    case {'TURQ', 'SBRD', 'CRVT'}
        pathoutput = fullfile(ncwmsdir, 'TURQ');
    
    case {'BONC', 'BFCV', 'NOCR'}
        pathoutput = fullfile(ncwmsdir, 'BONC');
end

if (~exist(pathoutput, 'dir'))
    mkdir(pathoutput)
end

if isQC
    fileVersionCode = 'FV01';
else
    fileVersionCode = 'FV00';
end

netcdfFilename = ['IMOS_ACORN_V_', dateforfileSQL, 'Z_', site_code, '_' fileVersionCode '_1-hour-avg.nc'];
% netcdfFilename = [filename(1:end-3) '_CODAR-to-ncWMS.nc'];
netcdfoutput = fullfile(pathoutput, netcdfFilename);

createNetCDF(netcdfoutput, site_code, isQC, timenc, timeStr, X, Y, Zrad, Urad, Vrad, QCrad, false, meta);

%CREATION OF A SECOND NETCDF FILE 
%THIS NETCDF FILE WILL THEN BE AVAILABLE ON THE DATAFABRIC AND ON THE QCIF OPENDAP SERVER
%
switch site_code
    case {'TURQ', 'SBRD', 'CRVT'}
        pathoutput = fullfile(outputdir, 'TURQ');
    
    case {'BONC', 'BFCV', 'NOCR'}
        pathoutput = fullfile(outputdir, 'BONC');
end

finalPathOutput = fullfile(pathoutput, yearDF, monthDF, dayDF);
if (~exist(finalPathOutput, 'dir'))
    mkdir(finalPathOutput);
end

netcdfFilename = ['IMOS_ACORN_V_', dateforfileSQL, 'Z_', site_code, '_' fileVersionCode '_1-hour-avg.nc'];
netcdfoutput = fullfile(finalPathOutput, netcdfFilename);

createNetCDF(netcdfoutput, site_code, isQC, timenc, timeStr, X, Y, Zrad, Urad, Vrad, QCrad, false, meta);

end
