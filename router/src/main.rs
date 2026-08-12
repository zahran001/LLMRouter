use axum::{routing::get, Router};

const DEFAULT_PORT: u16 = 8080;

#[tokio::main]
async fn main() {
    let port: u16 = std::env::var("ROUTER_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(DEFAULT_PORT);

    let app = Router::new().route("/health", get(health));

    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    println!("llmrouter listening on {addr}");
    axum::serve(listener, app).await.unwrap();
}

async fn health() -> &'static str {
    "ok"
}
