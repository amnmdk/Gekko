# Classifier Module

> `src/ndbot/classifier/` — Keyword classification and entity extraction

---

## Overview

The classifier module enriches raw `NewsEvent` objects with:
- **Domain assignment** (ENERGY_GEO vs AI_RELEASES)
- **Sentiment score** (-1.0 bearish to +1.0 bullish)
- **Importance score** (0.0 to 1.0)
- **Matched keywords** (which words triggered classification)
- **Named entities** (organisations, locations, chokepoints)

---

## KeywordClassifier

Rule-based classification using curated keyword dictionaries. No ML models, no API calls, O(n) per event.

### Domain Keywords

**ENERGY_GEO** keywords (examples per category):
- **Geopolitics**: sanctions, embargo, blockade, tension, conflict
- **Chokepoints**: Hormuz, Suez, Bab el-Mandeb, Malacca
- **Infrastructure**: pipeline, refinery, OPEC, production cut
- **Commodities**: crude oil, natural gas, LNG, barrel

**AI_RELEASES** keywords (examples per category):
- **Labs**: OpenAI, Anthropic, Google DeepMind, Meta AI
- **Products**: GPT, Claude, Gemini, Llama
- **Events**: launch, release, announcement, partnership
- **Incidents**: breach, vulnerability, outage, incident

### Sentiment Scoring

The classifier computes sentiment by counting bullish vs bearish keywords:

| Keyword Type | Sentiment Direction |
|---|---|
| Disruption, attack, sanctions | Bearish (-) |
| Supply increase, deal, agreement | Bullish (+) |
| AI launch, partnership, release | Bullish (+) |
| AI incident, breach, failure | Bearish (-) |

Final score: normalised to [-1.0, +1.0] based on ratio of bullish to bearish matches.

### Importance Scoring

Events are scored for importance based on:
- **Entity significance**: Chokepoints (Hormuz=high) vs generic locations
- **Keyword specificity**: "OPEC production cut" scores higher than "energy news"
- **Tag count**: More matched keywords → higher importance

---

## EntityExtractor

Pattern-based Named Entity Recognition (NER). No spaCy model download required — uses custom regex patterns.

### Extracted Entity Types

| Type | Pattern | Examples |
|---|---|---|
| `ORG` | Known organisation names | OPEC, Saudi Aramco, OpenAI, Anthropic |
| `LOCATION` | Known geopolitical regions | Middle East, Gulf of Oman, Sub-Saharan Africa |
| `CHOKEPOINT` | Strategic maritime passages | Strait of Hormuz, Suez Canal, Bab el-Mandeb |

### Usage

```python
from ndbot.classifier.entity_extractor import EntityExtractor

extractor = EntityExtractor()
entities = extractor.extract("OPEC cuts production amid Strait of Hormuz tensions")
# {"ORG": ["OPEC"], "CHOKEPOINT": ["Strait of Hormuz"]}
```

The extractor also enriches `NewsEvent` objects in-place:

```python
extractor.enrich(event)
# event.entities is now populated
```

---

## Design Decisions

### Why not use an LLM for classification?

1. **Latency**: An API call takes 200-500ms. Keyword matching takes <1ms.
2. **Cost**: Each event would cost tokens. At 60+ events/hour, this adds up.
3. **Auditability**: You can inspect exactly which keywords triggered a classification.
4. **Offline capability**: Works without internet in simulate mode.
5. **Pi 5 friendly**: No GPU, no model downloads, minimal RAM.

### Future: Optional AI Scoring Layer

The architecture supports adding an optional AI scoring layer on top of keyword classification. This could use Claude or GPT-4 to:
- Score news confirmation level (rumor vs confirmed)
- Assess time horizon (happening now vs 5 years)
- Evaluate positive/negative sentiment with nuance
- Produce a richer, multi-criteria score

This would be a **separate module** that wraps the existing classifier, not a replacement.
