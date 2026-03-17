# PokerBot (IIT PokerBots 2026)

This repo contains a poker bot implemented in `bot-engine-2026/bot.py` by my team AKQJ. I finished '128' with 351 wins and 152 losses :/.
Although not appealoing this was a great exercise for using different python libraries to code and evaluate th code based on gamelogs.
It is written against the `pkbot` API from the official IIT PokerBots `bot-engine-2026` runner.
This repo does not vendor the full game engine.

## Requirements

- Python 3.8+
- Pip deps in `bot-engine-2026/requirements.txt` (notably `eval7`)

Install dependencies:

```bash
cd bot-engine-2026
pip install -r requirements.txt
```

## How To Run

You need the official engine (provides `pkbot`, CLI runner, and game loop):

- https://github.com/iitpokerbots/bot-engine-2026

Once the engine is set up so `pkbot` is importable, run:

```bash
python bot-engine-2026/bot.py
```

## Bot Logic (from `bot.py`)

### State Tracking

- Equity estimates are cached per-hand in `self.equity_cache` and reset in `on_hand_start`.
- Opponent modeling: when opponent hole cards are revealed, the bot computes a heuristic preflop strength for those two cards and keeps a running average (`_opp_tightness`).

### Preflop Hand Strength (`_preflop_strength`)

Returns an integer 1 to 8 based on:

- Pairs: big pairs (AA..JJ) highest, then TT/99, 88/77, 66/55, then smaller pairs.
- Broadways and suited aces are boosted (AK/AQ/AJ/AT patterns).
- Suitedness and connectivity: suited connectors and suited high cards get extra points.
- "Family" heatmap tweaks: bonuses and penalties for certain rank families (e.g., AK/AQ/JT get bonuses; 32/94/85 get penalties).

### Preflop Actions (`_play_preflop`)

- When checked to: raises stronger hands (strength >= 6) to roughly `max(60, pot + 20)`; otherwise checks.
- Facing very large pressure (`cost >= 400` or `opp_wager >= 500`): continues only with premium hands (AA/KK/QQ/JJ/TT/AK/AQs), otherwise folds.
- Big blind defense:
  - Aggressive raise with very strong hands (strength >= 7) when the price is small (cost <= 40).
  - Folds weak hands to larger prices (e.g., cost >= 70 and strength < 4).
  - Otherwise calls with medium strength or cheap price.
- Not big blind:
  - Raises strong hands (strength >= 6) when the price is reasonable (cost <= 60).
  - Folds weak hands to larger prices (cost >= 80 and strength < 4).
  - Adjusts calling threshold based on opponent tightness: calls down to strength 2 if opponent looks tight (`_opp_tightness() >= 5.5`), else requires strength 3 (or calls very cheap prices).

### Auction Bidding (`_auction_bid`)

Starts from a baseline bid (15), then:

- Adds based on preflop strength (+35 / +20 / +10 buckets).
- Adds on dynamic/volatile boards: paired (+12), flushy (+10), connected (+8).
- Applies weighted heatmap family bonus/penalty.
- Caps bids on low-strength, heavily-penalized hands when the board is not dynamic.
- Returns `ActionBid` clamped to `[5, my_chips]`.

### Postflop Equity + Texture (`_play_postflop`)

Equity:

- Uses Monte Carlo simulation via `eval7` with opponent hand sampling.
- Iterations depend on timebank: 110 if `time_bank > 10`, else 55.
- Incorporates any opponent revealed cards already known on that street.

Board and made hand:

- `made_score` is a coarse bucket (0..8) derived from `eval7.handtype`.
- `texture` flags: paired, flushy (3+ same suit), very_flushy (4+), connected, and number of broadways on board.
- `danger` is an additive risk score from texture plus a "revealed card pressure" feature (high revealed rank, pairing the board, or being the board's high card).

Actions:

- When checked to (`cost == 0`):
  - Value raise: if `made_score >= 4` and `equity >= 0.74`, raises to `int(pot * 0.7) + 20`.
  - Light value: if `made_score >= 2` and `equity >= 0.72` (25% of the time), raises to `int(pot * 0.5) + 10`.
  - Pressure (opponent revealed): if `danger <= 2` and `equity >= 0.58`, raises to `int(pot * 0.38) + 10`.
  - Pressure (no reveal): if `danger <= 1` and `equity >= 0.67` (35% of the time), raises to `int(pot * 0.35) + 10`.
  - Otherwise checks.
- When facing a bet/raise (`cost > 0`):
  - Early fold (opponent revealed): if `made_score <= 1`, `equity < 0.52 + 0.03 * min(danger, 3)`, and `cost >= 45`.
  - River raise filters:
    - Folds if `made_score <= 2`.
    - Folds straights/flushes (`made_score` in `{4, 5}`) on paired boards.
    - Folds non-nut flushes for large prices (`cost >= max(160, pot // 3)`).
    - Folds small full houses (low pocket pair) for large prices (`cost >= max(200, pot // 3)`).
  - Large pot / very expensive calls: tightens up heavily (multiple guards using `pot >= 800` and large `cost` vs `pot` and vs stack).
  - Calls/raises based on pot odds:
    - If `equity >= pot_odds + 0.15`, may raise for value (strong made hands, good price), else calls.
    - Else calls if `made_score >= 2` and `equity >= pot_odds + 0.06`.
    - Else calls cheaply with small equity buffers in low-danger spots; otherwise folds.

## Evaluation (Gamelog Review)

To understand whether the bot was folding too often and which starting hands were common losers, I analyzed the engine gamelog using `bot-engine-2026/PokerBots_Review.ipynb`.

### What The Notebook Reads

The notebook expects a text gamelog (one line per event). It keys off common engine log lines like:

- `Round #...` to detect hand boundaries
- `<BOTNAME> folds` to mark that the bot folded in that hand
- `<BOTNAME> awarded <amount>` to record the hand result (winnings for that hand)
- `<BOTNAME> received [As Kd]` to extract hole cards
- `... vs ...` to infer the opponent name (used for some summary tables)

If your bot name differs, update `MY_BOT_NAMES` in the notebook (it is set to `['AKQJ', 'BotA']`).

### Metrics Computed

- Overall winnings stats: total/average/min/max, plus distributions and cumulative winnings over hands.
- Fold frequency and outcomes:
  - Counts hands where the bot folded and the hand result was negative (folded in lost hands).
  - Visualizes the distribution of losses in hands where the bot folded (helps spot frequent -5000 style losses).
- Starting hand analysis:
  - Zips extracted hole cards with per-hand winnings.
  - Aggregates average winnings by rank pair and renders a heatmap to highlight common losing hands with net winnings.
- Opponent interaction summary:
  - Derives a simple `opponent_folded` flag and produces a small table of outcomes split by whether the bot folded and whether the opponent folded.

### How To Use

1. Run matches using the official engine so you get a gamelog file.
2. Open `bot-engine-2026/PokerBots_Review.ipynb` (Jupyter or Google Colab) and load the gamelog.
3. Use the fold and starting-hand sections to spot overly-tight lines and adjust preflop/postflop thresholds accordingly.
