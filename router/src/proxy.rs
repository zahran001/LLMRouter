//! The transparent single-replica proxy handler.
//!
//! Week 1 scope (WEEK1_ROUTER_IMPL.md §0): the router is plumbing, not a
//! measurement point. Its whole correctness story is (a) bytes out == bytes
//! in and (b) it never intentionally collects the response body.

use std::sync::Arc;
use std::time::Duration;

use axum::body::{Body, Bytes};
use axum::extract::State;
use axum::http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode, Uri};
use axum::response::{IntoResponse, Response};

use crate::cost::{self, CostTokenizer};
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
    cost_tokenizer: Arc<CostTokenizer>,
}

impl AppState {
    pub fn new(upstream_base_url: String, cost_tokenizer: Arc<CostTokenizer>) -> Self {
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
            cost_tokenizer,
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
                // 502, not 500: the router is fine, the upstream is not. The
                // detail (which includes the upstream's address) goes to the
                // operator's log, not to the client.
                eprintln!("llmrouter: upstream request failed: {err}");
                (StatusCode::BAD_GATEWAY, "upstream request failed").into_response()
            }
        }
    }
}

/// Open the upstream request: build `<base><path>[?<query>]`, forward the
/// allowlisted request headers, send the body. Shared by the real handler and
/// (feature-gated) the negative-control handlers, so those differ from the
/// real router in exactly one respect: what they do with the response body.
///
/// `path` is passed explicitly rather than read off the `Uri` because the
/// negative-control routes live under their own prefix but must still hit the
/// upstream's real path.
///
/// Takes already-buffered `Bytes` rather than a `Body` (Week 3,
/// WEEK3_COST_CONTRACT.md section 2 architectural seam): the caller reads
/// the request body once and hands the SAME buffer both to this function
/// and to `cost::compute_request_cost`, so cost inspection can never
/// diverge from what is actually forwarded upstream.
pub async fn open_upstream(
    state: &AppState,
    method: Method,
    path: &str,
    query: Option<&str>,
    incoming: &HeaderMap,
    bytes: Bytes,
) -> Result<reqwest::Response, ProxyError> {
    let mut url = format!("{}{}", state.upstream_base_url, path);
    if let Some(query) = query {
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

/// Read the request body once, capped at `MAX_REQUEST_BODY_BYTES` --
/// shared by every caller of `open_upstream` (the real route and, via
/// `wrong.rs`, the negative-control routes) so there is exactly one place
/// that does this read.
pub(crate) async fn buffer_request_body(body: Body) -> Result<Bytes, ProxyError> {
    axum::body::to_bytes(body, MAX_REQUEST_BODY_BYTES)
        .await
        .map_err(ProxyError::ReadRequestBody)
}

/// `X-Request-Cost-*` response headers, attached only on a successfully
/// computed cost (WEEK3_COST_CONTRACT.md section 4). Never attached on a
/// `RequestCostError` -- an unsupported/uncostable request proxies through
/// with no extra headers, exactly as it did before Week 3.
fn cost_response_headers(cost: cost::RequestCost) -> [(HeaderName, HeaderValue); 3] {
    [
        (
            HeaderName::from_static("x-request-cost-input-tokens"),
            HeaderValue::from_str(&cost.input_tokens.to_string()).expect("numeric header value"),
        ),
        (
            HeaderName::from_static("x-request-cost-reserved-tokens"),
            HeaderValue::from_str(&cost.reserved_tokens.to_string()).expect("numeric header value"),
        ),
        (
            HeaderName::from_static("x-request-cost-estimated-kv-bytes"),
            HeaderValue::from_str(&cost.estimated_kv_bytes.to_string()).expect("numeric header value"),
        ),
    ]
}

/// POST /v1/chat/completions — the real router.
///
/// The whole Week 1 streaming claim lives in the body line below. Nothing
/// between the upstream socket and the client body collects, re-frames or
/// inspects the stream: no `.bytes().await`, no `.collect()`, no framed
/// codec, no intermediate `Vec<u8>`. Chunks are handed to hyper as they
/// arrive from the upstream (decision 2).
pub async fn proxy(
    State(state): State<AppState>,
    method: Method,
    uri: Uri,
    incoming: HeaderMap,
    body: Body,
) -> Result<Response, ProxyError> {
    let bytes = buffer_request_body(body).await?;

    // Week 3 (WEEK3_COST_CONTRACT.md section 2): a RequestCostError is
    // purely internal signal. It is never surfaced as an HTTP error and
    // never blocks forwarding -- `open_upstream` below receives the exact
    // same `bytes` regardless of whether costing succeeded.
    let cost_result = cost::compute_request_cost(&bytes, &state.cost_tokenizer, cost::provenance());

    let upstream =
        open_upstream(&state, method, uri.path(), uri.query(), &incoming, bytes).await?;

    let status = upstream.status();
    let mut response_headers = headers::response_headers(upstream.headers());
    if let Ok(cost) = cost_result {
        for (name, value) in cost_response_headers(cost) {
            response_headers.insert(name, value);
        }
    }

    // THE line. Do not "optimize" this into a collect.
    let body = Body::from_stream(upstream.bytes_stream());

    Ok((status, response_headers, body).into_response())
}
