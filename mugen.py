import os
import re
import json
import time
import ctypes
from datetime import datetime
import numpy as np
import cv2
from PIL import Image
import mss
import pygetwindow as gw
import vgamepad as vg
import requests
from dotenv import load_dotenv

# .env から LIQUID_API_KEY を読み込む
load_dotenv()

# ==========================================
# 0. 初期設定・DPI Awareness
# ==========================================
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ディレクトリの自動作成
CHARACTERS_DIR = "characters"
LOGS_DIR = "logs"
os.makedirs(CHARACTERS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# 操作するキャラクター（characters/{CHAR_NAME}.json を読み込みます）
CURRENT_CHAR = "ikamusume"

# ログファイル名（試合開始日時でファイル作成）
SESSION_START_TIME = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOGS_DIR, f"battle_{CURRENT_CHAR}_{SESSION_START_TIME}.jsonl")
TACTICS_FILE = "tactics.md"  # ラウンドごとの戦術メモ蓄積ファイル

DEBUG_IMG_PATH = "debug_hp_capture.png"
TPL_FIGHT_PATH = "tpl_fight.png"
TPL_KO_PATH = "tpl_ko.png"
TPL_TIMEOVER_PATH = "time-over.png"
TPL_TIME_PATH = "tpl_time.png"
TPL_SELECT_PATH = "versus-mode_select.png"
TPL_V_PATH = "tpl_v.png"
IKAMUSUME_IMG_PATH = "ikamusume.png"

# ==========================================
# 1. コントローラーとコマンド入力エンジン
# ==========================================
gamepad = vg.VX360Gamepad()

BUTTON_MAP = {
    "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "Z": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "C": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
}

DIRECTIONS = {
    "5": (0, 0),
    "6": (32767, 0),
    "4": (-32768, 0),
    "2": (0, -32768),
    "8": (0, 32767),
    "1": (-32768, -32768),
    "3": (32767, -32768),
    "7": (-32768, 32767),
    "9": (32767, 32767),
}

INVERT_DIR = {
    "5": "5", "2": "2", "8": "8",
    "6": "4", "4": "6",
    "3": "1", "1": "3",
    "9": "7", "7": "9",
}

def execute_command_string(cmd_str: str, facing_right: bool):
    """
    テンキーコマンド（例: '236Z', '623Y', '22X', '66', '4', '3'等）を
    キャラクターの向き（左右）に応じて自動反転しながら実行する
    """
    gamepad.reset()
    gamepad.update()

    # ガード (4)
    if cmd_str == "4":
        dir_key = "4" if facing_right else "6"
        gx, gy = DIRECTIONS[dir_key]
        gamepad.left_joystick(gx, gy)
        gamepad.update()
        time.sleep(0.8)
        gamepad.reset()
        gamepad.update()
        return

    # ほふく前進 (3)
    if cmd_str == "3":
        dir_key = "3" if facing_right else "1"
        gx, gy = DIRECTIONS[dir_key]
        gamepad.left_joystick(gx, gy)
        gamepad.update()
        time.sleep(0.5)
        gamepad.reset()
        gamepad.update()
        return

    # 前ダッシュ (66)
    if cmd_str == "66":
        dir_key = "6" if facing_right else "4"
        gx, gy = DIRECTIONS[dir_key]
        for _ in range(2):
            gamepad.left_joystick(gx, gy)
            gamepad.update()
            time.sleep(0.04)
            gamepad.left_joystick(0, 0)
            gamepad.update()
            time.sleep(0.03)
        time.sleep(0.1)
        gamepad.reset()
        gamepad.update()
        return

    # 方向キーとボタンの分離
    # 数字部分（1-9）と英字ボタン部分（X, Y, Z, A, B, C, +）に分離
    dir_part = "".join(ch for ch in cmd_str if ch in "123456789")
    btn_part = "".join(ch for ch in cmd_str if ch not in "123456789").upper()

    # ボタンリスト（同時押し対応: 例 "X+Y+Z" -> ["X", "Y", "Z"], "X+Y" -> ["X", "Y"]）
    buttons = [b.strip() for b in btn_part.split("+") if b.strip() in BUTTON_MAP]

    # めくり時の左右反転
    dirs = list(dir_part)
    if not facing_right:
        dirs = [INVERT_DIR[d] for d in dirs]

    # 同一方向の連続入力（例: '22'）の間にニュートラルを挟む
    expanded_dirs = []
    for i, d in enumerate(dirs):
        if i > 0 and d == dirs[i - 1]:
            expanded_dirs.append("5")
        expanded_dirs.append(d)

    # 方向キー入力シーケンス
    for d in expanded_dirs:
        gx, gy = DIRECTIONS[d]
        gamepad.left_joystick(gx, gy)
        gamepad.update()
        time.sleep(0.025)

    # 最後の方向キーが入った状態でボタンを押下（同時押しボタンを全て押す）
    if buttons:
        for b_name in buttons:
            gamepad.press_button(button=BUTTON_MAP[b_name])
        gamepad.update()
        time.sleep(0.09)
        for b_name in buttons:
            gamepad.release_button(button=BUTTON_MAP[b_name])
        gamepad.update()
    elif not dirs and buttons:
        # 単発ボタン連打
        for b_name in buttons:
            for _ in range(2):
                gamepad.press_button(button=BUTTON_MAP[b_name])
                gamepad.update()
                time.sleep(0.05)
                gamepad.release_button(button=BUTTON_MAP[b_name])
                gamepad.update()
                time.sleep(0.03)

    time.sleep(0.05)
    gamepad.reset()
    gamepad.update()

