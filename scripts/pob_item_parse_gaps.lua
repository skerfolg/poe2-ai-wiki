-- 아이템 문구 파싱 갭 덤프 — 트리판(pob_parse_gaps.lua)의 아이템 경로 짝.
-- src/pok/pob/item_parse_gaps.py 가 서브프로세스로 실행한다.
--
-- 트리와 같은 원칙: **PoB가 스스로 매긴 판정만 읽는다**(AD-1 — 계산 로직 재구현 금지).
-- `Classes/Item.lua:947`이 `applyRange`로 값 범위를 푼 뒤 `parseMod`에 넘기고,
-- 실패하면 다음 줄과 합쳐 재시도하며, 잔여가 남으면 `modLine.extra`를 세운다.
-- 그 줄은 `Item.lua:2138`의 `if not modLine.extra`에서 걸러져 **계산에 안 들어간다**.
--
-- 왜 아이템을 진짜로 만들어야 하나: KB 원문에는 `(35-42)%` 같은 값 범위가 있는데
-- 그 해석은 `Item.lua`가 한다. 문구만 떼어 `parseMod`에 직접 넣으면 멀쩡한 모드가
-- 파싱 실패로 잡힌다(오탐). 그래서 레코드마다 아이템 하나를 세워 PoB에게 묻는다.
-- 레코드 단위로 나누는 이유는 **줄 합치기 재시도가 레코드 안에서만** 일어나야 하기
-- 때문이다 — 한 아이템에 몰아넣으면 남의 줄과 합쳐져 없는 성공이 생긴다.
--
-- 사용: (cwd = <pob>/src)  luajit pob_item_parse_gaps.lua <입력파일>
-- 입력(줄 단위):
--   #REC<TAB><레코드 id><TAB><베이스명>
--   <문구 줄>…
--   #END
-- 출력(stdout):
--   POK_SCANNED:{"records":N,"lines":M}
--   POK_GAP:<id><TAB><줄번호><TAB>unknown|extra<TAB><문구><TAB><잔여>
--   POK_OK | POK_ERR:<사유>

package.preload['lua-utf8'] = function()
  return setmetatable({}, { __index = string })
end

local inPath = arg and arg[1]
if not inPath then
  print("POK_ERR:입력 파일 인자 누락")
  os.exit(2)
end
local fh = io.open(inPath, "rb")
if not fh then
  print("POK_ERR:입력 파일 열기 실패: " .. inPath)
  os.exit(2)
end

dofile("HeadlessWrapper.lua")

local function clean(s)
  return tostring(s):gsub("[%c]", " ")
end

local records, scannedLines = 0, 0
local id, base, lines = nil, nil, {}

local function flush()
  if not id then return end
  records = records + 1
  scannedLines = scannedLines + #lines
  -- 실제 아이템 텍스트 형식 그대로 — PoB가 베이스·희귀도를 읽어야 접사로 취급한다.
  local raw = "Rarity: RARE\nPoK Probe\n" .. base .. "\nItem Level: 100\n"
      .. table.concat(lines, "\n")
  local ok, item = pcall(function() return new("Item", raw) end)
  if not ok or not item then
    -- 파싱 중 PoB가 **예외를 던진** 경우. 조용한 0과는 성질이 다르다(예: "Socketed Gems
    -- are Supported by Level N X"가 PoE2에 없는 서포트를 찾다 죽는다). 갭으로 뭉뚱그리면
    -- 원인이 가려지므로 따로 낸다.
    print(string.format("POK_GAP:%s\t0\terror\t%s\t%s", clean(id), "<아이템 생성 실패>",
      clean(item)))
  else
    -- 어느 통에 담겼든(암시·명시·룬) 잔여 판정은 같다.
    local groups = { item.implicitModLines, item.explicitModLines, item.runeModLines,
                     item.enchantModLines }
    local seen = 0
    for _, group in ipairs(groups) do
      for _, modLine in ipairs(group or {}) do
        seen = seen + 1
        if modLine.extra then
          -- modList가 비어 있으면 파서가 아예 못 읽은 것, 있으면 부분 파싱 후 잔여.
          local kind = (modLine.modList and #modLine.modList > 0) and "extra" or "unknown"
          print(string.format("POK_GAP:%s\t%d\t%s\t%s\t%s",
            clean(id), seen, kind, clean(modLine.line), clean(modLine.extra)))
        end
      end
    end
  end
  id, base, lines = nil, nil, {}
end

for line in fh:lines() do
  local recId, recBase = line:match("^#REC\t([^\t]*)\t(.*)$")
  if recId then
    flush()
    id, base, lines = recId, recBase, {}
  elseif line == "#END" then
    flush()
  elseif id then
    lines[#lines + 1] = line
  end
end
fh:close()
flush()

print(string.format('POK_SCANNED:{"records":%d,"lines":%d}', records, scannedLines))
print("POK_OK")
