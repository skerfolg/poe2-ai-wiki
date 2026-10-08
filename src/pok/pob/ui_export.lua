local src = assert(arg[1], "missing PoB src path")
local mode = assert(arg[2], "missing export mode")
local out_path = assert(arg[3], "missing output path")

local function esc(s)
  return '"' .. tostring(s):gsub('[%z\1-\31\\"]', function(c)
    if c == "\\" then return "\\\\" end
    if c == '"' then return '\\"' end
    if c == "\b" then return "\\b" end
    if c == "\f" then return "\\f" end
    if c == "\n" then return "\\n" end
    if c == "\r" then return "\\r" end
    if c == "\t" then return "\\t" end
    return string.format("\\u%04x", c:byte())
  end) .. '"'
end

local function is_array(t)
  local n = 0
  for k in pairs(t) do
    if type(k) ~= "number" or k < 1 or k % 1 ~= 0 then
      return false
    end
    if k > n then n = k end
  end
  for i = 1, n do
    if rawget(t, i) == nil then return false end
  end
  return true, n
end

local diagnostics = {}

local function diag(path, kind, message)
  diagnostics[#diagnostics + 1] = {
    path = path,
    kind = kind,
    message = message,
  }
end

local function encode(v, seen, path)
  path = path or "$"
  local tv = type(v)
  if tv == "nil" then return "null" end
  if tv == "boolean" then return v and "true" or "false" end
  if tv == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    return string.format("%.17g", v)
  end
  if tv == "string" then return esc(v) end
  if tv == "function" then
    diag(path, "unsupported-lua-function", "Lua function serialized as marker string")
    return esc("<function>")
  end
  if tv ~= "table" then
    diag(path, "unsupported-lua-" .. tv, "Unsupported Lua value serialized as marker string")
    return esc("<" .. tv .. ">")
  end

  seen = seen or {}
  if seen[v] then
    diag(path, "cycle", "Cyclic Lua table serialized as marker string")
    return esc("<cycle>")
  end
  seen[v] = true

  local array, n = is_array(v)
  local parts = {}
  if array then
    for i = 1, n do parts[#parts + 1] = encode(v[i], seen, path .. "[" .. i .. "]") end
    seen[v] = nil
    return "[" .. table.concat(parts, ",") .. "]"
  end

  local keys = {}
  for k in pairs(v) do keys[#keys + 1] = k end
  table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
  local seen_keys = {}
  local collision = false
  for _, k in ipairs(keys) do
    local json_key = tostring(k)
    if seen_keys[json_key] then
      collision = true
      break
    end
    seen_keys[json_key] = true
  end
  if collision then
    diag(path, "json-key-collision", "Lua table serialized as typed key/value entries")
    for _, k in ipairs(keys) do
      parts[#parts + 1] = "{" ..
        esc("keyType") .. ":" .. esc(type(k)) .. "," ..
        esc("key") .. ":" .. encode(k, seen, path .. ".__key") .. "," ..
        esc("value") .. ":" .. encode(v[k], seen, path .. "[" .. tostring(k) .. "]") ..
        "}"
    end
    seen[v] = nil
    return "{" .. esc("__luaTable") .. ":" .. esc("typed-map") .. "," ..
      esc("entries") .. ":[" .. table.concat(parts, ",") .. "]}"
  end
  for _, k in ipairs(keys) do
    local json_key = tostring(k)
    parts[#parts + 1] = esc(json_key) .. ":" .. encode(v[k], seen, path .. "." .. json_key)
  end
  seen[v] = nil
  return "{" .. table.concat(parts, ",") .. "}"
end

local function write_json(value)
  local f = assert(io.open(out_path, "wb"))
  f:write(encode(value))
  f:close()
end

local function load_global()
  function copyTable(tbl, noRecurse)
    local out = {}
    for k, v in pairs(tbl) do
      if type(v) == "table" and not noRecurse then
        out[k] = copyTable(v)
      else
        out[k] = v
      end
    end
    return out
  end
  dofile(src .. "/Data/Global.lua")
end

local function mod(...)
  return { __kind = "mod", args = { ... } }
end

local function flag(...)
  return { __kind = "flag", args = { ... } }
end

local data
if mode == "versions" then
  dofile(src .. "/GameVersions.lua")
  data = {versions = treeVersionList, latest = latestTreeVersion, targetVersion = liveTargetVersion}
elseif mode == "gems" then
  data = dofile(src .. "/Data/Gems.lua")
elseif mode == "bases" then
  data = {}
  for i = 4, #arg do assert(loadfile(arg[i]))(data) end
elseif mode == "mods" then
  data = {}
  for i = 4, #arg do
    local chunk = dofile(arg[i])
    for id, row in pairs(chunk) do data[id] = row end
  end
elseif mode == "uniques" then
  data = {}
  for i = 4, #arg do
    local rows = dofile(arg[i])
    for _, text in ipairs(rows) do data[#data + 1] = text end
  end
elseif mode == "skills" then
  load_global()
  data = {}
  for i = 4, #arg do assert(loadfile(arg[i]))(data, mod, flag, mod) end
else
  error("unknown export mode: " .. tostring(mode))
end

write_json({ data = data, diagnostics = diagnostics })
