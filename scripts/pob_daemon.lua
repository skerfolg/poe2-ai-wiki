-- 상주 headless PoB — 최적화 루프용 (src/pok/pob/daemon.py 가 관리).
-- 기동(~2초, 트리·데이터 로드)을 1회로 상각하고 계산당 ~0.1초로 응답한다.
--
-- 프로토콜 (stdin 줄 단위):
--   부팅 완료  → "POK_READY" 출력
--   <xml 경로> → 계산 후 POK_META / POK_ALLOC / POK_JSON / POK_DONE 출력
--   TREE	<노드 CSV> → **로드된 빌드의 트리만** 갈아 끼우고 재계산(스킬·장비 재사용)
--   POWER	<스탯 CSV> → **미할당 노드 전량**을 하나씩 더했을 때의 델타(추가 방향)
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

-- ⛔ **오라클이 못 센 것을 스스로 신고한다** (#110).
--    PoB 0.23.1은 플레이어의 트리거·미라주 계산을 통째로 꺼 뒀다
--    (`Modules/CalcPerform.lua:3433` "TURNING OFF CALC TRIGGERS AND MIRAGES").
--    되살려 보니 `CalcTriggers.lua:396`·`CalcMirages.lua:59`이 둘 다
--    `skillFlags`(nil)에서 죽는다 — 정책이 아니라 **미완성**이다(실측 2026-08-23).
--    그래서 발동 스킬의 딜은 CombinedDPS에 **0으로** 들어간다. 그 사실이 결과에
--    안 남으면 트리거 빌드가 조용히 과소평가된다 — 「없는 값이 0으로 읽힌다」.
-- ⛔ **`CombinedDPS`가 속도 배수를 잃는 조건을 신고한다** (#113).
--    `Modules/CalcOffence.lua:6136`:
--        local baseDPS = output[(skillData.showAverage and "AverageDamage") or "TotalDPS"]
--        output.CombinedDPS = baseDPS
--    주력기에 `showAverage`가 서면 CombinedDPS의 **밑값이 1회 평균 피해**다 — 공격·시전
--    속도가 안 곱해진다. `TotalDPS`(:4447 = Avg x (HitSpeed or Speed))는 정상이므로
--    결함은 **축 선택 하나**에 있다. 신고가 없으면 속도 축이 조용히 0으로 읽힌다
--    (실측: 채택 35수 중 공격 속도 노터블 0건).
--    ⚠ 이 플래그 자체는 스킬 피해 모델의 결함 표지가 **아니다** — BACKLOG §3이 그 오독을
--       한 번 뒤집었다. 여기서 재는 것은 「CombinedDPS를 그대로 쓰면 안 되는가」뿐이다.
local function pokShowsAverage()
  local main = build.calcsTab and build.calcsTab.mainEnv
      and build.calcsTab.mainEnv.player and build.calcsTab.mainEnv.player.mainSkill
  if main and main.skillData and main.skillData.showAverage then return 1 end
  return 0
end

local function pokOracleGaps()
  local env = build.calcsTab and build.calcsTab.mainEnv
  local trig, mir = 0, 0
  if env and env.player and env.player.activeSkillList then
    for _, skill in ipairs(env.player.activeSkillList) do
      local sd = skill.skillData or {}
      local st = skill.skillTypes or {}
      if sd.triggered or skill.triggeredBy or st[SkillType.Triggered] then trig = trig + 1 end
      local cond = skill.skillCfg and skill.skillCfg.skillCond
      if sd.triggeredByMirageArcher or (cond and cond["usedByMirage"]) then mir = mir + 1 end
    end
  end
  -- 주력기 자신이 발동인가 — **오차의 방향이 갈린다**. 주력기가 아닌 발동 스킬은
  -- 기여가 0으로 빠져 과소평가지만, 주력기가 발동이면 발동률이 안 걸려 시전 속도대로
  -- 계산되므로 **과대평가**일 수 있다. 하나로 뭉치면 어느 쪽인지 말할 수 없다.
  local main = build.calcsTab.mainEnv and build.calcsTab.mainEnv.player
      and build.calcsTab.mainEnv.player.mainSkill
  local mainTrig = 0
  if main then
    local sd = main.skillData or {}
    local st = main.skillTypes or {}
    if sd.triggered or main.triggeredBy or st[SkillType.Triggered] then mainTrig = 1 end
  end
  return trig, mir, mainTrig
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
    'POK_META:{"class":"%s","ascendancy":"%s","level":%d,"allocPoints":%d,"allocAscendancy":%d,"allocSecondaryAscendancy":%d,"mainSkillShowsAverage":%d,"gapTriggeredSkills":%d,"gapMirageSkills":%d,"gapMainSkillTriggered":%d}',
    jesc(build.spec.curClassName or ""),
    jesc(build.spec.curAscendClassName or ""),
    build.characterLevel or 0, points or 0, asc or 0, secAsc or 0, pokShowsAverage(), pokOracleGaps()))

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

