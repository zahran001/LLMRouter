//! Startup configuration (WEEK1_ROUTER_IMPL.md decision 6).
//!
//! Everything the router needs to reach its upstream comes from the
//! environment. There is deliberately **no default** for the upstream base
//! URL: the mock -> vLLM swap must be a config change rather than a code
//! change, and a hardcoded fallback is exactly what lets a stale or wrong
//! upstream ship silently. Missing/garbage config fails loudly at startup.
//!
//! Implementation choice (not pinned by the spec): the parsing lives in a
//! pure `Config::parse` so it can be unit-tested without mutating process
//! environment (which is racy under cargo's parallel test threads);
//! `from_env` is the thin shell that reads the two variables.

use std::fmt;

pub const UPSTREAM_BASE_URL_ENV: &str = "UPSTREAM_BASE_URL";
pub const ROUTER_PORT_ENV: &str = "ROUTER_PORT";
pub const DEFAULT_PORT: u16 = 8080;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    /// Upstream origin, normalized without a trailing slash so request paths
    /// can be appended directly.
    pub upstream_base_url: String,
    pub port: u16,
}

#[derive(Debug, PartialEq, Eq)]
pub enum ConfigError {
    MissingUpstream,
    InvalidUpstream { value: String, reason: &'static str },
    InvalidPort { value: String },
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConfigError::MissingUpstream => write!(
                f,
                "{UPSTREAM_BASE_URL_ENV} is not set (or is empty). \
                 There is no default upstream by design — set it to the mock \
                 (e.g. http://127.0.0.1:9001) or to a vLLM replica."
            ),
            ConfigError::InvalidUpstream { value, reason } => write!(
                f,
                "{UPSTREAM_BASE_URL_ENV}={value:?} is not a usable upstream base URL: {reason}"
            ),
            ConfigError::InvalidPort { value } => write!(
                f,
                "{ROUTER_PORT_ENV}={value:?} is not a valid TCP port (expected 1-65535)"
            ),
        }
    }
}

impl std::error::Error for ConfigError {}

impl Config {
    pub fn from_env() -> Result<Self, ConfigError> {
        Config::parse(
            std::env::var(UPSTREAM_BASE_URL_ENV).ok().as_deref(),
            std::env::var(ROUTER_PORT_ENV).ok().as_deref(),
        )
    }

    /// Pure form of `from_env`: `None` means "variable unset".
    ///
    /// An unset port falls back to `DEFAULT_PORT`, but a *set but unparseable*
    /// port is an error rather than a silent fallback — a typo'd port that
    /// silently binds 8080 is the same class of bug as a hardcoded upstream.
    pub fn parse(upstream: Option<&str>, port: Option<&str>) -> Result<Self, ConfigError> {
        let raw = upstream
            .map(str::trim)
            .filter(|v| !v.is_empty())
            .ok_or(ConfigError::MissingUpstream)?;

        let rest = raw
            .strip_prefix("http://")
            .or_else(|| raw.strip_prefix("https://"))
            .ok_or_else(|| ConfigError::InvalidUpstream {
                value: raw.to_string(),
                reason: "must start with http:// or https://",
            })?;
        if rest.split('/').next().unwrap_or("").is_empty() {
            return Err(ConfigError::InvalidUpstream {
                value: raw.to_string(),
                reason: "no host after the scheme",
            });
        }

        let port = match port.map(str::trim).filter(|v| !v.is_empty()) {
            None => DEFAULT_PORT,
            Some(p) => p
                .parse::<u16>()
                .ok()
                .filter(|p| *p > 0)
                .ok_or_else(|| ConfigError::InvalidPort { value: p.to_string() })?,
        };

        Ok(Config {
            upstream_base_url: raw.trim_end_matches('/').to_string(),
            port,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_upstream_is_an_error() {
        assert_eq!(Config::parse(None, None), Err(ConfigError::MissingUpstream));
        assert_eq!(Config::parse(Some("   "), None), Err(ConfigError::MissingUpstream));
    }

    #[test]
    fn trailing_slash_is_normalized_away() {
        let cfg = Config::parse(Some("http://127.0.0.1:9001/"), None).unwrap();
        assert_eq!(cfg.upstream_base_url, "http://127.0.0.1:9001");
        assert_eq!(cfg.port, DEFAULT_PORT);
    }

    #[test]
    fn rejects_non_http_schemes_and_hostless_urls() {
        assert!(matches!(
            Config::parse(Some("127.0.0.1:9001"), None),
            Err(ConfigError::InvalidUpstream { .. })
        ));
        assert!(matches!(
            Config::parse(Some("ftp://127.0.0.1"), None),
            Err(ConfigError::InvalidUpstream { .. })
        ));
        assert!(matches!(
            Config::parse(Some("http:///v1"), None),
            Err(ConfigError::InvalidUpstream { .. })
        ));
    }

    #[test]
    fn port_parses_or_fails_loudly() {
        assert_eq!(Config::parse(Some("http://h:1"), Some("9999")).unwrap().port, 9999);
        assert!(matches!(
            Config::parse(Some("http://h:1"), Some("not-a-port")),
            Err(ConfigError::InvalidPort { .. })
        ));
        assert!(matches!(
            Config::parse(Some("http://h:1"), Some("0")),
            Err(ConfigError::InvalidPort { .. })
        ));
    }
}
