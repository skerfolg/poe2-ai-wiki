-- Preserve player axes; expose native selected-minion axes separately.
-- These are PoB's selected actor/skill values, not a reconstructed army total.
return function(output)
  local result = {}
  for key, value in pairs(output or {}) do result[key] = value end
  local minion = output and output.Minion
  if type(minion) == "table" then
    for key, value in pairs(minion) do
      if type(key) == "string" and type(value) == "number" and value == value
          and value ~= math.huge and value ~= -math.huge then
        local name = "Minion." .. key
        assert(result[name] == nil, "Native output collides with selected-minion namespace")
        result[name] = value
      end
    end
  end
  return result
end
