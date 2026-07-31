# Pattern Collections Configuration

## Overview

The `patterns.json` file allows you to define reusable collections of text patterns (literals or regex) that can be referenced in `rules.yaml` using the `@pattern_name` syntax.

This centralizes pattern management and makes rules easier to maintain.

## How It Works

### 1. Define Patterns in `patterns.json`

```json
{
  "patterns": {
    "real_estate": {
      "type": "literal",
      "description": "Real estate/property investment platforms",
      "patterns": [
        "rontgen.lt",
        "Rontgen"
      ]
    },
    "fund_providers": {
      "type": "literal",
      "description": "Investment fund providers",
      "patterns": [
        "SYNERGY FINANCE",
        "Synergy Finance"
      ]
    }
  }
}
```

### 2. Reference Patterns in `rules.yaml`

Simply use `@pattern_name` to reference a collection:

```yaml
action_rules:
  - action: II
    when:
      code: MK
      receiver_contains:
        - "@fund_providers"    # Resolves to all patterns in 'fund_providers' collection
  
  - action: II
    when:
      code: MK
      description_contains:
        - "@real_estate"       # Resolves to all patterns in 'real_estate' collection
        - "custom_literal"     # Inline literals still work!
```

## Pattern Collection Structure

Each collection in `patterns.json` has this schema:

```json
{
  "collection_name": {
    "type": "literal|regex",           // Currently "literal" is implemented
    "description": "Human-readable description of what these patterns match",
    "patterns": [
      "pattern1",
      "pattern2"
    ]
  }
}
```

- **type**: Pattern matching mode (currently only `literal` is implemented; `regex` planned)
- **description**: Optional documentation string
- **patterns**: Array of pattern strings to match

## Matching Behavior

### Literal Matching (Case-Insensitive)

```yaml
patterns:
  my_patterns:
    type: "literal"
    patterns:
      - "rontgen.lt"
      - "SYNERGY FINANCE"
```

Matches:
- `payment to rontgen.lt project` ✅ (case-insensitive substring match)
- `UAB Synergy Finance` ✅
- `synergyfinance.com` ✅ (substring match)

Does NOT match:
- `rontgen.com` ❌ (doesn't contain "rontgen.lt")

## Built-in Pattern Collections

See `patterns.json` for the current set. Key collections:

| Collection | Used For | Examples |
|-----------|----------|----------|
| `real_estate` | Property invest platforms | rontgen.lt |
| `fund_providers` | Fund providers | SYNERGY FINANCE |
| `fund_purchases` | Fund buy keywords | FONDŲ PIRKIMAS, Fondų pirkimas |
| `fund_redemptions` | Fund sell keywords | Už išperkamus Fodo vienetus |
| `pension_contributions` | Pension (to exclude) | III pakopos pensijų |
| `dividends` | Dividend keywords | DIVIDENDAI |

## Adding New Patterns

### Step 1: Edit `patterns.json`

```json
{
  "patterns": {
    // ... existing patterns ...
    "my_new_collection": {
      "type": "literal",
      "description": "Description of when to use this collection",
      "patterns": [
        "pattern1",
        "pattern2"
      ]
    }
  }
}
```

### Step 2: Use in `rules.yaml`

```yaml
action_rules:
  - action: II
    when:
      code: MK
      description_contains:
        - "@my_new_collection"
```

### Step 3: Run parser

```bash
python3 parse_ib.py source/statement.csv \
  --broker swedbank \
  --swedbank-rules rules.yaml \
  --year 2025
```

## Pattern Resolution Examples

### Example 1: Multiple Collections in One Rule

```yaml
action_rules:
  - action: II
    when:
      code: MK
      description_contains:
        - "@real_estate"       # Expands to: ["rontgen.lt"]
        - "@fund_purchases"    # Expands to: ["FONDŲ PIRKIMAS", "Fondų pirkimas", ...]
        - "custom_pattern"     # Stays as: ["custom_pattern"]
```

Resolves to 4+ patterns: `["rontgen.lt", "FONDŲ PIRKIMAS", "Fondų pirkimas", ..., "custom_pattern"]`

### Example 2: Pattern in Receiver Field

```yaml
action_rules:
  - action: II
    when:
      code: MK
      receiver_contains:
        - "@fund_providers"    # Checks receiver/beneficiary field for fund providers
```

Matches transactions where beneficiary name contains "SYNERGY FINANCE"

### Example 3: Mixed Literal & Regex (Future)

```yaml
patterns:
  mixed_example:
    type: "regex"
    patterns:
      - "^FONDAI_.*"            # Starts with FONDAI_
      - "rontgen\\.lt"          # Escaped dot for regex
```

*Regex matching is planned but not yet implemented.*

## Troubleshooting

### Error: "Unknown pattern reference: @pattern_name"

**Cause**: Pattern collection not defined in `patterns.json`

**Solution**: 
1. Check the spelling in `rules.yaml`
2. Verify the collection exists in `patterns.json`
3. Reload/restart the parser

### Patterns Not Matching

**Cause**: Mismatched case sensitivity or substring mismatch

**Solution**:
- Literal matching is case-insensitive, but requires substring match
- `"SYNERGY"` will match `"UAB Synergy Finance"` ✅
- `"Synergy Finance"` will match `"UAB Synergy Finance"` ✅
- `"Finance"` will match `"Synergy Finance"` ✅
- `"SYNERGY FINANCE LTD"` will NOT match `"SYNERGY FINANCE"` ❌ (no substring)

## Performance Notes

- Patterns are loaded once when the parser starts
- No runtime performance impact compared to inline literals
- Each pattern reference expands to all patterns in the collection
- Large collections (1000+ patterns) are supported

## Best Practices

1. **Group related patterns**: Keep fund names in one collection, not scattered
2. **Document purpose**: Use descriptive names and descriptions (e.g., `pension_exclusions` not `p10`)
3. **Avoid duplication**: Define a pattern once, reference many times
4. **Test after editing**: Run parser to verify pattern resolution works
5. **Use case variations**: Include both uppercase and mixed-case variants:
   ```json
   "fund_keywords": {
     "patterns": [
       "FONDŲ PIRKIMAS",      // Uppercase variant
       "Fondų pirkimas",      // Mixed case variant
       "Fondų Pirkimas"       // Alternative capitalization
     ]
   }
   ```

## Future Enhancements

Planned features:
- **Regex matching** (`type: "regex"`) for complex patterns
- **Pattern inheritance** (base collections extending others)
- **Dynamic loading** from external URLs
- **Pattern statistics** (how many times each pattern matched)

## See Also

- `rules.yaml` - Main rule configuration
- `CLAUDE.md` - VMI classification rules and concepts
- `CLAUDE.md` - General project documentation

