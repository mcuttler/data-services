#!/bin/bash

# test _graveyard_file_name
test_graveyard_file_name() {
    local tmp_file=`mktemp`
    export TRANSACTION_ID="TIMESTAMP"

    # absolute path
    assertEquals "_mnt_opendap_1_file.nc.TIMESTAMP" `_graveyard_file_name /mnt/opendap/1/file.nc`
    assertEquals "_mnt_opendap_1_file.nc_.TIMESTAMP" `_graveyard_file_name /mnt/opendap/1/file.nc/`

    # relative path
    assertEquals "opendap_1_ACORN_file.nc.TIMESTAMP" `_graveyard_file_name opendap/1/ACORN/file.nc`

    # make sure there are no new slashes in the name
    assertFalse "_graveyard_file_name /mnt/opendap/1/file.nc | grep '/'"
    unset TRANSACTION_ID
}

# test _set_permissions function
test_set_permissions() {
    local tmp_file=`mktemp`
    _set_permissions $tmp_file

    local file_perms=`stat --format=%a $tmp_file`

    assertEquals "$file_perms" "444"
}

# file staged to production, already exists
test_move_to_fs_file_exists() {
    local src_file=`mktemp`
    local dest_dir=`mktemp -d`
    local dest_file="$dest_dir/some_file"

    touch $dest_file # destination file exists

    _file_error_param=""
    function file_error() { _file_error_param=$1; }

    _move_to_fs $src_file $dest_file

    assertEquals "file_error called with source file" $_file_error_param $src_file

    unset _file_error_param
    rm -f $dest_dir/some_file; rm -f $src_file; rmdir $dest_dir
}

