"""노출 현황 자료를 비밀번호로 암호화해 media/media.enc.json 하나로 만든다.

build_media.py가 만든 media/outlets.json · articles.json · daily.json(평문, 저장소에 올리지 않음)을
한 묶음으로 합쳐 AES-256-GCM으로 암호화한다. 페이지(노출 현황)는 비밀번호를 받아
브라우저 안에서 풀어 보여 준다. 비밀번호가 없으면 암호문만 보인다.

비밀번호: 저장소 Secret `DASH_PASSWORDS` — 한 줄에 하나(8자 이상). '#'으로 시작하는 줄은 무시.
  여러 개를 넣으면 어느 것으로든 열린다. 한 사람을 끊으려면 그 줄을 지우고 media.yml을 실행.

구조(v1):
  데이터 키 dk(무작위 32바이트)로 묶음 전체를 암호화하고, 비밀번호마다
  PBKDF2-SHA256(비밀번호, salt, 600,000회)로 만든 키로 dk를 감싸 keys[]에 넣는다.
  salt는 매번 새로 만들고 모든 비밀번호가 함께 쓴다(페이지가 키 유도를 한 번만 하도록).
"""
import base64
import json
import os
import random
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

KST = timezone(timedelta(hours=9))
ITER = 600_000
OUT = Path("media/media.enc.json")
b64 = lambda b: base64.b64encode(b).decode()


def passwords():
    raw = os.environ.get("DASH_PASSWORDS", "")
    out = []
    for line in raw.splitlines():
        p = unicodedata.normalize("NFC", line.strip())
        if not p or p.startswith("#"):
            continue
        if len(p) < 8:
            print(f"::warning::8자보다 짧은 비밀번호 1개는 넣지 않았습니다({len(p)}자).")
            continue
        out.append(p)
    return out


def main():
    pws = passwords()
    if not pws:
        print("::warning::DASH_PASSWORDS가 비어 있어 노출 현황 암호화 파일을 만들지 않았습니다.")
        return 0
    rows = {n: json.loads(Path(f"media/{n}.json").read_text(encoding="utf-8"))
            for n in ("outlets", "articles", "daily")}
    for o in rows["outlets"]:            # 배너 캡처 이미지는 페이지에서 쓰지 않으므로 뺀다
        for k in ("shot", "shot_date", "shot_view"):
            o.pop(k, None)
    now = datetime.now(KST).isoformat(timespec="seconds")
    plain = json.dumps({"generated": now, **rows}, ensure_ascii=False, separators=(",", ":")).encode()

    dk, iv = AESGCM.generate_key(256), os.urandom(12)
    ct = AESGCM(dk).encrypt(iv, plain, b"kit-media-v1")
    salt = os.urandom(16)
    keys = []
    for p in pws:
        kek = PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(p.encode())
        wiv = os.urandom(12)
        keys.append({"iv": b64(wiv), "wrapped": b64(AESGCM(kek).encrypt(wiv, dk, b"kit-key-v1"))})
    random.SystemRandom().shuffle(keys)
    bundle = {"v": 1, "created": now,
              "kdf": {"name": "PBKDF2", "hash": "SHA-256", "iterations": ITER, "salt": b64(salt)},
              "keys": keys, "iv": b64(iv), "ct": b64(ct)}
    OUT.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    print(f"노출 현황 암호화: 비밀번호 {len(keys)}개, {len(plain):,}바이트 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
