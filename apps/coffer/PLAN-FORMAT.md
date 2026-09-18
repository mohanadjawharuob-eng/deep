# Writing a plan for Coffer

A plan is what you *meant* to do. Coffer already records what you actually did;
importing a plan puts the two side by side on the **Plan** tab.

Write it as plain text — in Word, in Notes, in a message to yourself — and paste
it into **Plan → Import a plan**. Coffer shows you every line and what it will do
before anything is changed, and nothing is applied while a single line is broken.

## The shape

```
# Plan: Cyprus move
covers: 2026-09 to 2027-08
review_by: 2027-02-01

## Budgets
- Groceries: 400
- Transport: 120
- Housing: 700 EUR
- Subscriptions: 60
- Subscriptions > Spotify: 12

## Income
- Salary: 45,000,000 LBP monthly into Wallet from 2026-09-25 plus 5 USD a day for Transport
- Contract: 2000 monthly into Wallet from 2026-09-01 until 2027-03-31 renews 60%
- Possible grant: 5000 at 40% once into Wallet from 2026-11-15

## Commitments
- Rent: 700 EUR monthly from BoC current, Housing, from 2026-09-01
- Gym: 29 monthly from Wallet, Health, from 2026-09-05

## Goals
- Cyprus deposit: 3000 by 2027-02-28
- Emergency fund: 5000

## Grants
- Museum fellowship: 20000 into Wallet from 2026-10-01 until 2027-06-30, The Museum
- Museum fellowship > Travel: 5000
- Museum fellowship > Materials: 12000
```

All five sections are optional. Every entry is one line:

```
- <name>: <amount> [CUR] [frequency] [into|from <account>] [, <category>] [by|from <date>]
```

Everything after the amount can come in any order.

## The rules, and why they are strict

| Part | Rule |
|---|---|
| **amount** | Required. `400`, `45,000,000` and `$400` all read the same. |
| **currency** | A three-letter code after the amount. It **must already have a rate** under Settings › Exchange rates — otherwise the line is refused rather than converted at a rate nobody chose. The rate is then frozen into the plan, so changing it later never re-values a plan you already imported. |
| **frequency** | `weekly`, `monthly`, `yearly` or `once` — the four Coffer keeps. Monthly if omitted. `fortnightly` and `quarterly` are refused by name rather than silently rounded. See below for what `once` means. |
| **account** | `into Wallet` for income, `from Wallet` for a commitment; a pocket is `from Bank › Cyprus`. Matched case-insensitively against the accounts you actually have. An unknown name is an error listing the ones that exist; a closed account is refused. |
| **category** | After a comma: `, Housing`. Leave it out and Coffer uses the entry's own name if that names a category, otherwise guesses from it and tells you which it picked. A category that doesn't exist is offered as a tickbox, never created behind your back. |
| **date** | `from 2026-09-01` or `by 2027-06-30`. Always `YYYY-MM-DD`. **"next March" is refused** — a date guessed at is a date that is quietly wrong. |
| **end date** | `until 2027-03-31` on an income line or a grant. Also `YYYY-MM-DD`, and also refused if written out. An end date before its start date is refused. |

A budget line's name *is* its category.

## For income that is not a salary

| Written | Means |
|---|---|
| `once` as the frequency | a lump sum on one date — a grant, a bonus, a project fee. It is **not** averaged into a monthly figure, because pretending a one-off is a monthly rate is exactly what makes contract income look like a salary. |
| `until 2027-03-31` | a terminal date. Projections stop there instead of assuming the contract runs forever, and Coffer warns you when an income line is about to end with nothing scheduled after it. |
| `at 40%` | how likely this is. A line at 40% counts as 40% of its value in the headline and says so, which means guaranteed and possible income can live in one plan instead of forcing two near-identical files. |
| `renews 60%` | how likely the contract is to **carry on past its end date**. Not the same as `at 40%`, which is whether each payment lands — this is whether there is another one at all. Leave it out and the projection stops dead at `until`, which is the honest default; write it and the projection carries the contract at that fraction and says on the chart that it is doing so. Needs an `until` to renew past. |
| `plus 5 USD a day for Transport` | an **allowance inside the pay**. A travel allowance is money for travel: Coffer asks how many days you worked, draws that pot down before your own Transport budget, and shows how much of the salary is actually pay. The currency is optional and the category must be one you already have. It is still your money — it counts as income and net worth like the rest of the pay. |

## Grants — money that is not yours

