#!/bin/bash
# Double-click to install Boom Box, or to update it after downloading a new version.
# Creates the 'boombox' Anaconda environment, or updates an existing one in place.
cd "$(dirname "$0")/app" || exit 1
source ./find_conda.sh || { read -r -p "Press Return to close."; exit 1; }

if conda env list | grep -qE '^boombox\s'; then
    echo "Updating the 'boombox' environment..."
    conda env update -n boombox -f environment.yml --prune
else
    echo "Creating the 'boombox' environment (a few minutes)..."
    conda env create -f environment.yml
fi
status=$?
echo
if [ $status -eq 0 ]; then
    read -r -p "Done. Press Return to close."
else
    read -r -p "Install FAILED (see the messages above). Press Return to close."
fi
