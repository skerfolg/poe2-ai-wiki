-- Load the pinned wrapper without changing its bytes on disk. Some LuaJIT
-- builds reject PoB's launcher header (#@), unlike the Windows runtime.
local nativeLoadfile, nativeDofile = loadfile, dofile
local function compatibleLoadfile(filename)
  if type(filename) ~= "string" then return nativeLoadfile(filename) end
  local file = io.open(filename, "rb")
  if not file then return nativeLoadfile(filename) end
  local first = file:read(1)
  if first ~= "#" then
    file:close()
    return nativeLoadfile(filename)
  end
  local source = first .. file:read("*a")
  file:close()
  -- Preserve the newline so parser diagnostics retain original line numbers.
  source = source:gsub("^#[^\n]*", "", 1)
  return loadstring(source, "@" .. filename)
end
loadfile = compatibleLoadfile
dofile = function(filename)
  if filename == nil then return nativeDofile() end
  local chunk, message = compatibleLoadfile(filename)
  if not chunk then error(message, 2) end
  return chunk()
end
return dofile("HeadlessWrapper.lua")
