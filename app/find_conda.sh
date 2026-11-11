# Sourced by the .command files: loads Anaconda/Miniconda so `conda activate` works.
CONDA_BASE=""
if command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base 2>/dev/null)"
fi
if [ -z "$CONDA_BASE" ]; then
    for d in "$HOME/anaconda3" "$HOME/opt/anaconda3" "$HOME/miniconda3" "$HOME/opt/miniconda3" \
             "$HOME/miniforge3" "/opt/anaconda3" "/opt/miniconda3" "/opt/homebrew/anaconda3" \
             "/opt/homebrew/Caskroom/miniconda/base" "/usr/local/anaconda3"; do
        if [ -f "$d/etc/profile.d/conda.sh" ]; then CONDA_BASE="$d"; break; fi
    done
fi
if [ -z "$CONDA_BASE" ] || [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    echo "Could not find Anaconda. Install Anaconda or Miniconda first."
    return 1
fi
source "$CONDA_BASE/etc/profile.d/conda.sh"
