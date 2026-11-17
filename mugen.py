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
from openai import OpenAI
from pydantic import BaseModel

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

def review_and_save_round(round_num: int, round_turns: list, my_hp: int, enemy_hp: int):
    """ラウンド終了時に戦況データをLLMに分析させ、tactics.md に記録する"""
    if not round_turns:
        return

    if my_hp > enemy_hp:
        winner = "勝利（WIN）"
    elif my_hp < enemy_hp:
        winner = "敗北（LOSE）"
    else:
        winner = "引き分け（DRAW）"

    total_dealt = sum(t.get("damage_dealt", 0) for t in round_turns)
    total_taken = sum(t.get("damage_taken", 0) for t in round_turns)
    hit_moves = list(set(t["action"] for t in round_turns if t.get("damage_dealt", 0) > 0))
    hurt_actions = list(set(t["action"] for t in round_turns if t.get("damage_taken", 0) > 0))
    actions_seq = [t["action"] for t in round_turns]

    review_prompt = f"""あなたは格闘ゲームMUGENのAI（イカ娘）の戦術コーチ兼プレイヤーです。
第{round_num}ラウンドが終了しました。対戦データを簡潔に反省・分析し、次のラウンドで勝つための戦術メモを作成してください。
【対戦結果】
・結果: {winner} (自HP: {my_hp} / 敵HP: {enemy_hp})
・与えた総ダメージ: {total_dealt} / 受けた総ダメージ: {total_taken}
・有効だった技: {hit_moves or 'なし'}
・被弾した行動: {hurt_actions or 'なし'}
・直近の技の流れ: {actions_seq[-10:]}

以下のMarkdown形式で短く簡潔に出力してください:
### 勝因・敗因の分析
（2〜3行で簡潔に）
### 次ラウンドの戦術方針
・（間合いや相手の動きに応じた具体的な技指定アドバイス1）
・（具体的な技指定アドバイス2）"""

    analysis_text = ""
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "格闘ゲームの対戦データを分析して短い戦術メモを作成するコーチです。"},
                {"role": "user", "content": review_prompt},
            ],
            max_tokens=250,
            temperature=0.7,
            extra_body={"reasoning_effort": "none"},
        )
        choice = response.choices[0]
        analysis_text = (choice.message.content or "").strip()
        if not analysis_text:
            reasoning = getattr(choice.message, "reasoning_content", None) or getattr(choice.message, "reasoning", None)
            if reasoning:
                analysis_text = reasoning.strip()
    except Exception as e:
        analysis_text = f"### 対戦結果\n与ダメ: {total_dealt}, 被ダメ: {total_taken}\n### 次ラウンドの戦術方針\n・間合いを意識して飛び道具(ikasumi_z)と牽制を軸に戦う"

    append_tactics(round_num, winner, my_hp, enemy_hp, analysis_text)
    print("=" * 65)
    print(f"📝 [戦術反省完了] 第{round_num}ラウンドの戦術メモを {TACTICS_FILE} に書き出しました！")
    print(analysis_text)
    print("=" * 65 + "\n")

# ==========================================
# 3. LLMクライアント設定
# ==========================================
client = OpenAI(
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio",
)
MODEL_NAME = "qwen/qwen3.5-9b"

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

    y_min = max(0, int(46 * scale_y))
    y_max = min(h - 1, int(66 * scale_y))

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

def detect_characters_and_distance(cv_img: np.ndarray, last_my_x: int, last_enemy_x: int) -> tuple[int, int, int, bool, str]:
    h, w, _ = cv_img.shape
    y1, y2 = int(h * 0.45), int(h * 0.80)
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
    suppress_radius = int(bw * 0.18)
    suppressed[max(0, p1 - suppress_radius):min(bw, p1 + suppress_radius)] = 0
    p2 = int(np.argmax(suppressed))

    pos_a, pos_b = min(p1, p2), max(p1, p2)

    dist_a_is_me = abs(pos_a - last_my_x) + abs(pos_b - last_enemy_x)
    dist_b_is_me = abs(pos_b - last_my_x) + abs(pos_a - last_enemy_x)

    if dist_a_is_me <= dist_b_is_me:
        my_x, enemy_x = pos_a, pos_b
    else:
        my_x, enemy_x = pos_b, pos_a

    facing_right = (my_x < enemy_x)
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

