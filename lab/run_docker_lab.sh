#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
IMAGE="${IMAGE:-iperf3-plotter-lab:latest}"
OUT_DIR="${OUT_DIR:-lab-results}"

docker build -f "${SCRIPT_DIR}/Dockerfile" -t "${IMAGE}" "${REPO_ROOT}"

mkdir -p "${REPO_ROOT}/${OUT_DIR}"

docker run --rm --privileged \
  -v "${REPO_ROOT}:/work" \
  -w /work \
  "${IMAGE}" \
  bash -lc 'exec python3 /work/lab/mininet_iperf_lab.py "$@"' \
  lab-entrypoint \
    --out "/work/${OUT_DIR}/raw" \
    "$@"

JSON_FILES=()
while IFS= read -r json_file; do
  JSON_FILES+=("${json_file}")
done < <(find "${REPO_ROOT}/${OUT_DIR}/raw" -name '*.json' -type f | sort)
if [ "${#JSON_FILES[@]}" -eq 0 ]; then
  echo "No iperf3 JSON files were produced." >&2
  exit 1
fi

PYTHONPATH="${REPO_ROOT}/src" python3 -m iperf3_plotter experiment \
  "${REPO_ROOT}/${OUT_DIR}/experiment.json" \
  --out "${REPO_ROOT}/${OUT_DIR}/analysis"

echo "Lab complete:"
echo "  raw JSON: ${REPO_ROOT}/${OUT_DIR}/raw"
echo "  experiment: ${REPO_ROOT}/${OUT_DIR}/experiment.json"
echo "  report: ${REPO_ROOT}/${OUT_DIR}/analysis/report.html"
