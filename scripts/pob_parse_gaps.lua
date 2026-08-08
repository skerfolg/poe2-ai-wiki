-- 트리 노드 문구 파싱 갭 덤프 — PoB가 **자기 로드 과정에서 이미 매긴 판정**을 그대로 노출.
-- src/pok/pob/parse_gaps.py 가 서브프로세스로 실행한다.
--
-- 왜 parseMod를 우리가 다시 돌리지 않나: `PassiveTree.lua:436-486`이 노드 문구를 읽을 때
-- ① 줄바꿈 분해 ② 실패 시 **뒤 줄과 합쳐 재시도**(parseMod(comb, true)) ③ 잔여 텍스트가
-- 남으면 `node.extra`, 아예 못 읽으면 `node.unknown`을 세운다. 그 절차를 밖에서 재현하면
-- 그게 곧 **계산 로직 재구현**이고(AD-1 금지), 스냅샷이 바뀌면 조용히 어긋난다.
-- PoB가 세워 둔 플래그를 읽으면 재현도 drift도 없다.
--
-- 판정의 값어치: `node.extra`가 선 줄은 `PassiveTree.lua:487-494`의
-- `if mod.list and not mod.extra`에서 걸러져 **modList에 들어가지 않는다**. 즉 그 노드의
-- 그 줄은 계산에 **0으로 기여**한다 — 경고 없이.
--
-- 사용: (cwd = <pob>/src)  luajit pob_parse_gaps.lua <build.xml 경로>
-- 출력(stdout, 줄 단위 프로토콜 — pob_driver.lua와 동일 계약):
--   POK_TREE:{"version":"0_5","nodes":4321}    검사한 트리·노드 수 (분모)
--   POK_GAP:{"id":123,"name":"..","socket":false,
--            "lines":[{"i":1,"text":"..","status":"extra","rest":".."}]}
--     socket=true는 주얼 소켓 — 그 문구는 효과가 아니라 구조 선언이라 미파싱이 손실이
--     아니다. 판정은 파이썬이 한다(거르되 **몇 건 걸렀는지 보고**하게).
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

local function jesc(s)
  return tostring(s):gsub('[\\"]', '\\%0'):gsub("[%c]", " ")
end

local tree = build.spec.tree
local ids = {}
for id, node in pairs(tree.nodes) do
  if type(id) == "number" and node.mods then
    ids[#ids + 1] = id
  end
end
table.sort(ids)
print(string.format('POK_TREE:{"version":"%s","nodes":%d}',
  jesc(build.spec.treeVersion or "?"), #ids))

for _, id in ipairs(ids) do
  local node = tree.nodes[id]
  -- 노드 단위 플래그(unknown/extra)만 보면 어느 줄이 샜는지 모른다 — 줄 단위로 낸다.
  local parts = {}
  for i, mod in pairs(node.mods) do
    local text = node.sd and node.sd[i]
    if text then
      local status = nil
      if not mod.list then
        status = "unknown"   -- 파서가 아예 못 읽음
      elseif mod.extra then
        status = "extra"     -- 부분 파싱 후 잔여 — modList 편입에서 탈락한다
      end
      if status then
        parts[#parts + 1] = string.format('{"i":%d,"text":"%s","status":"%s","rest":"%s"}',
          i, jesc(text), status, jesc(mod.extra or ""))
      end
    end
  end
  if #parts > 0 then
    -- 주얼 소켓의 「Sinister Jewel Socket」 같은 줄은 **효과가 아니라 구조 선언**이다.
    -- PoB는 소켓을 문구가 아니라 node.type == "Socket"으로 다루므로(PassiveTree.lua:225)
    -- 여기서 파싱이 안 되는 건 손실이 아니다. 거르지 않고 표시해 보내 파이썬이
    -- **센 뒤에 걸러 보고**하게 한다 — 조용히 빼면 분모가 흔들린다.
    print(string.format('POK_GAP:{"id":%d,"name":"%s","socket":%s,"lines":[%s]}',
      id, jesc(node.dn or node.name or ""),
      node.type == "Socket" and "true" or "false", table.concat(parts, ",")))
  end
end

print("POK_OK")
