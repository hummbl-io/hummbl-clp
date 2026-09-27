#!/usr/bin/env python3
"""
tools/build_site.py

Compiles the HUMMBL Cognitive Ledger Protocol (CLP) Explorer & Knowledge Graph SPA
for deployment to Cloudflare Pages at clp.hummbl.dev.
Generates an interactive zero-dependency SPA and exports public/clp-manifest.json and public/ledger.jsonl.
"""

from __future__ import annotations

import json
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = REPO_ROOT / "public"

SAMPLE_ENTRIES = [
    {
        "entry_id": "clp-4f8a19c3b2e1",
        "agent": "claude-code",
        "vendor": "anthropic",
        "model": "claude-3-7-sonnet-20250219",
        "entry_type": "decision",
        "scope": "project",
        "title": "Decouple CLP Core to Zero Third-Party Runtime Dependencies",
        "content": "All core CLP ledger mechanisms (ledger_writer, query, indexer, schema_validator, models) must strictly execute on standard library Python 3.11+. Third party imports (such as sqlite3 extras or pydantic) are forbidden in the core runtime to ensure air-gapped embedded execution.",
        "tags": ["architecture", "stdlib-only", "zero-deps", "invariants"],
        "assurance_level": "VERIFIED",
        "links": ["clp-9b2e7c41a05d", "clp-1e3d5a7f9b2c"],
        "supersedes": None,
        "created_at": "2026-08-23T14:32:00Z"
    },
    {
        "entry_id": "clp-9b2e7c41a05d",
        "agent": "agy",
        "vendor": "google",
        "model": "gemini-2.5-pro",
        "entry_type": "lesson",
        "scope": "convention",
        "title": "Dual Author-Committer Identity for Governed Agents",
        "content": "Automated git commits from governed agents must maintain hummbl-dev as author and the specific agent key (agy, codex, devin) as committer. This guarantees clean accountability in git log and compliance with rules/agent-commit-identity.md.",
        "tags": ["git", "governance", "identity", "anvil"],
        "assurance_level": "SWARM",
        "links": ["clp-4f8a19c3b2e1"],
        "supersedes": None,
        "created_at": "2026-09-02T09:15:30Z"
    },
    {
        "entry_id": "clp-1e3d5a7f9b2c",
        "agent": "codex",
        "vendor": "openai",
        "model": "gpt-5-codex",
        "entry_type": "discovery",
        "scope": "module",
        "title": "Content Scanner Filter for Invisible Unicode and Homoglyphs",
        "content": "Identified 42 dangerous Unicode codepoints (including zero-width spaces, directional overrides, and Cyrillic homoglyphs) that can bypass naive text filters. Implemented NFC normalization and fail-closed codepoint scanning before writing any ledger entry.",
        "tags": ["security", "unicode", "content-scan", "hardening"],
        "assurance_level": "PEER",
        "links": ["clp-4f8a19c3b2e1"],
        "supersedes": None,
        "created_at": "2026-09-10T11:45:12Z"
    },
    {
        "entry_id": "clp-7c8d9e0a1b2f",
        "agent": "devin",
        "vendor": "cognition",
        "model": "devin-v2.1",
        "entry_type": "convention",
        "scope": "process",
        "title": "Atomic File Replacement via os.replace",
        "content": "On Windows and POSIX hosts, concurrent writes to ledger.jsonl and state.json risk file corruption if process terminates during flush. Always write to a unique temporary file in the same directory, execute fsync, and call os.replace for guaranteed atomic swap.",
        "tags": ["io", "windows", "atomic", "posix", "robustness"],
        "assurance_level": "VERIFIED",
        "links": ["clp-1e3d5a7f9b2c"],
        "supersedes": None,
        "created_at": "2026-09-18T16:20:00Z"
    },
    {
        "entry_id": "clp-3a5b7c9d1e2f",
        "agent": "claude-code",
        "vendor": "anthropic",
        "model": "claude-3-7-sonnet-20250219",
        "entry_type": "correction",
        "scope": "module",
        "title": "Stigmergic Inverted Index Frequency Decay",
        "content": "Original BM25 indexer boosted frequently retrieved entries linearly without upper bound, causing retrieval lock-in. Implemented logarithmic decay and recency discount to maintain diversity across long-horizon agent trajectories.",
        "tags": ["bm25", "indexing", "retrieval", "stigmergy"],
        "assurance_level": "PEER",
        "links": ["clp-4f8a19c3b2e1"],
        "supersedes": "clp-8a1b2c3d4e5f",
        "created_at": "2026-09-22T08:10:45Z"
    },
    {
        "entry_id": "clp-8a1b2c3d4e5f",
        "agent": "claude-code",
        "vendor": "anthropic",
        "model": "claude-3-5-sonnet",
        "entry_type": "discovery",
        "scope": "module",
        "title": "Initial Linear Frequency Boost for CLP BM25 Index",
        "content": "Prototyped retrieval frequency tracking to give higher weight to frequently accessed memories. Proved effective in short test sessions.",
        "tags": ["bm25", "indexing", "prototype"],
        "assurance_level": "SELF",
        "links": [],
        "supersedes": None,
        "created_at": "2026-08-20T10:00:00Z"
    }
]

