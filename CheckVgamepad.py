import time
import vgamepad as vg

gamepad = vg.VX360Gamepad()
print("仮想コントローラー起動中... JoyToKeyの画面で反応を確認してください (Ctrl+Cで終了)")

try:
    while True:
        # 左スティックを右に倒す (JoyToKeyで Stick1: → が黄色く光る)
        gamepad.left_joystick(x_value=32767, y_value=0)
        gamepad.update()
        time.sleep(0.5)
        gamepad.left_joystick(x_value=0, y_value=0)
        gamepad.update()
        time.sleep(0.5)

        # Aボタンを押す (JoyToKeyで Button 1 が黄色く光る)
        gamepad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        gamepad.update()
        time.sleep(0.5)
        gamepad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        gamepad.update()
        time.sleep(1.0)
except KeyboardInterrupt:
    print("終了")