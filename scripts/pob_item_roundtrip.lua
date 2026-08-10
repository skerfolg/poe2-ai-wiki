-- 아이템 텍스트 **왕복 검사** — 우리가 만든 것과 PoB가 쓰는 것이 같은가 (백로그 #34).
-- src/pok/pob/roundtrip.py 가 서브프로세스로 실행한다.
--
-- 규격은 사용자가 올린 PoB 코드가 아니라 **PoB 소스**다: `Item.lua::BuildRaw()`가
-- PoB 자신이 아이템을 텍스트로 쓸 때 쓰는 함수이고, `BuildAndParseRaw`가 그 출력을
-- 다시 파싱한다(L1604). 즉 **BuildRaw 출력 = 파싱 가능한 정본**이다.
--
-- 검사: 입력 텍스트로 아이템을 세우고 `BuildRaw()`를 부른다. 출력이 입력과 다르면
-- 그 차이가 곧 "사람이 만든 것과 다른 물건"이다. 우리가 판정을 만들지 않는다 —
-- PoB가 자기 포맷으로 다시 쓴 결과를 그대로 낸다(AD-1).
--
-- 사용: (cwd = <pob>/src)  luajit pob_item_roundtrip.lua <입력파일>
-- 입력(줄 단위):  #ITEM<TAB><라벨> … 아이템 줄들 … #END
-- 출력(stdout):
--   POK_RAW:<라벨><TAB><BuildRaw 출력을 \n → \\n 으로 이스케이프>
--   POK_ERR_ITEM:<라벨><TAB><사유>
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

local function escape(s)
  return (tostring(s):gsub("\\", "\\\\"):gsub("\n", "\\n"):gsub("\r", ""):gsub("\t", " "))
end

local label, lines = nil, {}

local function flush()
  if not label then return end
  local raw = table.concat(lines, "\n")
  local ok, item = pcall(function() return new("Item", raw) end)
  if not ok or not item then
    print(string.format("POK_ERR_ITEM:%s\t%s", escape(label), escape(item)))
  else
    -- 룬은 `Sockets:`+`Rune:` 선언에서 PoB가 스스로 만든다(`UpdateRunes`, L1610) —
    -- 손으로 쓴 `{rune}` 줄이 있으면 여기서 **겹쳐 보인다**. 그게 #34의 D 사고다.
    -- PoB 자신의 생성 순서를 그대로 탄다(#34 근본 해결): `Craft()`가 모드 id에서
    -- 문구를 만들고 그때 `applyRange`·`getCatalystScalar`(촉매)를 적용한다(L1695~).
    -- 우리가 문구를 조립하지 않는 이유가 여기 있다 — 값은 PoB가 자기 정의에서 낸다.
    -- ⚠ `Craft()`는 `explicitModLines`를 **통째로 지우고** prefixes/suffixes에서 다시
    -- 만든다(L1704). `{custom}` 표식이 없는 손기입 줄은 그때 **사라진다** — PoB 자신이
    -- "크래프트 아이템의 정본은 모드 id"라고 말하는 것이다. 그래서 `Crafted: true`인
    -- 명세에만 건다. 안 그러면 손기입 아이템의 문구를 우리가 날린다(§0 ⑤).
    if item.Craft and raw:match("Crafted:%s*true") then
      pcall(function() item:Craft() end)
    end
    if item.UpdateRunes then pcall(function() item:UpdateRunes() end) end
    local okBuild, built = pcall(function() return item:BuildRaw() end)
    if not okBuild then
      print(string.format("POK_ERR_ITEM:%s\t%s", escape(label), escape(built)))
    else
      print(string.format("POK_RAW:%s\t%s", escape(label), escape(built)))
    end
  end
  label, lines = nil, {}
end

for line in fh:lines() do
  local name = line:match("^#ITEM\t(.*)$")
  if name then
    flush()
    label, lines = name, {}
  elseif line == "#END" then
    flush()
  elseif label then
    lines[#lines + 1] = line
  end
end
fh:close()
flush()

print("POK_OK")
