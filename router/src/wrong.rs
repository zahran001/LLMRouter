//! The two **deliberately wrong** routers (WEEK1_ROUTER_IMPL.md §4, §5).
//!
//! These are negative controls, not test fixtures: the router eval's validity
//! is *defined* by failing against them. A streaming test that cannot tell a
//! streaming router from a buffering one proves nothing, so both live
//! permanently in the tree, behind the `wrong-routers` feature (off by
//! default — a production build contains none of this code).
//!
//! * `WRONG_ROUTER_BUFFERS` — collects the whole response body before
//!   returning it. S1, S2 and O1 **must fail** against it.
//! * `WRONG_ROUTER_REEMIT` — deserializes each SSE chunk to JSON and
//!   re-serializes it. F1 (byte-identity) **must fail** against it, while F2
//!   (parser no-op) may still pass — which is exactly what proves F1 tests
//!   byte-identity rather than semantic equivalence.
//!
//! Both reach the upstream through `proxy::open_upstream`, the same function
//! the real router uses, so they differ from it in exactly one respect: what
//! they do with the response body. Each is mounted on its own path prefix so
//! one router process can serve the real route and both controls, which keeps
//! the eval free of process-startup skew between arms.

use axum::body::{Body, Bytes};
use axum::extract::State;
use axum::http::{HeaderMap, Method, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::Router;
use futures_util::StreamExt;

use crate::headers;
use crate::proxy::{open_upstream, AppState, ProxyError};

/// The upstream path both controls proxy to, regardless of the prefixed path
/// they were called on.
const UPSTREAM_CHAT_PATH: &str = "/v1/chat/completions";

pub const WRONG_ROUTER_BUFFERS_PATH: &str = "/__wrong__/buffers/v1/chat/completions";
pub const WRONG_ROUTER_REEMIT_PATH: &str = "/__wrong__/reemit/v1/chat/completions";

pub fn routes() -> Router<AppState> {
    Router::new()
        .route(WRONG_ROUTER_BUFFERS_PATH, post(wrong_router_buffers))
        .route(WRONG_ROUTER_REEMIT_PATH, post(wrong_router_reemit))
}

/// `WRONG_ROUTER_BUFFERS` — the load-bearing negative control (§4.2).
///
/// Identical to `proxy::proxy` except for the one awaited collect: the client
/// receives nothing until the upstream stream has finished, so first-chunk
/// arrival collapses onto completion time.
async fn wrong_router_buffers(
    State(state): State<AppState>,
    method: Method,
    uri: Uri,
    incoming: HeaderMap,
    body: Body,
) -> Result<Response, ProxyError> {
    let upstream = open_upstream(&state, method, UPSTREAM_CHAT_PATH, uri.query(), &incoming, body).await?;

    let status = upstream.status();
    let response_headers = headers::response_headers(upstream.headers());

    // The bug, on purpose.
    let collected = upstream.bytes().await.map_err(ProxyError::Upstream)?;

    Ok((status, response_headers, Body::from(collected)).into_response())
}

/// `WRONG_ROUTER_REEMIT` — still streams, but round-trips every SSE payload
/// through JSON (§4.1).
///
/// Chunks are forwarded as they arrive, so the streaming tests pass against
/// it; only the *bytes* change. `serde_json::Value` orders object keys
/// alphabetically and `to_string` emits compact separators, so the re-emitted
/// payload differs from the upstream's while carrying identical semantics.
async fn wrong_router_reemit(
    State(state): State<AppState>,
    method: Method,
    uri: Uri,
    incoming: HeaderMap,
    body: Body,
) -> Result<Response, ProxyError> {
    let upstream = open_upstream(&state, method, UPSTREAM_CHAT_PATH, uri.query(), &incoming, body).await?;

    let status = upstream.status();
    let response_headers = headers::response_headers(upstream.headers());

    let body = Body::from_stream(upstream.bytes_stream().map(|chunk| chunk.map(reemit_chunk)));

    Ok((status, response_headers, body).into_response())
}

/// Re-serialize every `data:` payload in one chunk.
///
/// Assumes chunk boundaries fall on line boundaries — true for this mock
/// (one write per SSE event) and good enough for a test-only wrong router; a
/// payload that is not valid UTF-8 or not valid JSON is passed through
/// untouched rather than corrupted, so any F1 failure is attributable to the
/// JSON round-trip and nothing else.
fn reemit_chunk(chunk: Bytes) -> Bytes {
    let Ok(text) = std::str::from_utf8(&chunk) else {
        return chunk;
    };

    let mut out = String::with_capacity(text.len());
    for line in text.split_inclusive('\n') {
        let payload = line
            .trim_end_matches(['\n', '\r'])
            .strip_prefix("data:")
            .map(str::trim)
            .filter(|p| *p != "[DONE]")
            .and_then(|p| serde_json::from_str::<serde_json::Value>(p).ok());

        match payload {
            Some(value) => {
                out.push_str("data: ");
                out.push_str(&value.to_string());
                out.push('\n');
            }
            None => out.push_str(line),
        }
    }

    Bytes::from(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reemit_changes_bytes_but_not_semantics() {
        let original = "data: {\"id\": \"x\", \"object\": \"chat.completion.chunk\", \"choices\": [{\"index\": 0}]}\n\n";
        let out = reemit_chunk(Bytes::from(original));
        let out = std::str::from_utf8(&out).unwrap();

        assert_ne!(out, original, "re-emit must perturb the bytes or F1 has nothing to catch");

        let parse = |s: &str| -> serde_json::Value {
            serde_json::from_str(s.trim().strip_prefix("data:").unwrap().trim()).unwrap()
        };
        assert_eq!(parse(out), parse(original), "re-emit must preserve semantics");
    }

    #[test]
    fn reemit_passes_through_terminator_and_blank_lines() {
        let terminator = "data: [DONE]\n\n";
        assert_eq!(&reemit_chunk(Bytes::from(terminator))[..], terminator.as_bytes());
    }
}
