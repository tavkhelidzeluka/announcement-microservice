# Compliance with the PIL RESTful API Guidelines

Traceability for every requirement in the guidelines that applies to this
service. `MUST` items are exhaustive; `SHOULD`/`MAY` items are listed where a
decision was made either way.

Legend: **✔** met · **◐** met with a documented deviation · **–** not
applicable to this service.

---

## API design

| § | Requirement | | Where |
|---|---|---|---|
| REST, no RPC | APIs MUST be RESTful | ✔ | One resource collection, `/announcements`, manipulated with HTTP methods. No verbs in paths. |
| Avoid nesting | APIs SHOULD be a flat collection of resources | ✔ | A single top-level collection; no sub-resources. |
| URIs as resources | Resources MUST be named with plural nouns | ✔ | `/announcements` |
| OpenAPI 3 | All APIs MUST be documented in OpenAPI 3, SHOULD be YAML | ✔ | [`api/openapi.yaml`](../api/openapi.yaml), OpenAPI 3.0.3 in YAML. `make validate` runs a spec validator. |
| Version control | Definitions MUST be under version control | ✔ | In this repository alongside the code that implements them. |
| Definition version | MUST follow `major.minor(.patch)` | ✔ | `info.version: 1.0.0` |
| Technology-agnostic | Definitions MUST be implementation-agnostic | ✔ | The published contract contains no AWS extension. They live in [`infrastructure/openapi-aws-overlay.yaml`](../infrastructure/openapi-aws-overlay.yaml) and are merged at build time. `scripts/validate.py` fails the build if one leaks in. |
| Completeness | Definitions SHOULD be as complete as possible | ✔ | Cache, CORS, conditional-request and compression headers are declared; every response code the API can emit is modelled with an example. |
| Regional deployment | Region MUST NOT appear for global services | ✔ | Announcements are identical worldwide, so the server URL is `https://{host}.api.philips.com/communications`. |
| API hostnames | `https://{host}.api.philips.com` | ◐ | The contract declares the canonical pattern. The deployed API is reached through its API Gateway invoke URL; a production deployment fronts it with a custom domain and a `communications` base-path mapping. |
| Idempotence / safety | MUST respect the semantics of the method | ✔ | `GET` reads only — enforced by IAM, not just by convention: the list function's role has no write permission. `POST` is the only mutating operation. |
| Standard methods | MUST use the method from the standard table | ✔ | List → `GET`, Create → `POST`. |

## API lifecycle

| § | Requirement | | Where |
|---|---|---|---|
| Versioning | APIs MUST have versioning, at service level | ✔ | One version for the whole service. |
| `Api-Version` header | Version MUST travel in an `Api-Version` header, major only, never in the URL | ✔ | [`security.check_api_version`](../src/announcements/app/security.py). The stage name `v1` names the deployment stage, not the API version; no URL carries a version. |
| Reject bad versions | MUST reject a missing, invalid or unsupported version | ✔ | `400 MISSING_API_VERSION` / `400 INVALID_API_VERSION`. Tests: `test_guideline_compliance.py`. |

## Naming

| § | Requirement | | Where |
|---|---|---|---|
| Resource type names | lower camel case, `[a-zA-Z0-9]`, plural | ✔ | `announcements` |
| Query parameter names | lower camel case | ✔ | `cursor`, `limit`, `sort` — all reserved names from Appendix A. |
| Header names | Train-Case | ✔ | `Api-Version`, `Api-Key`, `If-None-Match`, `Cache-Control`, `Accept-Encoding`. Matched case-insensitively on the way in, since HTTP header names are case-insensitive. |
| Property names | lower camel case, ascii, first character a letter | ✔ | `title`, `description`, `announcementDate`, `lastModified`, `pageSize`, `requestId` |
| Singular vs plural | Arrays plural, everything else singular | ✔ | `data`, `errors`, `links` are arrays or containers; `count`, `pageSize`, `title` are singular. |
| Reserved names | Reserved properties MUST carry their defined semantics | ✔ | `created` and `lastModified` in resource `meta`; `count` in list `meta`; `first`/`next` links; `cursor`, `limit`, `sort` parameters. |
| Meaningful names | SHOULD be descriptive and implementation-agnostic | ✔ | Nothing in the contract names DynamoDB, Lambda or a partition key. |

