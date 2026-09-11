# KRINEIA.md — hummbl-clp

**krineia_manifest_version:** 0.1
**schema:** krineia-manifest@0.1

This is the repo-local KRINEIA manifest for `hummbl-io/hummbl-clp`. It declares how this repo participates in KRINEIA governance.

---
krineia_manifest_version: "0.1"
schema: "krineia-manifest@0.1"

repo:
  full_name: "hummbl-io/hummbl-clp"
  default_branch: "master"
  visibility: "public"

authority:
  steward: "HUMMBL Research Institute"
  approving_human: "Reuben Bowlby"
  source_of_record: "git"
  receipt_authority: "external_observer"

governance_profile:
  status: "adopted"
  krineia_required: true
  trust_root_mode: "deployment_asserted"
  receipt_chain_required_for:
    - "canonical_docs"
    - "schema_changes"
    - "validator_changes"
    - "agent_handoffs"
    - "authority_changes"
    - "release_tags"

chains:
  primary:
    chain_id: "hummbl-clp-primary"
    storage: "_receipts/krineia/primary.jsonl"
    genesis_policy: "repo_bootstrap"
    hash_algorithm: "sha256"
    canonicalization: "json.dumps(sort_keys=True,separators=(',',':'))"

operators:
  allowed:
    - "append"
    - "project"
    - "cut"
  forbidden:
    - "update"
    - "delete"
    - "rewrite"
    - "summarize_and_replace"
    - "score_and_train"

boundaries:
  no_reward_path_self_reference: true
  external_analysis_only: true
  observed_agent_may_write_receipts: false
  receipts_may_train_agents: false

verification:
  validator: "external"
  required_before_merge: false
  required_before_release: true

related_docs:
  readme: "README.md"
  agents: "AGENTS.md"
  constitution: "CONSTITUTION.md"

last_reviewed: "2026-08-23"
---

## Notes

### Chain bootstrapping

The primary chain at `_receipts/krineia/primary.jsonl` is bootstrapped with a genesis receipt recording the adoption of this manifest.

### Extraction status

This repo is an extraction lane from founder-mode services. KRINEIA receipts track the decoupling milestones as core modules are separated from coupled extensions. The receipt chain provides provenance for each extraction step.
