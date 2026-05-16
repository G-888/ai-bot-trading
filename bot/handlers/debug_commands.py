"""
bot/handlers/debug_commands.py — Debug mode commands for strategy engine verification.

/debugfib        — Fibonacci raw detections + annotated chart
/debugsmc        — SMC raw detections + annotated chart
/debugconfluence — Confluence component scores + bar chart
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from market.data import fetch_ohlcv, fetch_gold_data
from market.indicators import swing_highs, swing_lows
from strategies.fibonacci import run_fibonacci_analysis
from strategies.smc import run_smc_analysis
from strategies.session import analyze_session
from signals.confluence import calculate_confluence
from charts.debug_charts import (
    generate_debug_fib_chart,
    generate_debug_smc_chart,
    generate_debug_confluence_chart,
)
from bot.keyboards.menus import back_to_menu

logger = logging.getLogger(__name__)

_LOOKBACK_H1 = 4
_TAIL = 60


# ── /debugfib ─────────────────────────────────────────────────────────────────

async def cmd_debugfib(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Full Fibonacci engine debug dump.
    Shows every detected swing, anchor selection, all levels, and confluence score.
    """
    status = await update.message.reply_text("⏳ Running Fibonacci debug analysis on 1H (60 bars)…")

    df_full = fetch_ohlcv("5d", "1h")
    if df_full is None or len(df_full) < 20:
        await status.edit_text("Could not fetch 1H data.", reply_markup=back_to_menu())
        return

    tail_df = df_full.tail(_TAIL).copy()
    if tail_df.index.tzinfo is not None:
        tail_df.index = tail_df.index.tz_localize(None)

    # ── All swing detections ───────────────────────────────────────────────────
    sh_mask = swing_highs(tail_df["High"], _LOOKBACK_H1)
    sl_mask = swing_lows(tail_df["Low"], _LOOKBACK_H1)

    all_sh = [(i, round(float(p), 2)) for i, (ts, p) in enumerate(
        tail_df["High"][sh_mask].items()
    )]
    all_sl = [(i, round(float(p), 2)) for i, (ts, p) in enumerate(
        tail_df["Low"][sl_mask].items()
    )]

    # ── Fibonacci analysis ─────────────────────────────────────────────────────
    fib = run_fibonacci_analysis(tail_df, lookback=_LOOKBACK_H1)

    # ── Text report ───────────────────────────────────────────────────────────
    sh_lines = "\n".join(f"  [bar {pos:02d}]  {price}" for pos, price in all_sh) or "  None detected"
    sl_lines = "\n".join(f"  [bar {pos:02d}]  {price}" for pos, price in all_sl) or "  None detected"

    if fib:
        levels = fib.get("levels", {})
        level_lines = "\n".join(
            f"  {name:22s} {price}" + (" ◄ nearest" if price == fib.get("nearest_price") else "")
            for name, price in sorted(levels.items(), key=lambda x: x[1], reverse=True)
        )
        anchor_section = (
            f"ANCHOR SELECTION\n"
            f"  Swing High:  {fib['swing_high']} (auto-detected)\n"
            f"  Swing Low:   {fib['swing_low']} (auto-detected)\n"
            f"  Direction:   {fib['direction']}\n"
            f"  Range:       {fib['range_size']} pts\n"
        )
        fib_section = (
            f"FIBONACCI LEVELS  (Python-computed)\n{level_lines}\n\n"
            f"NEAREST LEVEL:  {fib.get('nearest_level', 'N/A')} at {fib.get('nearest_price', 'N/A')}\n"
            f"CONFLUENCE:     {fib.get('confluence_score', 0):.0f}%\n"
            f"RSI:            {fib.get('rsi', 0)}\n"
            f"INVALIDATION:   {fib.get('invalidation', 'N/A')}\n"
            f"EXT TARGET:     {fib.get('target', 'N/A')}"
        )
    else:
        anchor_section = "ANCHOR SELECTION\n  Could not detect a clear swing\n"
        fib_section = "FIBONACCI LEVELS\n  Insufficient swing data"

    text = (
        f"DEBUG — Fibonacci Engine\n"
        f"{'─' * 32}\n"
        f"Timeframe: 1H  |  Bars analysed: {_TAIL}\n"
        f"Lookback for swings: {_LOOKBACK_H1}\n\n"
        f"SWING HIGHS DETECTED  ({len(all_sh)} total)\n{sh_lines}\n\n"
        f"SWING LOWS DETECTED  ({len(all_sl)} total)\n{sl_lines}\n\n"
        f"{anchor_section}\n"
        f"{fib_section}"
    )

    # ── Chart ──────────────────────────────────────────────────────────────────
    await status.delete()

    if fib:
        try:
            buf = generate_debug_fib_chart(tail_df, fib, lookback=_LOOKBACK_H1)
            await update.message.reply_photo(
                photo=buf,
                caption=f"Fibonacci Debug  •  {len(all_sh)} swing highs, {len(all_sl)} swing lows detected",
                reply_markup=back_to_menu(),
            )
        except Exception as e:
            logger.error("Debug fib chart error: %s", e)

    await update.message.reply_text(text, reply_markup=back_to_menu())