## Data

| § | Requirement | | Where |
|---|---|---|---|
| Property value format | MUST be JSON types | ✔ | Strings, integers, objects and arrays only. |
| Empty/null values | RECOMMENDED to drop empty or null values | ✔ | `links.next` and `meta` are omitted rather than sent as `null`; `createdBy` is stored but never emitted. |
| Enum values | SHOULD be strings | ✔ | Error `code`, resource `type`, `sort`. |
| Date-time values | MUST be RFC 3339 strings | ✔ | `announcementDate`, `created`, `lastModified` — all `YYYY-MM-DDTHH:MM:SSZ`. |
| Timezone normalisation | SHOULD accept other offsets, normalise to UTC | ✔ | [`validation.normalise_date_time`](../src/announcements/app/validation.py); tested for `+01:00`, `-05:00`, lowercase `t`/`z` and fractional seconds. |
| Country / language codes | ISO 3166-1 alpha-2 / ISO 639-1 | – | No localised fields. |

## API syntax

| § | Requirement | | Where |
|---|---|---|---|
| Content encoding | MUST be UTF-8 | ✔ | JSON serialised as UTF-8 throughout. |
| Content type | MUST support `application/json` | ✔ | The only media type produced and consumed. |
| `Accept` handling | SHOULD return 406 when nothing acceptable is offered | ✔ | [`http.negotiate`](../src/announcements/app/http.py). `*/*`, `application/*` and `+json` suffixes are honoured. |
| `Content-Type` handling | MUST return 415 for an unsupported type; absent means JSON | ✔ | Same module, plus an `UNSUPPORTED_MEDIA_TYPE` gateway response for rejections that never reach the handler. |
| Top-level structure | A JSON object at the root, with `data`, `errors` or `meta` | ✔ | Every response, including gateway-level errors. |
| `data` and `errors` | MUST NOT coexist | ✔ | Enforced structurally and asserted for **every** response by a collection-level Postman test. |
| Resource objects | MUST follow JSON API | ✔ | `{type, id, attributes, meta}` |
| Relationship links | SHOULD NOT be implemented | ✔ | None. |
| Compound documents | SHOULD NOT be implemented | ✔ | None. |
| Meta information | MUST follow JSON API | ✔ | `meta.count`, `meta.pageSize`, `meta.requestId`, and resource-level `created`/`lastModified`. |
| Links | MUST follow JSON API | ✔ | `self`, `first`, `next`. |
| Creating resources | MUST follow JSON API; SHOULD return 201; ids MAY be UUIDs | ✔ | `201` with the created resource; RFC 4122 v4 ids; `409` on a type mismatch; `403` on a client-generated id. |
| Errors | MUST follow the JSON API error shape | ✔ | `{id, status, code, title, detail, source}` — from the handlers *and* from API Gateway, via 14 `AWS::ApiGateway::GatewayResponse` resources. |

## Performance and bandwidth

| § | Requirement | | Where |
|---|---|---|---|
| `ETag` / `Last-Modified` | SHOULD be returned for retrievals | ✔ | Strong `ETag` over the exact response bytes. |
| `If-None-Match` | SHOULD be supported, 304 when unchanged | ✔ | `304` with no body and the same `ETag`. |
| `Cache-Control` | SHOULD always be returned | ✔ | `public, max-age=60` on list; `no-store` on create and on every error. |
| gzip | MUST support it, MUST NOT apply it unrequested | ✔ | API Gateway `MinimumCompressionSize: 1024`, which only compresses when the client sends `Accept-Encoding: gzip`. |
| Partial responses (`fields`) | MAY | – | Not implemented; announcements are small enough that field selection would add contract surface for no bandwidth saving. |
| Sorting | MAY; enabled properties MUST be listed in the definition | ✔ | `sort=announcementDate` / `-announcementDate`, declared as an enum in the contract. Anything else is `400`. |
| Filtering | `filter` SHOULD be the basis of any filtering | – | Not implemented. |

