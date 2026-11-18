import cv2
import mss
import numpy as np
import pygetwindow as gw

# "M.U.G.E.N" というタイトルを含むウィンドウを探す
windows = gw.getWindowsWithTitle("M.U.G.E.N")
if not windows:
    print("MUGENのウィンドウが見つかりません！起動した状態で実行してください。")
    exit()

win = windows[0]
# ウィンドウ全体の領域を取得
monitor = {"top": win.top, "left": win.left, "width": win.width, "height": win.height}

with mss.mss() as sct:
    img = np.array(sct.grab(monitor))
    frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    cv2.imwrite("mugen_window.png", frame)
    print(f"mugen_window.png を保存しました！（サイズ: {win.width}x{win.height}）")