-- 미할당 노드를 **하나씩 더했을 때**의 델타를 한 번에 낸다 (추가 방향 스파이크).
--
-- 우리 측정은 지금 「이미 찍은 노드를 빼면?」만 답한다(제거 축). 「안 찍은 노드를
-- 찍으면?」은 후보마다 전체 재계산을 가정해 전수 46일로 잡혀 있었는데, PoB에는
-- 그걸 위한 **전용 빠른 경로**가 있다 — `calcs.getMiscCalculator`는 기준 계산을
-- 한 번만 돌리고 환경·DB를 재사용하는 클로저를 돌려준다("accelerated pass for
-- hot loops"). PoB 자신의 노드 파워 색칠이 이 경로를 쓴다(`CalcsTab:PowerBuilder`).
--
-- ⚠ **경로 비용을 계산하지 않는다.** 노드 하나만 더한 값이라 「거기까지 잇는 데
--    몇 포인트가 드나」는 빠져 있다. PoB 자신도 이것을 "Estimate"라 부른다 —
--    조합 효과도 무시한다(단독 델타 0인 둘이 함께 1.44배인 사례가 있다).
--    그래서 이건 **후보를 좁히는 신호**이지 값 그 자체가 아니다.
local function respond_power(statCsv)
  if not build or not build.calcsTab then
    print("POK_ERR:로드된 빌드가 없다 — POWER 앞에 빌드 XML을 먼저 보낼 것")
    return
  end
  local wanted = {}
  for s in statCsv:gmatch("[^,]+") do wanted[#wanted + 1] = s end
  if #wanted == 0 then wanted = { "CombinedDPS", "TotalEHP" } end

  build.calcsTab:BuildOutput()
  local base = build.calcsTab.mainOutput
  local calcFunc = build.calcsTab:GetMiscCalculator()

  -- 같은 효과를 가진 노드는 계산을 공유한다(트리 4,509노드 = 효과 조합 2,086종).
  local cache, calls = {}, 0
  local rows = 0
  for nodeId, node in pairs(build.spec.nodes) do
    if not node.alloc and node.modKey and node.modKey ~= "" then
      local out = cache[node.modKey]
      if not out then
        out = calcFunc({ addNodes = { [node] = true } })
        cache[node.modKey] = out
        calls = calls + 1
      end
      local parts = {}
      for _, stat in ipairs(wanted) do
        parts[#parts + 1] = string.format('"%s":%.4f',
          jesc(stat), (out[stat] or 0) - (base[stat] or 0))
      end
      print(string.format('POK_POWER:{"node":%d,"d":{%s}}',
        nodeId, table.concat(parts, ",")))
      rows = rows + 1
    end
  end
  print(string.format('POK_POWERMETA:{"nodes":%d,"calcs":%d}', rows, calls))
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
  local powerCsv = line:match("^POWER	(.*)$")
  if powerCsv then
    local okP, errP = pcall(respond_power, powerCsv)
    if not okP then print("POK_ERR:" .. jesc(errP)) end
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