# ── /debugsmc ─────────────────────────────────────────────────────────────────

async def cmd_debugsmc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Full SMC engine debug dump.
    Shows all detected BOS, CHoCH, OBs, FVGs, liquidity sweeps with raw bar indices.
    """
    status = await update.message.reply_text("⏳ Running SMC debug analysis on 1H (60 bars)…")

    df_full = fetch_ohlcv("5d", "1h")
    if df_full is None or len(df_full) < 15:
        await status.edit_text("Could not fetch 1H data.", reply_markup=back_to_menu())
        return

    tail_df = df_full.tail(_TAIL).copy()
    if tail_df.index.tzinfo is not None:
        tail_df.index = tail_df.index.tz_localize(None)

    lb = 3
    smc = run_smc_analysis(tail_df, lookback=lb)

    sh_mask = swing_highs(tail_df["High"], lb)
    sl_mask = swing_lows(tail_df["Low"], lb)
    all_sh = [(i, round(float(p), 2)) for i, (ts, p) in enumerate(tail_df["High"][sh_mask].items())]
    all_sl = [(i, round(float(p), 2)) for i, (ts, p) in enumerate(tail_df["Low"][sl_mask].items())]

    # ── Format sections ────────────────────────────────────────────────────────
    def fmt_sh(pairs): return "\n".join(f"  [bar {p:02d}]  {pr}" for p, pr in pairs) or "  None"
    def fmt_sl(pairs): return "\n".join(f"  [bar {p:02d}]  {pr}" for p, pr in pairs) or "  None"

    bos_lines = "\n".join(
        f"  [bar {b.get('bar', '?'):02d}]  {b['direction']} BOS  level: {b['level']}"
        for b in smc.get("bos_list", [])
    ) or "  None detected"

    choch_lines = "\n".join(
        f"  [bar {c.get('bar', '?'):02d}]  {c['direction']} CHoCH  level: {c['level']}"
        + (f"\n         Note: {c.get('note', '')}" if c.get("note") else "")
        for c in smc.get("choch_list", [])
    ) or "  None detected"

    ob_lines = "\n".join(
        f"  [bar {ob.get('bar_idx', '?'):02d}]  {ob['type']}"
        f"  range: {ob['bottom']}–{ob['top']}  mid: {ob['mid']}"
        for ob in smc.get("order_blocks", [])
    ) or "  None detected"

    fvg_lines = "\n".join(
        f"  [bar {fvg.get('bar_idx', '?'):02d}]  {fvg['type']}"
        f"  range: {fvg['bottom']}–{fvg['top']}  mid: {fvg['mid']}"
        for fvg in smc.get("fvg_list", [])
    ) or "  None detected"

    sweep_lines = "\n".join(
        f"  [bar {sw.get('bar_idx', '?'):02d}]  {sw['type']}"
        f"  level: {sw['level']}  ({sw.get('note', '')})"
        for sw in smc.get("sweeps", [])
    ) or "  None detected"

    text = (
        f"DEBUG — Smart Money Concepts Engine\n"
        f"{'─' * 36}\n"
        f"Timeframe: 1H  |  Bars analysed: {_TAIL}\n"
        f"Lookback: {lb}  |  Price: {smc.get('price', 'N/A')}\n\n"
        f"SWING HIGHS  ({len(all_sh)} detected)\n{fmt_sh(all_sh)}\n\n"
        f"SWING LOWS  ({len(all_sl)} detected)\n{fmt_sl(all_sl)}\n\n"
        f"STRUCTURE BIAS\n  {smc.get('structure_bias', 'N/A')}\n\n"
        f"BREAK OF STRUCTURE  ({smc.get('bos_count', 0)} detected)\n{bos_lines}\n\n"
        f"CHANGE OF CHARACTER  ({smc.get('choch_count', 0)} detected)\n{choch_lines}\n\n"
        f"ORDER BLOCKS  ({len(smc.get('order_blocks', []))} detected)\n{ob_lines}\n\n"
        f"FAIR VALUE GAPS  ({len(smc.get('fvg_list', []))} detected)\n{fvg_lines}\n\n"
        f"LIQUIDITY SWEEPS  ({smc.get('sweep_count', 0)} detected)\n{sweep_lines}\n\n"
        f"PREMIUM/DISCOUNT\n  {smc.get('premium_discount', 'N/A')}\n"
        f"LIQUIDITY DIRECTION\n  {smc.get('liquidity_direction', 'N/A')}\n\n"
        f"OVERALL BIAS: {smc.get('overall_bias', 'N/A')}"
    )

    await status.delete()

    try:
        buf = generate_debug_smc_chart(tail_df, smc, lookback=lb)
        await update.message.reply_photo(
            photo=buf,
            caption=(
                f"SMC Debug  •  BOS:{smc.get('bos_count',0)}  "
                f"CHoCH:{smc.get('choch_count',0)}  "
                f"OBs:{len(smc.get('order_blocks',[]))}  "
                f"FVGs:{len(smc.get('fvg_list',[]))}  "
                f"Sweeps:{smc.get('sweep_count',0)}"
            ),
            reply_markup=back_to_menu(),
        )
    except Exception as e:
        logger.error("Debug SMC chart error: %s", e)

    await update.message.reply_text(text, reply_markup=back_to_menu())


# ── /debugconfluence ──────────────────────────────────────────────────────────

async def cmd_debugconfluence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Full confluence engine debug dump.
    Shows every component score, its max, percentage, and the note explaining the score.
    """
    status = await update.message.reply_text("⏳ Computing full confluence breakdown…")

    data = fetch_gold_data()
    if not data:
        await status.edit_text("Could not fetch gold data.", reply_markup=back_to_menu())
        return

    h1_df = data["h1_df"]
    h4_df = data["h4_df"]

    fib    = run_fibonacci_analysis(h1_df, lookback=_LOOKBACK_H1)
    smc    = run_smc_analysis(h1_df, lookback=3)
    sess   = analyze_session(h1_df, h4_df)
    result = calculate_confluence(data, h1_df, smc_result=smc, fib_result=fib, session_data=sess)

    bd = result.get("breakdown", {})
    maxima = {"TF Alignment": 25, "SMC": 20, "Fibonacci": 15, "RSI": 15, "Session": 15, "Volatility": 10}

    factor_lines = []
    for factor, (score, note) in bd.items():
        maxv = maxima.get(factor, 100)
        pct  = score / maxv * 100
        bar_filled = int(pct // 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        rating = "HIGH" if pct >= 70 else ("MED" if pct >= 40 else "LOW")
        factor_lines.append(
            f"{factor:15s}  [{bar}]  {score:4.1f}/{maxv}  ({pct:3.0f}%)  [{rating}]\n"
            f"               {note}"
        )

    total = result["total"]
    total_bar = "█" * int(total // 10) + "░" * (10 - int(total // 10))
    direction = "▲ BUY" if result["direction"] == "BUY" else "▼ SELL"
    strength  = result["signal_strength"]

    # Raw input data shown for verification
    raw_inputs = (
        f"RAW INPUTS\n"
        f"  Price:          {data['price']}\n"
        f"  1H Bias:        {data['h1_bias']} ({data['h1_pct']:+.2f}%)\n"
        f"  4H Trend:       {data['h4_trend']} ({data['h4_pct']:+.2f}%)\n"
        f"  Daily Momentum: {data['d1_momentum']} ({data['d1_pct']:+.2f}%)\n"
        f"  Alignment:      {data['alignment']}\n"
        f"  Volatility:     {data['volatility']}\n"
        f"  Session:        {sess.get('current_session', 'N/A')}\n"
        f"  Session Bias:   {sess.get('session_bias', 'N/A')}\n"
        f"  Continuation:   {sess.get('continuation_pct', 0):.0f}%\n"
        f"  SMC Bias:       {smc.get('overall_bias', 'N/A')}\n"
        f"  BOS:            {smc.get('bos_count', 0)}\n"
        f"  CHoCH:          {smc.get('choch_count', 0)}\n"
        f"  OBs:            {len(smc.get('order_blocks', []))}\n"
        f"  FVGs:           {len(smc.get('fvg_list', []))}\n"
        f"  Sweeps:         {smc.get('sweep_count', 0)}\n"
    )
    if fib:
        raw_inputs += (
            f"  Fib nearest:    {fib.get('nearest_level', 'N/A')} at {fib.get('nearest_price', 'N/A')}\n"
            f"  Fib confluence: {fib.get('confluence_score', 0):.0f}%\n"
            f"  RSI:            {fib.get('rsi', 0)}\n"
        )

    text = (
        f"DEBUG — Confluence Engine\n"
        f"{'─' * 34}\n\n"
        f"{raw_inputs}\n"
        f"COMPONENT SCORES\n"
        f"{'─' * 34}\n"
        + "\n\n".join(factor_lines)
        + f"\n\n{'─' * 34}\n"
        f"TOTAL  [{total_bar}]  {total:.0f} / 100\n"
        f"Signal: {direction}   Strength: {strength}"
    )

    await status.delete()

    try:
        buf = generate_debug_confluence_chart(result)
        await update.message.reply_photo(
            photo=buf,
            caption=f"Confluence Debug  •  {total:.0f}/100  {direction}  ({strength})",
            reply_markup=back_to_menu(),
        )
    except Exception as e:
        logger.error("Debug confluence chart error: %s", e)

    await update.message.reply_text(text, reply_markup=back_to_menu())
