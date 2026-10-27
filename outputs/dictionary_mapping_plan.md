# SKOS Term Mapping Plan — Finland, Meteorology and Soil

Status: plan only, not executed. No mappings are produced by this document.
Execution begins after #8 and after this plan is reviewed and accepted.

## 1. Scope

In: Finland. Meteorology and soil terms from ICOS, ACTRIS, DEIMS-SDR (recorded as ri="eLTER" in the data).
Pairings: ICOS–ACTRIS, ICOS–DEIMS, ACTRIS–DEIMS. ACTRIS–DEIMS is included because 37 of the 79 Finland station pairs are ACTRIS–eLTER (47%), the largest single cross-RI category. Mapping only ICOS–ACTRIS and ICOS–DEIMS would leave that category unmapped.

Out: other RIs; other term domains; measurement units and harmonised values; raw observation data; other countries.

## 2. Sources

Term inventory: outputs/dictionary_terms_finland.csv, 841 rows.
- ICOS: 124 distinct concept URIs across 14 of 25 Finnish stations, drawn from 60 distinct labels (a single label can map to several URIs; for example "wind speed" covers 4 URIs: ETC_WS, WS, WS_F, WS_n_n_n). Concept URIs under meta.icos-cp.eu/resources/dcat/var/. A NERC P07 skos:closeMatch exists for 4 of the 124 concept URIs, all under "wind speed" (CFSN0038). The mapping denominator is concept URIs, not labels.
- ACTRIS: 400 distinct names across 40 of 42 facilities. ACTRIS vocabulary label matches for 393 of 400 (label match, then URI supplied). No soil terms.
- DEIMS: 317 label/URI pairs across 13 of 20 Finnish sites. EnvThes URIs. 315 resolve; 2 do not (22319 wind speed, 22043); 6 deprecated, 4 with replacement. Five URIs carry different labels on different DEIMS sites.

Reference lookups: outputs/dictionary_reference_finland.csv, 768 rows. EnvThes, Standard Observations, Controlled Lists, ACTRIS vocabulary, NERC P07.

## 3. Relations

Five SKOS relations, one per mapping row, no composite.

- exactMatch: interchangeability in both directions. Project convention: only used when the source metadata declares identity (same URI, or a shared persistent ID such as gawid). This restriction is a project rule, not a SKOS requirement. SKOS allows exactMatch more broadly; we do not.
- closeMatch: near-interchangeable; not identical meaning. Expected to be the dominant relation for cross-RI rows.
- broadMatch: the object is the broader concept. `a broadMatch b` means b's meaning contains a's; a is narrower than b. SKOS Reference section: https://www.w3.org/TR/skos-reference/#mapping.
- narrowMatch: the object is the narrower concept. `a narrowMatch b` means a's meaning contains b's; a is broader than b.
- relatedMatch: related but not interchangeable; the softest.

Direction and use:
- Pick exactly one relation per row. broadMatch and narrowMatch are complementary; do not use both for the same pair. One-relation-per-row is a SKOS condition, not just a project convention: skos:exactMatch is disjoint with skos:broadMatch and skos:relatedMatch (SKOS Reference S46). Asserting both for the same pair would be inconsistent with the SKOS data model.
- Canonical placement rule, do not vary by pair:
  - For a pair (narrow term N, broad term B), write it as `N broadMatch B`. Subject = narrower, object = broader. Do not also write `B narrowMatch N` for the same pair; pick one direction per row.
  - If the natural reading is "broad → narrow", still write it as `narrow broadMatch broad`. The pair is the same; the direction convention does not change.
  - This direction was confirmed against the W3C SKOS Reference on [date] (see Section 13). a broadMatch b means b is broader than a; a narrowMatch b means b is narrower than a.

