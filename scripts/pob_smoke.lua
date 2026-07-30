-- headless PoB 스모크 테스트 — P3 Phase 0 왕복의 회귀 게이트.
-- 실행 (cwd = <pob>/src):
--   echo "" | LUA_PATH="./?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;;" \
--     luajit <repo>/scripts/pob_smoke.lua
-- 검증: 빌드 XML 로드 → 계산 → 스탯 JSON 1왕복. 실패 시 비-0 종료.
--
-- 스파이크에서 확정한 함정들 (어댑터 계약 — src/pok/pob/ 가 그대로 따라야 함):
--   * targetVersion은 빌드 포맷 버전 "0_1" 고정 — 다른 값이면 변환 팝업으로
--     조기 return되어 Tree/Skills 섹션이 통째로 무시된다 (헤드리스에선 무증상).
--   * 클래스는 신형식 classInternalId(7=Sorceress 등) + ascendancyInternalId
--     ("Sorceress1" — KB 어센던시 코드와 동일 체계). 구형식 classId는
--     legacyClassIdMap 재매핑에 걸려 엉뚱한 클래스가 된다.
--   * 시작점과 연결되지 않은 트리 노드는 로드 시 소리 없이 해제된다
--     (FindStartFromNode) → 로드 후 CountAllocNodes로 적법성을 검사한다.
--   * 로드만으로는 계산이 갱신되지 않는다 — calcsTab:BuildOutput() 명시 호출.

-- lua-utf8 C 모듈 폴리필: PoB는 ASCII 숫자 포맷(reverse/gsub/find/sub)에만 쓴다.
package.preload['lua-utf8'] = function()
  return setmetatable({}, { __index = string })
end

dofile("HeadlessWrapper.lua")

local xml = [[<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="90" characterLevelAutoMode="false" targetVersion="0_1" className="Sorceress" ascendClassName="Stormweaver" mainSocketGroup="1"/>
  <Skills sortGemsByDPS="true" activeSkillSet="1">
    <SkillSet id="1">
      <Skill enabled="true" label="" slot="Weapon 1" mainActiveSkill="1">
        <Gem gemId="Metadata/Items/Gems/SkillGemSpark" variantId="Spark" level="20" quality="0" enabled="true" nameSpec="Spark"/>
      </Skill>
    </SkillSet>
  </Skills>
  <Tree activeSpec="1">
    <Spec title="Default" treeVersion="0_5" classInternalId="7" ascendancyInternalId="Sorceress1" nodes="4739,22419"/>
  </Tree>
  <Items/>
  <Config/>
</PathOfBuilding2>]]

loadBuildFromXML(xml, "smoke")
build.calcsTab:BuildOutput()
local out = build.calcsTab.mainOutput

-- 단언: 로드·계산·트리 반영이 실제로 일어났는가
local failures = {}
local function check(cond, msg)
  if not cond then failures[#failures + 1] = msg end
end
check(build.spec.curClassName == "Sorceress",
  "클래스 미반영: " .. tostring(build.spec.curClassName))
check(build.characterLevel == 90, "레벨 미반영: " .. tostring(build.characterLevel))
check((build.spec:CountAllocNodes()) == 2,
  "트리 노드 할당 실패: " .. tostring(build.spec:CountAllocNodes()))
check(type(out.Life) == "number" and out.Life > 100, "Life 비정상: " .. tostring(out.Life))
check(type(out.TotalDPS) == "number" and out.TotalDPS > 0,
  "TotalDPS 비정상: " .. tostring(out.TotalDPS))
check(out.FireResist == -50, "저항 페널티 비정상: " .. tostring(out.FireResist))

local function jesc(s) return s:gsub('[\\"]', '\\%0') end
local keys = { "Life", "Mana", "EnergyShield", "Armour", "Evasion", "TotalDPS",
  "CombinedDPS", "CritChance", "FireResist", "ColdResist", "LightningResist",
  "ChaosResist", "TotalEHP", "PhysicalMaximumHitTaken", "Str", "Dex", "Int" }
local parts = {}
for _, k in ipairs(keys) do
  local v = out[k]
  if type(v) == "number" then
    parts[#parts + 1] = string.format('"%s":%.6g', jesc(k), v)
  end
end
print("POK_JSON:{" .. table.concat(parts, ",") .. "}")

if #failures > 0 then
  for _, msg in ipairs(failures) do
    print("POK_FAIL: " .. msg)
  end
  os.exit(1)
end
print("POK_OK")
