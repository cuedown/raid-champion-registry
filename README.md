# Raid: Shadow Legends - Complete Champion Registry

## Overview
This repository contains the definitive champion registry for Raid: Shadow Legends, covering all 650+ champions across all rarities (Common, Uncommon, Rare, Epic, Legendary) with detailed mastery builds, artifact recommendations, and stat targets.

## Data Structure
```
data/
├── champions/
│   ├── legendary_*.json    # Legendary champions (80+)
│   ├── epic_*.json        # Epic champions (150+)
│   ├── rare_*.json        # Rare champions (180+)
│   ├── uncommon_*.json    # Uncommon champions (140+)
│   └── common_*.json      # Common champions (100+)
```

## Champion Data Schema
Each champion entry includes:
- **id**: Unique identifier
- **name**: Champion name
- **rarity**: Common, Uncommon, Rare, Epic, or Legendary
- **affinity**: Shadow, Earth, Spirit, Fire, or Light
- **faction**: Faction affiliation
- **role**: Primary role (DPS, Support, Tank, etc.)
- **tier**: Tier rating (S+, S, A+, A, B+, B, C+)
- **builds**: Array of builds with:
  - `purpose`: Build purpose (Clan Boss, Arena, Dungeon Farmer, etc.)
  - `masteries`: Complete mastery tree paths
    - `offense`: 6-tier path
    - `defense`: 6-tier path
    - `support`: 6-tier path
  - `artifact_sets`: Recommended artifact sets
  - `gear_pieces`: Detailed recommendations for all 6 slots:
    - `set`: Artifact set name
    - `main_stat`: Optimal main stat
    - `desired_substats`: Ordered list of desired substats
    - `notes`: Special requirements
  - `substat_priority_overall`: Global substat priority
  - `stat_targets`: Recommended stat thresholds
  - `special_requirements`: Additional notes

## Example Champion Entry
```json
{
  "id": "the-dread-wolf",
  "name": "The Dread Wolf",
  "rarity": "Legendary",
  "affinity": "Shadow",
  "faction": "Dire Howls",
  "role": "DPS / Nuker",
  "tier": "S",
  "builds": [
    {
      "purpose": "Clan Boss - Damage Dealing",
      "masteries": {
        "offense": ["Deadly Precision", "Keen Strike", "Heart of Glory", "Single Out", "Bring It Down", "Warmaster"],
        "defense": [],
        "support": []
      },
      "artifact_sets": ["Lifesteal", "Savage"],
      "gear_pieces": {
        "weapon": { "set": "Lifesteal", "main_stat": "ATK", "desired_substats": ["SPD", "Crit Rate", "Crit DMG"], "notes": "Rank 6 Legendary" },
        "helmet": { "set": "Lifesteal", "main_stat": "HP", "desired_substats": ["SPD", "ATK%", "RES"], "notes": "" },
        "shield": { "set": "Savage", "main_stat": "DEF", "desired_substats": ["SPD", "Crit Rate", "ACC"], "notes": "" },
        "gloves": { "set": "Lifesteal", "main_stat": "Crit Rate%", "desired_substats": ["SPD", "ATK%", "Crit DMG"], "notes": "" },
        "chest": { "set": "Savage", "main_stat": "ATK%", "desired_substats": ["SPD", "Crit Rate", "Crit DMG"], "notes": "" },
        "boots": { "set": "Lifesteal", "main_stat": "SPD", "desired_substats": ["Crit Rate", "ATK%", "RES"], "notes": "" }
      },
      "substat_priority_overall": ["SPD", "Crit Rate", "Crit DMG", "ATK%"],
      "stat_targets": { "HP": 38000, "ATK": 4600, "DEF": 2100, "SPD": 190, "C_RATE": 100, "C_DMG": 150, "RES": 50, "ACC": 180 },
      "special_requirements": "Lifesteal 4-piece for sustain. Focus on raw damage output."
    }
  ]
}
```

## Mastery Tree Reference
### Offense Tree
- **T1**: Deadly Precision, Keen Strike, Heart of Glory
- **T2**: Single Out, Bring It Down, Warmaster
- **T3**: (Additional nodes)

### Defense Tree
- **T1**: Tough Skin, Blastproof, Rejuvenation
- **T2**: Resurgent, Delay Death, Retribution
- **T3**: (Additional nodes)

### Support Tree
- **T1**: Gifted Healer, Vitality, Nurturing
- **T2**: Lifeward, Sustainer, Mending
- **T3**: (Additional nodes)

## Artifact Sets Reference
- **Lifesteal**: HP% on hit (DPS sustain)
- **Healing**: Healing power boost (Support)
- **Savage**: Crit DMG boost (Burst DPS)
- **Cruel**: HP on hit (Early game DPS)
- **Speed**: Speed boost (Buffer/Speed lead)

## Usage
This data is designed to be consumed by companion applications for:
- Champion build optimization
- Team composition planning
- Artifact farming guidance
- Mastery path recommendations

## Data Freshness
Last updated: 2026-06-01
Game version: 2026-05-31

## Contributing
Pull requests welcome for:
- New champion additions
- Build optimization updates
- Meta changes
- Bug fixes

## License
MIT License
