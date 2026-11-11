#!/bin/bash
# Double-click to start Boom Box.
cd "$(dirname "$0")/app" || exit 1
source ./find_conda.sh || { read -r -p "Press Return to close."; exit 1; }

if ! conda env list | grep -qE '^boombox\s'; then
    echo "The 'boombox' environment is missing. Running first-time install..."
    conda env create -f environment.yml || { read -r -p "Install failed. Press Return to close."; exit 1; }
fi

conda activate boombox
python -m boombox "$@"
status=$?
if [ $status -ne 0 ]; then
    read -r -p "Boom Box exited with an error (code $status). Press Return to close."
fi
