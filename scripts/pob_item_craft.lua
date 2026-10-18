-- Native item rendering adapter, shared by the daemon and one-shot roundtrip.
-- This is a representation boundary, not an affix legality policy. Our checker
-- retains the season's independent per-side/total budgets. Never add mod text or
-- numbers here: PoB's own Craft/applyRange/stat merging renders every effect.
return function(item)
  if item.type == "Jewel" and item.rarity == "RARE" and item.crafted then
    -- The pinned Item.lua defaults rare jewels to two entries per side. It keeps
    -- a third Prefix declaration in ParseRaw/BuildRaw but Craft silently omits its
    -- effect. Tell the existing native API how many entries were actually given.
    -- ParseRaw pads normal empty entries with None; those remain harmless.
    for _, list in ipairs({item.prefixes, item.suffixes}) do
      for _, affix in ipairs(list) do
        if affix.modId ~= "None" and not item.affixes[affix.modId] then
          error("PoB cannot render declared jewel affix: " .. tostring(affix.modId))
        end
      end
      list.limit = #list
    end
  end
  item:Craft()
end
