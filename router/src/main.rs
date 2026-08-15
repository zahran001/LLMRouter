mod config;

use axum::{routing::get, Router};

use crate::config::Config;

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

    let app = Router::new().route("/health", get(health));

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
