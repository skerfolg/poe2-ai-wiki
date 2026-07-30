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

-- 메타: 적법성 신호 (연결 안 된 노드는 PoB가 소리 없이 해제하므로 여기서 노출)
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
