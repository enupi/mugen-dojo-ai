import os
import requests
from dotenv import load_dotenv

# .env から LIQUID_API_KEY を読み込む
load_dotenv()
API_KEY = os.getenv("LIQUID_API_KEY")

url = "https://api.liquid.ai/decisions/v1/systemone"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

payload = {
    "model": "d1.2-ultra",
    "state": (
        "あなたはMUGENの格闘ゲームプレイヤーです。"
        "現在の状況: 自分のHP 85%, 相手のHP 60%。"
        "直前の行動: jump_kick -> 結果: 相手に0.0%ダメージ / 自分が15.0%被弾（対空された）。"
        "戦術メモ: ジャンプ攻撃は落とされやすい。地上からの接近やガードが有効。"
    ),
    "questions": {
        "next_action": {
            "type": "choice",
            "instructions": "この戦況で次に取るべき最も勝率が高い行動を1つ選んでください。",
            "criteria": {
                "jab": "牽制の弱攻撃（発生が速く隙が少ない）",
                "dash_attack": "地上から素早く踏み込むダッシュ攻撃（中距離からの奇襲）",
                "guard": "相手の反撃を防ぐガード（被弾を抑える防御行動）",
                "jump_kick": "空からの奇襲ジャンプキック（対空に弱い）",
            },
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

response = requests.post(url, json=payload, headers=headers)
print("Status:", response.status_code)
print("Response:", response.json())