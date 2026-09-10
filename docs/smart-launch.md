# Smart Launch Recommendations

VektorDeck 0.4 adds transparent local launch recommendations for indexed GGUF language models. Version 0.4.1 adds one-click evidence validation and tighter promotion rules.

## Principle

A recommendation is never a mystery score and is never silently made the default profile.

VektorDeck exposes two recommendation classes:

### EVIDENCE-BACKED

Used only when a currently saved profile for the selected model has at least **two** benchmark runs classified as `HEALTHY` or `TIGHT`.

- `PRESSURED` runs are excluded.
- `UNVERIFIED` legacy runs are excluded.
- one clean run is not enough for promotion.
- average and best generation speed are calculated from trustworthy runs only.
- the recommendation reuses the proven saved profile configuration.

### EXPERIMENTAL

Used when repeated trustworthy benchmark evidence does not yet exist.

The starting profile is derived from explicit local facts:

- indexed model size
- GGUF-advertised context length when available
- total system RAM
- total VRAM
- local projector-pairing evidence
- saved profile defaults such as GPU layers, host and port
- llama.cpp capability detection for optional vision flags

The UI clearly labels the result as experimental and says it must earn repeated clean benchmark evidence before it can become evidence-backed.

## Conservative context tiers

The current heuristic intentionally favors headroom over maximum context:

- nominal 64 GB-class Windows systems are recognized from roughly 63 GiB usable RAM
- nominal 32 GB-class Windows systems are recognized from roughly 31 GiB usable RAM
- 32 GB-class RAM with 12+ GiB VRAM maps to a 16K starting tier
- when a large GGUF alone occupies at least roughly 65% of total VRAM and the starting tier is above 8K, the context is reduced one tier
- extremely VRAM-heavy models can be reduced more aggressively
- limited or unknown memory starts at 4K/8K tiers
- multimodal profiles do not start above 16K without evidence
- GGUF-advertised context is always treated as an upper bound when present

For an approximately 11 GiB multimodal model on a machine reporting around 31.6 GiB usable RAM and 16 GiB VRAM, this produces an **8K experimental starting point**: the machine first enters the 16K hardware tier, then the large model-to-VRAM ratio reduces that by one tier.

## Single-user defaults

Experimental recommendations normalize the profile to one llama.cpp server slot with:

```text
--parallel 1
```

When the selected model has a paired projector and the installed llama.cpp build advertises `--image-min-tokens`, VektorDeck also adds:

```text
--image-min-tokens 1024
```

If the installed `llama-server --help` does **not** advertise that option, VektorDeck does not inject it and explains the omission in the recommendation reasons. Runtime log advisories and CLI capability detection are deliberately treated as separate evidence sources.

## Projector pairing

Projectors are suggestions, never automatic mutations. Pairing evidence currently considers:

- same-folder placement
- shared filename/model tokens
- `mmproj` naming convention

The recommendation explanation shows why a projector was chosen.

## Profile creation safety

`CREATE SUGGESTED PROFILE`:

- creates a new SQLite launch profile
- does not overwrite existing profiles
- does not make the new profile default
- does not launch it
- does not delete benchmark history

## One-click evidence validation

`VALIDATE SUGGESTION` orchestrates existing VektorDeck safety and evidence endpoints rather than creating a second runtime controller.

The flow is:

1. run the existing quiet-workstation optimizer preflight
2. reuse an identical saved suggested profile when possible, otherwise create it
3. launch through the normal VektorDeck-owned llama.cpp endpoint
4. verify the live server reports exactly one inference slot
5. run benchmark 1 with hardware evidence
6. stop early if benchmark 1 is not `HEALTHY` or `TIGHT`
7. otherwise run benchmark 2
8. stop llama.cpp through the normal ownership-safe stop endpoint
9. recalculate Smart Launch using the newly saved evidence

A configuration is promoted to `EVIDENCE-BACKED` only when the same saved profile has at least two trustworthy runs. The validator never makes the profile default.

## API

```text
GET  /api/recommendations?model_path=<resolved model path>
POST /api/recommendations/profile
```

The POST body is:

```json
{
  "model_path": "<resolved model path>"
}
```

The response preserves the recommendation source and reasons alongside the newly created profile. Evidence validation itself composes existing preflight, launch, health, benchmark, stop and recommendation endpoints from the dashboard.
