#!/usr/bin/env bash
# CI **형상**으로 전량 테스트 — 로컬 통과가 CI 통과를 뜻하지 않는다.
#
# CI는 PoB 소스를 통째로 두지 않고 **카탈로그용 8개 파일만** 받는다
# (`.github/workflows/ci.yml`). 특히 `HeadlessWrapper.lua`를 **일부러 안 받아서**
# `resolve_snapshot()`이 실패하고 실행 계열 테스트가 스킵된다. 로컬엔 전량이 있으니
# 스냅샷을 요구하는 테스트가 **로컬에서만 통과**하는 상태를 못 본다.
#
# 실측 사고 2회:
#   - sparse-checkout이 로컬 macOS에선 되고 Windows 러너에선 파일 0개였다
#   - `test_parse_gap_sources.py`가 로컬 통과 · CI 실패(2026-08-11) —
#     유니크 원문이 CI엔 없어 KB 플레이스홀더로 되돌아갔다
#
# ⚠ `external/pob`만 숨기는 것은 **재현이 아니다** — CI엔 일부 파일이 있고,
# 그 차이가 정확히 문제를 만든다. 그래서 트리를 통째로 복사해 형상을 맞춘다.
#
# 사용: bash scripts/ci_shape_test.sh [pytest 인자...]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="${POK_CI_SHAPE_DIR:-${TMPDIR:-/tmp}/pok-ci-shape}"
commit="$(python3 -c "
import json, pathlib
p = pathlib.Path('$root/knowledge/ingest/manifest.json')
print(json.loads(p.read_text())['pob_commit'][:7])
")"

rm -rf "$work"
mkdir -p "$work/external/pob/$commit/src"
# `project_root()`가 패키지 위치에서 거슬러 올라가므로 **심링크가 아니라 복사**여야 한다
for d in src tests knowledge docs .github .git; do
  [ -e "$root/$d" ] && cp -R "$root/$d" "$work/$d"
done
cp "$root/pyproject.toml" "$work/pyproject.toml"

# CI가 받는 그 8개 파일만 (ci.yml의 목록과 일치해야 한다)
for f in Data/Gems.lua Data/Misc.lua Data/ModCache.lua Data/Skills/sup_dex.lua \
         Modules/ConfigOptions.lua Modules/Data.lua Modules/ModParser.lua \
         Modules/CalcPerform.lua; do
  mkdir -p "$work/external/pob/$commit/src/$(dirname "$f")"
  cp "$root/external/pob/$commit/src/$f" "$work/external/pob/$commit/src/$f"
done

cd "$work"
PYTHONPATH="$work/src" python3 -m pytest -p no:cacheprovider "$@"
