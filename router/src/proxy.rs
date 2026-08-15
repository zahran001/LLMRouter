//! The transparent single-replica proxy handler.
//!
//! Week 1 scope (WEEK1_ROUTER_IMPL.md §0): the router is plumbing, not a
//! measurement point. Its whole correctness story is (a) bytes out == bytes
//! in and (b) it never intentionally collects the response body.

use std::sync::Arc;
use std::time::Duration;

use axum::body::Body;
use axum::extract::State;
use axum::http::{HeaderMap, Method, StatusCode, Uri};
use axum::response::{IntoResponse, Response};

use crate::headers;

/// Cap on the *request* body the router will accept.
///
/// Documented choice (not pinned by the spec): the request body is read into
/// memory before being sent upstream, so the upstream sees a correct
/// `Content-Length` instead of a chunked body the client never asked for.
/// The no-buffering rule is about the *response* stream — request bodies are
/// bounded prompts, and streaming them costs upstream compatibility for no
/// measurable gain.
const MAX_REQUEST_BODY_BYTES: usize = 32 * 1024 * 1024;

/// Connect timeout only. There is deliberately no *request* timeout: that
/// would truncate long legitimate generations. Resilience proper is Week 6
/// (decision 5).
const UPSTREAM_CONNECT_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Clone)]
pub struct AppState {
    client: reqwest::Client,
    upstream_base_url: Arc<str>,
}

impl AppState {
    pub fn new(upstream_base_url: String) -> Self {
        let client = reqwest::Client::builder()
            .connect_timeout(UPSTREAM_CONNECT_TIMEOUT)
            // The router talks to a replica it was explicitly pointed at; a
            // system/env proxy silently inserting itself would corrupt both
            // routing and the overhead measurement.
            .no_proxy()
            .build()
            .expect("failed to build the upstream HTTP client");

        Self {
            client,
            upstream_base_url: upstream_base_url.into(),
        }
    }
}

/// Week 1 errors (decision 5): connect/send failure -> 502, unreadable
/// request body -> 400. No retries, no fallback, no graceful shutdown.
#[derive(Debug)]
pub enum ProxyError {
    ReadRequestBody(axum::Error),
    Upstream(reqwest::Error),
}

impl IntoResponse for ProxyError {
    fn into_response(self) -> Response {
        match self {
            ProxyError::ReadRequestBody(err) => {
                (StatusCode::BAD_REQUEST, format!("could not read request body: {err}")).into_response()
            }
            ProxyError::Upstream(err) => {
                // 502, not 500: the router is fine, the upstream is not.
                eprintln!("llmrouter: upstream request failed: {err}");
                (StatusCode::BAD_GATEWAY, format!("upstream request failed: {err}")).into_response()
            }
        }
    }
}

/// Open the upstream request: build `<base><path>[?<query>]`, forward the
/// allowlisted request headers, send the body. Shared by the real handler and
/// (feature-gated) the negative-control handlers, so those differ from the
/// real router in exactly one respect: what they do with the response body.
pub async fn open_upstream(
    state: &AppState,
    method: Method,
    uri: &Uri,
    incoming: &HeaderMap,
    body: Body,
) -> Result<reqwest::Response, ProxyError> {
    let bytes = axum::body::to_bytes(body, MAX_REQUEST_BODY_BYTES)
        .await
        .map_err(ProxyError::ReadRequestBody)?;

    let mut url = format!("{}{}", state.upstream_base_url, uri.path());
    if let Some(query) = uri.query() {
        url.push('?');
        url.push_str(query);
    }

    state
        .client
        .request(method, url)
        .headers(headers::request_headers(incoming))
        .body(bytes)
        .send()
        .await
        .map_err(ProxyError::Upstream)
}

/// POST /v1/chat/completions — the real router.
pub async fn proxy(
    State(state): State<AppState>,
    method: Method,
    uri: Uri,
    incoming: HeaderMap,
    body: Body,
) -> Result<Response, ProxyError> {
    let upstream = open_upstream(&state, method, &uri, &incoming, body).await?;

    let status = upstream.status();
    let response_headers = headers::response_headers(upstream.headers());

    // Skeleton stage: the body is collected here. Step 4 of the build order
    // replaces this with Body::from_stream(upstream.bytes_stream()).
    let collected = upstream.bytes().await.map_err(ProxyError::Upstream)?;

    Ok((status, response_headers, Body::from(collected)).into_response())
}