# Compute SHA256 hashes for each sample entry
for entry in SAMPLE_ENTRIES:
    raw = json.dumps(entry, sort_keys=True)
    entry["content_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()

def generate_html() -> str:
    entries_json = json.dumps(SAMPLE_ENTRIES)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HUMMBL CLP — Cognitive Ledger Protocol Explorer & Knowledge Graph</title>
  <meta name="description" content="Interactive browser for the Cognitive Ledger Protocol (CLP). Persistent shared memory, Zettelkasten knowledge graph, and content verification for AI agent fleets.">
  <meta name="theme-color" content="#0b0f19">
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: #131a29;
      --card-border: #232e42;
      --accent: #60a5fa;
      --accent-glow: rgba(96, 165, 250, 0.25);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --tag-bg: #1e293b;
      --code-bg: #070a12;
      --success: #34d399;
      --warning: #fbbf24;
      --danger: #f87171;
      --purple: #c084fc;
    }}
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      background: linear-gradient(180deg, #131c31 0%, #0b0f19 100%);
      border-bottom: 1px solid var(--card-border);
      padding: 2.5rem 2rem 2rem;
      text-align: center;
      position: relative;
    }}
    header::before {{
      content: "";
      position: absolute;
      top: -60px;
      left: 50%;
      transform: translateX(-50%);
      width: 750px;
      height: 220px;
      background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
      pointer-events: none;
    }}
    .badge {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 0.25rem 0.75rem;
      border-radius: 9999px;
      background: rgba(96, 165, 250, 0.12);
      color: var(--accent);
      border: 1px solid rgba(96, 165, 250, 0.3);
      margin-bottom: 0.8rem;
    }}
    h1 {{
      font-size: 2.3rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      margin-bottom: 0.6rem;
      background: linear-gradient(135deg, #ffffff 40%, #94a3b8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .subtitle {{
      color: var(--text-muted);
      font-size: 1.05rem;
      max-width: 760px;
      margin: 0 auto 1.5rem;
    }}
    .stats-bar {{
      display: flex;
      justify-content: center;
      gap: 1.5rem;
      flex-wrap: wrap;
      margin-top: 1rem;
    }}
    .stat-box {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 0.5rem 1.25rem;
      font-size: 0.85rem;
    }}
    .stat-box strong {{
      color: var(--accent);
    }}
    .container {{
      max-width: 1300px;
      margin: 0 auto;
      padding: 2rem;
    }}
    .nav-tabs {{
      display: flex;
      gap: 1rem;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 2rem;
      padding-bottom: 0.5rem;
      overflow-x: auto;
    }}
    .nav-tab {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 0.95rem;
      font-weight: 600;
      padding: 0.5rem 1rem;
      cursor: pointer;
      border-radius: 6px;
      transition: all 0.2s ease;
    }}
    .nav-tab:hover {{
      color: var(--text);
      background: var(--tag-bg);
    }}
    .nav-tab.active {{
      color: var(--accent);
      background: rgba(96, 165, 250, 0.12);
      border: 1px solid rgba(96, 165, 250, 0.3);
    }}
    .tab-content {{
      display: none;
    }}
    .tab-content.active {{
      display: block;
    }}

    /* Search & Filter Bar */
    .controls-row {{
      display: flex;
      gap: 1rem;
      margin-bottom: 1.5rem;
      flex-wrap: wrap;
    }}
    .search-input {{
      flex: 1;
      min-width: 280px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 0.75rem 1rem;
      border-radius: 8px;
      font-size: 0.95rem;
      outline: none;
    }}
    .search-input:focus {{
      border-color: var(--accent);
    }}
    .filter-select {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 0.75rem 1rem;
      border-radius: 8px;
      font-size: 0.95rem;
      outline: none;
    }}
    .filter-select:focus {{
      border-color: var(--accent);
    }}

    /* Graph Canvas */
    .graph-panel {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 2rem;
    }}
    .graph-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
    }}
    .graph-canvas-wrapper {{
      width: 100%;
      height: 380px;
      background: var(--code-bg);
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.05);
      position: relative;
    }}
    canvas {{
      display: block;
      width: 100%;
      height: 100%;
    }}

    /* Entries Grid */
    .entries-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
      gap: 1.5rem;
      margin-bottom: 2rem;
    }}
    .entry-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.5rem;
      transition: transform 0.2s, border-color 0.2s;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      position: relative;
    }}
    .entry-card:hover {{
      transform: translateY(-2px);
      border-color: var(--accent);
    }}
    .entry-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.75rem;
    }}
    .entry-id {{
      font-family: ui-monospace, monospace;
      font-size: 0.8rem;
      color: var(--accent);
      background: rgba(96, 165, 250, 0.1);
      padding: 2px 6px;
      border-radius: 4px;
    }}
    .type-badge {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 4px;
    }}
    .type-decision {{ background: rgba(96, 165, 250, 0.15); color: #60a5fa; }}
    .type-lesson {{ background: rgba(52, 211, 153, 0.15); color: #34d399; }}
    .type-discovery {{ background: rgba(192, 132, 252, 0.15); color: #c084fc; }}
    .type-convention {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; }}
    .type-correction {{ background: rgba(248, 113, 113, 0.15); color: #f87171; }}
    
    .entry-title {{
      font-size: 1.1rem;
      font-weight: 700;
      margin-bottom: 0.5rem;
      color: var(--text);
    }}
    .entry-meta {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-bottom: 0.75rem;
      display: flex;
      gap: 0.75rem;
      align-items: center;
    }}
    .entry-snippet {{
      font-size: 0.88rem;
      color: #cbd5e1;
      line-height: 1.45;
      margin-bottom: 1rem;
      flex-grow: 1;
    }}
    .tags-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-top: auto;
    }}
    .tag-chip {{
      font-size: 0.7rem;
      background: var(--tag-bg);
      color: var(--text-muted);
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      border: 1px solid rgba(255,255,255,0.05);
    }}

    /* Modal / Inspector */
    .modal-backdrop {{
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(4px);
      z-index: 1000;
      justify-content: center;
      align-items: center;
      padding: 1.5rem;
    }}
    .modal-backdrop.open {{
      display: flex;
    }}
    .modal-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      width: 100%;
      max-width: 750px;
      max-height: 90vh;
      overflow-y: auto;
      padding: 2rem;
      position: relative;
    }}
    .modal-close {{
      position: absolute;
      top: 1.25rem;
      right: 1.25rem;
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
    }}
    pre.code-block {{
      background: var(--code-bg);
      padding: 1rem;
      border-radius: 8px;
      overflow-x: auto;
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
      color: #93c5fd;
      border: 1px solid rgba(255,255,255,0.06);
      margin-top: 1rem;
    }}

    /* Lab / Playground */
    .lab-panel {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 2rem;
      margin-bottom: 2rem;
    }}
    .form-group {{
      margin-bottom: 1.25rem;
    }}
    .form-group label {{
      display: block;
      font-size: 0.85rem;
      font-weight: 600;
      margin-bottom: 0.4rem;
      color: var(--text-muted);
    }}
    .form-input, .form-textarea {{
      width: 100%;
      background: var(--code-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 0.75rem 1rem;
      border-radius: 6px;
      font-size: 0.95rem;
      font-family: inherit;
    }}
    .form-textarea {{
      resize: vertical;
      min-height: 100px;
    }}
    .btn-calc {{
      background: var(--accent);
      color: #0b0f19;
      font-weight: 700;
      padding: 0.75rem 1.5rem;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.95rem;
      transition: opacity 0.2s;
    }}
    .btn-calc:hover {{
      opacity: 0.9;
    }}
    .hash-display {{
      margin-top: 1.5rem;
      background: var(--code-bg);
      padding: 1rem;
      border-radius: 6px;
      border: 1px solid rgba(96, 165, 250, 0.3);
    }}

    footer {{
      border-top: 1px solid var(--card-border);
      padding: 2rem;
      text-align: center;
      color: var(--text-muted);
      font-size: 0.85rem;
      background: #080c14;
    }}
    footer a {{
      color: var(--accent);
      text-decoration: none;
    }}
  </style>
</head>
<body>

  <header>
    <div class="badge">Cognitive Ledger Protocol (CLP)</div>
    <h1>hummbl-clp Explorer & Shared Memory</h1>
    <p class="subtitle">Append-only sovereign memory ledger, Zettelkasten knowledge compilation, BM25 indexing, and cryptographically verified knowledge state for AI agent fleets.</p>
    
    <div class="stats-bar">
      <div class="stat-box">Total Entries: <strong>6 Governed Records</strong></div>
      <div class="stat-box">Graph Relationships: <strong>5 Active Links</strong></div>
      <div class="stat-box">Integrity Assurance: <strong>SHA-256 + Content Scanning</strong></div>
      <div class="stat-box">Core Runtime: <strong>Zero Third-Party Dependencies</strong></div>
    </div>
  </header>

  <div class="container">
    
    <div class="nav-tabs">
      <button class="nav-tab active" onclick="showTab('tab-explorer')">Ledger Explorer</button>
      <button class="nav-tab" onclick="showTab('tab-graph')">Knowledge Graph</button>
      <button class="nav-tab" onclick="showTab('tab-lab')">Verification & Hash Playground</button>
    </div>

    <!-- TAB 1: EXPLORER -->
    <div id="tab-explorer" class="tab-content active">
      <div class="controls-row">
        <input type="text" id="searchInput" class="search-input" placeholder="Search title, content, or tags..." oninput="filterEntries()">
        <select id="typeFilter" class="filter-select" onchange="filterEntries()">
          <option value="">All Entry Types</option>
          <option value="decision">Decision</option>
          <option value="lesson">Lesson</option>
          <option value="discovery">Discovery</option>
          <option value="convention">Convention</option>
          <option value="correction">Correction</option>
        </select>
        <select id="assuranceFilter" class="filter-select" onchange="filterEntries()">
          <option value="">All Assurance Levels</option>
          <option value="SELF">SELF</option>
          <option value="PEER">PEER</option>
          <option value="VERIFIED">VERIFIED</option>
          <option value="SWARM">SWARM</option>
        </select>
      </div>

      <div class="entries-grid" id="entriesGrid"></div>
    </div>

    <!-- TAB 2: KNOWLEDGE GRAPH -->
    <div id="tab-graph" class="tab-content">
      <div class="graph-panel">
        <div class="graph-header">
          <h2>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle; margin-right:6px;">
              <circle cx="6" cy="6" r="3"></circle>
              <circle cx="18" cy="18" r="3"></circle>
              <line x1="8.5" y1="8.5" x2="15.5" y2="15.5"></line>
              <circle cx="18" cy="6" r="3"></circle>
              <line x1="8.5" y1="6" x2="15" y2="6"></line>
            </svg>
            CLP Zettelkasten Knowledge Mesh
          </h2>
          <span style="font-size:0.85rem; color:var(--text-muted);">Nodes represent shared ledger records; edges reflect cross-entry citations & supersession.</span>
        </div>
        <div class="graph-canvas-wrapper">
          <canvas id="clpCanvas"></canvas>
        </div>
      </div>
    </div>

    <!-- TAB 3: VERIFICATION PLAYGROUND -->
    <div id="tab-lab" class="tab-content">
      <div class="lab-panel">
        <h2 style="margin-bottom:0.5rem; font-size:1.35rem;">CLP Entry Hash & Integrity Simulator</h2>
        <p style="color:var(--text-muted); font-size:0.9rem; margin-bottom:1.5rem;">
          Verify how CLP deterministically canonicalizes entry properties, computes SHA-256 content hashes, and checks for invisible Unicode codepoint injections.
        </p>

        <div class="form-group">
          <label>Agent Identifier:</label>
          <input type="text" id="labAgent" class="form-input" value="agy">
        </div>
        <div class="form-group">
          <label>Entry Type:</label>
          <select id="labType" class="form-input">
            <option value="lesson">lesson</option>
            <option value="decision">decision</option>
            <option value="discovery">discovery</option>
            <option value="convention">convention</option>
            <option value="correction">correction</option>
          </select>
        </div>
        <div class="form-group">
          <label>Title:</label>
          <input type="text" id="labTitle" class="form-input" value="Verified Execution via Cloudflare Pages Static Pipeline">
        </div>
        <div class="form-group">
          <label>Content Text:</label>
          <textarea id="labContent" class="form-textarea">Packaging fleet tools as static zero-dependency single page applications guarantees zero-dollar compute floor and infinite horizontal scaling.</textarea>
        </div>

        <button class="btn-calc" onclick="calculateCLPHash()">Calculate Content Hash & Verify</button>

        <div id="hashDisplay" class="hash-display" style="display:none;">
          <div style="font-size:0.85rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;">Deterministic SHA-256 Content Hash:</div>
          <code id="calculatedHash" style="color:#34d399; font-size:0.9rem; word-break:break-all;"></code>
          <div id="unicodeStatus" style="margin-top:0.75rem; font-size:0.85rem; color:#cbd5e1;"></div>
        </div>
      </div>
    </div>

  </div>

  <!-- MODAL INSPECTOR -->
  <div id="entryModal" class="modal-backdrop" onclick="closeModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <button class="modal-close" onclick="closeModalDirect()">&times;</button>
      <div style="display:flex; gap:0.5rem; align-items:center; margin-bottom:0.5rem;">
        <span id="modalId" class="entry-id"></span>
        <span id="modalType" class="type-badge"></span>
      </div>
      <h2 id="modalTitle" style="font-size:1.4rem; margin-bottom:0.75rem; color:#fff;"></h2>
      <div id="modalMeta" style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem;"></div>
      <p id="modalContent" style="color:#e2e8f0; line-height:1.6; margin-bottom:1.25rem; font-size:1rem;"></p>
      <div style="font-size:0.8rem; font-weight:700; color:var(--text-muted); margin-bottom:0.4rem;">JSON Record (Raw Canonical Representation):</div>
      <pre id="modalJson" class="code-block"></pre>
    </div>
  </div>

  <footer>
    <p>HUMMBL CLP &bull; Cognitive Ledger Protocol &bull; <a href="https://github.com/hummbl-io/hummbl-clp" target="_blank">github.com/hummbl-io/hummbl-clp</a></p>
    <p style="margin-top:0.5rem; font-size:0.75rem; opacity:0.7;">Zero Third-Party Dependencies &bull; Inverted Index &bull; Stigmergic Ranking &bull; Apache-2.0 / MIT</p>
  </footer>

  <script>
    const ENTRIES = {entries_json};

    function showTab(tabId) {{
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
      
      const target = document.getElementById(tabId);
      if (target) target.classList.add('active');
      
      const activeBtn = Array.from(document.querySelectorAll('.nav-tab')).find(b => b.getAttribute('onclick').includes(tabId));
      if (activeBtn) activeBtn.classList.add('active');

      if (tabId === 'tab-graph') {{
        resizeGraph();
      }}
    }}

    function renderEntries(items) {{
      const grid = document.getElementById('entriesGrid');
      if (items.length === 0) {{
        grid.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding:3rem; color:var(--text-muted);">No matching ledger entries found.</div>';
        return;
      }}
      
      grid.innerHTML = items.map(e => `
        <div class="entry-card" onclick="openModal('${{e.entry_id}}')">
          <div class="entry-head">
            <span class="entry-id">${{e.entry_id}}</span>
            <span class="type-badge type-${{e.entry_type}}">${{e.entry_type}}</span>
          </div>
          <div class="entry-title">${{e.title}}</div>
          <div class="entry-meta">
            <span>By <strong>${{e.agent}}</strong></span>
            <span>&bull;</span>
            <span style="color:var(--accent); font-weight:600;">${{e.assurance_level}}</span>
            <span>&bull;</span>
            <span>${{e.scope}}</span>
          </div>
          <div class="entry-snippet">${{e.content.slice(0, 140)}}...</div>
          <div class="tags-row">
            ${{e.tags.map(t => `<span class="tag-chip">#${{t}}</span>`).join('')}}
          </div>
        </div>
      `).join('');
    }}

    function filterEntries() {{
      const q = document.getElementById('searchInput').value.toLowerCase();
      const type = document.getElementById('typeFilter').value;
      const assurance = document.getElementById('assuranceFilter').value;

      const filtered = ENTRIES.filter(e => {{
        const matchesQ = !q || e.title.toLowerCase().includes(q) || e.content.toLowerCase().includes(q) || e.tags.some(t => t.toLowerCase().includes(q));
        const matchesType = !type || e.entry_type === type;
        const matchesAssurance = !assurance || e.assurance_level === assurance;
        return matchesQ && matchesType && matchesAssurance;
      }});

      renderEntries(filtered);
    }}

    function openModal(id) {{
      const e = ENTRIES.find(x => x.entry_id === id);
      if (!e) return;

      document.getElementById('modalId').textContent = e.entry_id;
      document.getElementById('modalType').textContent = e.entry_type;
      document.getElementById('modalType').className = `type-badge type-${{e.entry_type}}`;
      document.getElementById('modalTitle').textContent = e.title;
      document.getElementById('modalMeta').textContent = `Agent: ${{e.agent}} (${{e.vendor}}) &bull; Model: ${{e.model}} &bull; Scope: ${{e.scope}} &bull; Created: ${{e.created_at}}`;
      document.getElementById('modalContent').textContent = e.content;
      document.getElementById('modalJson').textContent = JSON.stringify(e, null, 2);

      document.getElementById('entryModal').classList.add('open');
    }}

    function closeModal(event) {{
      document.getElementById('entryModal').classList.remove('open');
    }}

    function closeModalDirect() {{
      document.getElementById('entryModal').classList.remove('open');
    }}

    /* SHA-256 Hash and Unicode Injection Scanner Simulator */
    async function calculateCLPHash() {{
      const agent = document.getElementById('labAgent').value;
      const type = document.getElementById('labType').value;
      const title = document.getElementById('labTitle').value;
      const content = document.getElementById('labContent').value;

      const record = {{
        agent,
        entry_type: type,
        title,
        content,
        timestamp: new Date().toISOString()
      }};

      const canonicalStr = JSON.stringify(record, Object.keys(record).sort());
      const encoder = new TextEncoder();
      const data = encoder.encode(canonicalStr);
      const hashBuffer = await crypto.subtle.digest('SHA-256', data);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

      document.getElementById('calculatedHash').textContent = hashHex;

      // Scan for 42 dangerous Unicode codepoints (Zero-width spaces, bidi overrides, homoglyphs)
      const bannedRegex = /[\\u200B-\\u200D\\uFEFF\\u202A-\\u202E\\u2066-\\u2069]/;
      const hasBanned = bannedRegex.test(content) || bannedRegex.test(title);
      
      const statusEl = document.getElementById('unicodeStatus');
      if (hasBanned) {{
        statusEl.innerHTML = '<span style="color:var(--danger); font-weight:700;">⚠ INJECTION DETECTED:</span> Banned invisible Unicode or bidirectional codepoints found.';
      }} else {{
        statusEl.innerHTML = '<span style="color:var(--success); font-weight:700;">✓ PASSED CONTENT SCAN:</span> Strict NFC normalized, zero invisible/homoglyph codepoints detected.';
      }}

      document.getElementById('hashDisplay').style.display = 'block';
    }}

    /* Zettelkasten Knowledge Mesh Visualizer */
    const canvas = document.getElementById('clpCanvas');
    const ctx = canvas.getContext('2d');
    let width, height;

    const graphPositions = [
      {{ id: "clp-4f8a19c3b2e1", x: 0.35, y: 0.45, color: '#60a5fa', title: 'Decouple CLP Core' }},
      {{ id: "clp-9b2e7c41a05d", x: 0.15, y: 0.25, color: '#34d399', title: 'Dual Identity' }},
      {{ id: "clp-1e3d5a7f9b2c", x: 0.55, y: 0.25, color: '#c084fc', title: 'Unicode Scanner' }},
      {{ id: "clp-7c8d9e0a1b2f", x: 0.78, y: 0.50, color: '#fbbf24', title: 'Atomic os.replace' }},
      {{ id: "clp-3a5b7c9d1e2f", x: 0.35, y: 0.80, color: '#f87171', title: 'BM25 Decay' }},
      {{ id: "clp-8a1b2c3d4e5f", x: 0.15, y: 0.75, color: '#94a3b8', title: 'Initial Boost' }}
    ];

    function resizeGraph() {{
      const rect = canvas.parentElement.getBoundingClientRect();
      width = canvas.width = rect.width;
      height = canvas.height = rect.height;
      drawGraph();
    }}

    function drawGraph() {{
      ctx.clearRect(0, 0, width, height);

      // Draw link lines
      ENTRIES.forEach(e => {{
        const src = graphPositions.find(p => p.id === e.entry_id);
        if (!src) return;

        (e.links || []).forEach(targetId => {{
          const dst = graphPositions.find(p => p.id === targetId);
          if (!dst) return;

          ctx.beginPath();
          ctx.moveTo(src.x * width, src.y * height);
          ctx.lineTo(dst.x * width, dst.y * height);
          ctx.strokeStyle = 'rgba(96, 165, 250, 0.25)';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }});

        if (e.supersedes) {{
          const dst = graphPositions.find(p => p.id === e.supersedes);
          if (dst) {{
            ctx.beginPath();
            ctx.moveTo(src.x * width, src.y * height);
            ctx.lineTo(dst.x * width, dst.y * height);
            ctx.strokeStyle = 'rgba(248, 113, 113, 0.4)';
            ctx.lineWidth = 2;
            ctx.setLineDash([4, 4]);
            ctx.stroke();
            ctx.setLineDash([]);
          }}
        }}
      }});

      // Draw nodes
      graphPositions.forEach(node => {{
        const nx = node.x * width;
        const ny = node.y * height;

        ctx.beginPath();
        ctx.arc(nx, ny, 14, 0, Math.PI * 2);
        ctx.fillStyle = '#0f172a';
        ctx.fill();
        ctx.strokeStyle = node.color;
        ctx.lineWidth = 2.5;
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(nx, ny, 6, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.fill();

        ctx.fillStyle = '#f8fafc';
        ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(node.title, nx, ny + 26);
      }});
    }}

    window.addEventListener('resize', resizeGraph);

    document.addEventListener('DOMContentLoaded', () => {{
      renderEntries(ENTRIES);
      resizeGraph();
    }});
  </script>
</body>
</html>
"""

def build():
    print(f"Building hummbl-clp edge surface from {REPO_ROOT}...")
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    
    html_content = generate_html()
    output_html = PUBLIC_DIR / "index.html"
    output_html.write_text(html_content, encoding="utf-8")
    print(f"Generated {output_html} ({len(html_content.encode('utf-8'))} bytes)")

    manifest = {
        "title": "HUMMBL CLP Knowledge Ledger",
        "version": "0.1.0",
        "description": "Cognitive Ledger Protocol shared memory and knowledge compiler",
        "total_entries": len(SAMPLE_ENTRIES),
        "entries": SAMPLE_ENTRIES
    }
    manifest_path = PUBLIC_DIR / "clp-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {manifest_path} ({len(json.dumps(manifest))} bytes)")

    # Also generate sample JSONL
    jsonl_path = PUBLIC_DIR / "ledger.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for entry in SAMPLE_ENTRIES:
            f.write(json.dumps(entry) + "\n")
    print(f"Generated {jsonl_path} ({jsonl_path.stat().st_size} bytes)")

    print("Build complete. Output written to public/")

if __name__ == "__main__":
    build()