## Pagination

| § | Requirement | | Where |
|---|---|---|---|
| Pagination | List methods SHOULD support index or cursor pagination | ✔ | Cursor-based — see [`architecture.md` §4](architecture.md#4-pagination) for why. |
| Server-defined default and maximum | MUST | ✔ | Default 20, maximum 100, in [`config.py`](../src/announcements/app/config.py) and declared in the contract. |
| Parameters optional | MUST be optional, with defaults applied | ✔ | `GET /announcements` with no parameters returns the first page. |
| Reserved names | MUST use `cursor` and `limit` | ✔ | Both, exactly as named in Appendix A. |
| Invalid values | MUST be a 4xx | ✔ | `400 INVALID_PARAMETER_VALUE` with `source.parameter`. Covers non-numeric, out-of-range, malformed, tampered, oversized and wrong-sort-order cursors — 8 cases in `test_pagination.py`. |
| `limit` only | SHOULD return that many results from the first page | ✔ | |
| `cursor` only | SHOULD return the default page size | ✔ | |
| Total count | MAY, and MUST live in `meta` | ✔ | `meta.count`, kept exact by writing the counter in the same transaction as the announcement. |

## Client identification, methods, parameters

| § | Requirement | | Where |
|---|---|---|---|
| Client identification | Every method MUST support it, via an `Api-Key` header | ✔ | [`security.identify_client`](../src/announcements/app/security.py), on both endpoints. |
| Missing/invalid key | MUST be 403 | ✔ | `403 MISSING_API_KEY` and `403 INVALID_API_KEY`. |
| Unsupported methods | MUST be 405 | ✔ | A catch-all `x-amazon-apigateway-any-method` on `/announcements` answers any other verb with a JSON API `405` and an `Allow` header. Without it API Gateway would answer `403 MISSING_AUTHENTICATION_TOKEN`. |
| Undefined query parameters | SHOULD be accepted and ignored | ✔ | Unknown parameters are ignored; tested in `test_list_announcements.py` and in Postman. |

## Miscellaneous

| § | Requirement | | Where |
|---|---|---|---|
| Hypermedia | MAY; if used, MUST be under `links` and declared | ✔ | Pagination links only, declared as the `PaginationLinks` schema. |
| CORS | If enabled MUST be declared in the definition and deny-by-default | ✔ | `OPTIONS` is a first-class operation in the contract. One explicitly configured origin, an explicit method list and an explicit header list. Never `*` — asserted in Postman. |

## Security

| § | Requirement | | Where |
|---|---|---|---|
| HTTPS only | MUST only provide HTTPS URLs and reject plaintext | ✔ | API Gateway does not open an HTTP port. |
| CA-signed certificates | MUST | ✔ | Provided by API Gateway (or ACM on a custom domain). |
| Access control per endpoint | Non-public services MUST authenticate and authorize | ✔ | `POST` requires an OAuth 2.0 access token with `announcements/write`, validated by a Cognito authorizer before the handler runs. `GET` is public by design and still requires client identification. |
| OAuth 2.0 flow | MUST use an enabled flow | ✔ | Client credentials (RFC 6749 §4.4). |
| Definition declares the scheme | MUST include the authorization server URL and scopes | ✔ | The `announcementsOAuth2` security scheme, with `tokenUrl` and the `announcements/write` scope. |
| Bearer tokens | Authorization header MUST follow RFC 6750 | ✔ | `Authorization: Bearer <jwt>`; failures carry a `WWW-Authenticate` challenge, including `error="insufficient_scope"` on a scope failure. |
| Rate limiting | SHOULD be enabled; MUST return 429 | ◐ | Stage and per-method throttling with a `429` gateway response. Per-**key** limiting is not implemented, because usage plans require the `x-api-key` header the guidelines override; [`architecture.md` §5](architecture.md#rate-limiting) covers the WAF alternative. |
| Reject unsupported methods | MUST be 405 | ✔ | See above. |
| Reject unsupported content types | MUST be 415 | ✔ | Handler and gateway response. |
| Unacceptable `Accept` | SHOULD be 406 | ✔ | |
| Hide internal error details | MUST NOT reveal stack traces or internals | ✔ | Every unexpected exception becomes an opaque `SERVER_ERROR` with only a request id. A unit test asserts no exception type, traceback or table name appears in a body; a Postman test scans every response for `Traceback`, `boto3`, `/var/task` and `arn:aws`. |
| Data in URL | MUST NOT put personal or sensitive data in a URL | ✔ | Credentials travel in headers. The only query parameters are `cursor`, `limit` and `sort`; the cursor holds an announcement id and a timestamp, neither of which is personal data. |

## Standard error codes (Appendix A)

Every code the guidelines define, and where this service emits it.

| Code | Status | Emitted when |
|---|---|---|
| `INVALID_PARAMETER_VALUE` | 400 | bad `limit`, `sort`, `cursor`, or an attribute that fails validation |
| `MISSING_PARAMETER` | 400 | a required member is absent from the payload |
| `MISSING_API_VERSION` | 400 | no `Api-Version` header |
| `INVALID_API_VERSION` | 400 | an unsupported `Api-Version` |
| `BAD_REQUEST` | 400 | body is not JSON, or a gateway rejection with no more specific code |
| `MISSING_API_KEY` | 403 | no `Api-Key` header |
| `INVALID_API_KEY` | 403 | an unrecognised `Api-Key` |
| `METHOD_NOT_ALLOWED` | 405 | any verb other than `GET`, `POST`, `OPTIONS` |
| `NOT_ACCEPTABLE` | 406 | `Accept` cannot be satisfied |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | a body in anything but `application/json` |
| `TOO_MANY_REQUESTS` | 429 | throttle or quota exceeded |
| `SERVER_ERROR` | 500 | any unexpected failure |
| `REQUEST_URI_TOO_LONG` | 414 | – handled by API Gateway's own limits |
| `HTTP_NOT_ALLOWED` | 403 | – unreachable; the gateway serves no HTTP port |

Four codes are added for cases the standard list does not cover. They follow
the same naming convention and are declared in the contract's `code` enum:

| Code | Status | Why |
|---|---|---|
| `UNAUTHORIZED` | 401 | no or invalid access token — the list has no 401 entry |
| `INSUFFICIENT_SCOPE` | 403 | a valid token without `announcements/write` (RFC 6750) |
| `CLIENT_GENERATED_ID_NOT_SUPPORTED` | 403 | required by JSON API when a client supplies an `id` |
| `RESOURCE_TYPE_MISMATCH` | 409 | required by JSON API when `data.type` does not match the collection |

---

## Deviations, in one place

1. **Hostname.** The contract declares the canonical
   `https://{host}.api.philips.com/communications`; the deployment answers on
   its API Gateway invoke URL until a custom domain is mapped.
2. **Rate limiting is per stage, not per API key.** AWS usage plans are
   hard-wired to `x-api-key`, which the guidelines override with `Api-Key`. The
   `429` MUST is met; the per-key SHOULD is not.
3. **`errors[].status` is optional in the schema.** It is present on every
   error the service produces. It is omitted only by the `DEFAULT_4XX` gateway
   response, which preserves the original status line and cannot read it back
   into the body — so the member is declared optional rather than promised and
   occasionally missing.
