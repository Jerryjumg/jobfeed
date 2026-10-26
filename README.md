# jobfeed

A daily job-search pipeline that pulls fresh openings from about 180 company job boards, throws out the ones I can't or shouldn't apply to, and ranks the rest by how likely they are to turn into an interview. It writes one spreadsheet each morning that I work through top to bottom.

I built it during my own new-grad job search as an international student on F-1 OPT. That situation shaped most of the design: many postings quietly rule out anyone who needs visa sponsorship, and the time I spent reading those was time I didn't spend on applications that could actually go somewhere.

## The problem

Job boards are built for volume. A typical morning on LinkedIn or Indeed gave me hundreds of results, and most of them failed for reasons I could only find by opening the posting:

- **"No sponsorship now or in the future"**, "must be a U.S. citizen", ITAR or clearance requirements, usually in the last paragraph.
- **"Senior" roles listed as entry level,** or a junior title that asks for 5+ years.
- **Duplicates and reposts** of jobs I had already looked at.
- **Locations that don't work,** including listings marked "Remote" that turn out to be remote within another country.

Doing that screening by hand took one to two hours a day. Worse, after a few weeks I looked at my own tracking sheet and found that **about 400 online applications to large companies had produced one technical interview, while about 45 emails sent directly to a hiring manager or professor had produced seven.** The bottleneck wasn't how many jobs I applied to. It was which ones, and whether there was a person I could write to.

## What it does

```
python jobfeed.py              # fetch, filter, score, write Jobs_<date>.xlsx
python jobfeed.py rescore 14   # re-rank everything from the last 14 days under the current rules
python alerts.py               # fold LinkedIn job-alert emails into the same workbook
```

1. **Fetches** open roles from the public posting APIs of Greenhouse, Lever, Ashby and Workday (company list in `companies.json`), the community new-grad lists on GitHub, and the monthly Hacker News "Who is hiring?" thread.
2. **Filters** each posting on:
   - **Title:** senior and non-technical roles are dropped.
   - **Location:** U.S. only, with Boston-area and remote roles kept.
   - **Freshness:** only jobs posted since my last run.
   - **Deal-breakers in the full description text:** no sponsorship, citizenship or clearance requirements, "no OPT/CPT", and green-card (PERM) ads that aren't real openings.
3. **Assesses fit** with [`jdfit`](jdfit/), a rule-based reader (in this repo) that separates required from preferred skills, finds the years of experience a posting really asks for, and compares both against my skills profile.
4. **Scores** each surviving job with a transparent multiplicative model (below) and explains the score in plain words, for example `+ small company (12 openings), contact email in posting; - asks 2+ yrs`.
5. **Writes** an Excel workbook:
   - **Apply:** ranked jobs, each with a link, the visa wording quoted from the posting, a "Find manager" LinkedIn search, and a **Contact** column.
   - **Filtered out:** every rejected job with its reason, so I can audit the filters.
   - My own Applied and Notes marks carry over from day to day.

A scheduled task runs it every morning, so the sheet is waiting when I start.

## How the score works

Every job starts at 100, and each factor multiplies it. Factors above 1 help, factors below 1 hurt, and all weights live in `config.json` so they can be tuned without touching code.

| Stage | Factors |
|---|---|
| **Job type** (9 lanes) | A prior for each lane: research/lab software, data and business systems, implementation, MES and manufacturing systems, iOS, IT coordination, QA and validation, applied AI, general software engineering |
| **Experience screen** | Asks 2+ years, "level II" titles, no level stated, internships that may require enrollment |
| **Skill match** | `jdfit` match, shrunk toward the middle when a posting names few recognizable skills, with a penalty per missing *required* skill |
| **Sponsorship** | Says it sponsors (up) or sounds uncertain (down) |
| **Competition** | Famous brand, remote national pool, tech hub vs. home market, posting age |
| **Company size** | Estimated from how many openings the company has on its own board: 20 or fewer is a small company, 200+ is a large one |
| **Direct contact** | An email address in the posting, or someone I'm connected to at the company (from LinkedIn's `Connections.csv` export) |
| **My edges** | The posting mentions Mandarin, accessibility work, my exact tools, or says it welcomes juniors |

## Problems I hit and how I fixed them

- **The ranking rewarded the wrong jobs.** The first version scored mostly on skill match, so famous companies with long software engineering postings rose to the top. Those were exactly the applications that never got answered. I rebuilt the score as a chain of stages an application has to survive, and set the lane weights from my actual results: research, data, QA and manufacturing-systems roles got interviews, general software engineering at large companies almost never did.
- **Small companies were invisible.** Most of my interviews came from small teams, but nothing in the data said how big a company is. I now use the number of open roles on a company's own job board as a size signal, and I added 35 Boston-area small and mid-size companies to the source list. Co-ops at small companies are no longer penalized as heavily, because they often hire recent graduates.
- **Applications without a person behind them went nowhere.** I added a Contact column and a score boost when the posting includes an email address, or when someone in my network works there.
- **Sponsorship language hides in boilerplate.** Simple keyword matching kept flagging equal-opportunity statements ("without regard to national origin, citizenship..."). Sentences that look like EEO boilerplate are now excluded before the visa check, and the remaining visa sentences are quoted in the sheet so I can read them myself.
- **"Remote" didn't mean U.S.** Location parsing handles state codes that collide with country codes (IN, DE, CA), Canadian provinces, and vague labels like "Hybrid" by reading the posting body.
- **Title filters were too blunt.** A rule that dropped every "manager" title also dropped "IT Project Manager Assistant", an entry-level role. It now excludes "manager" only when "assistant" doesn't follow.
- **Running it twice in one day lost jobs.** A second run moved the "since last pull" window forward, so it skipped jobs posted that morning. The run window now stays fixed for the rest of the day.
- **The spreadsheet was open in Excel.** Writing over an open workbook fails, so the script detects Excel's `~$` lock file and saves a timestamped copy instead.
- **One slow board stalled everything.** Fetches run in parallel with per-source timeouts. A failing board is skipped, but if more than 15% fail, the script writes nothing rather than produce a misleadingly short list.
- **I couldn't compare old jobs after changing the rules.** `rescore N` re-ranks everything from the last N days without touching the daily run's memory of what I've seen.

## Setup

Python 3.10+.

```
git clone https://github.com/Jerryjumg/jobfeed
cd jobfeed
pip install -r requirements.txt
cp jdfit/profile.example.json jdfit/profile.json   # then list your own skills
cd jobfeed && python jobfeed.py
```

Edit `jobfeed/config.json` to change locations, title rules, deal-breakers and scoring weights, and `jobfeed/companies.json` to change which job boards are pulled. `python jobfeed.py discover names.txt` checks which company names have a public Greenhouse, Lever or Ashby board.

## Repository layout

```
jobfeed/
  jobfeed.py       fetch, filter, score, write the workbook
  alerts.py        parse LinkedIn job-alert emails into the workbook
  config.json      filters, lanes and scoring weights
  companies.json   job boards to pull
jdfit/             job-description fit checker used for skill matching (has its own README and tests)
```

## Notes

- Only public posting APIs are used; nothing logs in or scrapes behind authentication.
- Daily output, seen-job history and personal profiles are git-ignored.
- The score is a ranking aid, not a measured probability. The weights are my best estimate from a small number of real outcomes and get adjusted as more come in.
- I built this with an AI pair programmer (Claude Code). I defined the rules and the scoring model from my own results, and reviewed and tested the code.
