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

-- ⛔ **아이템의 룬 소켓 예산을 오라클이 신고한다** (#120).
--    PoB는 아이템 텍스트의 `Sockets:` 줄을 **그대로 믿는다**(`Item.lua:577`
--    `self.itemSocketCount = #self.sockets`) — 어디와도 대조하지 않는다. 그래서
--    칸 수가 틀려도 계산은 조용히 나오고 **UI에서만** 터진다:
--    `ItemsTab.lua:696`이 룬 드롭다운을 **6개만** 만드는데
--    `UpdateRuneControls`(:2016)는 `for i = 1, item.itemSocketCount`로 돌아
--    7칸부터 `displayItemRune7`이 nil이다 — 아이템 상세보기에서 예외.
--
-- ⚠⚠ **예산은 베이스 한도가 아니다.** 넘기는 경로가 여럿 실재한다:
--    ① 유니크 자기 정의 (Atziri's Splendour 6 > 베이스 4 · Runeseeker's Call 5 > 3)
--    ② **트리 부여** — 마셜 아티스트 `Runic Meridians`(39552)가 투구+1·갑옷+2·
--       장갑+1·장화+1을 준다. PoB는 이 노드를 **한 줄도 파싱하지 못하므로**
--       (`pob_modeling.supported: false`) `base.socketLimit`에 절대 안 들어온다.
--    ③ 타락 등 이 함수가 모르는 경로.
--    실측 2026-08-25: 베이스 한도로만 쟀더니 사용자 신고 빌드 4건 중 **3건이
--    거짓 거부**였다(전부 ②로 정확히 설명된다). 거짓 거부는 게이트 우회를
--    학습시킨다(BACKLOG 형태 ⑪) — 그래서 여기서는 **사실만 낸다**:
--    `limit`(베이스/유니크) · `grant`(트리 부여) · `slot` · `corrupted`.
--    무엇을 막을지는 Python 쪽 `socket_problems`가 정한다.
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

-- 트리가 부여하는 **부위별 추가 룬 칸** — `Runic Meridians`(39552) 계열.
-- PoB 자신의 노드 문구를 읽는다(재구현 금지, AD-1). 문구 형태:
--     additional Rune-only sockets:
--     1 Helmet socket
--     2 Body Armour sockets
-- ⚠ 숫자 줄만 보면 안 된다 — "Rune-only sockets" 머리줄을 **먼저 만난 노드에서만**
--    센다. 안 그러면 주얼 소켓·다른 문구의 숫자 줄까지 룬 칸으로 오인한다.
local function pokRuneSocketGrants()
  local grants = {}
  if not (build and build.spec and build.spec.allocNodes) then return grants end
  for _, node in pairs(build.spec.allocNodes) do
    local armed = false
    for _, line in ipairs(node.sd or {}) do
      if line:lower():find("rune%-only sockets") then
        armed = true
      elseif armed then
        local count, slot = line:match("^(%d+)%s+(.-)%s+sockets?$")
        if count then
          grants[slot] = (grants[slot] or 0) + tonumber(count)
        else
          armed = false  -- 열거가 끝났다
        end
      end
    end
  end
  return grants
end

-- 아이템 id → 장착 슬롯 이름. 부위별 부여를 붙이려면 어느 칸에 꽂혔는지가 필요하다.
local function pokItemSlots()
  local out = {}
  for name, slot in pairs((build and build.itemsTab and build.itemsTab.slots) or {}) do
    if slot.selItemId and slot.selItemId ~= 0 then out[slot.selItemId] = name end
  end
  return out
end

local function pokItems()
  local tab = build and build.itemsTab
  if not tab or not tab.items then return "[]" end
  local uniques = pokUniqueSockets()
  local grants = pokRuneSocketGrants()
  local slotOf = pokItemSlots()
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
    local slot = slotOf[id] or ""
    local grant = grants[slot] or 0
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
      '{"id":"%s","name":"%s","base":"%s","rarity":"%s","slot":"%s","sockets":%d,'
      .. '"limit":%d,"limitSource":"%s","grant":%d,"corrupted":%s,"unknownRunes":[%s]}',
      jesc(id), jesc(item.title or item.name or ""), jesc(item.baseName or ""),
      jesc(item.rarity or ""), jesc(slot), sockets, limit, source, grant,
      item.corrupted and "true" or "false", table.concat(unknown, ","))
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