def check_game_status(cv_img: np.ndarray, p1_hp: int, p2_hp: int) -> str:
    if p1_hp == 0 or p2_hp == 0:
        return "KO"

    mean_val = np.mean(cv_img)
    if mean_val < 35:
        return "FINISHED"

    if _tpl_fight is not None:
        res_f = cv2.matchTemplate(cv_img, _tpl_fight, cv2.TM_CCOEFF_NORMED)
        if float(res_f.max()) > 0.65:
            return "FIGHT"

    if _tpl_ko is not None:
        res_k = cv2.matchTemplate(cv_img, _tpl_ko, cv2.TM_CCOEFF_NORMED)
        if float(res_k.max()) > 0.65:
            return "KO"

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

    battle_state = "WAITING_FIGHT"

    # 動的な技一覧プロンプトテキストを作成（LM Studioのコンテキスト制限に配慮したコンパクト形式）
    moves_guide_lines = []
    for mid, mdata in MOVES_DICT.items():
        moves_guide_lines.append(f"{mid}:{mdata['name']}[{mdata['range']}]")
    moves_guide_text = ", ".join(moves_guide_lines)
    allowed_actions = list(MOVES_DICT.keys())

    system_prompt = f"""あなたは格闘ゲームMUGENのAI（操作キャラ: {CHAR_DATA.get('character_name', CURRENT_CHAR)}）です。
相手との距離・左右関係・HP状況を見て、最適な技を技一覧から1つ選んでください。
【技一覧】
{moves_guide_text}
【方針】
・遠距離: 飛び道具(ikasumi_z)やダッシュで接近
・中距離: 牽制(heavy, norm_4y, ikasumi_trap)や突進
・至近距離: 小技(norm_5x)や投げ(throw_b)、対地昇竜(ikashoryu_x)
・相手ジャンプ: 対空昇竜(ikashoryu_y)や対空技
前置き不要。必ず以下のJSONのみを出力してください:
{{"thought": "戦況判断", "action": "技ID", "talk": "一言"}}"""

    print("=" * 65)
    print(f"MUGEN AI バトルシステム（操作キャラ: {CHAR_DATA.get('character_name', CURRENT_CHAR)}）")
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
        status = check_game_status(cv_img, p1_hp, p2_hp)

        # 1. FIGHT待ち
        if battle_state == "WAITING_FIGHT":
            if status == "FIGHT" or (p1_hp < 1000 or p2_hp < 1000):
                print(">>> 💥 FIGHT! 戦闘開始を検知しました！行動を開始します！ <<<\n")
                battle_state = "FIGHTING"
                time.sleep(0.3)
            else:
                time.sleep(0.2)
                continue

        # 2. KO・ラウンド終了待機
        if battle_state == "ROUND_OVER":
            if status == "FIGHT" or (p1_hp == 1000 and p2_hp == 1000):
                print(f">>> 🔄 第{round_num}ラウンドが開始されました！前回の戦術方針を適用します <<<\n")
                battle_state = "FIGHTING"
                turn = 0
                history.clear()
                round_turns.clear()
                latest_tactics = get_latest_tactics()
            else:
                time.sleep(0.5)
                continue

        # 3. 戦闘中 -> KO検知
        if status in ["KO", "FINISHED"]:
            print(f">>> 🏆 K.O. 検出！第{round_num}ラウンドが終了しました (自分HP:{p1_hp}, 相手HP:{p2_hp}) <<<")
            print(">>> コマンド入力を停止し、戦術ノート（tactics.md）の反省・分析を行います...\n")
            battle_state = "ROUND_OVER"
            gamepad.reset()
            gamepad.update()

            # ラウンドの反省分析を実行し tactics.md に追記
            review_and_save_round(round_num, round_turns, p1_hp, p2_hp)
            round_num += 1
            round_turns.clear()
            latest_tactics = get_latest_tactics()

            time.sleep(1.0)
            continue

        turn += 1

        # 位置・距離・めくり判定
        my_x, enemy_x, distance, facing_right, dist_desc = detect_characters_and_distance(cv_img, my_x, enemy_x)
        side_desc = "自分が左（相手は右）" if facing_right else "★めくり発生！自分が右（相手は左）"

        # AIへのプロンプト（tactics.md の反省メモを注入）
        user_msg = (
            f"【戦況】\n"
            f"・位置関係: {side_desc}\n"
            f"・相手との距離: {distance}px {dist_desc}\n"
            f"・自分のHP: {p1_hp}/1000 (直前の被ダメ: {last_damage_taken})\n"
            f"・相手のHP: {p2_hp}/1000 (直前の与ダメ: {last_damage_dealt})\n"
            f"・直近の行動履歴: {history[-5:]}\n"
            f"【前回の反省方針(tactics.md)】\n{latest_tactics}\n"
            f"前置き不要。上記方針を参考に、次の行動をJSON形式のみで出力してください。"
        )

        raw_text = ""
        try:
            try:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=150,
                    temperature=0.7,
                    extra_body={"reasoning_effort": "none"},
                )
            except Exception:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=150,
                    temperature=0.7,
                )

            choice = response.choices[0]
            raw_text = (choice.message.content or "").strip()
            if not raw_text:
                reasoning = getattr(choice.message, "reasoning_content", None) or getattr(choice.message, "reasoning", None)
                if reasoning:
                    raw_text = reasoning.strip()
        except Exception as api_err:
            print(f"[API警告] 呼び出しエラー: {api_err}。安全のためガードを実行します。")

        decision = None
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            try:
                decision = json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # フォールバック抽出
        if not decision or "action" not in decision:
            pattern = r'["\']action["\']\s*:\s*["\'](' + "|".join(allowed_actions) + r')["\']'
            act_match = re.search(pattern, raw_text)
            if act_match:
                decision = {
                    "thought": "状況に合わせて技を繰り出す",
                    "action": act_match.group(1),
                    "talk": "いくぞ！",
                }

        if not decision or "action" not in decision:
            decision = {
                "thought": "安全のためガード",
                "action": "guard",
                "talk": "一旦守る！",
            }

        action = decision["action"]
        thought = decision.get("thought", "")
        talk = decision.get("talk", "")

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
            "character": CURRENT_CHAR,
            "action": action,
            "move_name": move_name,
            "command": cmd_str,
            "thought": thought,
            "talk": talk,
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
