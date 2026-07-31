# Pattern Collections Summary

## What Changed

Refactored hardcoded transaction pattern literals into a configurable **pattern collection system**.

### Before (Hardcoded)
```yaml
action_rules:
  - action: II
    when:
      code: MK
      description_contains:
        - rontgen.lt
        - FONDŲ PIRKIMAS
  
  - action: II
    when:
      code: MK
      receiver_contains:
        - SYNERGY FINANCE
  
  - action: II
    when:
      code: MK
      description_contains:
        - Uz isperkamus Fando vienetus
```

**Problems:**
- Patterns scattered across rules
- Hard to find all instances of similar patterns
- Duplicating patterns requires editing multiple places
- No central repository of business rules

### After (Configurable Collections)
```yaml
# rules.yaml
action_rules:
  - action: II
    when:
      code: MK
      description_contains:
        - "@real_estate"          # Centrally managed
  
  - action: II
    when:
      code: MK
      receiver_contains:
        - "@fund_providers"       # Centrally managed
  
  - action: II
    when:
      code: MK
      description_contains:
        - "@fund_redemptions"     # Centrally managed
```

```json
// patterns.json - Single source of truth
{
  "patterns": {
    "real_estate": {
      "type": "literal",
      "patterns": ["rontgen.lt"]
    },
    "fund_providers": {
      "type": "literal",
      "patterns": ["SYNERGY FINANCE", "Synergy Finance"]
    },
    "fund_redemptions": {
      "type": "literal",
      "patterns": ["Uz isperkamus Fando vienetus", "Už išperkamus Fodo vienetus", ...]
    }
  }
}
```

**Benefits:**
- ✅ Single source of truth (`patterns.json`)
- ✅ Easy to add/modify patterns without touching rules
- ✅ Supports both inline literals and pattern references
- ✅ Self-documenting (each collection has description)
- ✅ Foundation for regex support (planned)

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `patterns.json` | **Created** | Central pattern repository (6 collections) |
| `rules.yaml` | **Updated** | Now uses `@pattern_name` references |
| `parse_ib.py` | **Updated** | Added pattern loading & resolution logic |
| `PATTERNS.md` | **Created** | Comprehensive pattern usage guide |

## New Python Functions

### `_load_patterns(patterns_path: Optional[str]) -> dict`
Loads JSON file containing pattern collections. Returns dict mapping pattern_name → list of patterns.

### `_resolve_pattern_references(value_list: list, patterns: dict) -> list`
Expands `@pattern_name` references to actual patterns. Handles mixed inline/referenced patterns.

## Pattern Collections Defined

| Name | Type | Count | Used For |
|------|------|-------|----------|
| `real_estate` | literal | 1 | Property investment platforms (rontgen.lt) |
| `fund_providers` | literal | 2 | Investment fund providers (Synergy Finance, variants) |
| `fund_purchases` | literal | 4 | Fund purchase keywords (FONDŲ PIRKIMAS, variants) |
| `fund_redemptions` | literal | 3 | Fund redemption/sale keywords (Už išperkamus Fodo vienetus, variants) |
| `pension_contributions` | literal | 2 | Pension contributions to exclude (III pakopos pensijų, variants) |
| `dividends` | literal | 1 | Dividend payment keywords (DIVIDENDAI) |

## Verification

✅ Output unchanged:
- 146 total rows (145 + 1 header)
- 124 II codes (deposits)
- 13 IV codes (dividends)  
- 8 PP codes (withdrawals)

✅ All special conditions working:
- Rontgen.lt real estate investments → II
- Synergy Finance fund purchases → II
- Fund redemptions → II
- Dividends → IV
- Pension contributions → IGNORE (filtered out)

## Usage Examples

### Add a new fund provider

**Option 1: Edit patterns.json**
```json
"fund_providers": {
  "patterns": [
    "SYNERGY FINANCE",
    "Synergy Finance",
    "NEW PROVIDER INC"        // Added
  ]
}
```

**Option 2: Inline in rules.yaml** (no change needed to patterns.json)
```yaml
action_rules:
  - action: II
    when:
      code: MK
      receiver_contains:
        - "@fund_providers"
        - "NEW PROVIDER INC"   // Works alongside collection
```

### Add a new business rule

```yaml
# rules.yaml
action_rules:
  # ... existing rules ...
  
  - action: II
    when:
      code: MK
      description_contains:
        - "@real_estate"
        - "property"           # Custom pattern
        - "@fund_redemptions"
```

## Configuration Best Practices

1. **Central Repository**: Keep all variations in `patterns.json`, not in rules
2. **Case Variants**: Include both uppercase and mixed case:
   ```json
   "fund_keywords": {
     "patterns": [
       "FONDŲ PIRKIMAS",
       "Fondų pirkimas",
       "fondų pirkimas"
     ]
   }
   ```

3. **Character Variants**: Support accented characters:
   ```json
   "pension": {
     "patterns": [
       "III pakopos pensiju",      // without accent
       "III pakopos pensijų"       // with accent
     ]
   }
   ```

4. **Documentation**: Add descriptions:
   ```json
   "real_estate": {
     "type": "literal",
     "description": "Lithuanian real estate crowdfunding platforms",
     "patterns": ["rontgen.lt", "Rontgen"]
   }
   ```

## Next Steps (Optional)

- [ ] Add regex pattern support (`type: "regex"`)
- [ ] Load patterns from multiple files
- [ ] Add pattern matching statistics (how many times each was used)
- [ ] Create UI in Flask app to manage patterns
- [ ] Validate patterns on load (warn about unused patterns)

## See Also

- `PATTERNS.md` - Detailed pattern configuration guide
- `rules.yaml` - Rule-specific documentation
- `CLAUDE.md` - VMI classification concepts

