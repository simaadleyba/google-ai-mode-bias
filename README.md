# google-ai-mode-bias

Sock-puppet audit of whether Google AI Overviews and AI Mode give different political answers and citations to accounts with different search histories.

## Pipeline

| step | script | what it does |
|---|---|---|
| 1. queries | `harvest_queries.py` | collects real phrasings from Google autocomplete; framing and loaded-premise columns are labeled by hand |
| 2. accounts | `google_ai_audit.py login <acc>` | opens real Chrome on the account's profile for manual sign-in (turn Web & App Activity on) |
| 3. seeding | `google_ai_audit.py seed <acc>` | searches the condition's seed queries and clicks results from the condition's domains |
| 4. collection | `google_ai_audit.py collect` | all accounts send the same query at the same moment; saves the AI Overview page, then clicks the AI Mode tab and saves the finished answer (HTML + screenshot) |
| 5. parsing | `parse_aimode.py` | saved AI Mode pages to `answers.jsonl`: answer text and claim to source pairs, incl. "+N" sources behind each citation chip |
| 6. labeling | `label_answers.py` | LLM labels premise handling, stance, hedging; rule-based source types; kappa and macro-F1 against human labels |

## Setup

```
pip install -r requirements.txt
playwright install chrome
```

Edit `ACCOUNTS`, `SEED`, `TEST_QUERIES` and `LOCALE` in `google_ai_audit.py`. Keep at least 2 accounts per condition so within-condition differences give the noise floor. Seed queries must not overlap with test queries.

## Usage

```
python harvest_queries.py stems.txt suggestions.csv
python google_ai_audit.py login acc_left_1
python google_ai_audit.py seed acc_left_1
python google_ai_audit.py collect
python parse_aimode.py audit/raw/aimode/*.html > answers.jsonl
python label_answers.py label answers.jsonl labels_llm.jsonl
python label_answers.py agree labels_llm.jsonl labels_human.jsonl
```

The parser fills `id`, `qid`, `account` and `ts` from the file name. Add `condition` (from `ACCOUNTS`) and `premise` (from your query sheet) before labeling.

## Notes

- Google markup changes often. Verify the selectors in a pilot: "AI Overview", "Show more", the "AI Mode" tab, the "AI Mode reply for" heading, and the parser's citation chip format (`data-suuid="nCd0md|..."`). The parser was tested on one saved page (Nov 2026).
- `audit/` is gitignored: the Chrome profiles in it hold logged-in Google sessions.
- CAPTCHA pages are logged and skipped, not bypassed.
