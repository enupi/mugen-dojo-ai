#!/usr/bin/env python3
"""
manage_history.py
=================
MUGEN AI の戦績履歴 (tactics.md および logs/battle_*.jsonl) を管理・修正するためのスクリプト。
誤った勝敗判定や認識ミスがあった際に、直前ラウンドの無効化・取り消し、または結果の反転・修正を行います。

主な使い方:
  python manage_history.py list            # 直近のラウンド記録一覧を表示
  python manage_history.py undo            # 直前のラウンド記録を無効化（[無効] タグ付与）
  python manage_history.py remove          # 直前のラウンド記録を tactics.md から完全削除
  python manage_history.py fix             # 直前のラウンドの勝敗（WIN/LOSE）を反転
  python manage_history.py fix --winner WIN    # 直前のラウンドの勝敗を「勝利（WIN）」に強制修正
  python manage_history.py fix --winner LOSE   # 直前のラウンドの勝敗を「敗北（LOSE）」に強制修正
"""

import os
import glob
import re
import argparse
from datetime import datetime

TACTICS_FILE = "tactics.md"
LOGS_DIR = "logs"

def get_latest_log_file() -> str | None:
    """最新のログファイルパスを取得する"""
    if not os.path.exists(LOGS_DIR):
        return None
    files = glob.glob(os.path.join(LOGS_DIR, "battle_*.jsonl"))
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

def parse_tactics_rounds(content: str) -> tuple[str, list[dict]]:
    """tactics.md のヘッダーと各ラウンドの内容をパースする"""
    parts = content.split("## Round ")
    header = parts[0]
    rounds = []
    for p in parts[1:]:
        full_text = "## Round " + p
        lines = p.strip().splitlines()
        first_line = lines[0] if lines else ""
        # 例: 1 [2026-11-18 00:01:19] - 結果: 敗北（LOSE） (自HP: 0 / 敵HP: 783)
        # または [無効] が含まれる場合
        m = re.match(r"^(\d+)\s*\[(.*?)\]\s*(?:\[(.*?)\])?\s*-\s*結果:\s*(.*?)(?:\s*\(|$)", first_line)
        round_num = m.group(1) if m else "?"
        timestamp = m.group(2) if m else ""
        tag = m.group(3) if (m and m.group(3)) else ("無効" if "[無効]" in first_line else "")
        winner = m.group(4).strip() if m else ""

        rounds.append({
            "raw": full_text,
            "round_num": round_num,
            "timestamp": timestamp,
            "tag": tag,
            "winner": winner,
            "first_line": first_line,
        })
    return header, rounds

