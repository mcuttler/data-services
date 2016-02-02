#!/bin/bash

GSLA_REGEX='^IMOS_OceanCurrent_HV_[[:digit:]]{8}T000000Z_GSLA_FV02_(NRT00|DM00)_C-[[:digit:]]{8}T[[:digit:]]{6}Z\.nc\.gz$'
GSLA_REGEX_YEARLY='^IMOS_OceanCurrent_HV_[[:digit:]]{4}_C-[[:digit:]]{8}T[[:digit:]]{6}Z\.nc\.gz$'
GSLA_BASE=OceanCurrent/GSLA

# returns a list of previous versions for a given file
# $1 - file relative path
get_previous_versions() {
    local path=`dirname $1`; local file=`basename $1`; shift

    # chop file so we have something like:
    # * IMOS_OceanCurrent_HV_19931231T000000Z_GSLA_FV02_DM00
    # * IMOS_OceanCurrent_HV_1996
    local file_no_version=`echo $file | sed -e 's/_C-[[:digit:]]\{8\}T[[:digit:]]\{6\}Z\.nc\.gz$//'`

    # if any file matches the $file_no_version pattern, it is a previous file
    local f previous_versions
    for f in `s3_ls $path`; do
        if echo $f | grep -q "^$file_no_version" && [ "$f" != "$file" ]; then
            previous_versions="$previous_versions $f"
        fi
    done

    local previous_version
    for previous_version in $previous_versions; do
        echo "$path/$previous_version"
    done
}

# validate regex, returns true (0) if passes, false (1) if not
# $1 - file
regex_filter() {
    local file=`basename $1`; shift
    echo $file | grep -q -E $GSLA_REGEX || \
        echo $file | grep -q -E $GSLA_REGEX_YEARLY
}

# return gsla file type
# $1 - file
get_type() {
    local file=$1; shift
    if basename $file | grep -q "_GSLA_FV02_NRT00_"; then
        echo "NRT00"
    elif basename $file | grep -q "_GSLA_FV02_DM00_"; then
        echo "DM00"
    elif basename $file | grep -q -E $GSLA_REGEX_YEARLY; then
        echo "DM00/yearfiles"
    else
        return 1
    fi
}

# given a file, return its hierarchy
# $1 - file
# $2 - file type (NRT00, DM00, DM00/yearfiles)
get_hierarchy() {
    local file=`basename $1`; shift
    local type=$1; shift

    if [ "$type" == "DM00/yearfiles" ]; then
        echo "$GSLA_BASE/$type/$file"
    else
        local year=`echo $file | cut -d_ -f4 | cut -c1-4`
        echo "$GSLA_BASE/$type/$year/$file"
    fi
}

# main
# $1 - file to handle
main() {
    local file=$1; shift

    regex_filter $file || file_error "Did not pass GSLA regex filter"

    # GSLA files are gzipped, so gunzip them before checking them
    local tmp_unzipped=`mktemp`
    gunzip --stdout $file > $tmp_unzipped
    check_netcdf $tmp_unzipped
    local -i nc_check_retval=$?

    if [ $nc_check_retval -ne 0 ]; then
        rm -f $tmp_unzipped
        file_error "Not a valid NetCDF file"
    fi

    local file_type=`get_type $file`
    if [ x"$file_type" = x ]; then
        rm -f $tmp_unzipped
        file_error "Unknown file type"
    fi

    local path_hierarchy
    path_hierarchy=`get_hierarchy $file $file_type`

    local previous_version
    for previous_version in `get_previous_versions IMOS/$path_hierarchy`; do
        log_info "Previous verison detected '$previous_version'"
        s3_del $previous_version
    done

    # index unzipped file, but push zipped file to S3
    if [ "$file_type" == "DM00" ] || [ "$file_type" == "NRT00" ]; then
        if ! index_file $tmp_unzipped IMOS/$path_hierarchy; then
          rm -f $tmp_unzipped
          file_error "Failed indexing"
        fi
    fi

    rm -f $tmp_unzipped # no need for that unzipped file any more

    s3_put_no_index $file IMOS/$path_hierarchy
}

# don't run main if running shunit
if [[ `basename $0` =~ ^shunit2_.* ]]; then
    true
else
    main "$@"
fi
