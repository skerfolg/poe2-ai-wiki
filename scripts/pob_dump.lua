-- PoB(PoE2) 게임 데이터 → JSON 덤프 (KB_INGEST §1: PoB 소스 획득)
-- 사용: luajit scripts/pob_dump.lua <pob-src-dir> <out-dir>
-- PoB 런타임 없이 동작: 순수 return 테이블은 직접 로드, Skills/*는 경량 스텁으로 로드.
-- 출력은 원시 스냅샷(artifacts/ingest-raw/<patch>/pob/)이며 가공하지 않는다.

local pob_src, out_dir = arg[1], arg[2]
assert(pob_src and out_dir, "usage: luajit pob_dump.lua <pob-src-dir> <out-dir>")

-- ── JSON 인코더 (외부 의존 없음) ──────────────────────────────
local function is_array(t)
  local n = 0
  for k in pairs(t) do
    if type(k) ~= "number" then return false end
    n = n + 1
  end
  return n == #t
end

local function esc(s)
  s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t')
  return s:gsub('[%z\1-\31]', function(c) return string.format('\\u%04x', c:byte()) end)
end

local encode
encode = function(v, depth)
  depth = depth or 0
  if depth > 40 then return '"<max-depth>"' end
  local tv = type(v)
  if tv == "nil" then return "null"
  elseif tv == "boolean" then return tostring(v)
  elseif tv == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    return string.format("%.14g", v)
  elseif tv == "string" then return '"' .. esc(v) .. '"'
  elseif tv == "function" or tv == "userdata" or tv == "thread" then
    return '"<' .. tv .. '>"'
  elseif tv == "table" then
    if is_array(v) then
      local parts = {}
      for i = 1, #v do parts[#parts + 1] = encode(v[i], depth + 1) end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      local keys = {}
      for k in pairs(v) do keys[#keys + 1] = tostring(k) end
      table.sort(keys)
      local parts = {}
      for _, k in ipairs(keys) do
        -- 원래 키 탐색 (숫자/문자 혼합 테이블 대응)
        local val = v[k]
        if val == nil then val = v[tonumber(k)] end
        parts[#parts + 1] = '"' .. esc(k) .. '":' .. encode(val, depth + 1)
      end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  end
end

local function write_json(path, tbl)
  local f = assert(io.open(path, "w"))
  f:write(encode(tbl))
  f:close()
  print("wrote " .. path)
end

-- ── 1) 순수 return 테이블 파일 (PoB 환경 불필요) ─────────────────
-- Mod*: 제작규칙(RC4)의 원천 — type(Prefix/Suffix)·level(ilvl)·group(배타)·
--       weightKey/weightVal(적용 가능 베이스)·modTags 가 전부 들어 있다.
local PURE = {
  "Gems", "Costs", "Global", "Misc",
  "ModItem", "ModItemExclusive", "ModRunes", "ModCorrupted", "Essence",
  "ModFlask", "ModCharm", "ModJewel",  -- 태그 어휘 교차(⑥)가 잡아낸 누락분
  "ModVeiled",  -- UniqueHeart*(우물의 심장 훼손 풀)·HistoricAbyssJewel* 원천
}
for _, name in ipairs(PURE) do
  local path = pob_src .. "/Data/" .. name .. ".lua"
  local chunk, err = loadfile(path)
  if chunk then
    local ok, data = pcall(chunk)
    if ok and type(data) == "table" then
      write_json(out_dir .. "/" .. name:lower() .. ".json", data)
    else
      print("skip " .. name .. " (실행 실패: " .. tostring(data) .. ")")
    end
  else
    print("skip " .. name .. " (" .. tostring(err) .. ")")
  end
end

-- ── 1b) Bases/*.lua — vararg 주입형 (`local itemBases = ...`) ──────
-- 파일마다 같은 테이블을 넘겨 하나로 모은다. 파일명 = 분류(mace, helmet…)는
-- 항목별 _base_file 로 보존한다 (PoB type 필드와 별개의 수집 계보).
local bases_out, bases_loaded, bases_failed = {}, 0, {}
local base_dir = pob_src .. "/Data/Bases"
local bp = io.popen('ls "' .. base_dir .. '"/*.lua 2>/dev/null')
for path in bp:lines() do
  local chunk, err = loadfile(path)
  if chunk then
    local file_key = path:match("([^/]+)%.lua$")
    -- ⚠ 같은 이름에 **여러 번 대입**하는 베이스가 있다 (백로그 #32). 평범한 테이블에
    -- 받으면 나중 것이 앞의 것을 덮는데, 셋은 인게임에서 **다른 아이템**이다:
    -- `Runemastered Runic Fork`는 추가 발사체 / 마나 재생 / 룬 수호로 갈린다.
    -- 실측 0.5.4b: 31종이 총 96개 정의를 갖는데 덤프엔 31개만 남아 65개가 사라졌다.
    -- 중복은 **한 파일 안**에서 나므로 대입 자체를 가로채야 한다.
    --
    -- ⚠ `__newindex`는 **키가 없을 때만** 불린다 — 평범한 테이블에 걸면 두 번째
    -- 대입이 그냥 덮어써서 아무것도 못 잡는다(실측: 변종 0건). 그래서 sink는 늘
    -- 비워 두는 **프록시**로 두고 실제 값은 `store`에 담는다. 이 형태로 luajit에
    -- 돌려 31종 — PoB 원본과 일치를 확인했다.
    local store = {}
    local sink = setmetatable({}, {
      __index = store,
      __newindex = function(_, key, value)
        local prev = store[key]
        if prev then
          local seen = prev._variants
            or { { implicit = prev.implicit, implicitModTypes = prev.implicitModTypes } }
          seen[#seen + 1] = { implicit = value.implicit, implicitModTypes = value.implicitModTypes }
          value._variants = seen
        end
        store[key] = value
      end,
    })
    local ok, e = pcall(chunk, sink)
    if ok then
      for name, base in pairs(store) do
        base._base_file = file_key
        bases_out[name] = base
      end
      bases_loaded = bases_loaded + 1
    else
      bases_failed[#bases_failed + 1] = path .. ": " .. tostring(e)
    end
  else
    bases_failed[#bases_failed + 1] = path .. ": " .. tostring(err)
  end
end
bp:close()
write_json(out_dir .. "/bases.json", bases_out)
print(string.format("bases files loaded=%d failed=%d", bases_loaded, #bases_failed))
for _, f in ipairs(bases_failed) do print("  FAIL " .. f) end

-- ── 2) Skills/*.lua — 경량 스텁 주입 로드 ──────────────────────
-- 파일 서명: local skills, mod, flag, skill = ...  + 전역 SkillType/ModFlag 등 참조
local function make_capture(kind)
  return function(...)
    return { __stub = kind, args = { ... } }
  end
end

-- SkillType.X → "X" 문자열 (테이블 키로 쓰여도 JSON 직렬화 가능)
local function name_table()
  return setmetatable({}, { __index = function(_, k) return tostring(k) end })
end

-- ModFlag/KeywordFlag는 bit.bor 대상 → 키마다 고유 비트값 부여
-- (실값과 다른 스텁 비트 — 카탈로그 덤프 용도. 계산은 P3에서 진짜 PoB 런타임 사용)
local function bit_table()
  local n = 0
  return setmetatable({}, { __index = function(t, k)
    local v = 2 ^ n
    n = n + 1
    rawset(t, k, v)
    return v
  end })
end

local stub_env = {
  SkillType = name_table(), ModFlag = bit_table(), KeywordFlag = bit_table(),
  math = math, table = table, string = string, pairs = pairs, ipairs = ipairs,
}

local skills_out, loaded, failed = {}, 0, {}
local sk_dir = pob_src .. "/Data/Skills"
local p = io.popen('ls "' .. sk_dir .. '"/*.lua 2>/dev/null')
for path in p:lines() do
  local chunk, err = loadfile(path)
  if chunk then
    setfenv(chunk, setmetatable(stub_env, { __index = _G }))
    local skills = {}
    local ok, e = pcall(chunk, skills, make_capture("mod"), make_capture("flag"), make_capture("skill"))
    if ok then
      local file_key = path:match("([^/]+)%.lua$")
      skills_out[file_key] = skills
      loaded = loaded + 1
    else
      failed[#failed + 1] = path .. ": " .. tostring(e)
    end
  else
    failed[#failed + 1] = path .. ": " .. tostring(err)
  end
end
p:close()

write_json(out_dir .. "/skills.json", skills_out)
print(string.format("skills files loaded=%d failed=%d", loaded, #failed))
for _, f in ipairs(failed) do print("  FAIL " .. f) end
