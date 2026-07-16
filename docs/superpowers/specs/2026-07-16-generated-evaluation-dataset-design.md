# Controlled T2I and TI2I Evaluation Dataset Design

## Objective

Replace every tracked placeholder/mock prompt, reference image, and model result with a compact but meaningful evaluation dataset. The replacement must make good and bad generations distinguishable, exercise the dashboard's scene/model aggregation, and remain compatible with dataset download and evaluation flows.

This change replaces only the repository-owned mock data under the task-specific prompt, reference, and result roots. It does not delete user-created database records or runtime uploads.

## Chosen Approach

Three approaches were considered:

1. **Controlled generation (chosen):** generate all references and outputs with explicit visual constraints, then create deliberate high/medium/weak variants. This gives the clearest comparisons, avoids licensing uncertainty, and makes structural validation deterministic.
2. **Hybrid web references plus generated outputs:** more photographic variety, but introduces provenance, availability, and licensing work while making edits harder to control.
3. **Curated public benchmark samples:** strongest external realism, but benchmark formats and licenses vary, and model outputs may not map cleanly to this application's folder and prompt conventions.

Controlled generation is preferred because this is smoke/evaluation fixture data rather than a scientific benchmark. The goal is reliable product testing, not publication-grade leaderboard claims.

## Dataset Shape

All images are RGB JPEG files at 768 x 768 pixels, encoded at JPEG quality 85 without embedded thumbnails or metadata. Target repository growth is approximately 20-35 MB.

### T2I

Three scenes, six prompts per scene, three neutral model names:

| Scene | Evaluation focus | Models |
|---|---|---|
| `portrait_anatomy` | hands, limbs, multi-person identity, pose, occlusion | `Atlas`, `Beacon`, `Cipher` |
| `text_product` | exact short text, packaging, signs, product geometry | `Atlas`, `Beacon`, `Cipher` |
| `spatial_composition` | object counts, left/right/front/behind relations, coherent interiors and streets | `Atlas`, `Beacon`, `Cipher` |

This creates 18 prompts and 54 output images.

### TI2I

Three scenes, six prompt/reference pairs per scene, two neutral model names:

| Scene | Evaluation focus | Models |
|---|---|---|
| `object_edit` | add, remove, or replace a local object without collateral changes | `Mosaic`, `Prism` |
| `appearance_edit` | change color, material, clothing, or product appearance while preserving structure | `Mosaic`, `Prism` |
| `background_style` | change background, lighting, or style while preserving the main subject | `Mosaic`, `Prism` |

This creates 18 reference images and 36 edited output images.

## File Layout and Naming

The replacement follows the existing application contract:

```text
prompt/
  T2I/<scene>.txt
  TI2I/<scene>.txt
ref_images/
  TI2I/<scene>/<sample_id>.jpg
results/
  T2I/<model>/<scene>/<sample_id>.jpg
  TI2I/<model>/<scene>/<sample_id>.jpg
tests/fixtures/
  generated_dataset_expectations.json
```

Each prompt file contains six non-empty UTF-8 records in the existing `<sample_id><TAB><prompt>` format. Sample IDs are scene-specific and stable, such as `portrait_01` and `object_edit_01`. An ID appears exactly once in its prompt file and maps to exactly one image per relevant model. Every TI2I ID also maps to exactly one reference image.

The expectation manifest is test-only. It records the intended quality tier and deliberately introduced failure mode for each output. It is never returned by an API or shown in the dashboard.

## Content and Quality Design

Prompts use concrete, observable requirements: exact object counts, simple spatial relations, short literal text, specified colors/materials, and identity-preservation constraints. Requirements are chosen so an evaluator can explain why an image is good or bad without relying only on taste.

### T2I quality profiles

- `Atlas`: predominantly high quality, with five high and one medium result per scene.
- `Beacon`: mixed quality, with two high, three medium, and one weak result per scene.
- `Cipher`: predominantly weak, with one medium and five weak results per scene.

High results satisfy the prompt and look coherent. Medium results remain usable but contain one visible, realistic defect, such as a slightly malformed hand, one incorrect word, or a minor spatial error. Weak results contain an obvious but safe failure, such as missing an instructed object, garbled text, anatomy deformation, duplicated elements, or a contradictory spatial arrangement.

### TI2I quality profiles

- `Mosaic`: predominantly high quality, with five high and one medium result per scene.
- `Prism`: predominantly weak, with two medium and four weak results per scene.

High edits satisfy the instruction while preserving unrelated pixels and subject identity. Medium edits complete the requested change but introduce limited drift. Weak edits visibly miss part of the instruction, alter protected content, or introduce local artifacts.

The quality profile is intentionally asymmetric so aggregate statistics and bad-case views have a clear signal. Model names remain neutral and no quality labels appear in the product UI.

## Generation Workflow

Generation proceeds in two stages:

1. **Pilot:** generate one representative T2I comparison triplet and one TI2I reference/edit pair for each scene. Assemble a contact sheet for visual review. Adjust prompt specificity or defect strength before scaling.
2. **Full generation:** generate approved high-quality bases, then derive controlled medium and weak variants with explicit edit instructions. Normalize dimensions, color mode, and JPEG encoding, and install files in the final task-specific layout.

For T2I, high-quality outputs are generated from the prompt and lower tiers are derived with targeted faults so comparisons keep similar composition. For TI2I, references are generated first; each model output is produced from the same reference and edit instruction. This reduces accidental content differences that would obscure edit fidelity.

Generated assets must not contain real people, brands, copyrighted characters, signatures, watermarks, or unsafe content.

## Removal and Migration

Delete the existing tracked mock content:

- T2I model folders `A`, `B`, and `C` and their `open` results.
- TI2I model folders `D` and `E` and their `open` results.
- Existing `prompt/T2I/open.txt` and `prompt/TI2I/open.txt`.
- Existing `ref_images/TI2I/open` references.

Add only the new scenes, neutral model folders, prompts, references, result images, and test expectation manifest. Existing database rows are not migrated automatically; test setup must use the new scene/model names.

## Error Handling and Compatibility

- Generation is staged outside the final data roots so incomplete batches cannot leave a partially valid dataset.
- A validation script checks image readability, exact dimensions, RGB mode, ID parity, counts, unexpected files, and expectation-manifest completeness before installation.
- TI2I ZIP downloads must contain the selected scene prompt file and all six matching references when “include references” is selected.
- T2I downloads remain prompt-only TXT files.
- The application must continue to behave gracefully if a scene or model folder is missing; the fixture validator is responsible for making the committed dataset complete.

## Testing and Acceptance Criteria

Automated checks must verify:

- exactly 3 T2I scenes, 18 T2I prompts, 3 T2I models, and 54 T2I outputs;
- exactly 3 TI2I scenes, 18 TI2I prompts, 18 references, 2 TI2I models, and 36 TI2I outputs;
- prompt IDs, reference IDs, result IDs, and expectation IDs match exactly;
- every image is a readable 768 x 768 RGB JPEG;
- old `open` scenes and A/B/C/D/E model folders are absent;
- T2I TXT and TI2I TXT/ZIP downloads contain the expected files;
- existing backend and frontend regression tests still pass.

Visual acceptance uses the pilot and final contact sheets. Each medium/weak image must have a named, visible defect matching the expectation manifest. At least one reviewer must confirm that scene intent, edit fidelity, and tier separation are understandable without seeing the hidden labels.

## Out of Scope

- Scientific benchmarking or claims that these images represent real third-party model performance.
- Adding new dashboard controls or changing scoring logic.
- Downloading third-party datasets or maintaining external attribution metadata.
- Preserving compatibility with the old mock scene/model names.
