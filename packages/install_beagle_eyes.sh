#!/usr/bin/env bash
# ==============================================================================
# Parent Repo Installer for Beagle Eyes (vendor/beagle_eyes)
# Clones/updates beagle_eyes, initializes Deep-Visual-Odometry-SLAM cleanly
# (without --recursive so Pangolin doesn't break), and optionally builds DPVO.
# ==============================================================================
set -euo pipefail

PARENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-${PARENT_ROOT}/vendor/beagle_eyes}"
REPO_URL="https://github.com/sangregoriokimpo/beagle_eyes.git"
BRANCH="main"

echo "============================================================"
echo " Installing Beagle Eyes into: ${TARGET_DIR}"
echo "============================================================"

# 1. Ensure vendor/beagle_eyes is ignored by the parent repo's Git
GITIGNORE_FILE="${PARENT_ROOT}/.gitignore"
REL_TARGET="${TARGET_DIR#"${PARENT_ROOT}/"}"
if [[ -f "${GITIGNORE_FILE}" ]] && ! grep -qxF "${REL_TARGET}/" "${GITIGNORE_FILE}"; then
    echo "" >> "${GITIGNORE_FILE}"
    echo "# Beagle Eyes (managed by install_beagle_eyes.sh)" >> "${GITIGNORE_FILE}"
    echo "${REL_TARGET}/" >> "${GITIGNORE_FILE}"
    echo "[1/4] Added '${REL_TARGET}/' to .gitignore"
else
    echo "[1/4] '${REL_TARGET}/' already in .gitignore (or no .gitignore found)"
fi

# 2. Clone or update beagle_eyes
mkdir -p "$(dirname "${TARGET_DIR}")"
if [[ -d "${TARGET_DIR}/.git" ]]; then
    echo "[2/4] Updating existing beagle_eyes repo on branch '${BRANCH}'..."
    git -C "${TARGET_DIR}" fetch origin "${BRANCH}"
    git -C "${TARGET_DIR}" checkout "${BRANCH}"
    git -C "${TARGET_DIR}" pull --ff-only origin "${BRANCH}"
else
    echo "[2/4] Cloning ${REPO_URL} (branch: ${BRANCH})..."
    rm -rf "${TARGET_DIR}"
    git clone --branch "${BRANCH}" "${REPO_URL}" "${TARGET_DIR}"
fi

# 3. Initialize Deep-Visual-Odometry-SLAM submodule WITHOUT --recursive
#    (Skips the broken nested modules/Pangolin reference in upstream DPVO)
echo "[3/4] Initializing vendor/Deep-Visual-Odometry-SLAM submodule..."
git -C "${TARGET_DIR}" submodule update --init vendor/Deep-Visual-Odometry-SLAM

# 4. Build DPVO CUDA extensions if visual_slam conda env is available (skip with --skip-build)
if [[ "${2:-}" != "--skip-build" ]] && [[ -x "${TARGET_DIR}/scripts/setup_dpvo.sh" ]]; then
    if command -v nvcc >/dev/null 2>&1 || [[ -d "/usr/local/cuda" ]] || [[ -d "/usr/local/cuda-13.0" ]]; then
        echo "[4/4] Running DPVO CUDA extension setup..."
        sed -i 's/import cuda_corr/import torch, cuda_corr/' "${TARGET_DIR}/scripts/setup_dpvo.sh"
        bash "${TARGET_DIR}/scripts/setup_dpvo.sh"
    else
        echo "[4/4] No CUDA toolkit detected on this machine — skipping DPVO CUDA build."
    fi
else
    echo "[4/4] Skipping DPVO CUDA build."
fi

echo "============================================================"
echo " Beagle Eyes installed at: ${TARGET_DIR}"
echo "   - Run Mock Sender : python ${REL_TARGET}/broadcast/mock_sender.py"
echo "   - Run Webcam VO   : python ${REL_TARGET}/scripts/webcam_vo.py --detect-people"
echo "   - Run UAV VO      : python ${REL_TARGET}/scripts/uav_vo.py --detect-people"
echo "   - React Hook      : ${REL_TARGET}/broadcast/useBeagleStream.ts"
echo "============================================================"