"""
Rating movement by tier — does rating volatility already correlate with
a player's rating level under the current K-factor?

Since K-factor is a linear scalar on rating_change, whatever pattern
exists today at K=20 would simply be amplified (not reshaped) by a
higher K for Round 2. So the real question is: does movement magnitude
already vary by rating tier under the current system?

Uses each game's actual player_pre_rating at the time of that game
(not a simplified current-rating snapshot), across the full historical
Player_Game_Log.

Usage:
  python3 rating_movement_by_tier.py
"""

from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
XLSX_PATH = REPO_ROOT / "output" / "pickleball_model_latest.xlsx"

BIN_WIDTH = 100


def main():
    print("=" * 70)
    print("RATING MOVEMENT BY TIER")
    print("=" * 70)
    print(__doc__.split("Usage:")[0].strip())
    print("=" * 70)
    print()

    log = pd.read_excel(XLSX_PATH, sheet_name="Player_Game_Log")
    rated = log[log["include_in_ratings"] == "Yes"].dropna(
        subset=["player_pre_rating", "rating_change"]
    ).copy()

    rated["abs_change"] = rated["rating_change"].abs()
    rated["tier"] = (rated["player_pre_rating"] // BIN_WIDTH * BIN_WIDTH).astype(int)

    grouped = rated.groupby("tier").agg(
        n_games=("abs_change", "size"),
        avg_abs_change=("abs_change", "mean"),
        avg_signed_change=("rating_change", "mean"),
        median_abs_change=("abs_change", "median"),
    ).sort_index()

    print(f"{'Tier':>12} | {'Games':>7} | {'Avg |Δ|':>9} | {'Median |Δ|':>11} | {'Avg Signed Δ':>13}")
    print("-" * 70)
    for tier, row in grouped.iterrows():
        label = f"{tier}-{tier + BIN_WIDTH}"
        print(f"{label:>12} | {int(row['n_games']):>7} | {row['avg_abs_change']:>9.2f} | "
              f"{row['median_abs_change']:>11.2f} | {row['avg_signed_change']:>+13.2f}")

    print()
    overall_avg = rated["abs_change"].mean()
    print(f"Overall average |rating change| per game (all tiers): {overall_avg:.2f}")
    print()

    # Correlation check: does pre-game rating predict movement magnitude?
    corr = rated["player_pre_rating"].corr(rated["abs_change"])
    print(f"Correlation (player_pre_rating vs. |rating_change|): {corr:+.3f}")
    print("(near 0 = no tier relationship; negative = lower-rated players move MORE;")
    print(" positive = higher-rated players move MORE, i.e. movement already")
    print(" concentrates in the upper tiers under the CURRENT K-factor, and a")
    print(" juiced K for Round 2 would amplify that same concentration.)")


if __name__ == "__main__":
    main()
