# V8 development — seven-stage goal remains active

The approved v8 development stage completed three GPU jobs on 2026-10-16.
Quality failed: selected correspondence remained 14/25 overall; small-object
correspondence improved to 2/4, but display-case correspondence regressed from
3/10 to 2/10 and duplicates persisted. The sunroom still missed both selected
small objects and had a generated enclosure covering visible openings.

Production v4, the original environment and worker settings were restored and
read back at 05:58:25 UTC. All three saved results passed artifact and Chrome
checks; those technical checks do not override the failed quality review.
No held-out or authenticated-browser GPU job was submitted. Evidence lives in
`.runtime/v8-gpu-comparison/development` and `development-review.json`.
The frozen v8 archive is preserved. Subsequent local fixes belong to v9;
see [the v9 plan](V9_VALIDATION_PLAN.md). The seven-stage goal remains incomplete.

## Implemented and locally tested

- Signed camera projection fitted from the shared pointmap, image-line Hough
  segments and vanishing-point orientation. Conflicting evidence abstains.
  Two independent vertical normal families can corroborate image lines when a
  horizontal surface is unavailable. Room classes are withheld without accepted
  orientation evidence.
- Small-object detection proposals use 14 multiscale regions instead of five,
  with eight of the 40 prompt slots reserved for localized detections. The three-job GPU run showed this budget still discards useful proposals;
  v9 removes the prompt cutoff.
- A nearly full-frame mask containing independent instances is retained as
  observed context, preserving those instances and visible stairs/openings.
  Unclassified observed context has its own viewer control and GLB node.
- Supports are queried on actual shelf triangles, without rejecting tall
  enclosures by their overall center. Movement is capped by the prop's size too.
  Actual load-bearing contacts must enclose the center, allowing stable overhangs
  while rejecting a single high corner or unstable support edge.
- Finite triangle sweeps, closed-component containment and sampled penetration
  depth replace blanket third-object AABB rejection. Finite room patches replace
  infinite-plane blocking. Exhausted collision-query budgets reject moves;
  open supports are explicitly marked as unknown-volume evidence, so a contact
  improvement is not reported as proof of zero penetration.
  scipy/rtree are declared and locked; finalization runs in the existing pinned
  SAM3D environment before the controller's idempotent verification.
- Bounded, shape-preserving depth translation was evaluated but is excluded from
  the execution path: the display-case proposals did not satisfy the combined
  pixel-motion/collision guards. The original meshes and poses are retained.

The current full unit/regression run passed **162 tests**. The lockfile check and
JavaScript syntax checks passed. Six development scenes passed GLB transform and
parent-group validation and actual Chrome rendering/toggles/byte-exact download.
These checks are not a quality acceptance claim.

`mapmaker_objects` and `mapmaker_space` are actual exported GLB parent nodes,
with world transforms preserved, rather than only viewer-side categories.

The local application candidate is frozen at
`cd5b11788181607418037af51fd8d902bd54c53811fface83eb0e6b458f208cf`.
`V8_VALIDATION_PLAN.md` specifies a staged maximum of 13 further submissions.
Both GPU runner stages passed a local dry-run; neither submitted a job.

## Saved evidence

- `.runtime/v8-candidate/final-ablation`: final 42 runs (six scenes, seven
  variants) completed. Names-removed outputs had identical GLB, placement and
  structure in all six scenes; every source hash was preserved and every result
  was idempotent. Removing the contact-polygon or finite-collision repair removes
  the one display-case contact improvement. Removing context routing reintroduces
  the stair-hall column-to-whole-scene move. Summary: `ablation-report.json`.
- `.runtime/v8-candidate/grouped-development`: all six original development
  runs preserved their source hashes and passed idempotence, artifact validation
  and Chrome checks. Individual assets and previews came from their original
  saved runs; no new GPU generation was performed.
- `.runtime/v8-candidate/local-visual-review.json`: the current fixed-mesh replay
  still fails visual quality in the sunroom and display case. Technical success
  must not be used as a deployment gate. The fresh detection path remains untested.
- `.runtime/v8-development/ablation-01`: 14 fixed-input runs across display-case
  and stair-hall scenes. Full names-removed runs had identical GLB hashes,
  placement and structure. Before depth registration was added, the display-case
  contact improved only with both the contact-polygon and finite-collision changes.
  Removing full-frame routing reintroduced the incorrect column-to-parent move.
  The provenance records the code at that time; it is not the final V8 ablation.
- `context-abstention-replay`: stair-hall context replaced the hallucinated
  full-scene solid, keeping 11 independent instances. Browser toggles and byte-exact
  GLB download passed. Room types remain unclassified because orientation evidence
  conflicts. The scene is not a fully recovered closed room.
- `body-checked-support-replay`: one display-case plate moved 0.013724 scene units
  upward to a sampled shelf contact. Open-support volume uncertainty remains;
  this is not a metric-ground-truth certification.
- `registration-proposals.json`: initial depth-fit proposals only, before collision
  acceptance. They must not be reported as accepted scene corrections.
- `registration-guarded-replay`: guarded registration accepted zero translations.
  It preserved the contact repair but provided no additional quality improvement,
  so it is not included in the runtime candidate.

## Rejected experiment

Replacing large composite instance meshes with residual pointmap surfaces reduced
overlap but fragmented the display-case shape. The production call was removed.
The diagnostic implementation is archived as
`.runtime/v8-development/rejected_residual_replacement.py`; its rendered result
is in `ownership-replay`. The remaining `scene_ownership.py` only selects disjoint
depth fitting targets and never replaces or deletes an instance mesh.

## Still required

1. Finish real-scene registration and duplicate-layout improvements; check support,
   penetration and preservation against source images, including wall-mounted TV
   as a case that must not be lowered onto a cabinet.
2. Replay the complete development corpus and final independent ablations, then
   freeze the candidate. All six previously used images are development data in
   `QUALITY_EVALUATION_V3.json`; the old manifests remain historical and unchanged.
3. Fresh living-room, utility-room and library images and 29 selected object
   annotations (five small objects) are frozen before any inference in V3.
   Retain their v4/v5 baselines and execute the necessary additional GPU batch
   within a concrete approved scope. The previous nine-job approval is consumed.
4. Verify the complete authenticated browser upload → generation → render →
   download route for the accepted release. Deploy only after the quality gate;
   failed quality runs require continued correction, not goal completion.
