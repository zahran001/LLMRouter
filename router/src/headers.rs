//! Header policy (WEEK1_ROUTER_IMPL.md decisions 3 and 4).
//!
//! Two deliberately different rules, because the two directions have
//! different failure modes:
//!
//! * **Request (client -> upstream): allowlist.** Only `Content-Type`,
//!   `Accept`, `Authorization`. Hop-by-hop / connection-level headers
//!   forwarded from the client can actively confuse the upstream (`Host`
//!   pointing at the router, a `Content-Length` that no longer matches, a
//!   `Transfer-Encoding` the router is not actually using). `Host` and
//!   `Content-Length` are set by the HTTP client for the request it really
//!   sends; the router never hand-copies them.
//! * **Response (upstream -> client): denylist.** The router should be
//!   transparent about what the upstream says about its *payload*
//!   (`Content-Type` above all — the streaming API is unusable without
//!   `text/event-stream`), while letting axum/hyper own HTTP *framing*. So
//!   everything is passed through except hop-by-hop and framing headers.

use axum::http::header::{ACCEPT, AUTHORIZATION, CONTENT_TYPE};
use axum::http::{HeaderMap, HeaderName};

/// The only client request headers forwarded upstream (decision 3).
pub const FORWARDED_REQUEST_HEADERS: [HeaderName; 3] = [CONTENT_TYPE, ACCEPT, AUTHORIZATION];

/// Hop-by-hop (RFC 9110 §7.6.1) plus the framing headers that describe *this*
/// connection rather than the payload. Never copied in either direction.
///
/// `content-encoding` is intentionally NOT here: the upstream client is built
/// without decompression features, so a compressed body is passed through
/// untouched and the header must travel with it to stay honest.
const HOP_BY_HOP_AND_FRAMING: [&str; 10] = [
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
];

fn is_hop_by_hop(name: &HeaderName) -> bool {
    HOP_BY_HOP_AND_FRAMING.contains(&name.as_str())
}

/// Allowlisted client headers to send upstream.
pub fn request_headers(incoming: &HeaderMap) -> HeaderMap {
    let mut out = HeaderMap::with_capacity(FORWARDED_REQUEST_HEADERS.len());
    for name in FORWARDED_REQUEST_HEADERS {
        if let Some(value) = incoming.get(&name) {
            out.insert(name, value.clone());
        }
    }
    out
}

/// Upstream response headers to return to the client: everything the upstream
/// said about its payload, nothing about its connection.
pub fn response_headers(upstream: &HeaderMap) -> HeaderMap {
    let mut out = HeaderMap::with_capacity(upstream.len());
    for (name, value) in upstream {
        if is_hop_by_hop(name) {
            continue;
        }
        out.append(name.clone(), value.clone());
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    fn map(pairs: &[(&'static str, &'static str)]) -> HeaderMap {
        let mut m = HeaderMap::new();
        for (k, v) in pairs {
            m.append(
                HeaderName::from_static(k),
                HeaderValue::from_static(v),
            );
        }
        m
    }

    #[test]
    fn request_allowlist_keeps_only_the_three() {
        let out = request_headers(&map(&[
            ("content-type", "application/json"),
            ("accept", "text/event-stream"),
            ("authorization", "Bearer t"),
            ("host", "router.local"),
            ("connection", "keep-alive"),
            ("transfer-encoding", "chunked"),
            ("content-length", "17"),
            ("user-agent", "curl/8"),
        ]));

        assert_eq!(out.len(), 3);
        assert_eq!(out.get("content-type").unwrap(), "application/json");
        assert_eq!(out.get("accept").unwrap(), "text/event-stream");
        assert_eq!(out.get("authorization").unwrap(), "Bearer t");
        for dropped in ["host", "connection", "transfer-encoding", "content-length", "user-agent"] {
            assert!(out.get(dropped).is_none(), "{dropped} should not be forwarded");
        }
    }

    #[test]
    fn request_allowlist_omits_headers_the_client_did_not_send() {
        let out = request_headers(&map(&[("content-type", "application/json")]));
        assert_eq!(out.len(), 1);
        assert!(out.get("authorization").is_none());
    }

    #[test]
    fn response_denylist_preserves_content_type_and_drops_framing() {
        let out = response_headers(&map(&[
            ("content-type", "text/event-stream; charset=utf-8"),
            ("cache-control", "no-cache"),
            ("x-request-id", "abc"),
            ("transfer-encoding", "chunked"),
            ("content-length", "42"),
            ("connection", "keep-alive"),
        ]));

        assert_eq!(out.get("content-type").unwrap(), "text/event-stream; charset=utf-8");
        assert_eq!(out.get("cache-control").unwrap(), "no-cache");
        assert_eq!(out.get("x-request-id").unwrap(), "abc");
        for dropped in ["transfer-encoding", "content-length", "connection"] {
            assert!(out.get(dropped).is_none(), "{dropped} should not be copied");
        }
    }
}