# ==========================================
# 2. キャラクター定義ファイルの読み込み
# ==========================================
def load_character_moves(char_name: str) -> dict:
    char_path = os.path.join(CHARACTERS_DIR, f"{char_name}.json")
    if not os.path.exists(char_path):
        raise FileNotFoundError(f"キャラクター定義ファイルが見つかりません: {char_path}")

    with open(char_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

CHAR_DATA = load_character_moves(CURRENT_CHAR)
MOVES_DICT = CHAR_DATA.get("moves", {})

# ==========================================
# 2.5 戦術ノート（tactics.md）管理モジュール
# ==========================================
def append_tactics(round_num: int, winner: str, my_hp: int, enemy_hp: int, analysis_text: str):
    """tactics.md にラウンドごとの分析メモを追記する"""
    header = ""
    if not os.path.exists(TACTICS_FILE) or os.path.getsize(TACTICS_FILE) == 0:
        header = "# MUGEN AI 戦術ノート (Tactics Note)\n\n各ラウンド終了後にAIが自動で反省・自己分析した戦術メモの記録です。\n\n---\n"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## Round {round_num} [{timestamp}] - 結果: {winner} (自HP: {my_hp} / 敵HP: {enemy_hp})\n\n{analysis_text.strip()}\n\n---\n"
    with open(TACTICS_FILE, "a", encoding="utf-8") as f:
        if header:
            f.write(header)
        f.write(entry)

def get_latest_tactics() -> str:
    """tactics.md から直近の戦術方針を抽出する（プロンプト用）"""
    if not os.path.exists(TACTICS_FILE):
        return "・状況に応じて間合いを意識して戦う"
    try:
        with open(TACTICS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        parts = content.split("## Round ")
        if len(parts) > 1:
            last_round = parts[-1]
            lines = last_round.strip().splitlines()
            # 「### 次ラウンドの戦術方針」以降の箇条書き行を抽出
            tactics_lines = []
            capture = False
            for line in lines:
                if "次ラウンド" in line or "戦術方針" in line or "方針" in line:
                    capture = True
                    continue
                if capture and line.strip().startswith("・"):
                    tactics_lines.append(line.strip())
                elif capture and line.startswith("###"):
                    break
            if tactics_lines:
                return "\n".join(tactics_lines[:3])
            # なければ直近の行を返す
            valid_lines = [l.strip() for l in lines[1:] if l.strip() and not l.startswith("#") and not l.startswith("---")]
            if valid_lines:
                return "\n".join(valid_lines[:3])
    except Exception:
        pass
    return "・相手との距離に合わせて最適な技を選択する"

# ==========================================
# 3. Liquid AI 設定
# ==========================================
LIQUID_API_KEY = os.getenv("LIQUID_API_KEY")
LIQUID_API_URL = "https://api.liquid.ai/decisions/v1/systemone"
MODEL_NAME = "d1.2-ultra"

if not LIQUID_API_KEY:
    print("⚠️ [警告] .env に LIQUID_API_KEY が設定されていません。")

def review_and_save_round(round_num: int, round_turns: list, my_hp: int, enemy_hp: int, forced_winner: str = ""):
    """ラウンド終了時に戦況データをLiquid AI (d1.2-ultra)に分析させ、tactics.md に記録する"""
    if not round_turns:
        return

    total_dealt = sum(t.get("damage_dealt", 0) for t in round_turns)
    total_taken = sum(t.get("damage_taken", 0) for t in round_turns)

    # 勝敗判定（1. Vマーク確定勝敗 -> 2. 終了時HP比較 -> 3. 総与ダメ・被ダメ比較。引き分けは発生させない）
    if forced_winner:
        winner = forced_winner
    elif my_hp > enemy_hp:
        winner = "勝利（WIN）"
    elif my_hp < enemy_hp:
        winner = "敗北（LOSE）"
    else:
        winner = "勝利（WIN）" if total_dealt >= total_taken else "敗北（LOSE）"

    hit_moves = list(set(t["action"] for t in round_turns if t.get("damage_dealt", 0) > 0))
    hurt_actions = list(set(t["action"] for t in round_turns if t.get("damage_taken", 0) > 0))
    actions_seq = [t["action"] for t in round_turns]

    strategies_criteria = {
        "keep_distance": "遠距離を維持し、飛び道具(ikasumi_z)や触手で安全に牽制する",
        "rush_down": "前ダッシュ(66)やほふく前進(3)で間合いを詰め、近接攻撃や投げで崩す",
        "counter_guard": "ガードとリフレクトガード(A)を固め、相手の隙に対地・対空昇竜で反撃する",
        "zone_trap": "イカスミ設置罠(ikasumi_x)を撒いて相手の突進や起き上がりを制限する",
    }

    state_text = (
        f"第{round_num}ラウンドが終了しました。\n"
        f"結果: {winner} (自HP: {my_hp}/1000, 敵HP: {enemy_hp}/1000)\n"
        f"与ダメージ合計: {total_dealt}, 被ダメージ合計: {total_taken}\n"
        f"有効だった技: {', '.join(hit_moves) if hit_moves else 'なし'}\n"
        f"被弾した行動: {', '.join(hurt_actions) if hurt_actions else 'なし'}\n"
        f"直近の技の流れ: {actions_seq[-10:]}"
    )

    payload = {
        "model": MODEL_NAME,
        "state": state_text,
        "questions": {
            "primary_strategy": {
                "type": "choice",
                "instructions": "次ラウンドで最も勝率を上げる基本戦術方針を選択してください。",
                "criteria": strategies_criteria,
            },
            "anti_air_focus": {
                "type": "noul",
                "instructions": "相手の飛び込みや空中攻撃を強く警戒し、対空迎撃(ikashoryu_y等)を優先すべきですか？",
            },
            "aggression_bias": {
                "type": "score",
                "instructions": "次ラウンドの全体的な攻めの姿勢はどうすべきですか？",
                "criteria": ["守備重視（引き気味）", "バランス（間合い管理）", "強気（インファイト）"],
            },
        },
    }

    try:
        res = requests.post(
            LIQUID_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {LIQUID_API_KEY}", "Content-Type": "application/json"},
            timeout=8.0,
        )
        if res.status_code == 200:
            answers = res.json().get("answers", {})
            strat_choice = answers.get("primary_strategy", {}).get("choice", "keep_distance")
            strat_desc = strategies_criteria.get(strat_choice, strat_choice)
            anti_air = answers.get("anti_air_focus", {}).get("noul", 0.0)
            aggression = answers.get("aggression_bias", {}).get("score", 1.0)

            aggression_text = "守備重視" if aggression < 0.8 else ("強気（インファイト）" if aggression > 1.3 else "バランス（間合い管理）")
            anti_air_text = "対空意識を高める（相手のジャンプに昇竜待機）" if anti_air > 0.5 else "地上戦を重視する"

            analysis_text = (
                f"### 勝因・敗因の分析\n"
                f"・結果: {winner} (与ダメ: {total_dealt} / 被ダメ: {total_taken})\n"
                f"・有効技: {', '.join(hit_moves) or 'なし'} / 被弾行動: {', '.join(hurt_actions) or 'なし'}\n"
                f"### 次ラウンドの戦術方針\n"
                f"・基本方針: {strat_desc}\n"
                f"・攻勢姿勢: {aggression_text} (スコア: {aggression:.2f})\n"
                f"・対空意識: {anti_air_text} (警戒度: {anti_air:.2f})"
            )
        else:
            raise RuntimeError(f"API Error {res.status_code}: {res.text}")
    except Exception as e:
        analysis_text = (
            f"### 対戦結果\n"
            f"与ダメ: {total_dealt}, 被ダメ: {total_taken}\n"
            f"### 次ラウンドの戦術方針\n"
            f"・間合いを意識して飛び道具(ikasumi_z)と牽制を軸に戦う\n"
            f"・相手の飛び込みには対空昇竜(ikashoryu_y)を合わせる"
        )

    append_tactics(round_num, winner, my_hp, enemy_hp, analysis_text)
    print("=" * 65)
    print(f"📝 [戦術反省完了] 第{round_num}ラウンドの戦術メモを {TACTICS_FILE} に書き出しました！")
    print(analysis_text)
    print("=" * 65 + "\n")

# ==========================================
# 4. 画像認識・HP・距離モジュール
# ==========================================
def is_hp_color(r: int, g: int, b: int) -> bool:
    return (r > 150) and (g > 100) and (b < 140) and (r >= g - 30) and (g > b + 20)

def detect_hp_from_image(img: Image.Image) -> tuple[int, int]:
    arr = np.array(img.convert("RGB"))
    h, w, _ = arr.shape

    scale_x = w / 646.0
    scale_y = h / 509.0

    p1_x_start = int(29 * scale_x)
    p1_x_end = int(268 * scale_x)
    p1_total = max(1, p1_x_end - p1_x_start + 1)

    p2_x_start = int(374 * scale_x)
    p2_x_end = int(613 * scale_x)
    p2_total = max(1, p2_x_end - p2_x_start + 1)

    # 上下の金色の外枠フレーム（y=46..49, y=64..65）を拾わないよう、HPバー本体の内側（y=53..60）のみをスキャン
    y_min = max(0, int(53 * scale_y))
    y_max = min(h - 1, int(60 * scale_y))

    best_p1_count = 0
    best_p2_count = 0

    for y in range(y_min, y_max + 1):
        c1 = sum(1 for x in range(p1_x_start, min(p1_x_end + 1, w)) if is_hp_color(*arr[y, x]))
        c2 = sum(1 for x in range(p2_x_start, min(p2_x_end + 1, w)) if is_hp_color(*arr[y, x]))
        best_p1_count = max(best_p1_count, c1)
        best_p2_count = max(best_p2_count, c2)

    p1_hp = int(round((best_p1_count / p1_total) * 1000))
    p2_hp = int(round((best_p2_count / p2_total) * 1000))

    return max(0, min(1000, p1_hp)), max(0, min(1000, p2_hp))

def score_ikamusume_likeness(crop_bgr: np.ndarray) -> float:
    """
    領域内のピクセルからイカ娘（白のワンピース・帽子、水色〜青の触手）らしさをスコアリングする。
    ポーズ変化（しゃがみ、ジャンプ、技モーション、被弾）に強く、左右反転しても変わらない。
    """
    if crop_bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    # 白（ワンピース・帽子）: 彩度が低く明度が高い
    white = (s < 55) & (v > 165)
    # 水色〜青（触手・髪）: H=85..135, 彩度中以上, 明度中以上
    blue = (h >= 85) & (h <= 135) & (s > 30) & (v > 45)

    score = np.sum(white) * 1.5 + np.sum(blue) * 2.0
    return float(score)

def detect_characters_and_distance(cv_img: np.ndarray, last_my_x: int, last_enemy_x: int) -> tuple[int, int, int, bool, str]:
    h, w, _ = cv_img.shape
    y1, y2 = int(h * 0.45), int(h * 0.85)
    band = cv_img[y1:y2, :]
    bw = band.shape[1]

    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobel_abs = np.abs(sobel_x)

    margin = int(bw * 0.08)
    sobel_abs[:, :margin] = 0
    sobel_abs[:, bw - margin:] = 0

    sobel_blurred = cv2.GaussianBlur(sobel_abs, (31, 1), 0)
    th = np.percentile(sobel_blurred, 75)
    sobel_th = np.where(sobel_blurred > th, sobel_blurred, 0)

    proj = sobel_th.sum(axis=0)
    kernel = np.ones(45) / 45.0
    smoothed = np.convolve(proj, kernel, mode='same')

    p1 = int(np.argmax(smoothed))
    suppressed = smoothed.copy()
    suppress_radius = int(bw * 0.16)
    suppressed[max(0, p1 - suppress_radius):min(bw, p1 + suppress_radius)] = 0
    p2 = int(np.argmax(suppressed))

    pos_a, pos_b = min(p1, p2), max(p1, p2)

    # 1. 密着・重なり判定（2つのピークが接近しすぎている場合）
    if abs(pos_b - pos_a) < 50:
        facing_right = (last_my_x < last_enemy_x)
        return last_my_x, last_enemy_x, 30, facing_right, "【超至近距離・密着】(投げや小技、ガードが有効)"

    # 2. 左右それぞれのキャラ周辺領域を切り出してイカ娘スコア（色特徴）を比較
    crop_w = 45
    crop_a = cv_img[y1:y2, max(0, pos_a - crop_w):min(w, pos_a + crop_w)]
    crop_b = cv_img[y1:y2, max(0, pos_b - crop_w):min(w, pos_b + crop_w)]

    score_a = score_ikamusume_likeness(crop_a)
    score_b = score_ikamusume_likeness(crop_b)

    # スコアが高い方が確実にイカ娘（自分）！
    if score_a >= score_b:
        my_x, enemy_x = pos_a, pos_b
        facing_right = True
    else:
        my_x, enemy_x = pos_b, pos_a
        facing_right = False  # ★めくり発生！自分が右（相手は左）

    distance = abs(enemy_x - my_x)

    if distance < 120:
        dist_desc = "【至近距離】(弱攻撃jabや投げthrow、切り返し昇竜が有効)"
    elif distance < 260:
        dist_desc = "【中距離】(jabは届きません！強攻撃、設置罠、ダッシュ攻撃が有効)"
    else:
        dist_desc = "【遠距離】(遠すぎます！イカスミ飛び道具やダッシュで詰めるのが有効)"

    return my_x, enemy_x, distance, facing_right, dist_desc

_tpl_fight = cv2.imread(TPL_FIGHT_PATH) if os.path.exists(TPL_FIGHT_PATH) else None
_tpl_ko = cv2.imread(TPL_KO_PATH) if os.path.exists(TPL_KO_PATH) else None
_tpl_timeover = cv2.imread(TPL_TIMEOVER_PATH) if os.path.exists(TPL_TIMEOVER_PATH) else None
_tpl_time = cv2.imread(TPL_TIME_PATH) if os.path.exists(TPL_TIME_PATH) else None
_tpl_select = cv2.imread(TPL_SELECT_PATH) if os.path.exists(TPL_SELECT_PATH) else None
_tpl_v = cv2.imread(TPL_V_PATH) if os.path.exists(TPL_V_PATH) else None

def detect_victory_marks(cv_img: np.ndarray) -> tuple[int, int]:
    """
    HPバーの下に表示される勝利マーク「V」の個数 (p1_v, p2_v) を検出する
    """
    if _tpl_v is None:
        return 0, 0

    h, w, _ = cv_img.shape
    scale_x = w / 646.0
    scale_y = h / 509.0

    y1, y2 = int(80 * scale_y), int(120 * scale_y)
    p1_area = cv_img[y1:y2, int(55 * scale_x):int(145 * scale_x)]
    p2_area = cv_img[y1:y2, int(500 * scale_x):int(595 * scale_x)]

    def _count_v(area: np.ndarray) -> int:
        if area.shape[0] < _tpl_v.shape[0] or area.shape[1] < _tpl_v.shape[1]:
            return 0
        res = cv2.matchTemplate(area, _tpl_v, cv2.TM_CCOEFF_NORMED)
        count = 0
        res_copy = res.copy()
        while True:
            _, max_val, _, max_loc = cv2.minMaxLoc(res_copy)
            if max_val >= 0.72:
                count += 1
                mx = max_loc[0]
                res_copy[:, max(0, mx - 12):min(res_copy.shape[1], mx + 13)] = 0
            else:
                break
        return count

    return _count_v(p1_area), _count_v(p2_area)

def check_game_status(cv_img: np.ndarray, p1_hp: int, p2_hp: int) -> str:
    """
    ゲーム画面の状態を判定する
    戻り値:
      - 'SELECT': キャラセレクト画面（VERSUS MODE）
      - 'MENU': タイトル、VS画面など（戦闘外・入力停止）
      - 'FIGHT': FIGHT! コール中
      - 'PLAYING': 通常戦闘中
      - 'KO': ノックアウト終了
      - 'FINISHED': 暗転・リザルト
    """
    # 0. キャラセレクト画面（VERSUS MODE）の検出（戦闘がすべて終了したことの判定）
    if _tpl_select is not None:
        res_s = cv2.matchTemplate(cv_img, _tpl_select, cv2.TM_CCOEFF_NORMED)
        if float(res_s.max()) > 0.70:
            return "SELECT"

    # 1. 画面全体の平均輝度（暗転チェック）
    mean_val = np.mean(cv_img)
    if mean_val < 30:
        return "FINISHED"

    # 2. 戦闘中画面（IN_BATTLE）かどうかの判定
    has_hp_bars = (p1_hp > 0 or p2_hp > 0)
    has_timer = False

    if _tpl_time is not None:
        h, w, _ = cv_img.shape
        # タイマーは画面中央上部に存在
        timer_area = cv_img[int(h * 0.05):int(h * 0.25), int(w * 0.40):int(w * 0.60)]
        if timer_area.shape[0] >= _tpl_time.shape[0] and timer_area.shape[1] >= _tpl_time.shape[1]:
            res_t = cv2.matchTemplate(timer_area, _tpl_time, cv2.TM_CCOEFF_NORMED)
            if float(res_t.max()) > 0.55:
                has_timer = True

    # HPバーもタイマーも検出できない場合は、キャラセレクトやタイトル等の非戦闘画面！
    if not has_hp_bars and not has_timer:
        return "MENU"

    # 3. FIGHT表示チェック
    if _tpl_fight is not None:
        res_f = cv2.matchTemplate(cv_img, _tpl_fight, cv2.TM_CCOEFF_NORMED)
        if float(res_f.max()) > 0.65:
            return "FIGHT"

    # 4. KO / タイムオーバーチェック（正規の戦闘画面内でのみ判定）
    if (p1_hp == 0 or p2_hp == 0) and has_timer:
        return "KO"

    if _tpl_ko is not None:
        res_k = cv2.matchTemplate(cv_img, _tpl_ko, cv2.TM_CCOEFF_NORMED)
        if float(res_k.max()) > 0.65:
            return "KO"

    if _tpl_timeover is not None:
        res_to = cv2.matchTemplate(cv_img, _tpl_timeover, cv2.TM_CCOEFF_NORMED)
        if float(res_to.max()) > 0.65:
            return "TIMEOVER"

    return "PLAYING"

def find_mugen_window():
    """M.U.G.E.N ウィンドウを正確に検索する（コマンドプロンプトやVS Code自身を除外）"""
    try:
        for w in gw.getAllWindows():
            if not w.title:
                continue
            title_lower = w.title.lower()
            # コマンドプロンプト、PowerShell、VSCode、Pythonコンソール自身を確実に除外！
            if any(exclude in title_lower for exclude in ["python", "cmd", "prompt", "powershell", "code", "terminal"]):
                continue
            clean_title = re.sub(r"[^a-zA-Z0-9]", "", w.title).lower()
            if "mugen" in clean_title:
                return w
    except Exception:
        pass
    return None

def capture_mugen_window() -> tuple[Image.Image, np.ndarray, str]:
    target = find_mugen_window()
    window_name = "None"

    if not target:
        try:
            active = gw.getActiveWindow()
            if active and active.width > 200 and active.height > 150:
                if not any(ex in active.title.lower() for ex in ["python", "cmd", "prompt", "powershell", "code"]):
                    target = active
        except Exception:
            pass

    if target:
        window_name = target.title
        try:
            left, top, width, height = target.left, target.top, target.width, target.height
            if width > 50 and height > 50:
                with mss.MSS() as sct:
                    monitor = {"top": top, "left": left, "width": width, "height": height}
                    sct_img = sct.grab(monitor)
                    pil_img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                    try:
                        pil_img.save(DEBUG_IMG_PATH)
                    except Exception:
                        pass
                    return pil_img, cv_img, window_name
        except Exception:
            pass

    if os.path.exists("mugen_window.png"):
        pil_img = Image.open("mugen_window.png")
        cv_img = cv2.imread("mugen_window.png")
        return pil_img, cv_img, "mugen_window.png (Fallback)"

    dummy = Image.new("RGB", (646, 509), (0, 0, 0))
    return dummy, np.zeros((509, 646, 3), dtype=np.uint8), "Black dummy"

# ==========================================
# 5. メインループ
# ==========================================
def main():
    history = []
    turn = 0
    round_num = 1
    round_turns = []
    latest_tactics = get_latest_tactics()

    my_x = 200
    enemy_x = 460
    facing_right = True

    last_damage_dealt = 0
    last_damage_taken = 0
    last_valid_my_hp = 1000
    last_valid_enemy_hp = 1000
    prev_p1_v = 0
    prev_p2_v = 0

    battle_state = "WAITING_BATTLE"

    # Liquid AI Decisions API 用の技 criteria を生成
    moves_criteria = {}
    for mid, mdata in MOVES_DICT.items():
        name = mdata.get("name", mid)
        rng = mdata.get("range", "全距離")
        desc = mdata.get("desc", "")
        short_desc = desc[:45] + "..." if len(desc) > 45 else desc
        moves_criteria[mid] = f"{name}[{rng}]: {short_desc}"

    print("=" * 65)
    print(f"MUGEN AI バトルシステム（操作キャラ: {CHAR_DATA.get('character_name', CURRENT_CHAR)}）")
    print(f"意思決定モデル: Liquid AI ({MODEL_NAME})")
    print(f"キャラクター定義: characters/{CURRENT_CHAR}.json")
    print(f"対戦ログファイル: {LOG_FILE}")
    print(f"登録技数: {len(MOVES_DICT)} 種類")
    print("=" * 65)

    target_win = find_mugen_window()
    if target_win:
        print(f"[検出成功] 対象ウィンドウ: {target_win.title!r} (サイズ: {target_win.width}x{target_win.height})")
    else:
        print("[注意] MUGENウィンドウを検索中...")

    input("\n試合を開始したら Enter を押してください...")
    print("  -> MUGENウィンドウをアクティブにして監視を開始します...")

    if target_win:
        try:
            target_win.activate()
        except Exception:
            pass

    time.sleep(1.5)
    print("\n[待機中] FIGHT! の合図を待っています（戦闘開始前は入力を停止します）...")

    while True:
        pil_img, cv_img, win_title = capture_mugen_window()
        p1_hp, p2_hp = detect_hp_from_image(pil_img)
        p1_v, p2_v = detect_victory_marks(cv_img)
        status = check_game_status(cv_img, p1_hp, p2_hp)

        # 0-a. キャラセレクト画面（VERSUS MODE）の検知 -> 戦闘が完全に終了したことを判定し入力停止
        if status == "SELECT":
            gamepad.reset()
            gamepad.update()
            # 万が一最終ラウンドのKOを認識できずにセレクト画面へ戻った場合、未保存のラウンド反省を記録する
            if round_turns:
                print(f"\n>>> 🏁 キャラセレクト画面（VERSUS MODE）への復帰を検知！第{round_num}ラウンドの戦術反省を保存します <<<")
                review_and_save_round(round_num, round_turns, last_valid_my_hp, last_valid_enemy_hp)
                round_turns.clear()
                latest_tactics = get_latest_tactics()
            if battle_state != "SELECT":
                print("\n[戦闘完全終了・待機中] キャラセレクト画面（VERSUS MODE）を検知しました（キー入力完全停止・次の対戦待機）...")
                battle_state = "SELECT"
            time.sleep(0.5)
            continue

        # 0-b. その他のメニュー画面（タイトル・VS画面等）の検知・入力完全遮断
        if status == "MENU":
            gamepad.reset()
            gamepad.update()
            if battle_state != "MENU":
                print("\n[待機中] タイトルまたは非戦闘画面を検知しました（キー入力停止中・対戦開始待機）...")
                battle_state = "MENU"
            time.sleep(0.5)
            continue

        # 1. セレクト・メニュー画面から対戦画面への復帰
        if battle_state in ["WAITING_BATTLE", "MENU", "SELECT"]:
            print("\n>>> 🎮 対戦画面を検知しました！FIGHTコールを待機します <<<")
            battle_state = "WAITING_FIGHT"
            round_num = 1
            turn = 0
            prev_p1_v, prev_p2_v = 0, 0
            history.clear()
            round_turns.clear()
            time.sleep(0.3)

        # 2. FIGHT待ち
        if battle_state == "WAITING_FIGHT":
            if status == "FIGHT" or (p1_hp < 1000 or p2_hp < 1000):
                print(">>> 💥 FIGHT! 戦闘開始を検知しました！行動を開始します！ <<<\n")
                battle_state = "FIGHTING"
                prev_p1_v, prev_p2_v = p1_v, p2_v
                time.sleep(0.3)
            else:
                time.sleep(0.2)
                continue

        # 3. KO・ラウンド終了待機
        if battle_state == "ROUND_OVER":
            if status == "FIGHT" or (p1_hp == 1000 and p2_hp == 1000):
                print(f">>> 🔄 第{round_num}ラウンドが開始されました！(Vマーク 自分:{p1_v} / 相手:{p2_v}) 前回の戦術方針を適用します <<<\n")
                battle_state = "FIGHTING"
                prev_p1_v, prev_p2_v = p1_v, p2_v
                turn = 0
                history.clear()
                round_turns.clear()
                latest_tactics = get_latest_tactics()
            else:
                time.sleep(0.5)
                continue

        # 4. 戦闘中 -> KO / タイムオーバー検知 または 勝利マーク「V」増加検知
        v_increased = (p1_v > prev_p1_v) or (p2_v > prev_p2_v)
        if status in ["KO", "TIMEOVER", "FINISHED"] or v_increased:
            gamepad.reset()
            gamepad.update()

            # Vマーク点灯の確定を少し待って再取得
            if not v_increased:
                time.sleep(0.4)
                _, re_cv, _ = capture_mugen_window()
                re_v1, re_v2 = detect_victory_marks(re_cv)
                if re_v1 > prev_p1_v or re_v2 > prev_p2_v:
                    p1_v, p2_v = re_v1, re_v2
                    v_increased = True

            # Vマークが増加していれば100%確実に勝敗を特定
            forced_winner = ""
            if p1_v > prev_p1_v and p2_v == prev_p2_v:
                forced_winner = "勝利（WIN）"
            elif p2_v > prev_p2_v and p1_v == prev_p1_v:
                forced_winner = "敗北（LOSE）"

            # 暗転時などでp1_hp==0かつp2_hp==0になっていた場合は直前の有効HPを使用
            eval_my_hp = p1_hp if (p1_hp > 0 or p2_hp > 0) else last_valid_my_hp
            eval_enemy_hp = p2_hp if (p1_hp > 0 or p2_hp > 0) else last_valid_enemy_hp

            reason_text = "タイムオーバー" if status == "TIMEOVER" else "K.O."
            print(
                f">>> 🏆 第{round_num}ラウンド終了（{reason_text}）を検出！ "
                f"(自分HP:{eval_my_hp}, 相手HP:{eval_enemy_hp} | Vマーク 自分:{p1_v}, 相手:{p2_v}) <<<"
            )
            print(">>> コマンド入力を停止し、戦術ノート（tactics.md）の反省・分析を行います...\n")

            review_and_save_round(round_num, round_turns, eval_my_hp, eval_enemy_hp, forced_winner=forced_winner)
            round_num += 1
            round_turns.clear()
            history.clear()
            turn = 0
            latest_tactics = get_latest_tactics()
            prev_p1_v, prev_p2_v = p1_v, p2_v

            # 既に次ラウンドが開始されてHPが1000/1000に戻っている場合はそのままFIGHTING継続
            if v_increased and p1_hp == 1000 and p2_hp == 1000 and status == "PLAYING":
                print(f">>> 🔄 そのまま第{round_num}ラウンドへ移行します！ <<<\n")
                battle_state = "FIGHTING"
            else:
                battle_state = "ROUND_OVER"
                time.sleep(1.0)
            continue

        turn += 1

        # 位置・距離・めくり判定
        my_x, enemy_x, distance, facing_right, dist_desc = detect_characters_and_distance(cv_img, my_x, enemy_x)
        side_desc = "自分が左（相手は右）" if facing_right else "★めくり発生！自分が右（相手は左）"

        # Liquid AI Decisions API への入力状況 (state) と questions（test_d1.py形式）
        state_text = (
            f"あなたは格闘ゲームMUGENのプレイヤー（操作キャラ: {CHAR_DATA.get('character_name', CURRENT_CHAR)}）です。\n"
            f"現在の状況:\n"
            f"・位置関係: {side_desc}\n"
            f"・相手との距離: {distance}px {dist_desc}\n"
            f"・自分のHP: {p1_hp}/1000 (直前の被ダメ: {last_damage_taken})\n"
            f"・相手のHP: {p2_hp}/1000 (直前の与ダメ: {last_damage_dealt})\n"
            f"・直近の行動履歴: {', '.join(history[-5:]) if history else 'なし'}\n"
            f"・戦術メモ方針(tactics.md): {latest_tactics}"
        )

        payload = {
            "model": MODEL_NAME,
            "state": state_text,
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": "この戦況で次に取るべき最も勝率が高い行動を1つ選んでください。",
                    "criteria": moves_criteria,
                },
                "is_danger": {
                    "type": "noul",
                    "instructions": "現在、連続被弾やHP不利による危険な状況ですか？",
                },
                "aggression": {
                    "type": "score",
                    "instructions": "この場面でどれくらい強気に攻めるべきですか？",
                    "criteria": ["守備重視", "様子見", "積極的に攻撃"],
                },
            },
        }

        action = "guard"
        thought = "安全のためガード"
        talk = "一旦守るでゲソ！"
        confidence = 0.0
        danger_level = 0.0
        aggression_score = 1.0

        try:
            response = requests.post(
                LIQUID_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {LIQUID_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=4.0,
            )
            if response.status_code == 200:
                res_data = response.json()
                answers = res_data.get("answers", {})

                act_info = answers.get("next_action", {})
                chosen_act = act_info.get("choice")
                if chosen_act in MOVES_DICT:
                    action = chosen_act
                confidence = act_info.get("confidence", 0.0)

                danger_info = answers.get("is_danger", {})
                danger_level = danger_info.get("noul", 0.0)

                agg_info = answers.get("aggression", {})
                aggression_score = agg_info.get("score", 1.0)

                thought = f"危険度:{danger_level:.2f} | 攻勢度:{aggression_score:.2f} | 確信度:{confidence:.2f}"

                # 状況に応じた発言
                if danger_level > 0.6:
                    talk = "ピンチでゲソ！ここは守りを固めるでゲソ！"
                elif aggression_score > 1.4:
                    talk = "好機でゲソ！一気に攻め込むでゲソ！"
                elif distance > 260:
                    talk = "遠距離からイカスミで狙い撃ちでゲソ！"
                elif distance < 120:
                    talk = "近寄られたら返り討ちにするでゲソ！"
                else:
                    talk = "間合いを見極めて隙を突くでゲソ！"
            else:
                print(f"[API警告] ステータス: {response.status_code} ({response.text})。安全のためガードを実行します。")
        except Exception as api_err:
            print(f"[API警告] 呼び出しエラー: {api_err}。安全のためガードを実行します。")

        # 登録されている技のコマンドを取得
        move_info = MOVES_DICT.get(action, MOVES_DICT.get("guard", {"command": "4", "name": "ガード"}))
        cmd_str = move_info.get("command", "4")
        move_name = move_info.get("name", action)

        pre_my_hp, pre_enemy_hp = p1_hp, p2_hp

        print(f"--- [Turn {turn}] ---")
        print(f"[位置] {side_desc} | 距離: {distance}px")
        print(f"[思考] {thought}")
        print(f"[行動] {action} ({move_name}) コマンド: {cmd_str} | [発言] {talk}")

        # テンキーコマンド実行（向き反転対応）
        execute_command_string(cmd_str, facing_right=facing_right)
        history.append(action)

        time.sleep(0.35)

        # ダメージ計算
        post_pil, _, _ = capture_mugen_window()
        post_my_hp, post_enemy_hp = detect_hp_from_image(post_pil)
        last_valid_my_hp, last_valid_enemy_hp = post_my_hp, post_enemy_hp

        last_damage_dealt = max(0, pre_enemy_hp - post_enemy_hp)
        last_damage_taken = max(0, pre_my_hp - post_my_hp)

        hit_mark = "💥" if last_damage_dealt > 0 else "  "
        hurt_mark = "⚠️" if last_damage_taken > 0 else "  "
        print(
            f"[HP変化] 自分: {pre_my_hp} -> {post_my_hp} ({hurt_mark}-{last_damage_taken}) | "
            f"相手: {pre_enemy_hp} -> {post_enemy_hp} ({hit_mark}-{last_damage_dealt})\n"
        )

        # ラウンド集計用バッファにターンデータを蓄積
        round_turns.append({
            "turn": turn,
            "action": action,
            "move_name": move_name,
            "distance": distance,
            "damage_dealt": last_damage_dealt,
            "damage_taken": last_damage_taken,
        })

        # ログ記録
        log_record = {
            "turn": turn,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": MODEL_NAME,
            "character": CURRENT_CHAR,
            "action": action,
            "move_name": move_name,
            "command": cmd_str,
            "thought": thought,
            "talk": talk,
            "confidence": confidence,
            "danger_level": danger_level,
            "aggression_score": aggression_score,
            "distance": distance,
            "facing_right": facing_right,
            "pre_my_hp": pre_my_hp,
            "post_my_hp": post_my_hp,
            "damage_taken": last_damage_taken,
            "pre_enemy_hp": pre_enemy_hp,
            "post_enemy_hp": post_enemy_hp,
            "damage_dealt": last_damage_dealt,
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_record, ensure_ascii=False) + "\n")

        time.sleep(0.2)

if __name__ == "__main__":
    main()
