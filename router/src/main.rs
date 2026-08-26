mod config;
mod cost;
mod headers;
mod proxy;
#[cfg(feature = "wrong-routers")]
mod wrong;

use std::sync::Arc;

use axum::{
    routing::{get, post},
    Router,
};

use crate::config::Config;
use crate::cost::CostTokenizer;
use crate::proxy::AppState;

#[tokio::main]
async fn main() {
    // Fail loudly, before binding anything: a router with no configured
    // upstream has nothing useful to do (WEEK1_ROUTER_IMPL.md decision 6).
    let cfg = match Config::from_env() {
        Ok(cfg) => cfg,
        Err(err) => {
            eprintln!("llmrouter: fatal config error: {err}");
            std::process::exit(2);
        }
    };

    // Week 3 (WEEK3_COST_CONTRACT.md): fail loudly at startup, same as the
    // upstream config above, rather than discovering a missing/unproven
    // tokenizer cache on the first request. A RequestCostError on a live
    // request is expected and never fatal (see cost::mod); a missing
    // tokenizer cache at startup is an operator error and is fatal.
    let cost_tokenizer_dir = crate::cost::tokenizer::default_cache_dir();
    let cost_tokenizer = match CostTokenizer::load(&cost_tokenizer_dir) {
        Ok(tok) => Arc::new(tok),
        Err(err) => {
            eprintln!("llmrouter: fatal cost-tokenizer error: {err}");
            std::process::exit(2);
        }
    };

    let state = AppState::new(cfg.upstream_base_url.clone(), cost_tokenizer);
    let app = Router::new()
        .route("/health", get(health))
        .route("/v1/chat/completions", post(proxy::proxy));

    // Negative controls, off unless explicitly compiled in. They serve their
    // own paths; the real route above is untouched by their presence.
    #[cfg(feature = "wrong-routers")]
    let app = {
        eprintln!(
            "llmrouter: WARNING — built with --features wrong-routers; \
             deliberately broken routers are mounted for the eval only"
        );
        app.merge(wrong::routes())
    };

    let app = app.with_state(state);

    let addr = format!("0.0.0.0:{}", cfg.port);
    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    println!(
        "llmrouter listening on {addr}, upstream {}",
        cfg.upstream_base_url
    );
    axum::serve(listener, app).await.unwrap();
}

async fn health() -> &'static str {
    "ok"
}
