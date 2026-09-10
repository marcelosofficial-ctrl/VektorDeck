# Model Intelligence

VektorDeck 0.3 adds a local GGUF metadata and compatibility subsystem without loading a model for inference.

## Goals

- understand what a GGUF file actually contains rather than relying on filenames alone
- keep inspection local and bounded
- cache unchanged metadata in SQLite
- let malformed files fail individually without breaking the library scan
- derive transparent profile-readiness checks from indexed assets and GGUF metadata
- provide projector-pairing hints without silently modifying saved profiles

## Safety model

The inspector reads only the GGUF header and key/value metadata section. It does not walk tensor payloads or initialize inference.

The parser applies explicit limits to metadata entry count, string byte length, array item count and nested metadata depth. Large arrays such as tokenizer tables are streamed/skipped and represented by compact summaries rather than materialized into Python lists or stored wholesale in SQLite.

Unsupported or malformed files are stored with `status=error` and a bounded error message. They remain visible in Model Inspector instead of crashing the application.

## Cached metadata

Metadata is keyed by resolved path and tied to the indexed file's `modified_ns` and `size_bytes`. If both values are unchanged, later inspections reuse the SQLite cache rather than parsing the file again.

When available, the summary exposes:

- GGUF version
- tensor count
- metadata count
- `general.architecture`
- `general.name`
- architecture-specific context length
- parameter count
- size label
- file type
- quantization version
- selected scalar GGUF metadata for inspection

Filename-based quantization hints such as `IQ3_XS`, `Q4_K_M`, `BF16` or `F16` are deliberately kept separate from GGUF's numeric file-type field.

## Projector pairing

Pairing hints are evidence-based rather than authoritative. VektorDeck currently scores projectors using local signals such as:

- model and projector living in the same folder
- shared filename tokens
- the `mmproj` naming convention

The highest-scoring projector is presented as a recommendation with the reasons that produced the score. VektorDeck never changes a profile automatically from this hint.

## Profile readiness

Saved profiles are classified as:

- `READY` when indexed files are present, the host is loopback-only, and inspected metadata does not reveal a conflict
- `WARN` when the profile remains launchable but metadata is missing, inspection failed, or requested context exceeds the GGUF-advertised context
- `BLOCKED` when required model/projector assets are not valid indexed files or the host violates local-only safety rules

Every classification includes explicit reasons. This keeps VektorDeck explainable rather than reducing compatibility to an opaque score.

## Benchmark evidence

Performance recommendations remain separate from model compatibility. Trends calculate trustworthy profile averages only from `HEALTHY` and `TIGHT` benchmark evidence. `PRESSURED` and `UNVERIFIED` history remains visible but cannot become a trustworthy winner.

## API

```text
GET  /api/model-intelligence
GET  /api/model-intelligence/item?path=<resolved path>
GET  /api/model-intelligence/pairings
GET  /api/model-intelligence/profiles
GET  /api/model-intelligence/profiles/<profile id>
POST /api/model-intelligence/scan
```

The scan endpoint works from the existing indexed model library and inspects GGUF language-model/projector files only.

## UI

The `MODELS` utility-rail control opens Model Inspector. It can refresh metadata on demand, browse inspected GGUF assets, display architecture/context/tensor/quantization metadata, show local projector-pairing evidence, and explain the readiness of every saved profile that uses the selected language model.
