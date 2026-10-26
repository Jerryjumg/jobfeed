#!/usr/bin/env python3
"""jdfit: turn a job description into a structured fit assessment.

Reads one or more job descriptions (plain text), finds the skills they ask for,
compares them against my own skills profile, and prints a report with:

  * a verdict (Strong / Okay / Stretch, or Skip / Too senior)
  * required vs preferred skills, each with the line of the JD it came from
  * true gaps (skills I do not have, so they must NOT go on a resume)
  * resume gaps (skills I have that this resume does not mention yet)
  * unrecognized terms, so the taxonomy can be extended over time

Standard library only. PDF resumes need `pdftotext` (poppler) or `pypdf`.

Usage:
    python jdfit.py examples/jd_automation_analyst.txt
    python jdfit.py jds/*.txt --resume my_resume.pdf
    python jdfit.py jd.txt --json > report.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------
# Order matters: "Preferred Qualifications" must be classified as preferred
# before the generic "qualification" keyword claims it as required.
HEADING_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("preferred", ("preferred", "nice to have", "nice-to-have", "bonus", "desired",
                   "extra credit", "pluses", "a plus")),
    ("ignore", ("benefit", "perks", "about us", "who we are", "about the company",
                "compensation", "salary", "pay range", "equal opportunity", "eeo",
                "why join", "why work", "our values", "life at")),
    ("required", ("requirement", "qualification", "must have", "must-have",
                  "what you'll need", "what you need", "what we're looking for",
                  "what we are looking for", "who you are", "you have", "you bring",
                  "skills", "experience", "minimum", "basic")),
    ("context", ("responsibilit", "what you'll do", "what you will do", "the role",
                 "about the role", "day to day", "duties", "your impact", "the job",
                 "overview", "summary")),
]

INLINE_PREFERRED = re.compile(
    r"\b(preferred|a plus|nice to have|bonus|desired|ideally|is a plus|are a plus)\b", re.I)

YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|to|–)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)\b", re.I)

BUCKET_WEIGHT = {"required": 3, "preferred": 1, "context": 1}
BUCKET_RANK = {"required": 3, "preferred": 2, "context": 1}


def classify_heading(line: str) -> str | None:
    """Return a bucket name if this line looks like a section heading, else None."""
    raw = line.strip()
    if re.match(r"^(?:[-•]|\*\s|\d+[.)]\s)", raw):
        return None  # bullet points are content, not headings
    text = raw.strip("#*_:-• ").strip()
    words = text.split()
    if not text or len(text) > 60 or len(words) > 8 or re.search(r"\d", text):
        return None
    if text.endswith((".", ",", ";")):
        return None
    # Needs a heading "shape": markdown/colon marker, ALL CAPS, Title Case, or very short.
    # Otherwise an unbulleted line like "Experience with Python and SQL" would
    # be mistaken for a heading.
    title_case = all(w[0].isupper() for w in words if len(w) > 3 and w[0].isalpha())
    shaped = (raw.startswith(("#", "**")) or raw.endswith(":") or text.isupper()
              or title_case or len(words) <= 3)
    if not shaped:
        return None
    lower = text.lower()
    for bucket, keywords in HEADING_RULES:
        if any(k in lower for k in keywords):
            return bucket
    return None


def split_sections(jd_text: str) -> tuple[list[tuple[str, str]], bool]:
    """Tag every non-empty line with a bucket.

    Returns (lines, found_requirement_headings). Lines before any heading are
    'context'. If the JD has no required/preferred headings at all, the caller
    treats context as required, since there is nothing better to go on.
    """
    tagged: list[tuple[str, str]] = []
    bucket = "context"
    found = False
    for raw in jd_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = classify_heading(line)
        if heading:
            bucket = heading
            found = found or heading in ("required", "preferred")
            continue
        if bucket == "ignore":
            continue
        line_bucket = bucket
        if bucket == "required" and INLINE_PREFERRED.search(line):
            line_bucket = "preferred"
        tagged.append((line_bucket, line))
    return tagged, found


# ---------------------------------------------------------------------------
# Skill matching
# ---------------------------------------------------------------------------
def compile_taxonomy(taxonomy: dict) -> dict[str, list[re.Pattern]]:
    patterns: dict[str, list[re.Pattern]] = {}
    for name, spec in taxonomy.items():
        if name.startswith("_"):
            continue
        compiled = []
        for alias in spec["aliases"]:
            # case_sensitive only applies to aliases written with a capital letter,
            # so "Swift" stays strict while "manufacturing execution system" does not.
            strict = spec.get("case_sensitive") and any(c.isupper() for c in alias)
            flags = 0 if strict else re.I
            if alias.startswith("re:"):
                compiled.append(re.compile(alias[3:], flags))
            else:
                # Custom boundaries so "C#", "C++", "Node.js" and ".NET" work,
                # and "Java" does not match inside "JavaScript".
                compiled.append(re.compile(
                    r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9+#])", flags))
        patterns[name] = compiled
    return patterns


def find_skills(text: str, patterns: dict[str, list[re.Pattern]]) -> set[str]:
    return {name for name, pats in patterns.items() if any(p.search(text) for p in pats)}


def extract_years(tagged: list[tuple[str, str]]) -> int | None:
    """Largest lower-bound 'N years' figure found on a required/context line about experience."""
    best = None
    for bucket, line in tagged:
        low_line = line.lower()
        if "experience" not in low_line:
            continue
        # "Ideally requires a minimum of 6-7 years" reads as preferred but is still a floor.
        if bucket == "preferred" and not re.search(r"\b(minimum|at least|requires?)\b", low_line):
            continue
        for m in YEARS_RE.finditer(line):
            low = int(m.group(1))
            if low > 20:  # "25 years in business" is about the company, not me
                continue
            best = low if best is None else max(best, low)
    return best


ACRONYM_RE = re.compile(r"\b(?:[A-Z]{2,6}|[A-Z][a-z]+[A-Z][A-Za-z]+|[A-Za-z]+\d+[A-Za-z]*)\b")
COMMON_ACRONYMS = {
    "US", "USA", "EEO", "PTO", "HR", "CEO", "CTO", "VP", "OK", "FAQ", "LLC", "INC", "ADA",
    "IT", "UI", "UX", "BS", "BA", "MS", "PHD", "TX", "MA", "CA", "NY", "GA", "TN", "SF",
    "NYC", "AND", "OR", "THE", "ID", "K12", "W2", "B2B", "B2C", "SAAS", "YOE",
}


def unrecognized_terms(tagged: list[tuple[str, str]], patterns: dict[str, list[re.Pattern]],
                       limit: int = 12) -> list[str]:
    """Tech-looking tokens on required/preferred lines that no taxonomy entry covers."""
    seen: dict[str, None] = {}
    for bucket, line in tagged:
        if bucket not in ("required", "preferred"):
            continue
        # Blank out text already explained by the taxonomy, so the "BI" in
        # "Power BI" or the "UA" in "OPC UA" is not reported as unknown.
        for pats in patterns.values():
            for pat in pats:
                line = pat.sub(" ", line)
        for tok in ACRONYM_RE.findall(line):
            if tok.upper() in COMMON_ACRONYMS or tok in seen:
                continue
            seen[tok] = None
    return list(seen)[:limit]


# ---------------------------------------------------------------------------
# Resume text
# ---------------------------------------------------------------------------
def read_resume(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="ignore")
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout
    try:
        from pypdf import PdfReader  # optional dependency
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except ImportError:
        sys.exit("Reading a PDF resume needs `pdftotext` or `pip install pypdf`. "
                 "Alternatively pass a .txt copy of the resume.")


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------
@dataclass
class SkillHit:
    skill: str
    bucket: str          # required | preferred | context
    status: str          # have | learning | gap
    evidence: str        # the JD line that mentioned it
    on_resume: bool | None = None


@dataclass
class Report:
    source: str
    title: str
    verdict: str
    score: float
    years_required: int | None
    red_flags: list[str]
    headings_found: bool
    skills: list[SkillHit] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)


def assess(jd_text: str, profile: dict, patterns: dict[str, list[re.Pattern]],
           resume_text: str | None = None, source: str = "<stdin>") -> Report:
    tagged, headings_found = split_sections(jd_text)
    if not headings_found:
        tagged = [("required" if b == "context" else b, line) for b, line in tagged]

    # Strongest bucket wins: a skill listed under Requirements and again under
    # Responsibilities counts as required. Keep the first line that proves it.
    hits: dict[str, SkillHit] = {}
    have, learning = set(profile["have"]), set(profile.get("learning", []))
    for bucket, line in tagged:
        for skill in sorted(find_skills(line, patterns)):
            prev = hits.get(skill)
            if prev and BUCKET_RANK[prev.bucket] >= BUCKET_RANK[bucket]:
                continue
            status = "have" if skill in have else "learning" if skill in learning else "gap"
            hits[skill] = SkillHit(skill, bucket, status, line[:140])

    if resume_text is not None:
        for hit in hits.values():
            if hit.status == "have":
                hit.on_resume = any(p.search(resume_text) for p in patterns[hit.skill])

    total = sum(BUCKET_WEIGHT[h.bucket] for h in hits.values())
    matched = sum(BUCKET_WEIGHT[h.bucket] for h in hits.values() if h.status == "have")
    score = round(matched / total, 2) if total else 0.0

    lower_jd = jd_text.lower()
    red_flags = [p for p in profile.get("red_flags", []) if p.lower() in lower_jd]
    years = extract_years(tagged)

    if red_flags:
        verdict = "Skip (red flag)"
    elif years is not None and years > profile.get("max_years_required", 99):
        verdict = "Too senior"
    elif not hits:
        verdict = "Unknown (no recognized skills)"
    elif score >= 0.65:
        verdict = "Strong fit"
    elif score >= 0.40:
        verdict = "Okay fit"
    else:
        verdict = "Stretch"

    title = next((line.strip("#* ") for line in jd_text.splitlines() if line.strip()), source)
    order = {"required": 0, "preferred": 1, "context": 2}
    skills = sorted(hits.values(), key=lambda h: (order[h.bucket], h.status != "have", h.skill))
    return Report(source, title[:80], verdict, score, years, red_flags, headings_found,
                  skills, unrecognized_terms(tagged, patterns))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def render_markdown(r: Report, max_years: int | None) -> str:
    out = [f"# {r.title}", f"_Source: {r.source}_", ""]
    out.append(f"**Verdict:** {r.verdict}  |  **Skill match:** {int(r.score * 100)}% (weighted)")
    yrs = f"{r.years_required}+" if r.years_required is not None else "not stated"
    out.append(f"**Years asked:** {yrs}" + (f" (my limit: {max_years})" if max_years is not None else ""))
    out.append(f"**Red flags:** {', '.join(r.red_flags) if r.red_flags else 'none'}")
    if not r.headings_found:
        out.append("> No requirement headings found, so every skill was treated as required.")
    out.append("")

    for bucket, label in (("required", "Required"), ("preferred", "Preferred"),
                          ("context", "Mentioned in responsibilities / intro")):
        rows = [h for h in r.skills if h.bucket == bucket]
        if not rows:
            continue
        have = sum(h.status == "have" for h in rows)
        out += [f"## {label} ({have}/{len(rows)} matched)", "",
                "| Skill | Me | JD evidence |", "|---|---|---|"]
        for h in rows:
            me = {"have": "yes", "learning": "learning", "gap": "no"}[h.status]
            evidence = h.evidence.replace("|", "/")
            out.append(f"| {h.skill} | {me} | {evidence} |")
        out.append("")

    gaps = [h.skill for h in r.skills if h.status == "gap" and h.bucket != "context"]
    learning = [h.skill for h in r.skills if h.status == "learning"]
    missing_on_resume = [h.skill for h in r.skills if h.on_resume is False]

    out.append("## What to do with this")
    out.append("")
    out.append("- **True gaps (do not add to resume):** " + (", ".join(gaps) or "none"))
    if learning:
        out.append("- **In progress, mention only once real:** " + ", ".join(learning))
    if any(h.on_resume is not None for h in r.skills):
        out.append("- **I have these but this resume does not say so:** "
                   + (", ".join(missing_on_resume) or "none, resume covers everything I have"))
    if r.unrecognized:
        out.append("- **Terms the taxonomy does not know yet (review, maybe add):** "
                   + ", ".join(r.unrecognized))
    out.append("")
    return "\n".join(out)


def render_summary(reports: list[Report]) -> str:
    out = ["# Summary", "", "| Match | Verdict | Years | Job | Source |", "|---|---|---|---|---|"]
    for r in sorted(reports, key=lambda r: r.score, reverse=True):
        yrs = f"{r.years_required}+" if r.years_required is not None else "-"
        out.append(f"| {int(r.score * 100)}% | {r.verdict} | {yrs} | {r.title} | {r.source} |")
    return "\n".join(out) + "\n"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Structured fit assessment for job descriptions.")
    ap.add_argument("jd", nargs="*", help="JD text file(s). Reads stdin if none given.")
    ap.add_argument("--profile", type=Path, default=HERE / "profile.json" if (HERE / "profile.json").exists() else HERE / "profile.example.json")
    ap.add_argument("--taxonomy", type=Path, default=HERE / "taxonomy.json")
    ap.add_argument("--resume", type=Path, help="Resume (.pdf or .txt) to check for missing skills.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    args = ap.parse_args(argv)

    profile = load_json(args.profile)
    patterns = compile_taxonomy(load_json(args.taxonomy))
    unknown = set(profile["have"]) | set(profile.get("learning", []))
    unknown -= set(patterns)
    if unknown:
        # Catch typos early: a misspelled profile skill silently never matches.
        print(f"warning: profile skills not in taxonomy: {', '.join(sorted(unknown))}", file=sys.stderr)

    resume_text = read_resume(args.resume) if args.resume else None
    sources = [(p, Path(p).read_text(encoding="utf-8", errors="ignore")) for p in args.jd]
    if not sources:
        sources = [("<stdin>", sys.stdin.read())]

    reports = [assess(text, profile, patterns, resume_text, src) for src, text in sources]

    if args.json:
        print(json.dumps([asdict(r) for r in reports], indent=2))
        return 0
    if len(reports) > 1:
        print(render_summary(reports))
    for r in reports:
        print(render_markdown(r, profile.get("max_years_required")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
