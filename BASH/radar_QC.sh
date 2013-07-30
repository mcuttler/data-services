#!/bin/bash

date
tic=$(date +%s.%N)
printf "\n"

# Need to set the environment variables relevant for ACORN
source /home/ggalibert/DEFAULT_PATH.env
source /home/ggalibert/STORAGE.env
source /home/ggalibert/ACORN.env

# Run Matlab script to produce FV01 hourly averaged gridded files
matlab -nodisplay -nojvm -r "cd(getenv('ACORN_EXP')); addpath(fullfile('.', 'Util')); acorn_summary('WERA', true); exit"

printf "\n"
date
toc=$(date +%s.%N)
printf "%6.1Fs\tFV01 radial files processed to hourly averaged gridded files\n"  $(echo "$toc - $tic"|bc )

tic=$(date +%s.%N)
printf "\n"

# Move produced files to OPENDAP
rsync -vaR --remove-source-files $DATA/ACORN/WERA/radial_QC/output/datafabric/gridded_1havg_currentmap_QC/./ $OPENDAP/ACORN/gridded_1h-avg-current-map_QC/

printf "\n"
date
toc=$(date +%s.%N)
printf "%6.1Fs\tFV01 hourly averaged gridded files moved from WIP to OPENDAP\n"  $(echo "$toc - $tic"|bc )