A grant is money sitting in your account that belongs to whoever gave it to
you. Coffer treats it as such: it is **out of your net worth, out of your burn
rate and out of your own category budgets**, and it lives in its own pocket
marked as already spoken for, so it never counts toward your runway.

```
- <name>: <total> [CUR] into <account> from <awarded> until <spend-by>, <funder>
- <name> > <heading>: <amount>
```

| Part | Rule |
|---|---|
| **into** | the account it sits in — **not** a pocket. Coffer makes the grant its own pocket inside that account and holds the money there. |
| **from** | the date it was awarded. The award is written into your ledger as income on that date, tagged to the grant, so the account balance is right. |
| **until** | the date it has to be spent by. Coffer warns you when that is close with money still unspent, and again if it passes with money left — usually money that has to go back. |
| **, funder** | after the comma, who it is from. The comma slot is the category everywhere else; a grant has no category, so it carries the funder instead. |
| **`Name > Heading`** | one allocation inside the grant — a **total for the whole award, not a monthly cap**, which is why these are not budgets. The grant itself has to be written on a line above its headings. |

Headings are held in the award's own currency, so a grant in EUR with a
heading in USD is refused rather than converted at a second rate nobody chose.
The headings do not have to add up to the award: Coffer says what is left
unsplit, or how much more is allocated than the award holds.

Re-importing updates the grant and its headings in place. **What has already
been spent against it is never touched** — a re-import corrects the terms, not
the history.

## Sub-budgets

`Subscriptions > Spotify: 12` caps one charge inside a parent category. The
parent is what transactions are actually filed under, so a sub-budget is kept as
a **breakdown** of the parent rather than a budget of its own — when
Subscriptions runs over you can see which line to cut. The parent must be a
category that exists.

## Review date

`review_by: 2027-02-01` at the top ties the plan to a real decision point — a
contract renewal, a move. Within 45 days the Plan tab says so, prominently, so
regenerating it is not left to memory.

## Scenarios

A plan can inherit from the one already imported and replace only the sections it
mentions:

```
# Plan: Contract lost
extends: current

## Income
- Stopgap: 600 monthly into Wallet from 2027-04-01
```

Budgets, commitments and goals are taken from the parent as they stand, so a
branching future does not mean two near-duplicate files kept in step by hand.
Lines the scenario drops are listed in the preview as *no longer in the plan* —
the records they created stay where they are, because they may have been logged
against; only the plan stops tracking them.

## Running it more than once

Every line is keyed by its section and name, and the records it creates are
stamped with that key. Re-importing an edited plan **updates the same entries
instead of making second copies**, so it is safe to run whenever the plan
changes. A goal's `saved` figure is never overwritten — that is real money you
already put aside.

**Plan → Copy it back out** writes the stored plan back into this format, so a
plan imported months ago can be edited and re-imported without retyping it.

## JSON instead

A file starting with `{` is read as JSON with the same four keys:

```json
{
  "name": "Cyprus move",
  "from": "2026-09", "to": "2027-08",
  "budgets":     [{ "category": "Groceries", "amount": 400 }],
  "income":      [{ "name": "Salary", "amount": 45000000, "currency": "LBP",
                    "frequency": "monthly", "account": "Wallet", "date": "2026-09-25" }],
  "commitments": [{ "name": "Rent", "amount": 700, "currency": "EUR",
                    "frequency": "monthly", "account": "BoC current",
                    "category": "Housing", "date": "2026-09-01" }],
  "goals":       [{ "name": "Cyprus deposit", "amount": 3000, "date": "2027-02-28" }],
  "grants":      [{ "name": "Museum fellowship", "amount": 20000, "account": "Wallet",
                    "date": "2026-10-01", "until": "2027-06-30", "category": "The Museum" },
                  { "name": "Museum fellowship > Travel", "amount": 5000 }]
}
```

Both forms go through exactly the same validation.

## What it does *not* do

- **Accounts** — a plan attaches to accounts you already have. The one thing it
  *does* create is a grant's pocket, because a grant without somewhere to sit
  is not a grant.
- **Investments** — a holding's worth is a figure only you can know, so it is
  set in the app rather than written into a plan.
- **Changes part-way through** — "rent becomes €700 from March" is not expressible;
  budgets are one figure per category with no time dimension. Re-import an
  edited plan when the figure changes.
- **.docx** — Word files are a ZIP of XML and prose inside them still would not
  parse. Copy the text out and paste it; that works from anywhere.
