-- Observe native post-calculation selection. Do not reconstruct the active list
-- from gem slots: supports, hidden effects and global toggles change that list.
local function quoted(value)
  if type(value) ~= "string" then return "null" end
  return '"' .. value:gsub('[\\"]', '\\%0'):gsub("[%c]", function(c)
    return string.format("\\u%04x", string.byte(c))
  end) .. '"'
end

local function ordinal(value)
  if type(value) ~= "number" or value ~= value or value == math.huge
      or value == -math.huge or value < 1 or value ~= math.floor(value) then
    return "null"
  end
  return tostring(value)
end

local function boolean(value)
  if value == nil then return "null" end
  return value and "true" or "false"
end

return function(build, types)
  local env = build and build.calcsTab and build.calcsTab.mainEnv
  local player = env and env.player
  if not player or not player.activeSkillList then
    return '{"format":"pok.native-selection.v1","status":"unavailable","groups":[],"actual":null}'
  end
  local main = player.mainSkill
  local current = {}
  for _, skill in ipairs(player.activeSkillList) do current[skill] = true end

  local function effectJson(skill, group, groupIndex, activeIndex, actorMain)
    local effect = skill.activeEffect or {}
    local granted = effect.grantedEffect or {}
    local source = effect.srcInstance
    local gemIndex
    if source and group then
      for index, gem in ipairs(group.gemList or {}) do
        if gem == source then gemIndex = index break end
      end
    end
    local gemData = effect.gemData or (source and source.gemData) or {}
    local mode = effect.statSet
    local modes = {}
    for index, statSet in ipairs(granted.statSets or {}) do
      modes[#modes + 1] = '{"index":' .. ordinal(index)
          .. ',"label":' .. quoted(statSet.label) .. '}'
    end
    local meta
    if types and types.Meta and skill.skillTypes then
      meta = not not skill.skillTypes[types.Meta]
    end
    return '{"group_index":' .. ordinal(groupIndex)
        .. ',"active_index":' .. ordinal(activeIndex)
        .. ',"gem_index":' .. ordinal(gemIndex)
        .. ',"gem_id":' .. quoted((source and source.gemId) or gemData.id)
        .. ',"gem_name":' .. quoted(source and source.nameSpec)
        .. ',"effect_id":' .. quoted(granted.id)
        .. ',"effect_name":' .. quoted(granted.name)
        .. ',"stat_set_index":' .. ordinal(mode and mode.index)
        .. ',"stat_set_resolved":' .. boolean(mode and type(mode.statSet) == "table")
        .. ',"stat_sets":[' .. table.concat(modes, ",") .. ']'
        .. ',"meta_container":' .. boolean(meta)
        .. ',"selected":' .. boolean(skill == (actorMain or main)) .. '}'
  end

  local groups = {}
  local actual
  for groupIndex, group in ipairs((build.skillsTab and build.skillsTab.socketGroupList) or {}) do
    local effects = {}
    for activeIndex, skill in ipairs(group.displaySkillList or {}) do
      if current[skill] then
        local entry = effectJson(skill, group, groupIndex, activeIndex)
        effects[#effects + 1] = entry
        if skill == main then actual = entry end
      end
    end
    groups[#groups + 1] = '{"group_index":' .. ordinal(groupIndex)
        .. ',"label":' .. quoted(group.label)
        .. ',"slot":' .. quoted(group.slot)
        .. ',"effects":[' .. table.concat(effects, ",") .. ']}'
  end
  local status = actual and "observed" or "default_or_unmapped"
  if not actual and main and current[main] then
    actual = effectJson(main, nil, nil, nil)
  end
  local minion = env.minion
  local minionMain = minion and minion.mainSkill
  local minionJson = minionMain and effectJson(minionMain, nil, nil, nil, minionMain) or "null"
  return '{"format":"pok.native-selection.v1","status":' .. quoted(status)
      .. ',"groups":[' .. table.concat(groups, ",") .. ']'
      .. ',"actual":' .. (actual or "null")
      .. ',"minion":{"scope":"native_selected_actor_not_army_total","stat_prefix":"Minion.","actual":' .. minionJson .. '}}'
end
