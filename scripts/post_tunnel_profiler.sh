#!/bin/bash

# Code:

set -e

# @CONF_OPTION LOCAL_OUTPUT_DIR: Output dir for local running experiments (so not on DAS4).
# This is hack to avoid rewriting a bunch of scripts, as the scripts look for the directory structure $LOCAL_OUTPUT_DIR/localhost/localhost
# For local experiments make sure to also set $OUTPUT_DIR
# TODO fix this so that we don't need the variable
if [ -n "$LOCAL_OUTPUT_DIR" ]; then
	cd $LOCAL_OUTPUT_DIR
else
	cd $OUTPUT_DIR
fi

CDIR=$PWD/localhost/localhost
echo "POST_TUNNEL_PROFILER: LOOKING FOR OUTPUT IN $CDIR"

# Loop through all of the output folders
for file in $(find $CDIR -maxdepth 1 -type d)
do
cd $file

# In each folder, graph the tunnel profile files
export OVERRIDE_TUNNEL_PIECHARTS_INPUTPATH=$file
export R_SCRIPTS_TO_RUN="\
tunnel_piecharts.R
"
graph_data.sh

done

