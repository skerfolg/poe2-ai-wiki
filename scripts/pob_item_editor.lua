-- Native item double-click probe. No calculation build or user file is changed.
-- ItemListControl.lua:186-189: BuildRaw -> new Item -> SetDisplayItem.
-- Flush every stage so a timeout still leaves the last reached operation.
package.preload['lua-utf8'] = function()
  return setmetatable({}, { __index = string })
end

local inputPath, outputPath = arg[1], arg[2]
if not inputPath or not outputPath then
  print('POK_ERR:item editor input/output path missing')
  os.exit(2)
end

dofile('HeadlessWrapper.lua')
local json = require('dkjson')
local inputFile = assert(io.open(inputPath, 'rb'))
local entries, _, decodeError = json.decode(inputFile:read('*a'))
inputFile:close()
if not entries then error(decodeError or 'item editor input invalid') end
local result = {protocol = 1, items = {}, complete = false}

local function flush()
  local output = assert(io.open(outputPath, 'wb'))
  output:write(assert(json.encode(result)))
  output:flush()
  output:close()
end

local function stage(row, name)
  row.stage = name
  flush()
end

for _, entry in ipairs(entries) do
  result.items[#result.items + 1] = {
    label = entry.label, stage = 'pending', checked = false, compatible = false,
  }
end
flush()

for index, entry in ipairs(entries) do
  local row = result.items[index]
  local ok, why = pcall(function()
    stage(row, 'parse')
    local original = new('Item', entry.text)
    if not original or not original.base then error('PoB did not recognize item base') end
    row.initial_sockets = original.itemSocketCount or 0
    stage(row, 'serialize_for_double_click')
    local serialized = original:BuildRaw()
    stage(row, 'reparse_for_double_click')
    local opened = new('Item', serialized)
    if not opened or not opened.base then error('PoB lost item base on double-click') end
    opened.id = original.id
    row.opened_sockets = opened.itemSocketCount or 0
    stage(row, 'set_display_item')
    build.itemsTab:SetDisplayItem(opened)
    if row.initial_sockets ~= row.opened_sockets then
      row.stage = 'double_click_count_check'
      row.code = 'count_changed'
      error(string.format('double-click changed socket count: %d -> %d',
        row.initial_sockets, row.opened_sockets))
    end
  end)
  row.checked = true
  row.compatible = ok
  if not ok then row.error = tostring(why) end
  if ok then row.stage = 'complete' end
  flush()
  -- Dispose the display reference without invoking more native UI work.
  build.itemsTab.displayItem = nil
end
result.complete = true
flush()
print('POK_OK')
