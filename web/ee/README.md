# Enterprise Edition — Web Frontend

Enterprise-only frontend pages and components for Observal. This directory mirrors the `ee/` backend pattern.

> **License**: This directory is covered by a separate Enterprise License (see `web/ee/LICENSE`). A commercial license is required for production use. Community contributions are not accepted for this directory.

## What belongs here

Enterprise-only **pages and components** that have no use in the open-source edition:

| Feature | Status | Description |
|---------|--------|-------------|
| Audit Log Viewer | Planned | Query + filter audit events, CSV export |
| Security Events Log | Planned | View structured security events from SIEM pipeline |
| SCIM Configuration | Planned | SCIM 2.0 provisioning management UI |
| SAML SSO Configuration | Planned | SAML IdP setup and metadata management |
| Admin Diagnostics | Planned | Enterprise config validation status, system health |
| Organization Management | Planned | Multi-org admin panel (create, list, edit orgs) |
| Webhook Delivery Tracking | Planned | Alert webhook delivery history and retry UI |

## What stays in core

Small conditional rendering (SSO login button, enterprise settings toggle, `deploymentMode` checks) stays in the core `web/src/` pages — extracting two-line conditionals into a separate directory adds indirection for no benefit.

## Constraints

- **One-way dependency**: `web/ee/` can import from `web/src/`. `web/src/` must NEVER import from `web/ee/`.
- **Core must work without ee/**: The open-source frontend must be fully functional if `web/ee/` is deleted.
- **Community contributions NOT accepted** into this directory.

## Directory layout

```
web/ee/
├── LICENSE                  # Enterprise license (same terms as ee/LICENSE)
├── README.md                # This file
├── components/              # Enterprise-only React components
└── pages/                   # Enterprise-only page components
```
