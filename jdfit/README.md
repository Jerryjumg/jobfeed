# jdfit

A small command-line tool that reads a job description and tells me, in about a second, whether it is worth my time and what my resume is missing.

## The problem

I am job hunting, and every posting I consider gets the same manual treatment. I read it looking for deal-breakers, check how many years of experience it really asks for, pull out the skills, compare them against what I can honestly claim, and then check whether my resume actually says the things I can claim. For a single posting that is several minutes of careful reading. Across dozens of postings a week it is the most repetitive part of my search, and it is error-prone in a specific way: when I am tired I skim, and I either miss a "5+ years" buried in the fourth bullet or I forget that a resume version leaves out a framework I have used.

jdfit does that first pass for me. I still read every posting I apply to. What changed is that I no longer spend the reading time on bookkeeping.

## What it does

```
python jdfit.py examples/jd_ios_engineer.txt --resume my_resume.pdf
```

For each job description it reports:

- **Verdict:** Strong fit, Okay fit, Stretch, Too senior, or Skip (red flag)
- **Required vs preferred skills,** each shown next to the exact line of the posting it came from
- **True gaps:** skills the posting wants that I do not have. These are listed under "do not add to resume" on purpose
- **Resume gaps:** skills I do have that this particular resume does not mention
- **Unrecognized terms:** tech-looking words the tool could not classify, so I know what to add to the taxonomy next

Pass several files and it prints a ranked summary table first:

```
python jdfit.py jds/*.txt
```

| Match | Verdict | Years | Job |
|---|---|---|---|
| 92% | Strong fit | 1+ | iOS Engineer I |
| 82% | Strong fit | 0+ | AI Operations Analyst |
| 43% | Too senior | 5+ | Senior Data Engineer |
| 0% | Skip (red flag) | 2+ | Controls Systems Engineer |

Full sample output is in [`examples/sample_report.md`](examples/sample_report.md) and [`examples/sample_report_with_resume.md`](examples/sample_report_with_resume.md). The four postings in `examples/` are synthetic ones I wrote to cover the cases I care about.

`--json` emits the same data as JSON, so the output can feed a tracker or another script.

## Setup

Python 3.10 or newer. No third-party packages are required. Reading a PDF resume uses `pdftotext` (from poppler) if it is installed, otherwise `pypdf` if available; a `.txt` resume always works.

```
git clone https://github.com/Jerryjumg/jobfeed
cd jobfeed/jdfit
python jdfit.py examples/*.txt
python -m unittest -v
```

To use it for yourself, copy `profile.example.json` to `profile.json` and edit it: list the skills you have, the skills you are learning, the maximum years of experience you are willing to apply for, and any phrases that should make you skip a posting.

## How it works

1. **Split the posting into sections.** Lines are tagged as required, preferred, context (responsibilities and intro), or ignored (benefits, company boilerplate) based on the headings above them. A line under "Requirements" that says "a plus" or "preferred" is moved to preferred.
2. **Match skills against a taxonomy.** `taxonomy.json` maps each canonical skill to its aliases, so "Postgres" and "PostgreSQL" count as the same thing and "VoiceOver" counts as accessibility work.
3. **Compare against my profile.** Each skill is marked have, learning, or gap. If a skill appears in more than one section, the strongest one wins.
4. **Score.** Required skills are weighted 3, preferred and context skills 1. The score is the weighted share I actually have. Red flags and the years-of-experience check override the score.
5. **Check the resume** (optional). For every skill I have that the posting asks for, check whether the resume mentions it.

## Decisions and why

**Deterministic rules instead of an LLM.** I use LLMs every day, and my first instinct was to send the posting to a model and ask for a fit assessment. I decided against it for the core for three reasons. I need to be able to trust a "Skip" without re-reading the posting, and a rule I wrote is something I can audit. The same input must give the same answer, or I cannot compare postings against each other. And the failure I most wanted to avoid is a tool that talks me into claiming a skill I do not have; a lookup table cannot do that. An LLM would be a sensible addition on top, for example to summarize what a team actually does, but not as the thing that decides.

**Every match shows its evidence.** Each skill in the report sits next to the line of the posting that produced it. When the tool is wrong, I can see why in one glance instead of guessing. This mattered more than accuracy while I was building it, because it is how I found most of the bugs.

**"Learning" never counts as a match.** Skills I am studying appear in the report so I know they are relevant, but they add nothing to the score. It would be easy to let them count, and it would make the numbers dishonest.

**Gaps are labeled "do not add to resume."** The point of the report is to tell me what to learn or address in a cover letter, not what to paste into a skills section.

**A hand-maintained taxonomy instead of automatic keyword extraction.** Generic keyword extraction returns words like "team" and "fast-paced". A curated list stays small and precise, and the "unrecognized terms" section tells me when it needs to grow. The list started from the skills in postings I have actually considered; adding a new skill is one line of JSON.

**Standard library only.** It should run on any machine with Python without installing anything, since the whole point is to save time.

## Problems I hit

- **Short words that are also English.** "REST" matched "the rest of the team", "Excel" matched "you excel in ambiguity", and "React" would match "react quickly to incidents" in security postings. The fix was per-skill case sensitivity plus a few targeted patterns (Excel is not a skill when followed by "at" or "in").
- **Names with symbols.** Standard word boundaries fail on `C#`, `C++`, `.NET`, and `Node.js`, and a naive pattern for Java also matches inside JavaScript. The matcher uses custom boundaries instead of `\b`.
- **Case sensitivity cut both ways.** Making "Swift" case-sensitive (to avoid "swift turnaround") initially broke matching because the alias was written in lowercase. Now case sensitivity only applies to aliases that contain a capital letter.
- **Headings vs content.** An unbulleted line like "3+ years of experience" was being read as an "Experience" heading. Headings now need a heading shape (a colon, markdown marker, all caps, Title Case, or three words or fewer) and cannot contain digits.
- **Noise in the unknown-terms list.** "BI" from Power BI and "UA" from OPC UA showed up as unknown. Text already explained by the taxonomy is now removed before looking for unknown terms.

The tests in `test_jdfit.py` cover each of these.

## Limitations

- It matches words, not meaning. "Mobile development" does not count as iOS experience, and soft skills are ignored entirely.
- Section detection is heuristic. Postings with unusual formatting can put skills in the wrong bucket; when no requirement headings are found, the report says so and treats everything as required.
- Years of experience are read only from lines that mention "experience", and the largest lower bound wins. "3 to 5 years" is read as 3.
- The score is a sorting aid, not a judgment. A 60% posting with one critical gap can be a worse fit than it looks.

## What I would add next

- Append each result as a row in my application tracker spreadsheet, which I currently update by hand.
- An optional LLM step that writes a two-sentence summary of the team and flags anything in the posting the rules could not classify, clearly marked as model output.
- Fetch a posting from a URL instead of pasting it into a text file.
