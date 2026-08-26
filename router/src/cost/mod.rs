//! Week 3 request-cost computation (`WEEK3_COST_CONTRACT.md`).
//!
//! `compute_request_cost` is the Rust counterpart to
//! `cost_model.reference.compute_request_cost` in the Python reference
//! implementation -- the two must agree exactly over the full pinned
//! corpus, edge cases, and negative controls
//! (`WEEK3_IMPLEMENTATION_README.md` section 2.10, no tolerances).
//!
//! Every `RequestCostError` fails the request closed -- never an
//! approximate cost, and never a reason to block forwarding the request.
//! `router::proxy::proxy` never turns a `RequestCostError` into an HTTP
//! error (`WEEK3_COST_CONTRACT.md` section 2).

pub mod provenance;
pub mod tokenizer;

use serde_json::Value;

pub use provenance::{provenance, Provenance};
pub use tokenizer::CostTokenizer;

/// The Week 3 request-cost signal (`WEEK3_COST_CONTRACT.md` section 3).
/// All arithmetic that produces this is integer arithmetic; never
/// floating point.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RequestCost {
    pub input_tokens: u32,
    pub max_output_tokens: u32,
    pub reserved_tokens: u32,
    pub estimated_kv_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RequestCostError {
    NotJson,
    UnsupportedShape(&'static str),
    WrongModel,
    MissingMaxTokens,
    InvalidMaxTokens,
    /// Defensive only: WEEK3_KV_REQUEST_COST_INVESTIGATION_REPORT.md
    /// section 8 shows u64 has enormous headroom over any supported
    /// request size. Kept as a real, checked failure mode rather than a
    /// silently-trusted invariant.
    Overflow,
}

const ALLOWED_TOP_LEVEL_KEYS: [&str; 4] = ["model", "messages", "max_tokens", "stream"];
const ALLOWED_MESSAGE_KEYS: [&str; 2] = ["role", "content"];

/// The benchmark-exact supported-request contract
/// (`WEEK3_COST_CONTRACT.md` section 1), then the locked formula
/// (`WEEK3_IMPLEMENTATION_README.md` section 2.5-2.6):
///
/// ```text
/// reserved_tokens    = input_tokens + max_output_tokens
/// estimated_kv_bytes = reserved_tokens * logical_kv_bytes_per_token
/// ```
///
/// Deliberately NOT `input_tokens + max_output_tokens - 1`, even though
/// that is the exact logical-KV-occupancy boundary for
/// `max_output_tokens >= 1` -- the one-token slack is documented
/// intentional conservatism, not a bug (`cost_model/README.md`).
pub fn compute_request_cost(
    bytes: &[u8],
    tok: &CostTokenizer,
    prov: &Provenance,
) -> Result<RequestCost, RequestCostError> {
    let value: Value = serde_json::from_slice(bytes).map_err(|_| RequestCostError::NotJson)?;
    let obj = value
        .as_object()
        .ok_or(RequestCostError::UnsupportedShape("request body is not a JSON object"))?;

    for key in obj.keys() {
        if !ALLOWED_TOP_LEVEL_KEYS.contains(&key.as_str()) {
            return Err(RequestCostError::UnsupportedShape("unsupported top-level field"));
        }
    }

    let model = obj.get("model").and_then(Value::as_str);
    if model != Some(prov.model_id.as_str()) {
        return Err(RequestCostError::WrongModel);
    }

    let messages = obj
        .get("messages")
        .and_then(Value::as_array)
        .ok_or(RequestCostError::UnsupportedShape("messages must be an array"))?;
    if messages.len() != 1 {
        return Err(RequestCostError::UnsupportedShape("messages must have exactly one entry"));
    }
    let message = messages[0]
        .as_object()
        .ok_or(RequestCostError::UnsupportedShape("messages[0] must be an object"))?;
    if message.len() != 2
        || !ALLOWED_MESSAGE_KEYS.iter().all(|k| message.contains_key(*k))
    {
        return Err(RequestCostError::UnsupportedShape(
            "messages[0] must have exactly {role, content}",
        ));
    }
    if message.get("role").and_then(Value::as_str) != Some("user") {
        return Err(RequestCostError::UnsupportedShape("messages[0].role must be \"user\""));
    }
    let content = message
        .get("content")
        .and_then(Value::as_str)
        .ok_or(RequestCostError::UnsupportedShape("messages[0].content must be a plain string"))?;

    if let Some(stream) = obj.get("stream") {
        if !stream.is_boolean() {
            return Err(RequestCostError::UnsupportedShape("stream must be a boolean"));
        }
    }

    let max_tokens_value = obj.get("max_tokens").ok_or(RequestCostError::MissingMaxTokens)?;
    // `Value::as_u64` already returns None for bools, negatives and
    // non-integer-literal floats (serde_json tracks float-vs-int by
    // literal syntax), so this rejects everything Python's
    // `isinstance(x, bool) or not isinstance(x, int) or x <= 0` check
    // does, via the type system instead of an explicit bool check.
    let max_output_tokens = max_tokens_value
        .as_u64()
        .filter(|&v| v > 0 && v <= u32::MAX as u64)
        .ok_or(RequestCostError::InvalidMaxTokens)? as u32;

    let rendered = tok
        .render(content)
        .map_err(|_| RequestCostError::UnsupportedShape("chat-template rendering failed"))?;
    let token_count = tok
        .encode_count(&rendered)
        .map_err(|_| RequestCostError::UnsupportedShape("tokenization failed"))?;
    let input_tokens = u32::try_from(token_count).map_err(|_| RequestCostError::Overflow)?;

    let reserved_tokens = input_tokens
        .checked_add(max_output_tokens)
        .ok_or(RequestCostError::Overflow)?;
    let estimated_kv_bytes = (reserved_tokens as u64)
        .checked_mul(prov.logical_kv_bytes_per_token)
        .ok_or(RequestCostError::Overflow)?;

    Ok(RequestCost {
        input_tokens,
        max_output_tokens,
        reserved_tokens,
        estimated_kv_bytes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn test_cache_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join(".tokenizer_cache")
            .join("meta-llama__Llama-3.2-3B-Instruct")
    }

    fn load_test_tokenizer() -> Option<CostTokenizer> {
        let dir = test_cache_dir();
        if !dir.exists() {
            eprintln!("skipping: {} not present (run scripts/fetch_tokenizer.py first)", dir.display());
            return None;
        }
        Some(CostTokenizer::load(&dir).expect("tokenizer should load"))
    }

    fn good_request() -> serde_json::Value {
        serde_json::json!({
            "model": provenance().model_id,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 10,
        })
    }

    #[test]
    fn accepts_the_supported_shape_and_matches_the_locked_formula() {
        let Some(tok) = load_test_tokenizer() else { return };
        let prov = provenance();
        let bytes = serde_json::to_vec(&good_request()).unwrap();
        let cost = compute_request_cost(&bytes, &tok, prov).expect("should be supported");
        assert_eq!(cost.max_output_tokens, 10);
        assert_eq!(cost.reserved_tokens, cost.input_tokens + 10);
        assert_eq!(cost.estimated_kv_bytes, cost.reserved_tokens as u64 * 114_688);
    }

    #[test]
    fn rejects_missing_max_tokens() {
        let Some(tok) = load_test_tokenizer() else { return };
        let mut req = good_request();
        req.as_object_mut().unwrap().remove("max_tokens");
        let bytes = serde_json::to_vec(&req).unwrap();
        assert_eq!(
            compute_request_cost(&bytes, &tok, provenance()),
            Err(RequestCostError::MissingMaxTokens)
        );
    }

    #[test]
    fn rejects_wrong_model() {
        let Some(tok) = load_test_tokenizer() else { return };
        let mut req = good_request();
        req["model"] = serde_json::json!("some-other-model");
        let bytes = serde_json::to_vec(&req).unwrap();
        assert_eq!(
            compute_request_cost(&bytes, &tok, provenance()),
            Err(RequestCostError::WrongModel)
        );
    }

    #[test]
    fn rejects_extra_top_level_field() {
        let Some(tok) = load_test_tokenizer() else { return };
        let mut req = good_request();
        req["tools"] = serde_json::json!([]);
        let bytes = serde_json::to_vec(&req).unwrap();
        assert!(matches!(
            compute_request_cost(&bytes, &tok, provenance()),
            Err(RequestCostError::UnsupportedShape(_))
        ));
    }

    #[test]
    fn rejects_multimodal_content() {
        let Some(tok) = load_test_tokenizer() else { return };
        let mut req = good_request();
        req["messages"][0]["content"] = serde_json::json!([{"type": "text", "text": "hi"}]);
        let bytes = serde_json::to_vec(&req).unwrap();
        assert!(matches!(
            compute_request_cost(&bytes, &tok, provenance()),
            Err(RequestCostError::UnsupportedShape(_))
        ));
    }

    #[test]
    fn rejects_bool_max_tokens() {
        let Some(tok) = load_test_tokenizer() else { return };
        let mut req = good_request();
        req["max_tokens"] = serde_json::json!(true);
        let bytes = serde_json::to_vec(&req).unwrap();
        assert_eq!(
            compute_request_cost(&bytes, &tok, provenance()),
            Err(RequestCostError::InvalidMaxTokens)
        );
    }

    /// Negative control #9 (WEEK3_IMPLEMENTATION_README.md section 6
    /// W3-4): using num_attention_heads (24) instead of num_key_value_heads
    /// (8) must NOT reproduce the locked 114,688 B/token constant.
    #[test]
    fn control_wrong_head_count_does_not_match_locked_constant() {
        let num_hidden_layers = 28u64;
        let num_attention_heads_wrong = 24u64; // should be num_key_value_heads = 8
        let head_dim = 128u64;
        let bytes_per_kv_element = 2u64;
        let wrong = 2 * num_hidden_layers * num_attention_heads_wrong * head_dim * bytes_per_kv_element;
        assert_ne!(wrong, provenance().logical_kv_bytes_per_token);
    }

    /// Negative control #8: the `-1` formula must not be what ships.
    #[test]
    fn control_minus_one_formula_diverges_from_the_locked_formula() {
        let Some(tok) = load_test_tokenizer() else { return };
        let prov = provenance();
        let bytes = serde_json::to_vec(&good_request()).unwrap();
        let cost = compute_request_cost(&bytes, &tok, prov).unwrap();
        let minus_one_reserved = cost.input_tokens + cost.max_output_tokens - 1;
        assert_ne!(cost.reserved_tokens, minus_one_reserved);
    }

    /// W3-5 CPU overhead characterization
    /// (WEEK3_IMPLEMENTATION_README.md section 6 W3-5): isolates
    /// `compute_request_cost`'s own CPU cost from network/streaming noise
    /// by timing it directly, in-process, at representative input lengths
    /// drawn from the real corpus's distribution (min/p50/p90/p99/max
    /// input_tokens, per benchmarks/workloads/week3_cost/golden_vectors.v1.jsonl).
    /// Not a GPU/TTFT claim -- CPU wall-clock only. Run with
    /// `cargo test --release -- --ignored --nocapture characterize_cpu_overhead`
    /// to see the printed table (release, since that's the binary that
    /// would actually be deployed -- same rationale as tests/router/conftest.py's
    /// CARGO_PROFILE choice for O1).
    #[test]
    #[ignore = "prints a report; run explicitly with --ignored --nocapture"]
    fn characterize_cpu_overhead_by_input_length() {
        let Some(tok) = load_test_tokenizer() else { return };
        let prov = provenance();

        let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
        let corpus_path = repo_root.join("corpus").join("baseline_prompts.jsonl");
        let golden_path = repo_root
            .join("benchmarks").join("workloads").join("week3_cost").join("golden_vectors.v1.jsonl");
        if !corpus_path.exists() || !golden_path.exists() {
            eprintln!(
                "skipping: corpus/golden vectors not present (run scripts/build_cost_golden_vectors.py)"
            );
            return;
        }

        let corpus_text = std::fs::read_to_string(&corpus_path).unwrap();
        let mut texts_by_id: std::collections::HashMap<u64, String> = std::collections::HashMap::new();
        for line in corpus_text.lines() {
            let row: serde_json::Value = serde_json::from_str(line).unwrap();
            let id = row["prompt_id"].as_u64().unwrap();
            let text = row["text"].as_str().unwrap().to_string();
            texts_by_id.insert(id, text);
        }

        let golden_text = std::fs::read_to_string(&golden_path).unwrap();
        let mut golden: Vec<(u64, u64)> = golden_text
            .lines()
            .map(|line| {
                let row: serde_json::Value = serde_json::from_str(line).unwrap();
                (row["prompt_id"].as_u64().unwrap(), row["input_tokens"].as_u64().unwrap())
            })
            .collect();
        golden.sort_by_key(|&(_, input_tokens)| input_tokens);

        let n = golden.len();
        let picks = [
            ("min", 0),
            ("p50", n / 2),
            ("p90", n * 90 / 100),
            ("p99", n * 99 / 100),
            ("max", n - 1),
        ];

        const ITERATIONS: usize = 200;
        println!("\ninput-length region | input_tokens | min us | mean us | p99 us");
        for (label, idx) in picks {
            let (prompt_id, input_tokens) = golden[idx];
            let text = &texts_by_id[&prompt_id];
            let request = serde_json::json!({
                "model": prov.model_id,
                "messages": [{"role": "user", "content": text}],
                "max_tokens": 512,
            });
            let bytes = serde_json::to_vec(&request).unwrap();

            let mut samples_us = Vec::with_capacity(ITERATIONS);
            for _ in 0..ITERATIONS {
                let start = std::time::Instant::now();
                let cost = compute_request_cost(&bytes, &tok, prov).expect("golden prompt must be supported");
                samples_us.push(start.elapsed().as_micros() as u64);
                assert_eq!(cost.input_tokens, input_tokens as u32);
            }
            samples_us.sort_unstable();
            let min_us = samples_us[0];
            let mean_us = samples_us.iter().sum::<u64>() / samples_us.len() as u64;
            let p99_us = samples_us[(samples_us.len() * 99 / 100).min(samples_us.len() - 1)];
            println!(
                "{label:>4} (prompt {prompt_id}) | {input_tokens:>12} | {min_us:>6} | {mean_us:>7} | {p99_us:>6}"
            );
        }
    }
}
