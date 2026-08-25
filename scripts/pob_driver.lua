-- 범용 headless PoB 드라이버 — src/pok/pob/runner.py 가 서브프로세스로 실행.
-- 사용: (cwd = <pob>/src)  luajit pob_driver.lua <build.xml 경로>
-- 출력(stdout, 줄 단위 프로토콜):
--   POK_META:{...}   클래스·레벨·할당 수 — 적법성 검사용
--   POK_ALLOC:[...]  실제 할당된 트리 노드 id — 요청과 비교해 잘린 노드 탐지
--   POK_JSON:{...}   mainOutput의 유한 숫자 스탯 전부
--   POK_OK | POK_ERR:<사유>
-- 계약 배경(스파이크 실측)은 scripts/pob_smoke.lua 머리주석 참조.

package.preload['lua-utf8'] = function()
  return setmetatable({}, { __index = string })
end

local xmlPath = arg and arg[1]
if not xmlPath then
  print("POK_ERR:XML 경로 인자 누락")
  os.exit(2)
end
local f = io.open(xmlPath, "rb")
if not f then
  print("POK_ERR:XML 파일 열기 실패: " .. xmlPath)
  os.exit(2)
end
local xmlText = f:read("*a")
f:close()

dofile("HeadlessWrapper.lua")
loadBuildFromXML(xmlText, "pok")
if not build or not build.calcsTab then
  print("POK_ERR:빌드 로드 실패")
  os.exit(1)
end
build.calcsTab:BuildOutput()
local out = build.calcsTab.mainOutput

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

-- ⛔ **아이템의 룬 소켓 수를 오라클이 신고한다** (#120).
--    PoB는 아이템 텍스트의 `Sockets:` 줄을 **그대로 믿는다**(`Item.lua:577`
--    `self.itemSocketCount = #self.sockets`) — 베이스 한도와 대조하지 않는다.
--    한도를 넘겨 적으면 계산은 조용히 그 값으로 나오고 **UI에서만** 터진다:
--    `ItemsTab.lua:696`이 룬 드롭다운을 **6개만** 만드는데
--    `UpdateRuneControls`(:2016)는 `for i = 1, item.itemSocketCount`로 돌아
--    7칸부터 `displayItemRune7`이 nil이다 — 아이템 상세보기에서 예외.
--    실측 2026-08-25(사용자 신고 빌드): 12개 중 4개가 한도 초과였고(3→4 셋 ·
--    4→7 하나) 7칸짜리에서 예외가 났다. 조립 게이트는 소켓 수를 아예 안 봤다.
-- ⚠ **베이스 한도로만 재면 정상 유니크를 거부한다** — 한도를 넘는 유니크가 실재한다
--    (실측: Atziri's Splendour 6>4 · Runeseeker's Call 5>3 · Darkness Enthroned 2>0).
--    유니크는 **자기 정의(`data.uniques`)가 정본**이고 베이스 한도는 그 다음이다.
--    거짓 거부는 게이트 우회를 학습시킨다(BACKLOG 형태 ⑪).
local pokUniqueSocketCache
local function pokUniqueSockets()
  if pokUniqueSocketCache then return pokUniqueSocketCache end
  pokUniqueSocketCache = {}
  for _, list in pairs(data.uniques or {}) do
    for _, raw in ipairs(list) do
      local name = raw:match("^%s*([^\n]+)")
      if name then
        local most = 0
        -- `Sockets: J J J`(주얼)는 세지 않는다 — 룬 칸만이 상세보기 컨트롤을 쓴다
        for spec in raw:gmatch("\nSockets:([^\n]*)") do
          local count = 0
          for _ in spec:gmatch("S") do count = count + 1 end
          if count > most then most = count end
        end
        if most > 0 then pokUniqueSocketCache[name] = most end
      end
    end
  end
  return pokUniqueSocketCache
end

local function pokItems()
  local tab = build and build.itemsTab
  if not tab or not tab.items then return "[]" end
  local uniques = pokUniqueSockets()
  local ids = {}
  for id in pairs(tab.items) do ids[#ids + 1] = id end
  table.sort(ids)
  local rows = {}
  for _, id in ipairs(ids) do
    local item = tab.items[id]
    local sockets = item.itemSocketCount or 0
    local limit, source = 0, "none"
    local declared = (item.rarity == "UNIQUE") and uniques[item.title or ""] or nil
    if declared then
      limit, source = declared, "unique"
    elseif item.base and item.base.socketLimit then
      limit, source = item.base.socketLimit, "base"
    end
    -- 이름을 못 찾는 룬이 하나라도 있으면 PoB는 `UpdateRunes()`를 **안 돌린다**
    -- (`Item.lua:1046~1058`) — 손기입 `{rune}` 줄이 그대로 남아 조용히 어긋난다.
    local unknown = {}
    for i = 1, sockets do
      local name = item.runes and item.runes[i]
      if name and name ~= "None"
          and not (data.itemMods and data.itemMods.Runes and data.itemMods.Runes[name]) then
        unknown[#unknown + 1] = '"' .. jesc(name) .. '"'
      end
    end
    rows[#rows + 1] = string.format(
      '{"id":"%s","name":"%s","base":"%s","rarity":"%s","sockets":%d,"limit":%d,"limitSource":"%s","unknownRunes":[%s]}',
      jesc(id), jesc(item.title or item.name or ""), jesc(item.baseName or ""),
      jesc(item.rarity or ""), sockets, limit, source, table.concat(unknown, ","))
  end
  return "[" .. table.concat(rows, ",") .. "]"
end

-- 메타: 적법성 신호 (연결 안 된 노드는 PoB가 소리 없이 해제하므로 여기서 노출)
local points, asc, secAsc = build.spec:CountAllocNodes()
-- ⚠ 다중 반환은 **인자 목록 끝에서만** 펼쳐진다 — 뒤에 인자를 더하면 조용히 1개로
--    잘린다. 그래서 먼저 받아 둔다(`gapMirageSkills`가 0으로 굳는 자리였다).
local gapTrig, gapMirage, gapMainTrig = pokOracleGaps()
print(string.format(
  'POK_META:{"class":"%s","ascendancy":"%s","level":%d,"allocPoints":%d,"allocAscendancy":%d,"allocSecondaryAscendancy":%d,"mainSkillShowsAverage":%d,"gapTriggeredSkills":%d,"gapMirageSkills":%d,"gapMainSkillTriggered":%d,"items":%s}',
  jesc(build.spec.curClassName or ""),
  jesc(build.spec.curAscendClassName or ""),
  build.characterLevel or 0, points or 0, asc or 0, secAsc or 0, pokShowsAverage(),
  gapTrig, gapMirage, gapMainTrig, pokItems()))

local ids = {}
for id, node in pairs(build.spec.allocNodes) do
  if node.type ~= "ClassStart" and node.type ~= "AscendClassStart" then
    ids[#ids + 1] = id
  end
end
table.sort(ids)
print("POK_ALLOC:[" .. table.concat(ids, ",") .. "]")

-- 스탯: 유한 숫자 전부 (선별은 Python 쪽 몫 — 드라이버는 whitelist를 관리하지 않는다)
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
print("POK_OK")
