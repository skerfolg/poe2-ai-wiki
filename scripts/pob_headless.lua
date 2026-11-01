-- Load the pinned wrapper without changing its bytes on disk. Some LuaJIT
-- builds reject PoB's launcher header (#@), unlike the Windows runtime.
local file = assert(io.open("HeadlessWrapper.lua", "rb"))
local source = file:read("*a")
file:close()
source = source:gsub("^#[^\n]*", "", 1)
return assert(loadstring(source, "@HeadlessWrapper.lua"))()
