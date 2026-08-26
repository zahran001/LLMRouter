//! Pinned tokenizer + chat-template rendering, matching
//! `cost_model/tokenizer.py` exactly (WEEK3_COST_CONTRACT.md section 1).
//!
//! Loaded once at startup from `TOKENIZER_CACHE_DIR` (default:
//! `.tokenizer_cache/meta-llama__Llama-3.2-3B-Instruct`, the same cache
//! `scripts/fetch_tokenizer.py` populates), and refuses to start costing
//! without a `PROVENANCE.json` present -- mirroring the Python side's
//! refusal to use a tokenizer whose identity was never proven.

use std::fmt;
use std::path::{Path, PathBuf};

use minijinja::value::Value as MjValue;
use minijinja::{Environment, Error as MjError, ErrorKind as MjErrorKind};
use tokenizers::Tokenizer;

const TEMPLATE_NAME: &str = "chat";
const DEFAULT_BOS_TOKEN: &str = "<|begin_of_text|>";

pub struct CostTokenizer {
    tokenizer: Tokenizer,
    env: Environment<'static>,
    bos_token: String,
}

#[derive(Debug)]
pub enum LoadError {
    MissingFile(PathBuf),
    MissingProvenance(PathBuf),
    Io(String),
    TokenizerLoad(String),
    ConfigParse(String),
    NoChatTemplate,
    TemplateParse(String),
}

impl fmt::Display for LoadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LoadError::MissingFile(dir) => write!(
                f,
                "tokenizer not cached under {} -- run scripts/fetch_tokenizer.py first \
                 (it proves the files are byte-identical to the gated meta-llama repo)",
                dir.display()
            ),
            LoadError::MissingProvenance(path) => write!(
                f,
                "{} has no PROVENANCE.json -- refusing to use a tokenizer whose identity was \
                 never proven",
                path.display()
            ),
            LoadError::Io(e) => write!(f, "io error reading tokenizer_config.json: {e}"),
            LoadError::TokenizerLoad(e) => write!(f, "tokenizer load error: {e}"),
            LoadError::ConfigParse(e) => write!(f, "tokenizer_config.json parse error: {e}"),
            LoadError::NoChatTemplate => {
                write!(f, "tokenizer_config.json carries no chat_template")
            }
            LoadError::TemplateParse(e) => write!(f, "chat template parse error: {e}"),
        }
    }
}

/// `TOKENIZER_CACHE_DIR` env var, default matching `.tokenizer_cache/...`,
/// the same cache directory `cost_model/tokenizer.py` reads by default.
pub fn default_cache_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("TOKENIZER_CACHE_DIR") {
        return PathBuf::from(dir);
    }
    PathBuf::from(".tokenizer_cache").join("meta-llama__Llama-3.2-3B-Instruct")
}

impl CostTokenizer {
    pub fn load(cache_dir: &Path) -> Result<Self, LoadError> {
        let tok_path = cache_dir.join("tokenizer.json");
        let cfg_path = cache_dir.join("tokenizer_config.json");
        let provenance_path = cache_dir.join("PROVENANCE.json");

        if !tok_path.exists() || !cfg_path.exists() {
            return Err(LoadError::MissingFile(cache_dir.to_path_buf()));
        }
        if !provenance_path.exists() {
            return Err(LoadError::MissingProvenance(provenance_path));
        }

        let tokenizer =
            Tokenizer::from_file(&tok_path).map_err(|e| LoadError::TokenizerLoad(e.to_string()))?;

        let cfg_text = std::fs::read_to_string(&cfg_path).map_err(|e| LoadError::Io(e.to_string()))?;
        let cfg: serde_json::Value =
            serde_json::from_str(&cfg_text).map_err(|e| LoadError::ConfigParse(e.to_string()))?;

        let template_src = cfg
            .get("chat_template")
            .and_then(|v| v.as_str())
            .ok_or(LoadError::NoChatTemplate)?
            .to_string();

        let bos_token = match cfg.get("bos_token") {
            Some(serde_json::Value::String(s)) => s.clone(),
            Some(serde_json::Value::Object(o)) => o
                .get("content")
                .and_then(|v| v.as_str())
                .unwrap_or(DEFAULT_BOS_TOKEN)
                .to_string(),
            _ => DEFAULT_BOS_TOKEN.to_string(),
        };

        // trim_blocks/lstrip_blocks match cost_model/tokenizer.py's
        // jinja2.Environment(trim_blocks=True, lstrip_blocks=True) exactly.
        let mut env: Environment<'static> = Environment::new();
        env.set_trim_blocks(true);
        env.set_lstrip_blocks(true);
        env.add_function("raise_exception", raise_exception);
        env.add_function("strftime_now", strftime_now);
        env.add_template_owned(TEMPLATE_NAME, template_src)
            .map_err(|e| LoadError::TemplateParse(e.to_string()))?;

        Ok(Self { tokenizer, env, bos_token })
    }

    /// Render exactly as vLLM will -- the single-user-message shape the
    /// Week 3 supported-request contract requires
    /// (`cost_model/tokenizer.py`'s `render`).
    pub fn render(&self, content: &str) -> Result<String, MjError> {
        let template = self.env.get_template(TEMPLATE_NAME)?;
        template.render(minijinja::context! {
            messages => vec![minijinja::context! { role => "user", content => content }],
            add_generation_prompt => true,
            bos_token => self.bos_token.clone(),
        })
    }

    /// Exact token count of already-rendered text. `add_special_tokens =
    /// false` matches the Python side -- the template already embeds BOS
    /// itself, so the tokenizer must not add another one.
    pub fn encode_count(&self, rendered: &str) -> Result<usize, tokenizers::Error> {
        let encoding = self.tokenizer.encode(rendered, false)?;
        Ok(encoding.len())
    }
}

fn raise_exception(msg: String) -> Result<MjValue, MjError> {
    Err(MjError::new(MjErrorKind::InvalidOperation, msg))
}

/// Matches Python's `datetime.now(timezone.utc).strftime(fmt)` directly --
/// chrono's `.format(fmt)` uses the same strftime-style specifiers, so this
/// is not a reimplementation of date formatting, just the same call
/// through a different binding. The template only uses this for a
/// "%d %b %Y"-style date string embedded in the system block; the exact
/// date differs between a Python run and a Rust run made on different
/// days, but the resulting TOKEN COUNT does not (fixed-width day/month
/// abbreviation/year), which is what request-cost conformance actually
/// requires (cost_model/README.md).
fn strftime_now(fmt: String) -> String {
    chrono::Utc::now().format(&fmt).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_cache_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join(".tokenizer_cache")
            .join("meta-llama__Llama-3.2-3B-Instruct")
    }

    #[test]
    fn loads_and_renders_and_tokenizes() {
        let dir = test_cache_dir();
        if !dir.exists() {
            eprintln!("skipping: {} not present (run scripts/fetch_tokenizer.py first)", dir.display());
            return;
        }
        let tok = CostTokenizer::load(&dir).expect("tokenizer should load");
        let rendered = tok.render("hello").expect("render should succeed");
        assert!(rendered.contains("hello"));
        let count = tok.encode_count(&rendered).expect("encode should succeed");
        assert!(count > 0);
    }

    #[test]
    fn missing_cache_dir_fails_loudly() {
        let err = CostTokenizer::load(Path::new("/definitely/does/not/exist"));
        assert!(matches!(err, Err(LoadError::MissingFile(_))));
    }
}