# file staged to production, already exists
test_move_to_fs_file_exists_with_force() {
    local src_file=`mktemp`
    echo "new_file_content" > $src_file
    local dest_dir=`mktemp -d`
    local dest_file="$dest_dir/some_file"

    function _graveyard_file_name() { echo "graveyard_file_name"; }

    export GRAVEYARD_DIR=`mktemp -d`

    touch $dest_file # destination file exists

    _move_to_fs_force $src_file $dest_file

    assertTrue "some_file moved to graveyard" "test -f $GRAVEYARD_DIR/graveyard_file_name"
    assertTrue "new file is now in production" "test -f $dest_dir/some_file"

    local new_file_content=`cat $dest_dir/some_file`
    assertEquals "new file has correct content" "$new_file_content" "new_file_content"

    rm -f $dest_dir/some_file; rm -f $src_file; rmdir $dest_dir
    rm -f $GRAVEYARD_DIR/*; rmdir $GRAVEYARD_DIR
    unset _file_error_param
    unset GRAVEYARD_DIR
}

# file staged to production, didn't exist before
test_move_to_fs_new_file() {
    local src_file=`mktemp`
    local dest_dir=`mktemp -d`
    local dest_file="$dest_dir/some_file"

    _set_permissions_called_param=0
    function _set_permissions() { _set_permissions_called=$1; }

    _move_to_fs $src_file $dest_file

    assertTrue "File copied" "test -f $dest_file"
    assertEquals "_set_permissions called with source file" $_set_permissions_called $src_file

    unset _set_permissions_called
    rm -f $dest_dir/some_file; rmdir $dest_dir
}

# test the removal of file in production
test_remove_file_when_exists() {
    local prod_file=`mktemp`
    local prod_dir=`dirname $prod_file`

    export GRAVEYARD_DIR=`mktemp -d`
    _collapse_hierarchy_called_param=""
    function _collapse_hierarchy() { _collapse_hierarchy_called_param=$1; }

    _remove_file $prod_file
    return

    local dest_file="$GRAVEYARD_DIR/"`basename $prod_file`

    assertTrue "File moved" "test -f $dest_file"
    assertTrue "_collapse_hierarchy called with directory" $_collapse_hierarchy_called_param $prod_dir

    rm -f $GRAVEYARD_DIR/*; rmdir $GRAVEYARD_DIR
    unset _collapse_hierarchy_called_param
    unset GRAVEYARD_DIR
}

# test the removal of file in production
test_remove_file_when_is_directory() {
    local prod_dir=`mktemp -d`

    _remove_file $prod_dir
    local -i retval=$?

    assertEquals "_remove_file fails" $retval 1
    assertTrue "Does not remove directory" "test -d $prod_dir"

    rmdir $prod_dir
}

# test _collapse_hierarchy function
test_collapse_hierarchy() {
    local prod_dir=`mktemp -d`
    mkdir -p $prod_dir/1/2/3/4
    touch $prod_dir/1/2/some_file

    _collapse_hierarchy $prod_dir/1/2/3/4
    local -i retval=$?

    # those directories will be deleted
    assertFalse "Removes empty directories" "test -d $prod_dir/1/2/3/4"
    assertFalse "Removes empty directories" "test -d $prod_dir/1/2/3"

    assertTrue "Stops at a directory with a file" "test -d $prod_dir/1/2"
    assertTrue "Stops at a directory with a file" "test -d $prod_dir/1"
    assertTrue "Stops at a directory with a file" "test -d $prod_dir"
    assertTrue "Stops at a directory with a file" "test -f $prod_dir/1/2/some_file"

    rm -f $prod_dir/1/2/some_file;
    rmdir $prod_dir/1/2
    rmdir $prod_dir/1
    rmdir $prod_dir
}

# test get_relative_path
test_get_relative_path() {
    assertEquals "test.nc" `get_relative_path /mnt/opendap/1/test.nc /mnt/opendap/1`
    assertEquals "test.nc" `get_relative_path /mnt/opendap/1/test.nc /mnt/opendap/1/`
    assertEquals "1/test.nc" `get_relative_path /mnt/opendap/1/test.nc /mnt/opendap`
    assertEquals "/mnt/opendap/1/test.nc" `get_relative_path /mnt/opendap/1/test.nc`
}

# test get_uploader_email
test_get_uploader_email() {
    local ftp_log=`mktemp`
    local rsync_log=`mktemp`
    local email_lookup_file=`mktemp`

    export INCOMING_DIR=/var/incoming

    function _log_files_ftp() { echo $ftp_log; }
    function _log_files_rsync() { echo $rsync_log; }
    function _email_lookup_file() { echo $email_lookup_file; }

    cat <<EOF > $ftp_log
Wed Jun 24 12:44:21 2015 [pid 3] [user1] OK UPLOAD: Client "1.1.1.1", "/realtime/slocum_glider/StormBay20150616/unit286_track_24hr.png", 23022 bytes, 111.31Kbyte/sec
Wed Jun 24 12:46:51 2015 [pid 3] CONNECT: Client "1.1.1.4"
Wed Jun 24 12:44:21 2015 [pid 3] [user2] OK UPLOAD: Client "1.1.1.2", "/realtime/slocum_glider/StormBay20150616/unit286_track_48hr.png", 23090 bytes, 114.94Kbyte/sec
Wed Jun 24 12:44:22 2015 [pid 3] [user3] OK UPLOAD: Client "1.1.1.3", "/realtime/slocum_glider/StormBay20150616/unit286_track_mission.png", 23103 bytes, 103.59Kbyte/sec
Wed Jun 24 12:44:22 2015 [pid 3] [user5] OK UPLOAD: Client "1.1.1.3", "/ANFOG/realtime/slocum_glider/StormBay20150616/unit287_track_mission.png", 23103 bytes, 103.59Kbyte/sec
Wed Jun 24 12:46:51 2015 [pid 3] CONNECT: Client "1.1.1.2"
Wed Jun 24 12:46:51 2015 [pid 3] CONNECT: Client "1.1.1.3"
Wed Jun 24 12:55:07 2015 [pid 3] [user4] FAIL UPLOAD: Client "1.1.1.4", "/AM/pco2_mooring_data_KANGAROO_5.csv", 0.00Kbyte/sec
EOF

    cat <<EOF > $rsync_log
2015/06/24 14:13:05 [8979] recv unknown [2.2.2.2] srs_staging (user5) sst/ghrsst/L3C-1d/index.nc 5683476
2015/06/24 14:13:05 [8979] recv unknown [3.3.3.3] srs_staging (user6) sst/ghrsst/L3C-3d/index.nc 5686584
EOF

    cat <<EOF > $email_lookup_file
user1: user1@email.com
user2: user2@email.com
user3: user3@email.com
user4: user4@email.com
user5: user5@email.com
user6: user6@email.com
EOF
    newaliases -oA$email_lookup_file

    assertEquals "user1@email.com" `get_uploader_email /var/incoming/ANFOG/realtime/slocum_glider/StormBay20150616/unit286_track_24hr.png`
    assertEquals "user2@email.com" `get_uploader_email /var/incoming/ANFOG/realtime/slocum_glider/StormBay20150616/unit286_track_48hr.png`
    assertEquals "user3@email.com" `get_uploader_email /var/incoming/ANFOG/realtime/slocum_glider/StormBay20150616/unit286_track_mission.png`
    assertEquals "user5@email.com" `get_uploader_email /var/incoming/ANFOG/realtime/slocum_glider/StormBay20150616/unit287_track_mission.png`

    get_uploader_email /var/incoming/AM/pco2_mooring_data_KANGAROO_5.csv
    assertFalse "should ignore failed uploads" "get_uploader_email /var/incoming/AM/pco2_mooring_data_KANGAROO_5.csv"

    assertEquals "user5@email.com" `get_uploader_email /var/incoming/sst/ghrsst/L3C-1d/index.nc`
    assertEquals "user6@email.com" `get_uploader_email /var/incoming/sst/ghrsst/L3C-3d/index.nc`

    rm -f $ftp_log $rsync_log $email_lookup_file ${email_lookup_file}.db
}

# test rsync log parsing functions
test_sync_rsync() {
    local rsync_itemized=`mktemp`

    cat <<EOF > $rsync_itemized
*deleting   c
.d..t...... ./
>f.st...... a
>f+++++++++ b
EOF

    local rsync_deletions=`mktemp`
    local rsync_deletions_expected=`mktemp`
    echo "c" >> $rsync_deletions_expected
    get_rsync_deletions $rsync_itemized > $rsync_deletions
    assertTrue "rsync deletions" "cmp -s $rsync_deletions $rsync_deletions_expected"

    local rsync_additions=`mktemp`
    local rsync_additions_expected=`mktemp`
    echo "a" >> $rsync_additions_expected
    echo "b" >> $rsync_additions_expected
    get_rsync_additions $rsync_itemized > $rsync_additions
    assertTrue "rsync additions" "cmp -s $rsync_additions $rsync_additions_expected"

    rm -f $rsync_itemized \
        $rsync_deletions $rsync_deletions_expected \
        $rsync_additions $rsync_deletions_expected
}


# test lftp synchronization functions
test_lftp_sync() {
    local lftp_log=`mktemp`

    # log generated by running:
    # lftp -e "mirror -e --parallel=10 --log=/tmp/lftp.log /ifremer/argo/dac /tmp/argo/dac; quit" ftp.ifremer.fr

    cat <<EOF > $lftp_log
get -O /tmp/argo/dac/kma/2900170/profiles ftp://ftp.ifremer.fr/ifremer/argo/dac/kma/2900170/profiles/D2900170_007.nc
chmod 644 file:/tmp/argo/dac/csio/2900313/2900313_meta.nc
rm file:/tmp/argo/dac/nmdis/2901615/2901615_prof.nc.should_delete
chmod 644 file:/tmp/argo/dac/csio/2900313/2900313_prof.nc
get -O /tmp/argo/dac/kma/2900170/profiles ftp://ftp.ifremer.fr/ifremer/argo/dac/kma/2900170/profiles/D2900170_006.nc
get -O /tmp/argo/dac/meds/2900193 ftp://ftp.ifremer.fr/ifremer/argo/dac/meds/2900193/2900193_tech.nc
chmod 644 file:/tmp/argo/dac/csio/2900313/2900313_tech.nc
chmod 755 file:/tmp/argo/dac/csio/2900313/profiles
mkdir file:/tmp/argo/dac/csio/2900322
rm file:/tmp/argo/dac/nmdis/2901615/2901615_prof.nc.should_delete2
get -O /tmp/argo/dac/csio/2900322 ftp://ftp.ifremer.fr/ifremer/argo/dac/csio/2900322/2900322_Rtraj.nc
get -O /tmp/argo/dac/kordi/2900202 ftp://ftp.ifremer.fr/ifremer/argo/dac/kordi/2900202/2900202_tech.nc
EOF

    local lftp_expected_additions=`mktemp`
    cat <<EOF > $lftp_expected_additions
kma/2900170/profiles/D2900170_007.nc
kma/2900170/profiles/D2900170_006.nc
meds/2900193/2900193_tech.nc
csio/2900322/2900322_Rtraj.nc
kordi/2900202/2900202_tech.nc
EOF

    local lftp_expected_deletions=`mktemp`
    cat <<EOF > $lftp_expected_deletions
nmdis/2901615/2901615_prof.nc.should_delete
nmdis/2901615/2901615_prof.nc.should_delete2
EOF

    local lftp_additions=`mktemp`
    local lftp_deletions=`mktemp`

    get_lftp_additions $lftp_log "/tmp/argo/dac" > $lftp_additions
    get_lftp_deletions $lftp_log "/tmp/argo/dac" > $lftp_deletions

    assertTrue "cmp -s $lftp_additions $lftp_expected_additions"
    assertTrue "cmp -s $lftp_deletions $lftp_expected_deletions"

    rm -f $lftp_log $lftp_additions $lftp_deletions
}

##################
# SETUP/TEARDOWN #
##################

oneTimeSetUp() {
    function sudo() { "$@"; }
    function log_info() { true; }
    function log_error() { true; }
}

oneTimeTearDown() {
    true
}

setUp() {
    local dir=`dirname $0`
    source $dir/../../common/util.sh
    source $dir/../../common/email.sh
    source $dir/../../common/sync.sh
}

tearDown() {
    true
}

# load and run shUnit2
. /usr/share/shunit2/shunit2
