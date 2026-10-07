---
specialty_packaging_allowed: true
minimum_margin_pct: 35
consumer_weight: 0.45
commercial_weight: 0.30
feasibility_weight: 0.25
---
# Commercial and manufacturing guardrails

These are fictional Northstar policies for demonstration.

Specialty packaging is available through a contract packer when allowed above.
Change `specialty_packaging_allowed` to `false` to represent loss of that capacity.
Python must exclude specialty-bottle options from the recommended pilot when false,
even if an agent recommends one.

The standard can line is available. No new formula has a confirmed bill of materials,
unit cost, or validated selling price. Historical SKU margin is not a new-product forecast.
Unknown proposal margin requires a cost gate before pilot authorization.

The weights above are policy preferences, not measured probabilities. Agent fit scores
are subjective assessments on a 1-5 scale. The harness computes their weighted score.
