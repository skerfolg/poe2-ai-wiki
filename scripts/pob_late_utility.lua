-- Read-only post-calculation utility axes. Keep PoB's original output intact:
-- pinned CalcPerform stores EffectiveLootRarityMod before applying Mageblood.
-- Query native helpers after BuildOutput rather than replicating the formula.
return function(env)
  local result = {}
  local mods = env and env.player and env.player.modDB
  if not mods then return result end
  local queries = {
    LateLootRarityInc = function() return mods:Sum("INC", nil, "LootRarity") end,
    LateLootRarityMore = function() return mods:More(nil, "LootRarity") end,
    LateLootRarityMod = function() return calcLib.mod(mods, nil, "LootRarity") end,
  }
  for key, query in pairs(queries) do
    local ok, value = pcall(query)
    if ok and type(value) == "number" and value == value
        and value ~= math.huge and value ~= -math.huge then
      result[key] = value
    end
  end
  return result
end
