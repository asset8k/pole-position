# Updating FIA regulations

Run `scripts/update_regulations.py` from the project root. It accepts one PDF,
several PDFs, or every PDF directly inside a directory. Download the official
**2026** files yourself; filenames do not need to follow a naming convention.

Before the **first** `--apply`, restart/deploy the backend with this updater's
new version-filter/cache code (or keep the old server stopped during the update).
An older server without the document-ID filter must not serve traffic while
replacement points are being staged into its collection. Do not overwrite the
existing PDF files: put replacements in a separate incoming directory.

```sh
mkdir -p regulations/incoming
# Place downloaded PDFs in regulations/incoming, then preview:
uv run python scripts/update_regulations.py --pdf-dir regulations/incoming

# After reviewing the printed summary and generated artifacts:
uv run python scripts/update_regulations.py --pdf-dir regulations/incoming --apply
```

A single-section update uses exactly the same workflow:

```sh
uv run python scripts/update_regulations.py --pdf "regulations/incoming/section-b.pdf"
uv run python scripts/update_regulations.py --pdf "regulations/incoming/section-b.pdf" --apply
```

## What the command does

1. Checks existing local PDF hashes/page counts and reads each incoming FIA cover:
   section, season, issue, publication date, approval date, and PUBLISHED status.
   SHA-256 and page counts are calculated automatically. Older versions, wrong
   seasons, and multiple input PDFs for one section are rejected.
2. Skips byte-identical PDFs. Copies changed PDFs into `regulations/versions/`
   under immutable, issue-and-hash-based IDs; keeps previous PDFs and artifacts.
3. Runs extraction, normalization, structure/clause parsing, and all three
   chunkers. The updater excludes struck-out revision deletions while retaining
   coloured additions. It checks unique identifiers, text preservation, metadata,
   exact citation pages, and applicable appendix coverage. Unknown appendices or
   unsupported structures require code/policy review rather than silent omission.
   Existing future-year/visual-only appendix exclusions still apply.
4. Writes all five artifact stages and builds the proposed BM25 corpus locally.
   **Without `--apply`, there are no OpenAI/Qdrant calls, no manifest activation,
   and no database writes.** A preview still creates local staged files/reports.
5. With `--apply`, checks the existing Qdrant `dense` cosine collection (1536
   dimensions) and audits the current documents before embedding anything.
   Embeds changed chunks using the existing `text-embedding-3-small` model and
   upserts batches with stable UUIDs. Every payload and vector is audited.
   A failed update can be retried: verified staged points are reused; only missing
   chunks are embedded. This is resumable upserting, not a transaction that rolls
   back paid API calls.
6. Audits the entire proposed corpus, then atomically replaces the working
   manifest. This is the activation boundary: dense search uses its document-ID
   allowlist and BM25 reloads when the manifest changes. Both methods use the same
   snapshot for each chat/evaluation request. Old points are retained but excluded
   from current search. Qdrant `is_active` flags are synced for the dashboard;
   if that sync fails, the report warns, but the manifest filter still protects
   retrieval. Old in-flight requests can finish using their previous snapshot.

PostgreSQL/Supabase users, conversations, and saved citation excerpts are **not
modified**. Old conversations keep the sources originally used for their answers.
The Qdrant dashboard's total now includes archived/staged points: it is not the
active-corpus chunk count.

## Reports, review and rollback

Each invocation creates `artifacts/updates/<run-id>/` with `report.json`,
`manifest.before.json`, and (after successful preparation) `manifest.proposed.json`.
These files, staged artifacts and PDFs are ignored by Git. Back them up separately
if you need rollback after changing machines or deploying elsewhere.

Successful application prints the exact rollback command:

```sh
uv run python scripts/update_regulations.py \
  --restore-manifest "artifacts/updates/<run-id>/manifest.before.json" --apply
```

Rollback audits the old PDFs, chunk artifacts, and Qdrant points before switching
the manifest back. It does not re-embed or delete anything. Do not remove old
artifacts/points if you want rollback to remain possible. Only one updater may
run per project directory; independently deployed copies need operational
coordination, not concurrent updates to the same collection.

Changed bytes with the **same issue number** are rejected by default. Only after
confirming that FIA issued an official corrected PDF, use `--allow-same-issue`.
The hash suffix ensures it cannot overwrite the earlier version's point IDs.

Automated checks are structural/provenance checks, not a legal interpretation
audit. Review changed passages and exclusions. Review `data/eval/questions.json`
for changed source IDs and shifted PDF pages; gold expectations are deliberately
not rewritten automatically. Then rerun retrieval evaluation and live chat checks.

## Deployment

Restart the backend once after deploying the new version-filter/cache code.
Subsequent manifest updates are picked up automatically on the next request.
Run the updater in the backend's actual data filesystem, with `.env` pointing to
the intended Qdrant collection. Updating a local manifest does **not** update a
separately hosted backend's manifest/artifacts: deploy those together, or run the
command on that host with persistent storage. Read-only/ephemeral hosting needs
an appropriate deployment/data-storage workflow.

## October 2026 release

FIA's category listing marks all six entries as published on 1 October, but the
2026 PDF covers identify newer issues only for **B (09), D (08), and F (11)**.
A (03), C (20), and E (06) remain their previous issues. The listing also includes
a 2027 Section C PDF: do not upload it for this 2026 corpus. The updater trusts
cover metadata and content hashes, not the category page's upload date.

Sources: [FIA listing](https://api.fia.com/regulation/category/110),
[PyMuPDF text decoration detection](https://pymupdf.readthedocs.io/en/latest/vars.html#text-collect-styles).
