# Public Launch Checklist

Use this checklist before making Deck.Check publicly accessible.

## Legal Pages
- Publish `Imprint` with complete legal entity details.
- Publish `Privacy Policy` with controller/contact, purpose, retention, and third-party processors.
- Verify country-specific obligations (for example Swiss and EU markets can require specific disclosures).

## Security
- Enable HTTPS end-to-end (TLS at CDN/ALB and upstream).
- Set production `TRUSTED_HOSTS` and `FORCE_HTTPS=1` for API.
- Restrict `CORS_ALLOWED_ORIGINS` to production domains only.
- Keep security headers enabled at app and edge.

## Data Protection
- Minimize retention for logs and simulation artifacts.
- Document processors/sub-processors (hosting, database, monitoring, email).
- Add a contact channel for data access/deletion requests.
- If using non-essential cookies/trackers, implement consent before activation.

## Reliability
- Configure uptime checks for `/health/live` and `/health/ready`.
- Add alerting for worker queue growth, failed jobs, and API error rates.
- Run regular backup/restore drills for Postgres.
- Verify daily update jobs and source freshness indicators.

## Abuse and Cost Controls
- Add rate limiting/WAF rules for public endpoints.
- Cap request sizes and simulation run limits by tier.
- Cache repeated analyses by deck hash/config.

## Product Readiness
- Validate legal links are visible from the UI (`/imprint`, `/privacy`).
- Verify favicon, robots, and sitemap routes resolve.
- Run smoke checks from a clean deployment:
  - web loads
  - parse/tag/sim/analyze/guides flow succeeds
  - image and combo integrations degrade gracefully on upstream failures

## Legal Reference Links
- Swiss e-commerce information obligations (SECO): https://www.kmu.admin.ch/kmu/en/home/concrete-know-how/sme-management/e-commerce/general-information-duty-in-e-commerce.html
- EU consumer rights and pre-contractual information (European Commission): https://commission.europa.eu/law/law-topic/consumer-protection-law/consumer-contract-law/consumer-rights-directive_en
- GDPR information obligations overview (EDPB): https://www.edpb.europa.eu/sme-data-protection-guide/respect-individuals-rights_en
