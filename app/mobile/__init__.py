"""Mobile API surface.

A unified facade over management / Gennis / Turon missions for the mobile
client. The mobile app authenticates against `POST /mobile/auth/login` with a
`system` selector (`management` | `gennis` | `turon`) and from that point on
hits the same `/mobile/missions` routes regardless of which backend the user
actually lives in. The JWT carries the system + external user id; each
endpoint reads them via `get_mobile_identity` and routes the query to the
right database internally.
"""
