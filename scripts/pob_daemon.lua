-- 상주 headless PoB — 최적화 루프용 (src/pok/pob/daemon.py 가 관리).
-- 기동(~2초, 트리·데이터 로드)을 1회로 상각하고 계산당 ~0.1초로 응답한다.
--
-- 프로토콜 (stdin 줄 단위):
--   부팅 완료  → "POK_READY" 출력
--   <xml 경로> → 계산 후 POK_META / POK_ALLOC / POK_JSON / POK_DONE 출력
--   TREE	<노드 CSV> → **로드된 빌드의 트리만** 갈아 끼우고 재계산(스킬·장비 재사용)
--   "QUIT"     → 종료 (EOF도 동일)
-- 각 응답 블록은 POK_DONE으로 닫힌다. 오류는 POK_ERR:<사유> 후 POK_DONE.
-- 출력 형식 자체는 scripts/pob_driver.lua(1회 실행)와 동일 계약.

package.preload['lua-utf8'] = function()
  return setmetatable({}, { __index = string })
end

dofile("HeadlessWrapper.lua")

local function jesc(s)
  return tostring(s):gsub('[\\"]', '\\%0'):gsub("[%c]", " ")
end

-- 계산 + 출력. 로드는 호출자가 이미 끝냈다고 본다.
local function emit()
  if not build or not build.calcsTab then
    print("POK_ERR:빌드 로드 실패")
    return
  end
  build.calcsTab:BuildOutput()
  local out = build.calcsTab.mainOutput

  local points, asc, secAsc = build.spec:CountAllocNodes()
  print(string.format(
    'POK_META:{"class":"%s","ascendancy":"%s","level":%d,"allocPoints":%d,"allocAscendancy":%d,"allocSecondaryAscendancy":%d}',
    jesc(build.spec.curClassName or ""),
    jesc(build.spec.curAscendClassName or ""),
    build.characterLevel or 0, points or 0, asc or 0, secAsc or 0))

  local ids = {}
  for id, node in pairs(build.spec.allocNodes) do
    if node.type ~= "ClassStart" and node.type ~= "AscendClassStart" then
      ids[#ids + 1] = id
    end
  end
  table.sort(ids)
  print("POK_ALLOC:[" .. table.concat(ids, ",") .. "]")

  local keys = {}
  for k, v in pairs(out) do
    if type(k) == "string" and type(v) == "number" and v == v
        and v ~= math.huge and v ~= -math.huge then
      keys[#keys + 1] = k
    end
  end
  table.sort(keys)
  local parts = {}
  for _, k in ipairs(keys) do
    parts[#parts + 1] = string.format('"%s":%.10g', jesc(k), out[k])
  end
  print("POK_JSON:{" .. table.concat(parts, ",") .. "}")
end

local function respond(xmlText)
  loadBuildFromXML(xmlText, "pok")
  emit()
end

-- 트리만 갈아 끼우고 다시 계산한다 (#70 후속 — 실측 2026-08-13).
--
-- **왜 필요한가**: 최적화 루프는 노드만 바꾸는데 매 호출마다 빌드를 통째로 다시
-- 로드했다. 실측: 최소 0.38초 · 장비15까지 0.60초 · **스킬9까지 3.68초** —
-- 장비는 +0.22초인데 **스킬이 +3.16초**다. 루프에서 스킬은 한 번도 안 바뀌는데
-- 매 호출마다 젬 32개를 다시 세운 셈이라 그 3.16초가 통째로 낭비였다.
--
-- ⛔ 계산을 우리가 하지 않는다(AD-1) — PoB 자신의 `ImportFromNodeList`를 부른다.
--    XML 로드 경로(`PassiveSpec:Load`)가 쓰는 것과 **같은 함수**다.
local function respond_tree(nodeCsv)
  if not build or not build.spec then
    print("POK_ERR:로드된 빌드가 없다 — TREE 앞에 빌드 XML을 먼저 보낼 것")
    return
  end
  local hashList = {}
  for hash in nodeCsv:gmatch("%d+") do
    hashList[#hashList + 1] = tonumber(hash)
  end
  local spec = build.spec
  -- ⚠ **속성 노드 선택(hashOverrides)과 마스터리를 넘겨야 한다.** 빈 값으로 두면
  --    `ImportFromNodeList`가 그것들을 지운다 — 할당 노드는 똑같은데 스탯이 달라진다
  --    (실측 2026-08-13: Accuracy 846 → 636, DPS 1.4% 차이). PoB 자신의 XML 로드
  --    경로(`PassiveSpec:Load` L219)도 `copyTable(self.hashOverrides, true)`와
  --    masteryEffects를 그대로 넘긴다 — 같은 것을 한다.
  local masteryEffects = {}
  for mastery, effect in pairs(spec.masterySelections or {}) do
    masteryEffects[mastery] = effect
  end
  spec:ImportFromNodeList(nil, spec.curClassId, spec.curAscendClassId,
                          spec.curSecondaryAscendClassId or 0, hashList, {},
                          copyTable(spec.hashOverrides or {}, true), masteryEffects)
  spec:BuildAllDependsAndPaths()
  build.buildFlag = true
  emit()
end

-- 아이템 명세 → PoB 정본 텍스트 (#34). **부팅을 상각하려고** 데몬에 붙였다 —
-- 별도 프로세스로 띄우면 호출마다 9.8초가 든다(실측 2026-08-09).
-- 순서는 PoB 자신의 것이다: ParseRaw → Craft(문구·촉매) → UpdateRunes(룬) → BuildRaw.
local function respond_item(raw)
  local ok, item = pcall(function() return new("Item", raw) end)
  if not ok or not item then
    print("POK_ERR:" .. jesc(tostring(item)))
    return
  end
  -- `Craft()`는 explicitModLines를 통째로 지우고 모드 id에서 다시 만든다(L1704) —
  -- `{custom}` 없는 손기입 줄은 사라지므로 `Crafted: true`인 명세에만 건다.
  if item.Craft and raw:match("Crafted:%s*true") then
    pcall(function() item:Craft() end)
  end
  if item.UpdateRunes then pcall(function() item:UpdateRunes() end) end
  local okBuild, built = pcall(function() return item:BuildRaw() end)
  if not okBuild then
    print("POK_ERR:" .. jesc(tostring(built)))
    return
  end
  print("POK_RAW:" .. (tostring(built):gsub("\\", "\\\\"):gsub("\n", "\\n"):gsub("\r", "")))
end

print("POK_READY")
io.stdout:flush()

for line in io.lines() do
  if line == "QUIT" then break end
  -- `ITEM<TAB><경로>` = 아이템 명세 렌더, 그 외 = 빌드 XML 경로(기존 규약 유지)
  local treeCsv = line:match("^TREE	(.*)$")
  if treeCsv then
    local okT, errT = pcall(respond_tree, treeCsv)
    if not okT then print("POK_ERR:" .. jesc(errT)) end
    print("POK_DONE")
    io.stdout:flush()
    goto continue
  end
  local itemPath = line:match("^ITEM\t(.*)$")
  local path = itemPath or line
  local f = io.open(path, "rb")
  if not f then
    print("POK_ERR:파일 열기 실패: " .. path)
  else
    local text = f:read("*a")
    f:close()
    local ok, err = pcall(itemPath and respond_item or respond, text)
    if not ok then
      print("POK_ERR:" .. jesc(err))
    end
  end
  print("POK_DONE")
  io.stdout:flush()
  ::continue::
end