def list_rounds(n: int = 5):
    """直近 n 件のラウンドを表示する"""
    if not os.path.exists(TACTICS_FILE):
        print(f"⚠️ {TACTICS_FILE} が見つかりません。")
        return

    with open(TACTICS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    _, rounds = parse_tactics_rounds(content)
    if not rounds:
        print("記録されているラウンドはありません。")
        return

    print("=" * 65)
    print(f"📋 直近のラウンド履歴 (全{len(rounds)}件中 直近{min(n, len(rounds))}件):")
    print("=" * 65)
    for idx, r in enumerate(rounds[-n:], 1):
        status_tag = f"【{r['tag']}】" if r['tag'] else "【有効】"
        print(f"[{len(rounds) - min(n, len(rounds)) + idx}] Round {r['round_num']} ({r['timestamp']}) {status_tag} - 結果: {r['winner']}")
    print("=" * 65)

def undo_latest_round(dry_run: bool = False):
    """直前のラウンドに [無効] タグを付与する"""
    if not os.path.exists(TACTICS_FILE):
        print(f"⚠️ {TACTICS_FILE} が見つかりません。")
        return

    with open(TACTICS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    header, rounds = parse_tactics_rounds(content)
    if not rounds:
        print("無効化できるラウンドがありません。")
        return

    last_round = rounds[-1]
    if last_round["tag"] == "無効" or "[無効]" in last_round["first_line"]:
        print(f"ℹ️ 直前の Round {last_round['round_num']} は既に [無効] になっています。")
        return

    # 見出し行に [無効] を挿入
    new_raw = last_round["raw"].replace(
        last_round["first_line"],
        last_round["first_line"].replace("] - 結果:", "] [無効] - 結果:")
    )
    rounds[-1]["raw"] = new_raw

    new_content = header + "".join(r["raw"] for r in rounds)

    if dry_run:
        print("[ドライラン] 以下の内容に更新されます:")
        print(new_raw[:200])
        return

    with open(TACTICS_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"✅ Round {last_round['round_num']} ({last_round['timestamp']}) を【無効】に設定しました。")
    print(f"   ※ AIは次回以降、このラウンドの戦術方針を読み飛ばします。")

def remove_latest_round():
    """直前のラウンドを tactics.md から完全に削除する"""
    if not os.path.exists(TACTICS_FILE):
        print(f"⚠️ {TACTICS_FILE} が見つかりません。")
        return

    with open(TACTICS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    header, rounds = parse_tactics_rounds(content)
    if not rounds:
        print("削除できるラウンドがありません。")
        return

    removed = rounds.pop()
    new_content = header + "".join(r["raw"] for r in rounds)

    with open(TACTICS_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"🗑️ Round {removed['round_num']} ({removed['timestamp']}) の記録を tactics.md から削除しました。")

def fix_latest_round(winner_override: str | None = None):
    """直前ラウンドの勝敗結果を反転または上書きする"""
    if not os.path.exists(TACTICS_FILE):
        print(f"⚠️ {TACTICS_FILE} が見つかりません。")
        return

    with open(TACTICS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    header, rounds = parse_tactics_rounds(content)
    if not rounds:
        print("修正できるラウンドがありません。")
        return

    last_round = rounds[-1]
    curr_first = last_round["first_line"]

    if winner_override:
        if "WIN" in winner_override.upper():
            new_winner = "勝利（WIN）"
        elif "LOSE" in winner_override.upper():
            new_winner = "敗北（LOSE）"
        else:
            new_winner = winner_override
    else:
        # 自動反転
        if "勝利" in curr_first or "WIN" in curr_first:
            new_winner = "敗北（LOSE）"
        else:
            new_winner = "勝利（WIN）"

    # 見出しおよび本文の勝敗表記を置換
    new_first = re.sub(r"結果:\s*[^(\n]+", f"結果: {new_winner} ", curr_first)
    new_raw = last_round["raw"].replace(curr_first, new_first)
    # 本文の「結果: 敗北」や「結果: 勝利」も置換
    new_raw = re.sub(r"・結果:\s*[^\n]+", f"・結果: {new_winner}", new_raw)

    rounds[-1]["raw"] = new_raw
    new_content = header + "".join(r["raw"] for r in rounds)

    with open(TACTICS_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"✏️ Round {last_round['round_num']} ({last_round['timestamp']}) の結果を【{new_winner}】に修正しました！")

def main():
    parser = argparse.ArgumentParser(description="MUGEN AI 戦績・戦術メモ管理ツール")
    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="直近のラウンド履歴一覧を表示")
    p_list.add_argument("-n", type=int, default=5, help="表示件数 (デフォルト: 5)")

    # undo
    subparsers.add_parser("undo", help="直前のラウンドに [無効] マークを付けてAIの読み込み対象から除外")

    # remove
    subparsers.add_parser("remove", help="直前のラウンドを tactics.md から完全に削除")

    # fix
    p_fix = subparsers.add_parser("fix", help="直前ラウンドの勝敗（WIN/LOSE）を反転または修正")
    p_fix.add_argument("--winner", choices=["WIN", "LOSE", "win", "lose"], help="勝敗を明示的に指定 (WIN または LOSE)")

    args = parser.parse_args()

    if args.command == "list" or not args.command:
        list_rounds(args.n if hasattr(args, "n") else 5)
    elif args.command == "undo":
        undo_latest_round()
    elif args.command == "remove":
        remove_latest_round()
    elif args.command == "fix":
        fix_latest_round(args.winner)

if __name__ == "__main__":
    main()