Ambiguity rule (weaker wins):
- If a pair plausibly satisfies more than one relation, choose the weaker (more conservative) relation. Ordering, strongest to weakest: exactMatch > closeMatch > broadMatch ≈ narrowMatch > relatedMatch. Choose the rightmost plausible option. Rationale: weaker-wins is safe because it never overclaims. If a pair turns out to satisfy a stronger relation, writing the weaker one is still correct in SKOS (the weaker is a broader claim that the stronger falls under). The reverse — writing the stronger and being wrong — would be an overclaim. Note the sub-property direction: skos:exactMatch is a sub-property of skos:closeMatch (SKOS Reference S42), so asserting exactMatch implies closeMatch, not the other way. Choosing closeMatch when exactMatch is plausible is the conservative choice and does not preserve the exactMatch entailment; that is deliberate.
- Record the runner-up in evidence_text: "candidate could also be closeMatch; chose broadMatch as the weaker."

relatedMatch counts as allowed but is never counted as "interchangeable". Only exactMatch and closeMatch count as interchangeability when reporting.

## 4. Candidate generation

A candidate is a (term_a, term_b) pair from different RIs, both in the Finland inventory, where at least one side is in the reviewed scope list.

scope_candidate is a keyword flag; it produces false negatives as well as false positives. Review proceeds in two passes.

Pass 1 — all flagged rows. Review every row where scope_candidate = true, decide per row whether it is genuinely meteorology or soil, record accepted / rejected.

Pass 2 — false-negative check. Draw a random sample of 50 rows where scope_candidate = false. For each, decide whether it is genuinely meteorology or soil. If the sample contains one or more misses, expand in batches of 50 until the miss rate is stable or zero. Report sample size, miss rate, and any added terms. Seed the random number generator with a documented seed (default 42) so the sample is reproducible; record the seed and sample size in the summary.

