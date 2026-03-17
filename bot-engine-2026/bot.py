from pkbot.actions import ActionBid, ActionCall, ActionCheck, ActionFold, ActionRaise
from pkbot.base import BaseBot
from pkbot.runner import parse_args, run_bot
from pkbot.states import GameInfo, PokerState

import eval7
import random


RANKS = "23456789TJQKA"
HEATMAP_FAMILY_BONUS = {
    "AK": 2,
    "AQ": 2,
    "AJ": 1,
    "KJ": 2,
    "KT": 1,
    "QJ": 1,
    "QT": 1,
    "Q9": 2,
    "JT": 2,
    "J9": 2,
    "T9": 1,
    "76": 1,
    "65": 1,
}
HEATMAP_FAMILY_PENALTY = {
    "32": -3,
    "94": -3,
    "85": -2,
    "54": -2,
    "A5": -2,
    "Q5": -1,
    "K3": -1,
    "J7": -1,
}


class Player(BaseBot):
    def __init__(self):
        self.equity_cache = {}
        self.opp_revealed_strength_sum = 0.0
        self.opp_revealed_count = 0

    def on_hand_start(self, game_info: GameInfo, state: PokerState):
        self.equity_cache = {}

    def on_hand_end(self, game_info: GameInfo, state: PokerState):
        opp_cards = [card for card in state.opp_revealed_cards if card != "?"]
        if len(opp_cards) == 2:
            self.opp_revealed_strength_sum += self._preflop_strength(opp_cards)
            self.opp_revealed_count += 1

    def _legal_fallback(self, state: PokerState):
        if state.can_act(ActionCheck):
            return ActionCheck()
        if state.can_act(ActionCall):
            return ActionCall()
        return ActionFold()

    def _hand_key(self, hand):
        a, b = hand
        ra, sa = a[0], a[1]
        rb, sb = b[0], b[1]
        if ra == rb:
            return ra + rb
        if RANKS.index(ra) < RANKS.index(rb):
            ra, rb = rb, ra
            sa, sb = sb, sa
        return f"{ra}{rb}{'s' if sa == sb else 'o'}"

    def _hand_family(self, hand):
        key = self._hand_key(hand)
        return key if len(key) == 2 else key[:2]

    def _preflop_strength(self, hand):
        key = self._hand_key(hand)
        family = self._hand_family(hand)
        pair = len(key) == 2
        suited = key.endswith("s")
        high = key[0]
        low = key[1]

        if pair:
            if high in "AAKKQQJJ":
                return 8
            if high in "TT99":
                return 7
            if high in "8877":
                return 6
            if high in "6655":
                return 5
            return 4

        if high == "A" and low in "KQJ":
            return 8 if suited else 7
        if high == "A" and low == "T":
            return 7 if suited else 6
        if high == "A":
            return 6 if suited else 4
        if high == "K" and low in "QJ":
            return 7 if suited else 6
        if high == "Q" and low == "J":
            return 6 if suited else 5
        if suited and abs(RANKS.index(high) - RANKS.index(low)) == 1 and RANKS.index(high) >= RANKS.index("7"):
            return 5
        if suited and high in "KQJT":
            return 4
        if high in "KQJ" and low in "T98":
            return 3
        if suited:
            base = 2
        else:
            base = 1

        if suited and abs(RANKS.index(high) - RANKS.index(low)) <= 2 and RANKS.index(high) >= RANKS.index("8"):
            base += 1
        base += HEATMAP_FAMILY_BONUS.get(family, 0)
        base += HEATMAP_FAMILY_PENALTY.get(family, 0)
        return max(1, min(base, 8))

    def _raise_to(self, state: PokerState, desired_amount: int):
        if not state.can_act(ActionRaise):
            return None
        min_raise, max_raise = state.raise_bounds
        return ActionRaise(max(min_raise, min(desired_amount, max_raise)))

    def _opp_tightness(self):
        if self.opp_revealed_count == 0:
            return 5.0
        return self.opp_revealed_strength_sum / self.opp_revealed_count

    def _is_premium_preflop(self, hand):
        key = self._hand_key(hand)
        return key in {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"}

    def _hole_pair_rank(self, state: PokerState):
        if state.my_hand[0][0] != state.my_hand[1][0]:
            return -1
        return RANKS.index(state.my_hand[0][0])

    def _flush_hole_rank(self, state: PokerState):
        suit_counts = {}
        for card in state.my_hand + state.board:
            suit_counts[card[1]] = suit_counts.get(card[1], 0) + 1

        flush_suit = next((suit for suit, count in suit_counts.items() if count >= 5), None)
        if flush_suit is None:
            return -1

        hole_ranks = [RANKS.index(card[0]) for card in state.my_hand if card[1] == flush_suit]
        return max(hole_ranks) if hole_ranks else -1

    def _made_hand_score(self, state: PokerState):
        cards = [eval7.Card(card) for card in (state.my_hand + state.board)]
        value = eval7.evaluate(cards)
        hand_type = eval7.handtype(value)
        order = {
            "High Card": 0,
            "Pair": 1,
            "Two Pair": 2,
            "Trips": 3,
            "Straight": 4,
            "Flush": 5,
            "Full House": 6,
            "Quads": 7,
            "Straight Flush": 8,
        }
        return order.get(hand_type, 0)

    def _board_texture(self, state: PokerState):
        board_cards = [eval7.Card(card) for card in state.board]
        if not board_cards:
            return {"paired": False, "flushy": False, "very_flushy": False, "connected": False, "broadway": 0}

        suits = [card.suit for card in board_cards]
        suit_counts = [suits.count(suit) for suit in set(suits)]
        ranks = sorted(card.rank for card in board_cards)
        broadway = sum(1 for rank in ranks if rank >= RANKS.index("T"))

        return {
            "paired": len(set(ranks)) < len(ranks),
            "flushy": max(suit_counts) >= 3,
            "very_flushy": max(suit_counts) >= 4,
            "connected": (max(ranks) - min(ranks) <= 4) if len(ranks) >= 3 else False,
            "broadway": broadway,
        }

    def _revealed_card_pressure(self, state: PokerState):
        revealed = [card for card in state.opp_revealed_cards if card != "?"]
        if not revealed:
            return 0

        revealed_rank = RANKS.index(revealed[0][0])
        board_ranks = [RANKS.index(card[0]) for card in state.board]
        pressure = 0
        if revealed_rank >= RANKS.index("T"):
            pressure += 1
        if revealed_rank in board_ranks:
            pressure += 2
        if board_ranks and revealed_rank >= max(board_ranks):
            pressure += 1
        return pressure

    def _estimate_equity(self, state: PokerState, iters: int):
        revealed = tuple(card for card in state.opp_revealed_cards if card != "?")
        key = (tuple(state.my_hand), tuple(state.board), revealed, iters)
        if key in self.equity_cache:
            return self.equity_cache[key]

        my_cards = [eval7.Card(card) for card in state.my_hand]
        board = [eval7.Card(card) for card in state.board]
        wins = 0.0

        for _ in range(iters):
            deck = eval7.Deck()
            for card in my_cards + board:
                if card in deck.cards:
                    deck.cards.remove(card)

            opp_hand = []
            for card in revealed:
                opp_card = eval7.Card(card)
                if opp_card in deck.cards:
                    deck.cards.remove(opp_card)
                opp_hand.append(opp_card)

            while len(opp_hand) < 2:
                drawn = random.choice(deck.cards)
                deck.cards.remove(drawn)
                opp_hand.append(drawn)

            runout = random.sample(deck.cards, 5 - len(board))
            my_value = eval7.evaluate(my_cards + board + runout)
            opp_value = eval7.evaluate(opp_hand + board + runout)

            if my_value > opp_value:
                wins += 1.0
            elif my_value == opp_value:
                wins += 0.5
        equity = wins / iters
        self.equity_cache[key] = equity
        return equity

    def _auction_bid(self, state: PokerState):
        strength = self._preflop_strength(state.my_hand)
        family = self._hand_family(state.my_hand)
        board_cards = [eval7.Card(card) for card in state.board]
        suits = [card.suit for card in board_cards]
        paired_board = len({card.rank for card in board_cards}) < len(board_cards)
        flushy_board = any(suits.count(suit) >= 2 for suit in set(suits))
        connected_board = False
        if board_cards:
            ranks = sorted(card.rank for card in board_cards)
            connected_board = (max(ranks) - min(ranks) <= 4)

        bid = 15
        if strength >= 7:
            bid += 35
        elif strength >= 5:
            bid += 20
        elif strength >= 3:
            bid += 10

        if paired_board:
            bid += 12
        if flushy_board:
            bid += 10
        if connected_board:
            bid += 8

        bid += 4 * HEATMAP_FAMILY_BONUS.get(family, 0)
        bid += 3 * HEATMAP_FAMILY_PENALTY.get(family, 0)

        if strength <= 2 and HEATMAP_FAMILY_PENALTY.get(family, 0) <= -2 and not (paired_board or flushy_board or connected_board):
            bid = min(bid, 8)
        elif strength <= 3 and HEATMAP_FAMILY_PENALTY.get(family, 0) < 0:
            bid = min(bid, 12)

        return ActionBid(min(state.my_chips, max(5, bid)))

    def _play_preflop(self, state: PokerState):
        strength = self._preflop_strength(state.my_hand)
        cost = state.cost_to_call
        opp_tightness = self._opp_tightness()
        premium = self._is_premium_preflop(state.my_hand)

        if cost == 0:
            if strength >= 6:
                raise_action = self._raise_to(state, max(60, state.pot + 20))
                if raise_action is not None:
                    return raise_action
            return self._legal_fallback(state)

        if cost >= 400 or state.opp_wager >= 500:
            if premium and state.can_act(ActionCall):
                return ActionCall()
            return ActionFold() if state.can_act(ActionFold) else self._legal_fallback(state)

        if cost >= 140 and not premium and strength < 6:
            return ActionFold() if state.can_act(ActionFold) else self._legal_fallback(state)

        if state.is_bb:
            if strength >= 7 and cost <= 40:
                raise_action = self._raise_to(state, max(120, state.pot + 60))
                if raise_action is not None:
                    return raise_action
            if cost >= 70 and strength < 4:
                return ActionFold()
            if strength >= 3 or cost <= 20:
                return ActionCall() if state.can_act(ActionCall) else self._legal_fallback(state)
            return ActionFold()

        if strength >= 6 and cost <= 60:
            raise_action = self._raise_to(state, max(100, state.pot + 40))
            if raise_action is not None:
                return raise_action
        if cost >= 80 and strength < 4:
            return ActionFold()
        defend_threshold = 2 if opp_tightness >= 5.5 else 3
        if strength >= defend_threshold or cost <= 10:
            return ActionCall() if state.can_act(ActionCall) else self._legal_fallback(state)
        return ActionFold()

    def _play_postflop(self, game_info: GameInfo, state: PokerState):
        iters = 110 if game_info.time_bank > 10 else 55
        equity = self._estimate_equity(state, iters)
        pot = state.pot
        cost = state.cost_to_call
        pot_odds = cost / (pot + cost) if cost > 0 else 0.0
        revealed = [card for card in state.opp_revealed_cards if card != "?"]
        made_score = self._made_hand_score(state)
        texture = self._board_texture(state)
        revealed_pressure = self._revealed_card_pressure(state)
        hole_pair = state.my_hand[0][0] == state.my_hand[1][0]
        hole_pair_rank = self._hole_pair_rank(state)
        flush_hole_rank = self._flush_hole_rank(state) if made_score == 5 else -1
        is_river_raise = state.street == "river" and state.my_wager > 0 and state.opp_wager > state.my_wager
        danger = 0
        if texture["paired"]:
            danger += 1
        if texture["flushy"]:
            danger += 1
        if texture["very_flushy"]:
            danger += 1
        if texture["connected"]:
            danger += 1
        if texture["broadway"] >= 3:
            danger += 1
        danger += revealed_pressure

        if cost == 0:
            if made_score >= 4 and equity >= 0.74:
                raise_action = self._raise_to(state, int(pot * 0.7) + 20)
                if raise_action is not None:
                    return raise_action
            if made_score >= 2 and equity >= 0.72 and random.random() < 0.25:
                raise_action = self._raise_to(state, int(pot * 0.5) + 10)
                if raise_action is not None:
                    return raise_action
            if revealed and danger <= 2 and equity >= 0.58 and state.can_act(ActionRaise):
                raise_action = self._raise_to(state, int(pot * 0.38) + 10)
                if raise_action is not None:
                    return raise_action
            if not revealed and danger <= 1 and equity >= 0.67 and state.can_act(ActionRaise) and random.random() < 0.35:
                raise_action = self._raise_to(state, int(pot * 0.35) + 10)
                if raise_action is not None:
                    return raise_action
            return self._legal_fallback(state)

        if revealed and made_score <= 1 and equity < (0.52 + 0.03 * min(danger, 3)) and cost >= 45:
            return ActionFold()

        if is_river_raise:
            if made_score <= 2:
                return ActionFold()
            if texture["paired"] and made_score in {4, 5}:
                return ActionFold()
            if made_score == 5 and flush_hole_rank < RANKS.index("A") and cost >= max(160, pot // 3):
                return ActionFold()
            if made_score == 6 and hole_pair and hole_pair_rank <= RANKS.index("6") and cost >= max(200, pot // 3):
                return ActionFold()

        if pot >= 800 or cost >= max(220, pot // 2, max(1, state.my_chips // 3)):
            if made_score <= 1:
                return ActionFold()
            if made_score == 2 and (hole_pair or texture["paired"] or texture["flushy"] or danger >= 2):
                return ActionFold()
            if texture["paired"] and made_score in {4, 5}:
                return ActionFold()

        if cost >= max(150, pot):
            if made_score >= 5 and equity >= 0.84 and state.can_act(ActionCall):
                return ActionCall()
            if made_score <= 2:
                return ActionFold()
            return ActionFold()

        if state.street == "river" and cost >= max(90, pot // 4):
            if made_score <= 1 and (texture["paired"] or texture["flushy"] or texture["connected"]):
                return ActionFold()
            if made_score == 2 and (hole_pair or texture["paired"] or texture["very_flushy"]):
                return ActionFold()

        if cost >= max(90, pot // 2) and made_score <= 1:
            return ActionFold()

        if danger >= 3 and made_score <= 2 and cost >= max(70, pot // 3):
            return ActionFold()

        if equity >= pot_odds + 0.15:
            if state.can_act(ActionRaise) and made_score >= 3 and equity >= 0.8 and cost <= max(90, pot // 3):
                raise_action = self._raise_to(state, int((pot + cost) * 0.75))
                if raise_action is not None:
                    return raise_action
            if state.can_act(ActionRaise) and revealed and danger <= 1 and equity >= 0.7 and cost <= max(50, pot // 5):
                raise_action = self._raise_to(state, int((pot + cost) * 0.45))
                if raise_action is not None:
                    return raise_action
            if state.can_act(ActionCall):
                return ActionCall()

        if made_score >= 2 and equity >= pot_odds + 0.06 and state.can_act(ActionCall):
            return ActionCall()

        if made_score <= 1 and cost > max(40, pot // 4):
            return ActionFold()

        if revealed and danger <= 1 and equity >= pot_odds + 0.02 and cost <= max(45, pot // 4) and state.can_act(ActionCall):
            return ActionCall()

        if equity >= pot_odds + 0.04 and cost <= max(25, pot // 6) and state.can_act(ActionCall):
            return ActionCall()

        if state.can_act(ActionCheck):
            return ActionCheck()
        return ActionFold()

    def get_move(self, game_info: GameInfo, state: PokerState):
        if state.street == "pre-flop":
            return self._play_preflop(state)
        if state.street == "auction":
            return self._auction_bid(state)
        if state.street in {"flop", "turn", "river"}:
            return self._play_postflop(game_info, state)
        return self._legal_fallback(state)


if __name__ == "__main__":
    run_bot(Player(), parse_args())
