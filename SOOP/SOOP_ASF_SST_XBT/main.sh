#!/bin/bash
#to call the script, either ./main.sh XBT  or ./main.sh ASF_SST

function read_env(){
    export LOGNAME=lbesnard
    export HOME=/home/lbesnard
    export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games

    if [ ! -f `readlink -f env` ]
    then
        echo "env file does not exist. exit" 2>&1
        exit 1
    fi

    # read environmental variables from config.txt
    source `readlink -f env`  # read symlink env file
    # subsistute env var from config.txt | delete lines starting with # | delete empty lines | remove empty spaces | add export at start of each line
    source /dev/stdin <<<  `envsubst  < config.txt | sed '/^#/ d' | sed '/^$/d' | sed 's:\s::g' | sed 's:^:export :g' `
}

function process_xbt(){
    echo "START PROCESS XBT"
    # launch python script to process XBT data
    python "SOOP_XBT_RT.py" 2>&1 | tee  ${DIR}/${APP_NAME}".log1"

    # rsync data between rsyncSourcePath and rsyncDestinationPath
    rsyncSourcePath=$temporary_data_folder_sorted_xbt_path
    rsync  --itemize-changes  --stats -tzhvr --remove-source-files --progress ${rsyncSourcePath}/  ${destination_production_data_public_soop_xbt_path}/ ;
}

function process_asf_sst(){
    echo "START PROCESS ASF SST"
    python "SOOP_BOM_ASF_SST.py" 2>&1 | tee  ${DIR}/${APP_NAME}".log2"

    # rsync data between rsyncSourcePath and rsyncDestinationPath
    rsyncSourcePath=$temporary_data_folder_sorted_asf_sst_path
    rsync  --itemize-changes  --stats -tzhvr --remove-source-files  --progress ${rsyncSourcePath}/  ${destination_production_data_opendap_soop_asf_sst_path}/ ;
}


function main(){
    APP_NAME=SOOP_SST_ASF_XBT
    DIR=/tmp
    lockfile=${DIR}/${APP_NAME}.lock

    read_env
    {
      if ! flock -n 9
      then
        echo "Program already running. Unable to lock $lockfile, exiting" 2>&1
        exit 1
      fi


        if [[ "$1" == "XBT" ]] ; then
            process_xbt
        elif [[ "$1"  == "ASF_SST" ]] ; then
            process_asf_sst
        else
            echo "Unknown optional argument. Try ./main.sh XBT  or ./main.sh ASF_SST" 2>&1
            exit 1
        fi

    } 9>"$lockfile"
}

main $1