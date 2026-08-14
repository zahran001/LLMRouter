# tests/fixtures

## Faithfulness Layer 1 & 3 -- not built here (GPU session required)

`WEEK1_MEASUREMENT_SPEC.md` §6 defines three faithfulness layers. This
module's test suite implements **Layer 2 only**
(`tests/faithfulness/test_schema.py`) -- the $0, CI-runnable schema
assertion against the mock.

Layers 1 and 3 require a GPU session running real vLLM and are explicitly
out of scope for this build:

- **Layer 1**: capture real vLLM output once and commit it here as
  `vllm_real_stream.txt`, prefixed with `# captured from vLLM <version> on
  <date>` (see spec §6 for the exact `curl` command).
- **Layer 3**: run the same `assert_faithful_sse_schema` function from
  `tests/faithfulness/_schema_assertions.py` against `vllm_real_stream.txt`,
  then diff key SETS (not values) between a mock chunk and a real chunk,
  recursively into `choices[0]` and `delta`. Any key vLLM sends that the
  mock omits is a gap to add to `mock/app.py`.

Do this when a GPU session is available: capture the fixture, confirm the
schema assertion and key-set diff both pass with zero mock changes, tear
the GPU down immediately (spec §7).
