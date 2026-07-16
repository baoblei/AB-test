# Controlled T2I and TI2I Evaluation Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all repository-owned placeholder T2I/TI2I prompts, references, and outputs with a controlled 108-image evaluation fixture whose visual quality tiers are meaningful and whose structure is automatically validated.

**Architecture:** Prompt text and a hidden expectation manifest define the fixture contract. Images are generated into `.generated-dataset-staging/`, visually reviewed as contact sheets, normalized to a single JPEG contract, and only then copied into the application data roots. A focused validator checks the committed data independently of dashboard runtime code; repository smoke tests verify the real download artifacts.

**Tech Stack:** Python 3.9+, Pillow 11.x, standard-library `json`/`pathlib`/`zipfile`/`unittest`, existing FastAPI dataset service, OpenAI image generation/editing, Git.

## Global Constraints

- Replace only tracked mock content under `prompt/T2I`, `prompt/TI2I`, `ref_images/TI2I`, `results/T2I`, and `results/TI2I`; do not delete database rows or runtime uploads.
- T2I contains exactly 3 scenes, 18 prompts, 3 models, and 54 outputs.
- TI2I contains exactly 3 scenes, 18 prompts, 18 references, 2 models, and 36 outputs.
- Every image is a 768 x 768 RGB JPEG encoded at quality 85 without EXIF metadata or embedded thumbnails.
- Model names are neutral: T2I uses `Atlas`, `Beacon`, `Cipher`; TI2I uses `Mosaic`, `Prism`.
- Expected quality tiers and defect descriptions exist only in `tests/fixtures/generated_dataset_expectations.json` and are never exposed by the application.
- Generated assets contain no real people, brands, copyrighted characters, signatures, watermarks, or unsafe content.
- T2I download remains TXT-only; TI2I downloads TXT by default and ZIP with six matching references when selected.

---

### Task 1: Dataset fixture validator and image tooling

**Files:**
- Modify: `requirements.txt`
- Create: `scripts/generated_dataset.py`
- Create: `tests/test_generated_dataset_tools.py`

**Interfaces:**
- Produces: `load_prompt(path: Path) -> dict[str, str]`, `normalize_jpeg(source: Path, destination: Path) -> None`, `validate_dataset(repo_root: Path, manifest_path: Path, *, check_images: bool = True, prompt_root: Path | None = None) -> list[str]`, and `render_contact_sheet(entries: list[tuple[str, Path]], destination: Path, columns: int = 3) -> None`.
- Produces CLI subcommands: `normalize-tree ROOT` normalizes supported images in place through temporary sibling files; `validate --root ROOT --manifest FILE [--prompt-root ROOT]` prints the image count and errors and exits nonzero on any error; `contact-sheet ROOT OUTPUT` discovers images in sorted relative-path order and labels them with those paths.
- Consumes: Pillow `Image`, `ImageDraw`, and `ImageOps`; the committed prompt/result/reference directory contract.

- [ ] **Step 1: Add failing unit tests using a temporary miniature fixture**

Create tests that write one T2I prompt, one TI2I prompt/reference, and model output folders under a temporary root. Assert that `load_prompt` parses tab-separated IDs, `normalize_jpeg` produces RGB `(768, 768)` JPEG data with no EXIF, `validate_dataset` returns `[]` for a manifest whose counts and paths match, and returns path-specific errors for a missing output, extra output, ID mismatch, wrong size, non-RGB image, and malformed expectation entry.

```python
def test_normalize_jpeg_enforces_fixture_contract(self):
    source = self.root / "source.png"
    Image.new("RGBA", (640, 480), (20, 80, 140, 128)).save(source)
    destination = self.root / "normalized.jpg"
    normalize_jpeg(source, destination)
    with Image.open(destination) as image:
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (768, 768))
        self.assertFalse(image.getexif())

def test_validator_reports_missing_result_by_relative_path(self):
    manifest = self.build_valid_fixture()
    missing = self.root / "results/T2I/Atlas/portrait_anatomy/portrait_01.jpg"
    missing.unlink()
    errors = validate_dataset(self.root, manifest)
    self.assertIn("missing results/T2I/Atlas/portrait_anatomy/portrait_01.jpg", errors)
```

- [ ] **Step 2: Run the tooling tests and verify RED**

Run: `python3 -m unittest tests.test_generated_dataset_tools -v`

