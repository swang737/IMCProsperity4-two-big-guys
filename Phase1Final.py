import json
from typing import Any, List

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append([trade.symbol, trade.price, trade.quantity, trade.buyer, trade.seller, trade.timestamp])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            encoded_candidate = json.dumps(candidate)
            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()

# ── Osmium constants ──────────────────────────────────────────────────────────
OSM_PRODUCT       = "ASH_COATED_OSMIUM"
OSM_POSITION_LIMIT = 78   # normal MM/take limit
OSM_SNIPE_LIMIT    = 80   # extended limit only for ±98 snipe orders

# ── Pepper constants ──────────────────────────────────────────────────────────
PEP_PRODUCT        = "INTARIAN_PEPPER_ROOT"
PEP_POSITION_LIMIT = 80   # hard limit — only snipe orders can reach this
PEP_SOFT_LIMIT     = 79   # normal trading cap
PEP_INITIAL_LONG   = 75
PEP_SKEW_K         = 0.5  # adj_fair = fair + SKEW_K * (INITIAL_LONG - position)


class Trader:
    # ── Osmium tuning ─────────────────────────────────────────────────────────
    OSM_VOL_THRESHOLD = 20
    OSM_MEAN          = 10000
    OSM_SKEW_K        = 0.5   # 0=no skew, 1=always trade at 10k exactly
    OSM_INV_K         = 4     # max inventory penalty at full position
    OSM_INV_EXP       = 2     # shape: 1=linear, 2=kicks in harder near limit
    OSM_EMPTY_OFFSET  = 98    # quote this far from adj_fair when one side is empty

    def __init__(self):
        # Osmium state
        self._last_fair:   dict[str, float] = {}
        self._prev_mm_bid: dict[str, float] = {}
        self._prev_mm_ask: dict[str, float] = {}
    
    def bid(self):
        return 0

    # ── Osmium helpers ────────────────────────────────────────────────────────

    def _osm_fill_mm(self, order_depth: OrderDepth, product: str):
        """Returns (fair, pred_bid, pred_ask)."""
        qual_bids = sorted(
            [p for p, v in order_depth.buy_orders.items() if v > self.OSM_VOL_THRESHOLD],
            reverse=True
        )
        qual_asks = sorted(
            [p for p, v in order_depth.sell_orders.items() if abs(v) > self.OSM_VOL_THRESHOLD]
        )

        bid_p = qual_bids[1] if len(qual_bids) > 1 else (qual_bids[0] if qual_bids else None)
        ask_p = qual_asks[1] if len(qual_asks) > 1 else (qual_asks[0] if qual_asks else None)

        prev_bid  = self._prev_mm_bid.get(product)
        prev_ask  = self._prev_mm_ask.get(product)
        last_fair = self._last_fair.get(product)

        pred_bid = bid_p
        pred_ask = ask_p

        if bid_p is not None and ask_p is not None:
            fair = (bid_p + ask_p) / 2
            self._prev_mm_bid[product] = bid_p
            self._prev_mm_ask[product] = ask_p
            self._last_fair[product]   = fair

        elif ask_p is not None:
            if prev_ask is not None and prev_bid is not None:
                delta    = ask_p - prev_ask
                pred_bid = prev_bid + delta
                fair     = (pred_bid + ask_p) / 2
                self._last_fair[product] = fair
            else:
                fair = last_fair
            self._prev_mm_ask[product] = ask_p

        elif bid_p is not None:
            if prev_bid is not None and prev_ask is not None:
                delta    = bid_p - prev_bid
                pred_ask = prev_ask + delta
                fair     = (bid_p + pred_ask) / 2
                self._last_fair[product] = fair
            else:
                fair = last_fair
            self._prev_mm_bid[product] = bid_p

        else:
            pred_bid = prev_bid
            pred_ask = prev_ask
            if prev_bid is not None and prev_ask is not None:
                fair = (prev_bid + prev_ask) / 2
            else:
                fair = last_fair

        return fair, pred_bid, pred_ask

    def _trade_osmium(self, state: TradingState) -> List[Order]:
        orders: List[Order] = []
        product = OSM_PRODUCT

        if product not in state.order_depths:
            return orders

        order_depth = state.order_depths[product]
        fair_price, pred_bid, pred_ask = self._osm_fill_mm(order_depth, product)

        if fair_price is None:
            return orders

        adj_fair = fair_price + self.OSM_SKEW_K * (self.OSM_MEAN - fair_price)

        position_limit    = OSM_POSITION_LIMIT
        position          = state.position.get(product, 0)
        original_position = position

        pos_ratio   = position / position_limit
        inv_penalty = self.OSM_INV_K * (abs(pos_ratio) ** self.OSM_INV_EXP) * (1 if pos_ratio > 0 else -1)
        adj_fair   -= inv_penalty

        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        asks = sorted(order_depth.sell_orders.keys())
        lone_ask = len(asks) == 1
        lone_bid = len(bids) == 1
        took_lone_ask = False
        took_lone_bid = False

        # 1. TAKE: buy asks below adj_fair, sell bids above adj_fair
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price >= adj_fair:
                break
            buy_qty = min(-order_depth.sell_orders[ask_price], position_limit - position)
            if buy_qty <= 0:
                break
            orders.append(Order(product, ask_price, buy_qty))
            position += buy_qty
            if lone_ask:
                took_lone_ask = True

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price <= adj_fair:
                break
            sell_qty = min(order_depth.buy_orders[bid_price], position_limit + position)
            if sell_qty <= 0:
                break
            orders.append(Order(product, bid_price, -sell_qty))
            position -= sell_qty
            if lone_bid:
                took_lone_bid = True

        # Normal MM qty capped at OSM_POSITION_LIMIT (75)
        bid_qty = position_limit - max(position, original_position)
        ask_qty = position_limit + min(position, original_position)

        # Snipe qty uses OSM_SNIPE_LIMIT (80) — only for ±98 orders
        snipe_bid_qty = OSM_SNIPE_LIMIT - max(position, original_position)
        snipe_ask_qty = OSM_SNIPE_LIMIT + min(position, original_position)

        # 2. MAKE — if we took a lone order, post snipe on that side instead of diming
        if took_lone_ask and snipe_ask_qty > 0:
            orders.append(Order(product, round(adj_fair + self.OSM_EMPTY_OFFSET), -snipe_ask_qty))
        if took_lone_bid and snipe_bid_qty > 0:
            orders.append(Order(product, round(adj_fair - self.OSM_EMPTY_OFFSET), snipe_bid_qty))

        placed_bid = took_lone_bid
        if not took_lone_bid:
            for bid_level in bids:
                dime_bid = bid_level + 1
                if dime_bid < adj_fair and (not asks or dime_bid < asks[0]):
                    if bid_qty > 0:
                        orders.append(Order(product, dime_bid, bid_qty))
                    placed_bid = True
                    break
            if not placed_bid:
                if not bids and snipe_bid_qty > 0:
                    orders.append(Order(product, round(adj_fair - self.OSM_EMPTY_OFFSET), snipe_bid_qty))
                elif pred_bid is not None and bid_qty > 0:
                    orders.append(Order(product, round(pred_bid), bid_qty))

        placed_ask = took_lone_ask
        if not took_lone_ask:
            for ask_level in asks:
                dime_ask = ask_level - 1
                if dime_ask > adj_fair and (not bids or dime_ask > bids[0]):
                    if ask_qty > 0:
                        orders.append(Order(product, dime_ask, -ask_qty))
                    placed_ask = True
                    break
            if not placed_ask:
                if not asks and snipe_ask_qty > 0:
                    orders.append(Order(product, round(adj_fair + self.OSM_EMPTY_OFFSET), -snipe_ask_qty))
                elif pred_ask is not None and ask_qty > 0:
                    orders.append(Order(product, round(pred_ask), -ask_qty))

        logger.print(
            f"[{product}] fair={fair_price:.2f} adj_fair={adj_fair:.2f} inv_pen={inv_penalty:.2f} "
            f"best_bid={bids[0] if bids else 'n/a'} best_ask={asks[0] if asks else 'n/a'} pos={original_position}"
        )
        return orders

    # ── Pepper helpers ────────────────────────────────────────────────────────

    def _trade_pepper(self, state: TradingState, saved: dict) -> tuple[List[Order], dict]:
        orders: List[Order] = []
        product  = PEP_PRODUCT
        position = state.position.get(product, 0)
        original_position = position

        prev_ts      = saved.get("ts", -1)
        new_day      = state.timestamp <= prev_ts
        reached_long = (False if new_day else saved.get("rl", False)) or position >= PEP_INITIAL_LONG
        last_mm_bid  = saved.get("lb", None)
        last_mm_ask  = saved.get("la", None)
        fair_base    = None if new_day else saved.get("fb", None)

        od = state.order_depths.get(product)
        if od is None:
            new_saved = {"rl": reached_long, "lb": last_mm_bid, "la": last_mm_ask, "fb": fair_base, "ts": state.timestamp}
            return orders, new_saved

        if fair_base is None and od.buy_orders and od.sell_orders:
            mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
            fair_base = round(mid / 1000) * 1000

        mm_bids = [p for p, v in od.buy_orders.items()  if v > 15]
        mm_asks = [p for p, v in od.sell_orders.items() if abs(v) > 15]
        cur_bid = max(mm_bids) if mm_bids else None
        cur_ask = min(mm_asks) if mm_asks else None
        if cur_bid is not None:
            last_mm_bid = cur_bid
        if cur_ask is not None:
            last_mm_ask = cur_ask

        bids = sorted(od.buy_orders.keys(),  reverse=True)
        asks = sorted(od.sell_orders.keys())

        # Phase 1: accumulate to INITIAL_LONG
        if not reached_long:
            for ask_price in asks:
                if position >= PEP_INITIAL_LONG:
                    break
                if abs(od.sell_orders[ask_price]) > 15:
                    continue
                buy_qty = min(-od.sell_orders[ask_price], PEP_INITIAL_LONG - position)
                if buy_qty > 0:
                    orders.append(Order(product, ask_price, buy_qty))
                    position += buy_qty
            if position >= PEP_INITIAL_LONG:
                reached_long = True
            new_saved = {"rl": reached_long, "lb": last_mm_bid, "la": last_mm_ask, "fb": fair_base, "ts": state.timestamp}
            return orders, new_saved

        # Phase 2: skew-fair trading
        if fair_base is None:
            new_saved = {"rl": reached_long, "lb": last_mm_bid, "la": last_mm_ask, "fb": fair_base, "ts": state.timestamp}
            return orders, new_saved

        fair     = fair_base + 0.001 * state.timestamp
        adj_fair = fair + PEP_SKEW_K * (PEP_INITIAL_LONG - position)

        lone_ask = len(asks) == 1
        lone_bid = len(bids) == 1
        took_lone_ask = False
        took_lone_bid = False

        # 1. TAKE: capped at SOFT_LIMIT
        for ask_price in asks:
            if ask_price >= adj_fair or position >= PEP_SOFT_LIMIT:
                break
            buy_qty = min(-od.sell_orders[ask_price], PEP_SOFT_LIMIT - position)
            if buy_qty > 0:
                orders.append(Order(product, ask_price, buy_qty))
                position += buy_qty
                if lone_ask:
                    took_lone_ask = True

        for bid_price in bids:
            if bid_price <= adj_fair or position <= -PEP_SOFT_LIMIT:
                break
            sell_qty = min(od.buy_orders[bid_price], PEP_SOFT_LIMIT + position)
            if sell_qty > 0:
                orders.append(Order(product, bid_price, -sell_qty))
                position -= sell_qty
                if lone_bid:
                    took_lone_bid = True

        # 2. MAKE: normal uses SOFT_LIMIT; snipe uses full POSITION_LIMIT
        bid_qty_normal = PEP_SOFT_LIMIT     - max(position, original_position)
        ask_qty_normal = PEP_SOFT_LIMIT     + min(position, original_position)
        bid_qty_snipe  = PEP_POSITION_LIMIT - max(position, original_position)
        ask_qty_snipe  = PEP_POSITION_LIMIT + min(position, original_position)

        # If we took a lone order, post snipe on that side instead of diming
        if took_lone_ask and ask_qty_snipe > 0:
            orders.append(Order(product, round(adj_fair + 120), -ask_qty_snipe))
        if took_lone_bid and bid_qty_snipe > 0:
            orders.append(Order(product, round(adj_fair - 120), bid_qty_snipe))

        if not bids:
            if bid_qty_snipe > 0:
                orders.append(Order(product, round(adj_fair - 120), bid_qty_snipe))
        elif bid_qty_normal > 0 and not took_lone_bid:
            placed_bid = False
            for bid_level in bids:
                dime = bid_level + 1
                if dime < adj_fair:
                    orders.append(Order(product, dime, bid_qty_normal))
                    placed_bid = True
                    break
            if not placed_bid:
                ref = cur_ask if cur_ask is not None else last_mm_ask
                if ref is not None:
                    orders.append(Order(product, ref - 20, bid_qty_normal))
                elif last_mm_bid is not None:
                    orders.append(Order(product, last_mm_bid, bid_qty_normal))

        if not asks:
            if ask_qty_snipe > 0:
                orders.append(Order(product, round(adj_fair + 120), -ask_qty_snipe))
        elif ask_qty_normal > 0 and not took_lone_ask:
            placed_ask = False
            for ask_level in asks:
                dime = ask_level - 1
                if dime > adj_fair:
                    orders.append(Order(product, dime, -ask_qty_normal))
                    placed_ask = True
                    break
            if not placed_ask:
                ref = cur_bid if cur_bid is not None else last_mm_bid
                if ref is not None:
                    orders.append(Order(product, ref + 20, -ask_qty_normal))
                elif last_mm_ask is not None:
                    orders.append(Order(product, last_mm_ask, -ask_qty_normal))

        logger.print(
            f"[{product}] fair={fair:.1f} adj_fair={adj_fair:.1f} skew={adj_fair - fair:+.1f} pos={original_position}"
        )

        new_saved = {"rl": reached_long, "lb": last_mm_bid, "la": last_mm_ask, "fb": fair_base, "ts": state.timestamp}
        return orders, new_saved

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        try:
            saved = json.loads(state.traderData)
        except Exception:
            saved = {}

        osm_orders = self._trade_osmium(state)
        pep_orders, pep_saved = self._trade_pepper(state, saved)

        result = {
            OSM_PRODUCT: osm_orders,
            PEP_PRODUCT: pep_orders,
        }

        trader_data = json.dumps(pep_saved)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
