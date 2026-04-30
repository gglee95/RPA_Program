"""
_get_drive_type 키워드 디버그 테스트
"""

_4WD_KEYWORDS_EN = ['AWD', '4WD', 'XDRIVE', '4MATIC', '4MOTION']
_4WD_KEYWORDS_KO = ['콰트로', '4매틱', '4모션', '4륜', 'x드라이브']

def get_drive_type(car_type: str) -> str:
    if not car_type:
        return '2'
    upper = car_type.upper()
    for kw in _4WD_KEYWORDS_EN:
        if kw in upper:
            return '3'
    for kw in _4WD_KEYWORDS_KO:
        if kw in car_type:
            return '3'
    return '2'

# ── 테스트 케이스 (예상값, 입력값) ──────────────────────────────────
test_cases = [
    # ✅ 4WD로 잡혀야 하는 케이스
    ('3', 'AWD'),
    ('3', '4WD'),
    ('3', 'xDrive20d'),
    ('3', 'X드라이브 20d'),
    ('3', 'X드라이브20d'),
    ('3', 'BMW 5시리즈 530d xDrive'),
    ('3', '아우디 A4 콰트로'),
    ('3', '벤츠 E220d 4MATIC'),
    ('3', '벤츠 E220d 4매틱'),
    ('3', '폭스바겐 티구안 4MOTION'),
    ('3', '폭스바겐 티구안 4모션'),
    ('3', '싼타페 4륜'),
    ('3', 'SANTA FE AWD'),
    ('3', 'Santa Fe AWD Premium'),
    ('3', '4WD 터보'),
    ('3', 'Q5 QUATTRO'),  # 영문 콰트로 → 'QUATTRO'는 키워드에 없음 → 2 예상
    # ❌ 2WD로 잡혀야 하는 케이스
    ('2', '소나타 2.0'),
    ('2', '아반떼 1.6 가솔린'),
    ('2', '그랜저 3.3'),
    ('2', '스타리아 3.5'),
    ('2', '2WD 투싼'),          # 2WD는 키워드에 없으니 2
    ('2', 'BMW 320i'),
    ('2', 'Mercedes E220d'),
    ('2', '카니발 4인승'),       # '4' 포함하지만 키워드 아님
    ('2', '4도어 세단'),         # '4' 포함하지만 키워드 아님
]

print("=" * 60)
print(f"{'입력값':<30} {'예상':>4} {'결과':>4}  {'판정'}")
print("=" * 60)

pass_count = 0
fail_count = 0
for expected, car_type in test_cases:
    result = get_drive_type(car_type)
    ok = result == expected
    mark = "✅ OK" if ok else "❌ FAIL"
    label = "4륜" if result == '3' else "2륜"
    print(f"{car_type:<30} {'4륜' if expected=='3' else '2륜':>4} {label:>4}  {mark}")
    if ok:
        pass_count += 1
    else:
        fail_count += 1

print("=" * 60)
print(f"통과: {pass_count}  /  실패: {fail_count}  /  전체: {len(test_cases)}")

# QUATTRO(영문)는 현재 키워드에 없음 → 별도 안내
print()
print("[참고] 'QUATTRO'(영문)는 키워드 목록에 없어 2륜으로 처리됩니다.")
print("       필요하면 _4WD_KEYWORDS_EN 에 'QUATTRO' 추가하세요.")
print()
input("엔터를 누르면 창이 닫힙니다...")
