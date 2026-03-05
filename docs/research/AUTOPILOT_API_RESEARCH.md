# API and Data Research (Autopilot Iteration)

This document tracks external inputs that can enrich Deck.Check.

## Integrated now

1. Scryfall API
- Endpoint examples:
  - `https://api.scryfall.com/cards/named?exact=Sol%20Ring`
  - `https://api.scryfall.com/bulk-data`
- Current use:
  - Oracle data/tagging fields
  - image metadata (`image_uris`, `card_faces[].image_uris`)
  - outbound links (`scryfall_uri`, `purchase_uris.cardmarket`)

2. CommanderSpellbook API
- Endpoint used: `https://backend.commanderspellbook.com/variants/`
- Verified shape includes `results[]`, `id`, and `uses[].card.name`.
- Current use:
  - complete combo detection
  - near-miss combo diagnosis
  - combo support score for intent and optimization

3. Archidekt API (URL import)
- Endpoint used: `https://archidekt.com/api/decks/{deck_id}/`
- Current use:
  - best-effort deck URL import as robust fallback when Moxfield blocks server-side requests.

4. Cardmarket links
- Via Scryfall `purchase_uris.cardmarket` when present.
- Fallback search URL: `https://www.cardmarket.com/en/Magic/Products/Search?searchString={card}`.

## Evaluated for next integrations

1. MTGJSON
- Endpoints:
  - `https://mtgjson.com/api/v5/Meta.json`
  - `https://mtgjson.com/api/v5/AllPrintings.json`
- Potential use:
  - additional print/metadata consistency checks
  - backup enrichment for card attributes and legalities snapshots

2. Cardmarket native API
- Docs: `https://api.cardmarket.com/ws/documentation/API_Main_Page`
- Limitation:
  - OAuth/app-key setup required; not suitable for anonymous local-first default path.
- Potential use:
  - authenticated price history and market depth if user configures keys.

3. Moxfield URL import
- Moxfield endpoints are often Cloudflare-blocked for server-side fetches.
- Current product behavior should keep URL import as best-effort and steer users to text export paste.

## Primer quality references and conventions

Because some dedicated help pages are behind anti-bot protection, primer structure follows common high-quality Commander/cEDH conventions across public deck primers:
- clear thesis and win vectors
- mulligan protocol
- early/mid/late sequencing
- combo lines and backups
- common traps and pod-speed adjustments
- upgrade priorities grounded in simulation evidence

## Next candidates

- Optional user-key integration for Cardmarket API.
- Optional CommanderSpellbook card-relationship graph for combo redundancy visualizations.
- Optional MTGJSON local mirror for offline-first operation.
