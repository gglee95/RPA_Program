"""
차량 1개 업로드 테스트
- 기존 엑셀에서 상품코드를 순서대로 읽어 공개 상세 페이지 크롤링
- 배기량 0cc 차량은 건너뜀
- DRY_RUN = False → 실제 제출까지 진행
"""
import sys
import importlib.util
import pandas as pd
from pathlib import Path
from glob import glob

HERE = Path(__file__).parent

BEFORWARD_DIR = Path(r"C:\Users\gglee\OneDrive\Desktop\비포워드 생태계\비포워드_자동화")
if str(BEFORWARD_DIR) not in sys.path:
    sys.path.insert(0, str(BEFORWARD_DIR))

# mango_to_beforward 모듈 로드 (DRY_RUN 패치 후)
spec = importlib.util.spec_from_file_location("m2b", HERE / "mango_to_beforward.py")
m2b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2b)
m2b.DRY_RUN = False  # 실제 제출 ON

# mango_crawler 로드
spec2 = importlib.util.spec_from_file_location("mc", HERE / "mango_crawler.py")
mc = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(mc)

# ── 엑셀에서 상품코드 목록 로드 ─────────────────────────────────────────────
xlsx_files = sorted(glob(str(HERE / "지지오토_차량목록_*.xlsx")))
if not xlsx_files:
    print("[오류] 엑셀 파일 없음")
    sys.exit(1)

df = pd.read_excel(xlsx_files[-1])
df.columns = [str(c) for c in df.columns]

code_col = None
vin_col = None
for col in df.columns:
    if df[col].astype(str).str.startswith("MGC_").any():
        code_col = col
    if df[col].astype(str).str.match(r'^[A-HJ-NPR-Z0-9]{17}$').any():
        vin_col = col

if not code_col:
    print("[오류] 상품코드 컬럼 못찾음:", list(df.columns))
    sys.exit(1)

mgc_rows = df[df[code_col].astype(str).str.startswith("MGC_")]

# 재원표에 있고 옵션 데이터가 풍부한 차량 우선
PREFERRED_CODES = [
    "MGC_260420_10002000",  # 현대 그랜저 HG — 옵션 22개 (AM/FM 라디오 fix 검증용)
    "MGC_260420_10002003",  # 현대 싼타페 — 옵션 27개
]

# PREFERRED_CODES 우선순위 그대로 정렬, 없으면 엑셀 순서
all_rows = list(mgc_rows.iterrows())
def _rank(row):
    code = str(row[code_col]).strip()
    try:
        return PREFERRED_CODES.index(code)
    except ValueError:
        return len(PREFERRED_CODES) + 999

ordered_rows = [r for _, r in sorted(all_rows, key=lambda kv: _rank(kv[1]))]

driver = mc.make_driver()
detail = None
chosen_code = None
chosen_vin = None

try:
    for row in ordered_rows:
        code = str(row[code_col]).strip()
        vin_from_excel = str(row[vin_col]).strip() if vin_col else ""

        print(f"상세 확인 중: {code} ...")
        d = mc.extract_detail(driver, code)
        if vin_from_excel and not d.get("차대번호"):
            d["차대번호"] = vin_from_excel

        car_info = m2b._make_car_info(d)
        if not car_info.inspection_chassis_no:
            print(f"  → 차대번호 없음, 건너뜀")
            continue

        if not car_info.price:
            print(f"  → 가격 없음, 건너뜀")
            continue

        print(f"  → 선택: {code} | {car_info.car_type} | 배기량: {car_info.displacement} | VIN: {car_info.inspection_chassis_no}")
        detail = d
        chosen_code = code
        chosen_vin = car_info.inspection_chassis_no
        break
finally:
    driver.quit()

if not detail:
    print("[오류] 업로드 가능한 차량 없음 (0cc 아닌 차량 없음)")
    sys.exit(1)

print()
print("=" * 60)
print(f"업로드 대상: {chosen_code} | VIN: {chosen_vin}")
print("=" * 60)
print("수집된 상세 데이터:")
for k, v in detail.items():
    print(f"  {k}: {v}")

print()
print("=" * 60)
print("비포워드 업로드 시작 (DRY_RUN=False)")
print("=" * 60)

total, success = m2b.upload_to_beforward([detail])
print(f"\n결과: {success}/{total} 성공")
