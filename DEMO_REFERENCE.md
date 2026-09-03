# Demo Q&A Reference — rehearsed fallback

Six questions with real, already-verified answers and citations, pulled
directly from `query_log.db`'s actual logged `/ask` calls (not re-run —
compiled with zero new Gemini API calls, to preserve free-tier quota).
Each answer below was independently reproduced across multiple real calls
today with consistent figures and citations.

If live generation is degraded or rate-limited during the interview,
these are safe to ask (or to describe verbatim if a live call can't be
made) since the exact output is already known-good.

## 1. Cross-year revenue comparison

**Ask:** "How did Tata Steel's revenue from operations change between
FY2023-24 and FY2024-25?"

**Expected answer:**
> Between FY2023-24 and FY2024-25, Tata Steel's revenue changed as follows:
> Consolidated Revenue decreased from ₹2,29,170.78 crore in FY2023-24 to
> ₹2,18,542.51 crore in FY2024-25. In India, revenue decreased from
> ₹1,34,248.75 crore to ₹1,26,360.05 crore, and Outside India revenue
> decreased from ₹94,922.03 crore to ₹92,182.46 crore. Standalone Total
> Revenue decreased from ₹1,40,932.65 crore in FY2023-24 to ₹1,32,516.66
> crore in FY2024-25.

**Citation:** tata-steel-fy2025.pdf, page 72.

## 2. `fiscal_year` filter demo

**Ask:** "What was the revenue from operations?" — with the `fiscal_year`
parameter set to `FY2022-23` (demonstrates the hard-filter feature, not
just retrieval).

**Expected answer:**
> Total revenue from operations was ₹1,29,007 crore in FY2022-23 (compared
> to ₹1,29,021 crore in FY2021-22). Breakdown: Sale of products ₹1,25,565
> crore, Sale of power and water ₹1,902 crore, Other operating revenue
> ₹1,540 crore. NINL contributed ₹1,645.55 crore and SFML contributed
> ₹28.42 crore to revenue from operations from their respective
> acquisition dates.

**Citations:** tata-steel-fy2023.pdf, pages 212, 539, 537.

## 3. General company overview

**Ask:** "What is Tata Steel?"

**Expected answer:**
> Tata Steel is one of the largest integrated steel manufacturers in the
> world and one of the most geographically diversified steel companies
> globally. It has manufacturing operations in India, the Netherlands, the
> United Kingdom, and Thailand, raw material resources in India and
> Canada, as well as downstream presence in the United States, France,
> Germany, and other countries.

**Citations:** tata-steel-fy2023.pdf page 7; tata-steel-fy2024.pdf page 80.

## 4. Single-year revenue figure

**Ask:** "What was Tata Steel's revenue from operations in FY2024-25?"

**Expected answer:**
> In FY2024-25, Tata Steel's total consolidated revenue was ₹2,18,542.51
> crore (also mentioned as ₹2,18,543 crore). On a standalone basis, Tata
> Steel's total revenue in FY2024-25 was ₹1,32,516.66 crore.

**Citations:** tata-steel-fy2025.pdf, pages 72 and 16.

## 5. Correct refusal (out-of-scope query)

**Ask:** "What was Tata Steel's profit in FY2019-20?"

**Expected answer:** `not found in the provided documents` (`found: false`,
no citations). Reproduced identically across every real run today — this
is the intended, correct behavior for a question outside the 3 indexed
fiscal years, not a bug. Good to demo deliberately to show the system
refuses rather than fabricates.

## 6. Known limitation — avoid, or use deliberately to discuss the tradeoff

**Ask (with caution):** "What was Tata Steel's Property, Plant and
Equipment as at March 31, 2025?"

**What actually happens:** `not found in the provided documents` — every
time, reproduced consistently. The correct figure (₹93,203.83 crore, per
the Balance Sheet on page 280 of tata-steel-fy2025.pdf, confirmed manually
during Day 1 review) exists in the corpus but isn't retrieved: a single
dense/sparse vector for an 83-row table dilutes relevance for any one line
item below what the retriever's top-k can reach. See CLAUDE.md's "Known
limitations" section for what was tried and why it's an accepted,
documented gap rather than a live bug.

**Recommendation:** don't ask this live unless you want to walk through
the retrieval-dilution tradeoff as a talking point — the system's refusal
here is itself evidence it doesn't fabricate under an accepted limitation,
which can be a reasonable thing to show deliberately.
