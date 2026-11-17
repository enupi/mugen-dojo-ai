import time
import vgamepad as vg

gamepad = vg.VX360Gamepad()
print("仮想コントローラーを接続しました。")
print("JoyToKeyやMUGENの入力設定画面を開いてください。\n")

# (表示名, 入力タイプ, 値)
inputs_to_assign = [
    ("Up (上 / Stick1 ↑)", "stick", (0, 32767)),
    ("Down (下 / Stick1 ↓)", "stick", (0, -32768)),
    ("Left (左 / Stick1 ←)", "stick", (-32768, 0)),
    ("Right (右 / Stick1 →)", "stick", (32767, 0)),
    ("A (Button 1)", "button", vg.XUSB_BUTTON.XUSB_GAMEPAD_A),
    ("B (Button 2)", "button", vg.XUSB_BUTTON.XUSB_GAMEPAD_B),
    ("C (Button 6 / RB)", "button", vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER),
    ("X (Button 3)", "button", vg.XUSB_BUTTON.XUSB_GAMEPAD_X),
    ("Y (Button 4)", "button", vg.XUSB_BUTTON.XUSB_GAMEPAD_Y),
    ("Z (Button 5 / LB)", "button", vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER),
    ("Start (Button 8)", "button", vg.XUSB_BUTTON.XUSB_GAMEPAD_START),
]

for label, input_type, val in inputs_to_assign:
    input(f"設定画面で【 {label} 】の入力待ち状態にしてから、ここで Enter を押してください...")
    print("  -> 3秒後に入力を送信します。急いで対象ウィンドウをアクティブにしてください！")
    time.sleep(3)

    if input_type == "stick":
        x, y = val
        gamepad.left_joystick(x_value=x, y_value=y)
        gamepad.update()
        time.sleep(0.2)
        gamepad.left_joystick(x_value=0, y_value=0)
        gamepad.update()
    elif input_type == "button":
        gamepad.press_button(button=val)
        gamepad.update()
        time.sleep(0.2)
        gamepad.release_button(button=val)
        gamepad.update()

    print(f"  -> {label} を送信しました！\n")

print("すべての入力設定が完了しました！設定を保存してください。")