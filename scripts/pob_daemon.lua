-- 상주 headless PoB — 최적화 루프용 (src/pok/pob/daemon.py 가 관리).
-- 기동(~2초, 트리·데이터 로드)을 1회로 상각하고 계산당 ~0.1초로 응답한다.
--
-- 프로토콜 (stdin 줄 단위):
--   부팅 완료  → "POK_READY" 출력
--   <xml 경로> → 계산 후 POK_META / POK_ALLOC / POK_JSON / POK_DONE 출력
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

local function respond(xmlText)
  loadBuildFromXML(xmlText, "pok")
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

print("POK_READY")
io.stdout:flush()

for line in io.lines() do
  if line == "QUIT" then break end
  local f = io.open(line, "rb")
  if not f then
    print("POK_ERR:XML 파일 열기 실패: " .. line)
  else
    local xmlText = f:read("*a")
    f:close()
    local ok, err = pcall(respond, xmlText)
    if not ok then
      print("POK_ERR:" .. jesc(err))
    end
  end
  print("POK_DONE")
  io.stdout:flush()
end