Expected: FAIL because `scripts.generated_dataset` does not exist.

- [ ] **Step 3: Add Pillow and implement the focused helpers**

Add `Pillow>=11,<12` to `requirements.txt`. Implement strict prompt parsing, centered cover-crop resizing through `ImageOps.fit(..., (768, 768), method=Image.Resampling.LANCZOS)`, RGB conversion, `save(..., format="JPEG", quality=85, optimize=True, exif=b"")`, manifest/path/count validation, and a labeled contact sheet with 240-pixel thumbnails. `validate_dataset` must collect all errors rather than stop at the first error and must reject unexpected scene/model/image files.

```python
def normalize_jpeg(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        image = ImageOps.fit(
            original.convert("RGB"),
            (768, 768),
            method=Image.Resampling.LANCZOS,
        )
        image.save(destination, "JPEG", quality=85, optimize=True, exif=b"")
```

- [ ] **Step 4: Run the tooling tests and verify GREEN**

Run: `python3 -m unittest tests.test_generated_dataset_tools -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the reusable validation tooling**

```bash
git add requirements.txt scripts/generated_dataset.py tests/test_generated_dataset_tools.py
git commit -m "test: add generated dataset validator"
```

---

### Task 2: Prompts and hidden quality contract

**Files:**
- Delete: `prompt/T2I/open.txt`
- Delete: `prompt/TI2I/open.txt`
- Create: `prompt/T2I/portrait_anatomy.txt`
- Create: `prompt/T2I/text_product.txt`
- Create: `prompt/T2I/spatial_composition.txt`
- Create: `prompt/TI2I/object_edit.txt`
- Create: `prompt/TI2I/appearance_edit.txt`
- Create: `prompt/TI2I/background_style.txt`
- Create: `tests/fixtures/generated_dataset_expectations.json`
- Modify: `tests/test_generated_dataset_tools.py`

**Interfaces:**
- Produces: 36 stable prompt IDs and a manifest with `version`, `image`, `tasks`, and one `{tier, defect}` expectation for every one of the 90 model outputs.
- Consumes: Task 1's `load_prompt` and manifest validation schema.

- [ ] **Step 1: Add a failing contract test for exact prompt/model/scene sets and tier totals**

```python
def test_repository_manifest_has_expected_shape(self):
    manifest_path = Path("tests/fixtures/generated_dataset_expectations.json")
    errors = validate_dataset(Path("."), manifest_path, check_images=False)
    self.assertEqual(errors, [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    self.assertEqual(set(manifest["tasks"]["T2I"]), {"Atlas", "Beacon", "Cipher"})
    self.assertEqual(set(manifest["tasks"]["TI2I"]), {"Mosaic", "Prism"})
```

Also assert per scene: Atlas `5 high + 1 medium`, Beacon `2 high + 3 medium + 1 weak`, Cipher `1 medium + 5 weak`, Mosaic `5 high + 1 medium`, and Prism `2 medium + 4 weak`.

- [ ] **Step 2: Run the contract test and verify RED**

Run: `python3 -m unittest tests.test_generated_dataset_tools.GeneratedDatasetRepositoryContractTests -v`

Expected: FAIL because the new prompt files and manifest do not exist.

- [ ] **Step 3: Replace the prompt files with these exact tab-separated records**

```text
# prompt/T2I/portrait_anatomy.txt
portrait_01	Editorial studio portrait of an adult ceramic artist holding a cobalt-blue mug with both hands at chest height; both hands fully visible with five natural fingers each, warm gray backdrop, soft window light, realistic photography.
portrait_02	Two adult friends standing side by side while the person on the left ties a red scarf around the other person's neck; four hands visible, distinct faces, natural arms, candid winter street photograph.
portrait_03	Full-body photograph of an adult contemporary dancer balancing on the left foot with the right leg extended backward and both arms forming a wide V; anatomically correct limbs, simple black studio floor.
portrait_04	An adult chef pouring tea from a small white teapot into a blue cup while looking at the cup; one hand on the handle and one supporting the lid, realistic fingers, cozy restaurant interior.
portrait_05	An adult gardener kneeling beside three terracotta pots, holding a trowel in the right hand and a seedling in the left; complete hands and legs visible, bright greenhouse photograph.
portrait_06	Three adult jazz musicians seated in a row: a saxophonist on the left, a guitarist in the center, and a drummer on the right; distinct instruments, coherent hands, intimate stage lighting.

# prompt/T2I/text_product.txt
text_01	Minimal mint-green beverage carton on a cream pedestal. The front shows exactly the large words "MINT DAY" and the small line "FRESH & CALM" in clean dark-green type; no other text, realistic product photograph.
text_02	Night market poster pinned to a brick wall, with exactly three readable lines: "NIGHT MARKET", "FRIDAY", and "8 PM"; orange and navy geometric design, straight-on photograph.
text_03	Small modern bakery storefront at morning. Above the door is one clearly readable sign saying exactly "BAKE LAB"; no other words or logos, realistic street photograph.
text_04	Matte black coffee bag standing upright on a wooden counter. The label contains exactly "NORTH" on the first line and "ROAST" on the second line; simple white typography, product photograph.
text_05	Transparent sparkling-water bottle with a pale-blue label reading exactly "CLOUD"; silver cap, water droplets, blue gradient background, no additional text.
text_06	A clean transit ticket on a white table, printed with exactly "CITY PASS" and "24H" plus a simple blue arrow icon; crisp overhead product photograph.

# prompt/T2I/spatial_composition.txt
spatial_01	On a white tabletop, place one red cube to the left of one blue sphere, with a small yellow cone centered behind both objects; exactly three objects, soft studio shadows.
spatial_02	Bright dining room with exactly four wooden chairs around a round table; a green vase is centered on the table and a pendant lamp hangs directly above it, realistic interior photograph.
spatial_03	Quiet city sidewalk where a blue bicycle stands behind a wooden bench, a red mailbox is to the right of the bench, and one tree is to the left; all objects fully visible.
spatial_04	White wall shelf with exactly two levels: three books and one clock on the top level, two ceramic bowls on the bottom level; front-facing catalog photograph.
spatial_05	Calm bedroom with a bed centered between two identical bedside tables; one lamp on each table, a framed mountain print above the bed, symmetrical composition.
spatial_06	Cozy cafe counter scene: a glass pastry case in front of the barista, an espresso machine behind the barista, and exactly three red stools aligned along the counter.

# prompt/TI2I/object_edit.txt
object_edit_01	Add one small red apple on the empty white plate. Preserve the plate, table, cup, lighting, framing, and every other object exactly.
object_edit_02	Remove the blue vase from the shelf and reconstruct the wall behind it. Preserve all books, the plant, shelf geometry, and lighting.
object_edit_03	Replace only the yellow desk lamp with a matte-black lamp of the same size and position. Preserve the desk, notebook, chair, and room.
object_edit_04	Add a folded green towel to the right side of the bathroom sink. Preserve the mirror, faucet, soap bottle, tiles, and reflections.
object_edit_05	Remove the orange traffic cone beside the bicycle. Preserve the bicycle, pavement, wall, shadows, and camera framing.
object_edit_06	Replace the white mug on the tray with a clear glass tumbler in the same position. Preserve the tray, book, sofa, and lighting.

# prompt/TI2I/appearance_edit.txt
appearance_01	Change only the armchair upholstery from beige fabric to deep-blue velvet. Preserve its shape, seams, room, floor, and lighting.
appearance_02	Change only the handbag material from brown leather to woven natural straw. Preserve its silhouette, handles, table, and background.
appearance_03	Change only the jacket from gray to bright red. Preserve the adult subject's face, pose, body, jeans, street, and lighting.
appearance_04	Change only the ceramic teapot from glossy white to matte forest green. Preserve its exact shape, cup, table, and shadows.
appearance_05	Turn only the silver bicycle frame pastel pink. Preserve the wheels, handlebars, basket, street, and all geometry.
appearance_06	Change only the kitchen cabinet doors from white paint to light oak wood. Preserve handles, countertop, appliances, layout, and lighting.

# prompt/TI2I/background_style.txt
background_01	Replace the plain studio background with a soft sunset beach while preserving the potted cactus exactly in shape, scale, position, and lighting direction.
background_02	Change the daytime city background to a rainy evening with wet reflections. Preserve the adult cyclist, bicycle, pose, clothing, and framing.
background_03	Replace the indoor wall behind the red sneaker with a clean pale-blue paper backdrop. Preserve the sneaker, pedestal, shadows, and product details.
background_04	Change the forest background to a snowy winter forest. Preserve the wooden bench exactly, including its shape, position, texture, and camera angle.
background_05	Restyle the background as a flat pastel illustration while keeping the foreground glass perfume bottle photorealistic and unchanged.
background_06	Change the kitchen lighting from neutral daylight to warm golden-hour light. Preserve every object, material, geometry, and camera position.
```

- [ ] **Step 4: Create the complete expectation manifest**

Use keys in path order `task -> model -> scene -> sample_id`. Every expectation is exactly `{"tier": "high|medium|weak", "defect": "observable sentence"}`. For `high`, defect must be `"none"`. For medium/weak outputs, name one intended defect tied to the prompt, such as `right hand has six fingers`, `FRIDAY rendered as FRIDAI`, `yellow cone moved in front`, `unrequested shelf books changed`, or `subject face drifted`. The validator rejects generic descriptions such as `bad quality`, empty text, or tier totals that differ from the global profile.

- [ ] **Step 5: Run the prompt/manifest contract tests and verify GREEN**

Run: `python3 -m unittest tests.test_generated_dataset_tools.GeneratedDatasetRepositoryContractTests -v`

Expected: all contract tests pass with `check_images=False`.

- [ ] **Step 6: Commit the prompt and expectation contract**

```bash
git add prompt/T2I prompt/TI2I tests/fixtures/generated_dataset_expectations.json tests/test_generated_dataset_tools.py
git commit -m "data: define controlled evaluation prompts"
```

---

### Task 3: Generate and review the six-scene pilot

**Files:**
- Create outside Git: `.generated-dataset-staging/pilot/**`
- Create outside Git: `.generated-dataset-staging/pilot-contact-sheet.jpg`
- Modify if visual review requires it: prompt files and `tests/fixtures/generated_dataset_expectations.json`

**Interfaces:**
- Consumes: Task 2 prompt IDs `portrait_01`, `text_01`, `spatial_01`, `object_edit_01`, `appearance_01`, and `background_01`; Task 1 normalization/contact-sheet functions.
- Produces: one T2I Atlas/Beacon/Cipher triplet and one TI2I reference/Mosaic/Prism group for each scene, normalized and arranged for review.

- [ ] **Step 1: Read and follow the imagegen skill before generating assets**

Use `/Users/baobinglei/.codex/skills/.system/imagegen/SKILL.md`. Generate brand-new T2I bases and TI2I references without supplied images; derive model variants through reference-image editing.

- [ ] **Step 2: Generate the pilot with fixed prompt wrappers**

For high T2I bases, append: `Commercially neutral synthetic scene, no real person, no brand, no watermark, no signature. Follow every count, relation, anatomy, and quoted text requirement exactly.`

For medium variants, edit the base with: `Preserve composition, lighting, identity, and all unmentioned details. Introduce only this subtle but clearly visible evaluation defect: ` followed by the exact non-`none` defect sentence from that output's manifest entry, then `Keep the result otherwise plausible and polished.`

For weak variants, edit the base with: `Preserve the broad scene and visual style. Introduce this unmistakable evaluation failure: ` followed by the exact defect sentence from that output's manifest entry, then `Do not add watermarks, labels explaining the error, unsafe content, or unrelated corruption.`

For TI2I references, generate exactly the unedited scene implied by the instruction, ensuring the target object/background exists and protected details are clearly visible. For outputs, apply the prompt plus the same high/medium/weak preservation rules.

- [ ] **Step 3: Normalize pilot files and render the contact sheet**

Run:

```bash
python3 scripts/generated_dataset.py normalize-tree .generated-dataset-staging/pilot
python3 scripts/generated_dataset.py contact-sheet .generated-dataset-staging/pilot .generated-dataset-staging/pilot-contact-sheet.jpg
```

Expected: 18 labeled groups are readable at full size; each file reports RGB JPEG 768 x 768.

- [ ] **Step 4: Visual checkpoint**

Show the pilot contact sheet to the user. Accept only if the scene requirements are obvious, the high results are usable, medium defects are visible on inspection, weak defects are obvious, and TI2I unrequested regions remain stable enough to judge. If rejected, adjust the specific prompt/defect entry, regenerate only that group, and rebuild the sheet.

- [ ] **Step 5: Commit any approved prompt/manifest corrections**

```bash
git add prompt/T2I prompt/TI2I tests/fixtures/generated_dataset_expectations.json
git diff --cached --quiet || git commit -m "data: refine evaluation quality cues"
```

---

### Task 4: Generate and stage the complete image corpus

**Files:**
- Create outside Git: `.generated-dataset-staging/full/ref_images/TI2I/**`
- Create outside Git: `.generated-dataset-staging/full/results/T2I/**`
- Create outside Git: `.generated-dataset-staging/full/results/TI2I/**`
- Create outside Git: `.generated-dataset-staging/final-contact-sheet.jpg`

**Interfaces:**
- Consumes: all 36 prompts and 90 expectation entries, the approved Task 3 wrappers, and Task 1 normalization/contact-sheet functions.
- Produces: 108 normalized images with exact final relative paths.

- [ ] **Step 1: Generate 18 independent high-quality T2I bases**

Generate one base per T2I prompt. Use it directly wherever the manifest marks a high output; use reference editing to derive each medium/weak output so the three model results remain comparable. Do not mechanically degrade blur or compression: every defect must be semantic and match its manifest sentence.

- [ ] **Step 2: Generate 18 TI2I references**

Each reference must make the edit target and all protected regions visible. Save it as `ref_images/TI2I/<scene>/<sample_id>.jpg` in staging before deriving either model output.

- [ ] **Step 3: Generate all 36 TI2I outputs from their matching reference**

Use the exact TI2I prompt as the requested edit. For Mosaic high outputs, preserve unrelated content. For the single Mosaic medium and Prism medium/weak outputs in each scene, apply only the manifest defect in addition to the requested edit.

- [ ] **Step 4: Normalize and audit the full staging tree**

Run:

```bash
python3 scripts/generated_dataset.py normalize-tree .generated-dataset-staging/full
python3 scripts/generated_dataset.py validate --root .generated-dataset-staging/full --manifest tests/fixtures/generated_dataset_expectations.json --prompt-root .
python3 scripts/generated_dataset.py contact-sheet .generated-dataset-staging/full .generated-dataset-staging/final-contact-sheet.jpg
```

Expected: `validated 108 images; 0 errors`, with a final contact sheet grouped by task, scene, sample, and model.

- [ ] **Step 5: Independent visual review**

Dispatch a reviewer who has access to the prompts and images but not the manifest tiers. Ask them to rank each model group and name visible failures. Compare their report with the manifest: accept when at least 80% of pairwise high-over-medium, medium-over-weak expectations agree and every weak result has an identifiable prompt or preservation failure. Regenerate only mismatched groups and repeat the review.

---

### Task 5: Atomically replace the repository mock data

**Files:**
- Delete: `ref_images/TI2I/open/**`
- Delete: `results/T2I/A/**`, `results/T2I/B/**`, `results/T2I/C/**`
- Delete: `results/TI2I/D/**`, `results/TI2I/E/**`
- Create: `ref_images/TI2I/{object_edit,appearance_edit,background_style}/**`
- Create: `results/T2I/{Atlas,Beacon,Cipher}/{portrait_anatomy,text_product,spatial_composition}/**`
- Create: `results/TI2I/{Mosaic,Prism}/{object_edit,appearance_edit,background_style}/**`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 4's validated staging tree.
- Produces: the final application-visible dataset roots; keeps `.generated-dataset-staging/` untracked.

- [ ] **Step 1: Ignore generation staging**

Add exactly `/.generated-dataset-staging/` to `.gitignore`.

- [ ] **Step 2: Remove only the explicitly scoped tracked mock image trees**

Use `apply_patch` for text-file changes and `git rm` for the listed binary mock trees. Do not touch `database.db`, other untracked files, or any path outside the listed roots.

- [ ] **Step 3: Copy the already-validated staged images into final roots**

Use a deterministic copy preserving the Task 4 relative paths. Immediately run:

```bash
python3 scripts/generated_dataset.py validate --root . --manifest tests/fixtures/generated_dataset_expectations.json
```

Expected: `validated 108 images; 0 errors`.

- [ ] **Step 4: Review the staged Git diff for exact scope and size**

Run:

```bash
git status --short
git diff --stat
find results/T2I results/TI2I ref_images/TI2I -type f -name '*.jpg' | wc -l
```

Expected: 108 JPEG files, no old `open`/A/B/C/D/E paths, and no `database.db` staged.

- [ ] **Step 5: Commit the generated corpus**

```bash
git add .gitignore ref_images/TI2I results/T2I results/TI2I
git commit -m "data: replace mock evaluation images"
```

---

### Task 6: Repository smoke downloads and committed-data acceptance tests

**Files:**
- Create: `tests/test_generated_dataset.py`
- Modify: `tests/test_dataset_download.py`

**Interfaces:**
- Consumes: Task 1's `validate_dataset`; application `list_datasets` and `create_dataset_artifact`.
- Produces: automated regression coverage for all committed fixture files and representative TXT/ZIP downloads.

- [ ] **Step 1: Replace the old hard-coded `open` smoke test and add failing corpus assertions**

```python
class RepositoryGeneratedDatasetTests(unittest.TestCase):
    def test_committed_dataset_matches_manifest(self):
        self.assertEqual(
            validate_dataset(Path("."), Path("tests/fixtures/generated_dataset_expectations.json")),
            [],
        )

    def test_old_mock_names_are_absent(self):
        for path in (
            "prompt/T2I/open.txt", "prompt/TI2I/open.txt", "ref_images/TI2I/open",
            "results/T2I/A", "results/T2I/B", "results/T2I/C",
            "results/TI2I/D", "results/TI2I/E",
        ):
            self.assertFalse(Path(path).exists(), path)
```

Update the repository download test to assert `list_datasets("T2I")` and `list_datasets("TI2I")` return the three expected scene names with six prompts each. For `object_edit`, assert TXT-only download equals the prompt bytes and the ZIP contains `object_edit.txt` plus `ref_images/object_edit_01.jpg` through `ref_images/object_edit_06.jpg` in deterministic order.

- [ ] **Step 2: Run targeted tests and verify the assertions detect any remaining mismatch**

Run:

```bash
python3 -m unittest tests.test_generated_dataset tests.test_dataset_download.RepositorySmokeDatasetTests -v
```

Expected before final corrections: FAIL if any path/count/archive name differs from the committed contract.

- [ ] **Step 3: Make only fixture/test corrections identified by the failing assertions**

Do not relax exact counts, dimensions, model names, scene names, or ID parity. Correct the data path, manifest entry, or expected ZIP member responsible for each failure.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_generated_dataset tests.test_dataset_download tests.test_generated_dataset_tools -v
```

Expected: all generated-dataset and download tests pass.

- [ ] **Step 5: Commit acceptance coverage**

```bash
git add tests/test_generated_dataset.py tests/test_dataset_download.py
git commit -m "test: verify generated evaluation corpus"
```

---

### Task 7: Full verification and handoff

**Files:**
- Modify if required by verified behavior only: `README.md`
- Inspect: all changed files and final contact sheet

**Interfaces:**
- Consumes: the complete committed dataset and all test suites.
- Produces: fresh evidence that the replacement is structurally, visually, and functionally complete.

- [ ] **Step 1: Document the new sample scene/model names if README still names old fixtures**

Keep documentation limited to the public directory contract and neutral names. Do not expose quality-tier expectations or defect annotations.

- [ ] **Step 2: Run the complete automated suite**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q main.py app_core scripts
python3 scripts/generated_dataset.py validate --root . --manifest tests/fixtures/generated_dataset_expectations.json
git diff --check
```

Expected: all tests pass, compilation exits 0, dataset validation reports 108 images and 0 errors, and diff check is clean.

- [ ] **Step 3: Verify real artifacts directly**

Create one T2I TXT artifact and one TI2I ZIP artifact through `create_dataset_artifact`, inspect ZIP members, and confirm the ZIP includes the exact six references matching the selected prompt IDs.

- [ ] **Step 4: Request independent code/data review**

Ask a fresh reviewer to check spec compliance, deletion scope, manifest/UI separation, image counts, prompt-image alignment, download compatibility, and test coverage. Resolve only concrete findings, then rerun the affected tests and the complete suite.

- [ ] **Step 5: Commit final documentation or review corrections**

```bash
git add README.md scripts tests prompt ref_images results .gitignore requirements.txt
git diff --cached --quiet || git commit -m "docs: describe generated evaluation fixtures"
```

- [ ] **Step 6: Use the branch-finishing workflow**

After fresh verification, present the merge/push/keep/discard options without modifying unrelated user files.
