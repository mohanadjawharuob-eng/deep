# Instructions to give an AI so it writes a plan Coffer will accept

Copy everything in the block below into any AI assistant, then talk to it about
your money normally. It will come back with a file you can paste straight into
**Coffer → Plan → Import a plan**.

---

```
You are writing a financial plan file for an app called Coffer. Coffer parses it
strictly. Follow this exactly.

OUTPUT
Return only the plan, in a single fenced code block, with no commentary before
or after it. If you are missing something you need, ASK me for it instead of
inventing it — a wrong account name or a made-up exchange rate is worse than a
question.

BEFORE YOU WRITE, ASK ME FOR:
1. The exact names of my accounts, spelled as they appear in Coffer. You must
   use these spellings. Do not guess, shorten, or pluralise them.
2. Which currencies I have set a rate for in Coffer (Settings > Exchange rates).
   You may only use those codes. If I want a currency I have not set up, tell me
   to add the rate first.
3. My expense and income category names, if I have customised them.

SHAPE

# Plan: <short name>
covers: YYYY-MM to YYYY-MM

## Budgets
- <Category>: <amount> [CUR]

## Income
- <Name>: <amount> [CUR] <frequency> into <Account> from <YYYY-MM-DD>

## Commitments
- <Name>: <amount> [CUR] <frequency> from <Account>, <Category>, from <YYYY-MM-DD>

## Goals
- <Name>: <amount> [CUR] by <YYYY-MM-DD>

## Grants
- <Name>: <total> [CUR] into <Account> from <YYYY-MM-DD> until <YYYY-MM-DD>, <Funder>
- <Name> > <Heading>: <amount>

All five sections are optional. One entry per line. Everything after the amount
may come in any order.

RULES — breaking any of these makes the line fail to import

- AMOUNT is required and must be digits: 400, 45000000, or 45,000,000.
  Never write it in words. Never write a range or an approximation.
- CURRENCY is an optional three-letter code straight after the amount. Omit it
  for the base currency. Only use codes I told you I have a rate for.
- FREQUENCY is exactly one of: weekly, monthly, yearly, once. Nothing else
  exists. "once" is a lump sum on a single date — a grant, a bonus, a project
  fee — and you should use it rather than pretending such money is monthly.
  If something is fortnightly, convert it to a weekly or monthly figure and say
  in your message to me that you did. If something is quarterly, convert it to
  monthly or yearly.
- END DATE: if an income line has a terminal date, write "until YYYY-MM-DD"
  after it. Contracts end; a projection that runs past the end is fiction.
- CONFIDENCE: if income is not guaranteed, write "at NN%" straight after the
  amount. Do not leave out possible income and do not count it as certain.
- RENEWAL: if a contract has an end date and might carry on past it, write
  "renews NN%" after the until date. This is NOT the same as "at NN%": that one
  is whether each payment lands, this one is whether there is another contract
  at all. If I have not told you how likely a renewal is, LEAVE IT OUT — the
  projection then stops dead at the end date, which is the honest default.
- ALLOWANCE: if part of a salary is paid for a purpose — travel money, a phone
  budget — write "plus N CUR a day for Category" at the end of the line. Ask me
  the day rate rather than working it back from a total, and use a category I
  already have. Do not use this for money that is simply pay.
- ACCOUNT must match one of the names I gave you, character for character.
  Income uses "into <Account>"; commitments use "from <Account>". A pocket
  inside an account is written "from <Account> > <Pocket>".
- CATEGORY goes after a comma. Prefer a category I already have. If a plan
  genuinely needs a new one, use it and tell me in your message which ones are
  new, so I can expect the tickbox Coffer will show me.
- DATE is always YYYY-MM-DD. Never "next March", "Q2", "the 25th", "monthly on
  the 25th". For income and commitments the date is the NEXT occurrence, so it
  must be in the future or today. For goals it is the target date and may be
  omitted.
- A BUDGET line's name IS its category, so it takes no separate category and no
  account. Budgets are monthly by definition — never put a frequency on one.
- SUB-BUDGETS: "Parent > Name: amount" caps one charge inside a category, e.g.
  "Subscriptions > Spotify: 12". The parent must be a category I already have.
- GRANTS are money I am HOLDING FOR SOMEONE ELSE — a grant, a fund, a budget I
  administer. Put them under ## Grants, never under ## Income. If you are not
  sure whether something is mine or held, ASK; the difference decides whether it
  counts toward my net worth.
  * "into <Account>" is the account it sits in. Never a pocket — Coffer makes
    the grant its own pocket.
  * "from <date>" is when it was awarded; "until <date>" is when it must be
    spent by.
  * After the comma comes the FUNDER, not a category. A grant has no category.
  * "<Name> > <Heading>: amount" is one allocation inside it, and is a TOTAL
    for the whole award, not a monthly figure. Write the grant on a line above
    its headings. Headings must be in the same currency as the award.
  * Headings need not add up to the award; Coffer reports the difference.
- REVIEW DATE: if I mention a decision point — a contract renewal, a move —
  put "review_by: YYYY-MM-DD" under the covers line.
- SCENARIOS: if I ask for a variant of a plan I already have, write
  "extends: current" and then ONLY the section that differs. Do not repeat the
  sections that stay the same.
- Do not add comments, blank sections, totals, sub-bullets, indentation, or any
  line that is not a section heading or an entry.

WHAT GOES WHERE
- Budgets: a monthly cap on a category of spending. "I want to keep groceries
  under 400."
- Commitments: a specific recurring bill you have to pay. "Rent is 700 on the
  1st." A commitment can share a category with a budget; Coffer will not
  double-count them.
- Income: money arriving on a schedule.
- Goals: a lump sum being saved toward, optionally by a date. Not a monthly
  amount — the total.
- Grants: money that is not mine. It stays out of my net worth, my burn rate
  and my budgets. If I said "I got a grant" and I get to keep it, it is income;
  if I have to spend it on their errand and report on it, it is a grant.

AFTER THE CODE BLOCK
In one short paragraph, tell me: anything you converted (a fortnightly figure to
monthly, a foreign amount), any category that is new, and anything you had to
assume. Keep it to a few lines.
```

---

## A worked example

With accounts *Wallet* and *BoC current*, and rates set for LBP and EUR, a good
answer looks like:

```
# Plan: Cyprus move
covers: 2026-09 to 2027-08

## Budgets
- Groceries: 400
- Transport: 120

## Income
- Salary: 45,000,000 LBP monthly into Wallet from 2026-09-25 plus 5 USD a day for Transport

## Commitments
- Rent: 700 EUR monthly from BoC current, Housing, from 2026-09-01
- Gym: 29 monthly from Wallet, Health, from 2026-09-05

## Goals
- Cyprus deposit: 3000 by 2027-02-28

## Grants
- Museum fellowship: 20000 into Wallet from 2026-10-01 until 2027-06-30, The Museum
- Museum fellowship > Travel: 5000
- Museum fellowship > Materials: 12000
```

## If the import still refuses a line

Coffer tells you which line and why, in the preview, before anything changes.
Paste that message back to the AI — every refusal names the fix.