The reviewed list is outputs/dictionary_scope_reviewed.csv. Columns: `in_scope_reviewed` (the decision), `scope_candidate_original` (from #8, so false negatives are visible), `review_pass` (1 or 2), `reason` (one line). Rejected rows do not enter the candidate pool.

After review, run the candidate generator against the reviewed list. The generator's only decisions are: which terms are in the reviewed list, which terms have URIs to match against, and the source lines to show for each candidate.

Blocking rule on candidate count: if the generated candidate list is larger than 200 pairs, do not begin hand mapping. Narrow the scope first (e.g. restrict to one domain per round, or to one RI pair per round). The 200 threshold is a review-capacity estimate, not a scientific cut; Ali adjusts it if needed.

The generator proposes; the reviewer decides.

## 5. Row schema for accepted mappings

Every row, whether accepted or rejected, carries at minimum:

- ri_a, term_label_a, term_uri_a
- ri_b, term_label_b, term_uri_b
- relation (one of the five, or "rejected")
- evidence_basis (uri | uri_and_label | label_fallback)
- evidence_text (human sentence, one line, cites the URI or label used)
- checked_by
- checked_at

term_uri_a and term_uri_b carry the URI when one exists and are blank when it does not. Label and URI are separate columns everywhere; there is no combined column. For label_fallback rows where a URI exists but was not the evidence, the URI still goes in term_uri_a / term_uri_b, and evidence_text says the mapping rests on the label, not the URI.

No row exists without evidence_text. No row exists without checked_by. Rejected rows carry relation = "rejected" and say why in evidence_text.

## 6. Evidence basis

Three values, reported separately, never pooled:

- uri: both sides have URIs, and the mapping follows from the URIs themselves (identical, or EnvThes/NERC published a skos relation between them). Strongest evidence.
- uri_and_label: URI candidate confirmed by matching labels; typical of ACTRIS, where URI is supplied from ACTRIS vocab by label match. Middle evidence.
- label_fallback: at least one side has no URI, or URIs are absent; mapping rests on label plus human judgement. Typical of ICOS, where most terms carry no NERC P07 closeMatch. Weakest.

For label_fallback rows, always record both the term label and the raw source URI in separate columns, and say in evidence_text that the URI is recorded but is not the evidence. The URI remains traceable; the label and the human judgement are what carries the mapping.

Reporting: URI-based mappings (uri + uri_and_label) and label_fallback are always shown in separate columns in every result table. Coverage on URI-based mappings and on label_fallback is reported as two numbers, never as a single pooled figure.

## 7. Coverage expectations (stated as results, not commitments)

- ICOS: 4 of 124 concept URIs have a NERC P07 skos:closeMatch. Most ICOS mappings will be label_fallback. This is a coverage fact, not a failure.
- ACTRIS: 393 of 400 terms match ACTRIS vocab by label, so URIs can be supplied but the match is label-based. These rows are uri_and_label, not pure uri.
- DEIMS: 315 of 317 URIs resolve in EnvThes. Cleanest side; most DEIMS mappings are uri.
- ACTRIS has zero soil terms in the Finnish records (PR #5). Soil comparison is ICOS–DEIMS only.
- 5 EnvThes URIs carry different labels across DEIMS sites. The mapping uses EnvThes prefLabel as authoritative; the DEIMS variant is recorded in evidence_text.
- 6 of 317 DEIMS URIs are deprecated, 4 with replacements. A deprecated URI is mapped with a note in evidence_text; the replacement is not auto-followed.

## 8. Decision procedure

For each proposed candidate:

1. Reviewer opens the row's evidence_text and, if needed, the source URI.
2. Reviewer picks one relation from the five, or marks the pair "rejected" (evidence_text says why), or marks "unclear" and excludes it (same convention as station labels: same_place is empty, row is counted, not scored).
3. Reviewer writes evidence_basis and fills checked_by / checked_at.
4. No automated step picks a relation. No LLM proposes or selects a relation. If an LLM is used as a reading aid (e.g. to summarise an EnvThes definition), its output is not written to the mapping file.

Rejected pairs are kept in the file (relation = "rejected"), not dropped. Without them the denominator is lost, which is the same lesson as the station labels.

## 9. Reporting (not precision)

Precision is not computed. There is no independent reference for the hand mappings; the hand mappings are the ground truth. A precision figure would need a separate reference, such as a relation that the source vocabularies publish themselves (EnvThes to EnvThes, or ACTRIS vocab to ACTRIS vocab). If such a reference exists, it becomes a separate small exercise; not part of this plan.

What is reported:

- Counts by relation (exactMatch / closeMatch / broadMatch / narrowMatch / relatedMatch / rejected / unclear).
- Counts by evidence_basis (uri / uri_and_label / label_fallback), per RI pair.
- Coverage: terms mapped / terms in the reviewed scope, per RI and per RI pair.
- URI-based coverage and label_fallback coverage, always in separate columns, never pooled.
- No acceptance threshold is set in this plan. The threshold is decided before execution, using the coverage numbers this plan will produce.

## 10. Deliverables when execution starts

- outputs/dictionary_mapping_plan.md (this document)
- outputs/dictionary_scope_reviewed.csv (the hand-reviewed scope list from section 4)
- outputs/dictionary_mapping_finland.csv (the mapping table, hand-filled)
- outputs/dictionary_mapping_finland_summary.md (counts and coverage as in section 9)
- A methods paragraph in the thesis stating the five relations, the three evidence_basis values, the hand-decision rule, the weaker-wins ambiguity rule, and why URI-based and label_fallback results are reported separately.

## 11. Out of scope

- RIs other than ICOS, ACTRIS, DEIMS
- Domains other than meteorology and soil
- Measurement units, calibration, or value harmonisation
- Automated mapping or LLM relation choice
- Cross-RI observation data comparison
- The station-level crosswalk (separate deliverable, already done)

## 12. Output format

CSV as the default. A SKOS Turtle export can be added later if Allan says the dictionary should be published as a formal vocabulary. This is the same output-format question already open for milestone #4; waiting on Allan.

## 13. Blocking verifications before execution

- ~~SKOS Reference direction check~~ — done. Verified against https://www.w3.org/TR/skos-reference/#mapping on [date]. The specification's own Example 51 (Section 10.5) and S43 (Section 10.3) confirm the direction used in Section 3. Quoted by Ali from the live page; not fetched by project tools.
- Random seed for the pass-2 sample (Section 4): record seed and sample size in the reviewed-scope summary.
- Hand review of scope_candidate (Section 4), both passes.
- Candidate count under the 200 cap after the hand review.
- Output format decided (Section 12).

## 14. Timeline

Plan only. No execution timeline until #8 completes and this plan is reviewed and accepted.