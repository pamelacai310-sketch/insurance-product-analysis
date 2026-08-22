# No-customer-data boundary

This skill evaluates products, not people. Apply this gate before extraction and again before any semantic review packet is created.

## Allowed product data

Allowed inputs describe a published product or public benchmark:

- contract terms, endorsements, product summaries, rate tables, cash-value schedules, and illustrations;
- published issue-age ranges/grids, sex or rate classes, premium terms, annuity-start options, and guarantee options;
- public yield curves, inflation scenarios, insurer metadata, and peer product data with source/version provenance.

An issue-age or sex column in a published product table is a product dimension. The agent should encode the available published grid rather than ask which row matches a person; the engine analyzes every supplied configuration and does not claim to infer omitted rows.

## Prohibited customer data

Do not request, accept in configuration, normalize, model, transmit, or use:

- name, contact details, address, government/account identifiers, or policyholder ID;
- date of birth or a person's current age/sex submitted for selection;
- income, assets, liabilities, expenses, emergency funds, or existing portfolio;
- desired retirement income, retirement date, goals, preferences, or risk tolerance;
- family, beneficiary, health, medical, longevity, estate, tax, or inheritance circumstances;
- free-form suitability notes or recommendation history.

Schema denylist examples include `customer_age`, `date_of_birth`, `income`, `assets`, `expenses`, `risk_tolerance`, `retirement_goal`, `health`, and `life_expectancy`. Schemas must use `additionalProperties: false`; aliases and nested occurrences must also be rejected.

## Personalized documents

Detect likely applications, customer quotations, advice reports, completed forms, and identifiers before analysis. If a source combines product tables with identifiable or customer-selected data, reject it or require a sanitized product-only copy. Do not echo suspected personal values in logs, diagnostics, outputs, or review packets.

A clearly generic, published example may be retained as source evidence when it contains no identifiable person and is labeled `published_example`; it must not be treated as the user or used as a suitability profile.

## Runtime enforcement

- CLI/configuration accepts product documents, published configurations, and public analysis assumptions only.
- A prohibited field or personalized source fails before external access or LLM routing.
- No default customer profile may be synthesized.
- No metric may depend on customer data.
- Reports state that results are product economics under published variants/scenarios, not personalized advice or suitability analysis.

The v1 schema does not accept a mortality table, so it does not emit mortality-weighted metrics. A future mortality module may use only a named public/product basis for an entire published variant; a user's health or expected lifespan is never an assumption.

## Required tests

Tests cover recursive prohibited keys and recognizable values, source-wide quarantine without value echo, no LLM route after rejection, acceptance of published age/rate dimensions, unresolved-state blocking, and report language that contains no suitability or customer-specific recommendation.
