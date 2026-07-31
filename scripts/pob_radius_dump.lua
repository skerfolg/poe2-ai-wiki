-- 주얼 소켓 반경 판정 덤프 — PoB가 미리 계산한 socket.nodesInRadius를 그대로 노출.
-- tests/integration/test_tree_radius.py 가 KB 좌표(passive.data.position) 기반 판정과
-- 대조하는 오라클로 실행한다 (KB 좌표 공간 = PoB 반경 판정 공간 검증).
-- 사용: (cwd = <pob>/src)  luajit pob_radius_dump.lua <build.xml 경로>
-- 출력(stdout, 줄 단위 프로토콜 — pob_driver.lua와 동일 계약):
--   POK_RADII:[{"inner":0,"outer":1000},...]   data.jewelRadius 정의 순서 그대로 (1-based index)
--   POK_RADIUS:{"<socketId>":{"<radiusIndex>":[nodeId,...]},...}
--   POK_OK | POK_ERR:<사유>

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
if not build or not build.spec or not build.spec.tree then
  print("POK_ERR:빌드/트리 로드 실패")
  os.exit(1)
end

local rparts = {}
for _, info in ipairs(data.jewelRadius) do
  rparts[#rparts + 1] = string.format('{"inner":%d,"outer":%d}', info.inner, info.outer)
end
print("POK_RADII:[" .. table.concat(rparts, ",") .. "]")

local sparts = {}
for socketId, socket in pairs(build.spec.tree.sockets) do
  if socket.nodesInRadius then
    local iparts = {}
    for radiusIndex, nodes in ipairs(socket.nodesInRadius) do
      local ids = {}
      for id in pairs(nodes) do
        ids[#ids + 1] = id
      end
      table.sort(ids)
      iparts[#iparts + 1] = string.format('"%d":[%s]', radiusIndex, table.concat(ids, ","))
    end
    sparts[#sparts + 1] = string.format('"%d":{%s}', socketId, table.concat(iparts, ","))
  end
end
print("POK_RADIUS:{" .. table.concat(sparts, ",") .. "}")
print("POK_OK")
