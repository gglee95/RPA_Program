"""
망고월드카 지지오토 → 비포워드 자동 업로드 GUI
- A열="망고카지지오토 api", P열="게시" 필터 고정
- C열(모델) 다중 선택 필터
- Q열(차량광고가) 기준 상위 N개 선택
- 결과 목록은 시트 원본 열 이름 그대로 출력
"""
import sys
import re
import logging
import threading
import traceback
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# ── 로깅 ───────────────────────────────────────────────────────────────────────
LOG_FILE = HERE / "mango_upload_gui.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── 시트 설정 ──────────────────────────────────────────────────────────────────
MANGO_SHEET_ID  = "1P6AJOgbyksLdySg4Pn5KpGK7dKVhSfV3oxIdCkyyKS0"
MANGO_SHEET_GID = "1710203054"
SHEET_START_ROW = 2

# 확인된 실제 열 구조
# A: 회원명  B: 회사명  C: 모델  D: 등급  E: 연료  F: 배기량
# G: 차대번호  H: 연식  I: 주행거리  J: A/M  K: 매물등록일
# L: 최종수정일  M: 구매요청일  N: 판매완료일  O: 업로드링크
# P: 매물상태  Q: 차량광고가
COL_SOURCE   = "A"   # 회원명 ("망고카지지오토 api" 필터)
COL_CARNAME  = "C"   # 모델
COL_FUEL     = "E"   # 연료
COL_DISPLACE = "F"   # 배기량
COL_VIN      = "G"   # 차대번호
COL_YEAR     = "H"   # 연식
COL_MILEAGE  = "I"   # 주행거리
COL_TRANS    = "J"   # A/M (변속기)
COL_DRIVE    = "O"   # 업로드링크
COL_STATUS   = "P"   # 매물상태 ("게시" 필터)
COL_PRICE    = "Q"   # 차량광고가

SOURCE_FILTER = "망고카지지오토 api"
STATUS_FILTER = "게시"

# 트리뷰에서 숨길 열 이름
HIDDEN_COLUMNS = {"매물등록일", "최종수정일", "구매요청일", "판매완료일"}


def _col_to_idx(col: str) -> int:
    idx = 0
    for c in col.upper():
        idx = idx * 26 + (ord(c) - ord("A") + 1)
    return idx - 1


def _find_sa_file() -> str:
    p = HERE / "adjustmentdata-51a7199ac3ba.json"
    return str(p) if p.exists() else ""


def _to_num(v) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", str(v)))
    except Exception:
        return 0.0


# ── GUI 앱 ────────────────────────────────────────────────────────────────────

class MangoUploadApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("망고카 지지오토 → 비포워드 업로드")
        self.root.geometry("1200x820")
        self.root.minsize(900, 600)

        self.all_rows: list[dict] = []
        self.filtered_rows: list[dict] = []
        self.sheet_headers: list[str] = []   # 원본 헤더 (A~Q)
        self.visible_headers: list[str] = [] # 표시 헤더 (숨김 제외)

        self.sa_file_var = tk.StringVar(value=_find_sa_file())
        self.bf_user_var = tk.StringVar(value="joonsookang@mangoworldcar.com")
        self.bf_pass_var = tk.StringVar(value="k4ycwYk6")

        self._build_ui()
        self._log("프로그램 시작. 서비스 계정 JSON을 확인 후 [시트 데이터 로드]를 클릭하세요.")

    # ── UI 구성 ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 1) 설정
        cfg = ttk.LabelFrame(main, text="설정", padding=8)
        cfg.pack(fill=tk.X, **pad)
        cfg.columnconfigure(1, weight=1)
        cfg.columnconfigure(4, weight=1)

        # Google 서비스 계정
        ttk.Label(cfg, text="서비스 계정 JSON:").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Entry(cfg, textvariable=self.sa_file_var).grid(row=0, column=1, sticky=tk.EW, padx=4)
        ttk.Button(cfg, text="찾기…", command=self._browse_sa).grid(row=0, column=2, padx=2)
        ttk.Button(cfg, text="시트 데이터 로드", command=self._load_data).grid(
            row=0, column=3, padx=(12, 0))

        # 비포워드 계정
        ttk.Label(cfg, text="비포워드 ID:").grid(row=1, column=0, sticky=tk.W, padx=(0, 4), pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.bf_user_var).grid(
            row=1, column=1, sticky=tk.EW, padx=4, pady=(6, 0))
        ttk.Label(cfg, text="PW:").grid(row=1, column=2, sticky=tk.W, padx=(8, 4), pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.bf_pass_var, show="*").grid(
            row=1, column=3, sticky=tk.EW, padx=4, pady=(6, 0))

        # 2) 필터 영역
        flt = ttk.Frame(main)
        flt.pack(fill=tk.BOTH, expand=True, **pad)
        flt.columnconfigure(0, weight=3)
        flt.columnconfigure(1, weight=2)

        # 2-a) C열 모델 선택
        c_frm = ttk.LabelFrame(flt, text="C열 – 모델 선택  (Ctrl+클릭: 복수 선택)", padding=8)
        c_frm.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 4))
        c_frm.rowconfigure(1, weight=1)
        c_frm.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(c_frm)
        btn_row.grid(row=0, column=0, sticky=tk.W, pady=(0, 4))
        ttk.Button(btn_row, text="전체 선택", command=self._select_all_cars).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="전체 해제", command=self._deselect_all_cars).pack(
            side=tk.LEFT, padx=4)

        lw = ttk.Frame(c_frm)
        lw.grid(row=1, column=0, sticky=tk.NSEW)
        lw.rowconfigure(0, weight=1)
        lw.columnconfigure(0, weight=1)

        self.car_listbox = tk.Listbox(
            lw, selectmode=tk.MULTIPLE, font=("맑은 고딕", 10),
            activestyle="none", selectbackground="#4a9fd4", selectforeground="white",
        )
        c_sb = ttk.Scrollbar(lw, orient=tk.VERTICAL, command=self.car_listbox.yview)
        self.car_listbox.configure(yscrollcommand=c_sb.set)
        self.car_listbox.grid(row=0, column=0, sticky=tk.NSEW)
        c_sb.grid(row=0, column=1, sticky=tk.NS)

        # 2-b) Q열 상위 N개
        q_frm = ttk.LabelFrame(flt, text="Q열 (차량광고가) – 상위 N개 선택", padding=8)
        q_frm.grid(row=0, column=1, sticky=tk.NSEW, padx=(4, 0))

        top_row = ttk.Frame(q_frm)
        top_row.pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(top_row, text="상위").pack(side=tk.LEFT)
        self.top_n_var = tk.IntVar(value=10)
        ttk.Spinbox(top_row, from_=1, to=9999, textvariable=self.top_n_var,
                    width=7, font=("맑은 고딕", 10)).pack(side=tk.LEFT, padx=4)
        ttk.Label(top_row, text="개").pack(side=tk.LEFT)

        ttk.Label(q_frm, text="정렬:").pack(anchor=tk.W, pady=(10, 2))
        self.q_sort_var = tk.StringVar(value="desc")
        ttk.Radiobutton(q_frm, text="내림차순 (큰 값 우선)",
                        variable=self.q_sort_var, value="desc").pack(anchor=tk.W)
        ttk.Radiobutton(q_frm, text="오름차순 (작은 값 우선)",
                        variable=self.q_sort_var, value="asc").pack(anchor=tk.W)

        ttk.Separator(q_frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Label(q_frm, text="광고가 미리보기 (상위 30):", font=("맑은 고딕", 9)).pack(anchor=tk.W)
        self.q_preview = scrolledtext.ScrolledText(
            q_frm, height=10, font=("Consolas", 9), state=tk.DISABLED)
        self.q_preview.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # 3) 액션 바
        act = ttk.Frame(main)
        act.pack(fill=tk.X, **pad)

        ttk.Button(act, text="필터 적용 및 미리보기", command=self._apply_filter).pack(side=tk.LEFT)
        self.count_label = ttk.Label(act, text="선택: 0건", foreground="#555")
        self.count_label.pack(side=tk.LEFT, padx=16)
        self.upload_btn = ttk.Button(
            act, text="▶  비포워드 업로드 시작", command=self._start_upload)
        self.upload_btn.pack(side=tk.RIGHT)

        # 4) 결과 트리뷰 (동적 컬럼 — 로드 후 재구성)
        self.res_frame = ttk.LabelFrame(main, text="업로드 예정 차량 목록", padding=8)
        self.res_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.res_frame.rowconfigure(0, weight=1)
        self.res_frame.columnconfigure(0, weight=1)

        self.result_tree = ttk.Treeview(self.res_frame, show="headings", height=7)
        t_sb = ttk.Scrollbar(self.res_frame, orient=tk.VERTICAL,
                             command=self.result_tree.yview)
        t_sbx = ttk.Scrollbar(self.res_frame, orient=tk.HORIZONTAL,
                              command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=t_sb.set, xscrollcommand=t_sbx.set)
        self.result_tree.grid(row=0, column=0, sticky=tk.NSEW)
        t_sb.grid(row=0, column=1, sticky=tk.NS)
        t_sbx.grid(row=1, column=0, sticky=tk.EW)

        # 5) 로그
        log_frm = ttk.LabelFrame(main, text="로그", padding=6)
        log_frm.pack(fill=tk.BOTH, expand=True, **pad)
        self.log_text = scrolledtext.ScrolledText(
            log_frm, height=6, font=("Consolas", 9), state=tk.NORMAL)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ── 유틸 ──────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        log.info(msg)
        self.root.update_idletasks()

    def _browse_sa(self):
        path = filedialog.askopenfilename(
            title="서비스 계정 JSON 선택",
            filetypes=[("JSON 파일", "*.json"), ("모든 파일", "*.*")],
        )
        if path:
            self.sa_file_var.set(path)

    # ── 트리뷰 동적 재구성 ────────────────────────────────────────────────────

    def _rebuild_tree(self, headers: list[str]):
        """헤더 목록으로 트리뷰 컬럼을 다시 만든다 (숨김 열 제외)."""
        visible = [h for h in headers if h not in HIDDEN_COLUMNS]
        self.visible_headers = visible
        self.result_tree.configure(columns=visible)
        for h in visible:
            self.result_tree.heading(h, text=h)
            w = 80 if any(k in h for k in ("등급", "A/M", "연식")) else 120
            if h in ("모델", "차대번호"):
                w = 160
            if h in ("차량광고가",):
                w = 100
            self.result_tree.column(h, width=w, minwidth=50)

    # ── 데이터 로드 ───────────────────────────────────────────────────────────

    def _load_data(self):
        self._log("Google Sheets 데이터 로드 시작…")
        threading.Thread(target=self._load_thread, daemon=True).start()

    def _load_thread(self):
        try:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
            except ImportError:
                self.root.after(0, lambda: messagebox.showerror(
                    "패키지 없음", "pip install gspread google-auth"))
                return

            sa_file = self.sa_file_var.get()
            if not sa_file or not Path(sa_file).exists():
                self.root.after(0, lambda: messagebox.showerror(
                    "오류", "서비스 계정 JSON 파일을 선택하거나 경로를 입력하세요."))
                return

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ]
            creds = Credentials.from_service_account_file(sa_file, scopes=scopes)
            gc = gspread.authorize(creds)
            spreadsheet = gc.open_by_key(MANGO_SHEET_ID)

            worksheet = None
            for ws in spreadsheet.worksheets():
                if str(ws.id) == MANGO_SHEET_GID:
                    worksheet = ws
                    break
            if worksheet is None:
                worksheet = spreadsheet.sheet1

            self.root.after(0, lambda: self._log(f"시트 '{worksheet.title}' 읽는 중…"))
            all_values = worksheet.get_all_values()

            if not all_values:
                self.root.after(0, lambda: self._log("시트에 데이터 없음"))
                return

            # 원본 헤더 저장 (빈 열 제거)
            raw_header = all_values[0]
            headers = [h.strip() for h in raw_header]
            # 뒤쪽 빈 헤더 제거
            while headers and not headers[-1]:
                headers.pop()

            # 필터 적용 (A=SOURCE_FILTER, P=STATUS_FILTER)
            src_idx    = _col_to_idx(COL_SOURCE)
            status_idx = _col_to_idx(COL_STATUS)
            q_idx      = _col_to_idx(COL_PRICE)

            rows: list[dict] = []
            for row_num, row in enumerate(
                all_values[SHEET_START_ROW - 1:], start=SHEET_START_ROW
            ):
                def cell(idx: int, _row=row) -> str:
                    return _row[idx].strip() if idx < len(_row) else ""

                if cell(src_idx) != SOURCE_FILTER:
                    continue
                if cell(status_idx) != STATUS_FILTER:
                    continue

                # 원본 열 값 전체를 헤더명 키로 저장
                raw = {
                    headers[i]: cell(i)
                    for i in range(len(headers))
                }
                # 업로드용 추가 키
                raw["_q_val"]      = cell(q_idx)
                raw["_sheet_row"]  = row_num
                raw["_drive_link"] = cell(_col_to_idx(COL_DRIVE))
                # 업로드 모듈이 인식하는 키 별칭
                raw["차량명"]        = cell(_col_to_idx(COL_CARNAME))
                raw["연식"]          = cell(_col_to_idx(COL_YEAR))
                raw["주행거리(상세)"] = cell(_col_to_idx(COL_MILEAGE))
                raw["배기량"]        = cell(_col_to_idx(COL_DISPLACE))
                raw["연료타입"]      = cell(_col_to_idx(COL_FUEL))
                raw["변속기"]        = cell(_col_to_idx(COL_TRANS))
                raw["색상"]          = ""
                raw["위치"]          = ""
                raw["가격(USD)"]     = cell(q_idx)
                raw["차대번호"]      = cell(_col_to_idx(COL_VIN))
                raw["차대번호_상세"] = cell(_col_to_idx(COL_VIN))
                raw["보유옵션(전체)"] = ""
                raw["판매자"]        = cell(_col_to_idx("B"))  # 회사명
                raw["상품코드"]      = cell(_col_to_idx(COL_VIN))  # VIN을 식별자로

                rows.append(raw)

            self.all_rows = rows
            self.sheet_headers = headers
            self.root.after(0, self._on_loaded)

        except Exception as e:
            msg = str(e)
            err = traceback.format_exc()
            self.root.after(0, lambda m=msg: self._log(f"[오류] 데이터 로드 실패: {m}"))
            self.root.after(0, lambda m=msg, t=err: messagebox.showerror(
                "오류", f"데이터 로드 실패:\n{m}\n\n{t}"))

    def _on_loaded(self):
        n = len(self.all_rows)
        self._log(f"로드 완료: {n}건  (A열='{SOURCE_FILTER}', P열='{STATUS_FILTER}')")

        # 트리뷰 컬럼을 원본 헤더로 재구성
        self._rebuild_tree(self.sheet_headers)

        # C열(모델) 고유값
        car_names = sorted({r["차량명"] for r in self.all_rows if r["차량명"]})
        self.car_listbox.delete(0, tk.END)
        for name in car_names:
            self.car_listbox.insert(tk.END, name)
        self.car_listbox.select_set(0, tk.END)

        # Q열 미리보기
        self._refresh_q_preview()
        self._log(f"C열 모델 종류: {len(car_names)}개")

    def _refresh_q_preview(self):
        pairs = [(r.get("차량명", ""), r["_q_val"]) for r in self.all_rows]
        reverse = self.q_sort_var.get() == "desc"
        pairs_sorted = sorted(pairs, key=lambda x: _to_num(x[1]), reverse=reverse)

        self.q_preview.configure(state=tk.NORMAL)
        self.q_preview.delete(1.0, tk.END)
        for i, (name, val) in enumerate(pairs_sorted[:30], 1):
            self.q_preview.insert(tk.END, f"{i:>3}. {val:>12}  {name}\n")
        self.q_preview.configure(state=tk.DISABLED)

    # ── 전체 선택 / 해제 ──────────────────────────────────────────────────────

    def _select_all_cars(self):
        self.car_listbox.select_set(0, tk.END)

    def _deselect_all_cars(self):
        self.car_listbox.select_clear(0, tk.END)

    # ── 필터 적용 ────────────────────────────────────────────────────────────

    def _apply_filter(self):
        if not self.all_rows:
            messagebox.showwarning("경고", "먼저 [시트 데이터 로드]를 클릭하세요.")
            return

        sel_idx = self.car_listbox.curselection()
        if sel_idx:
            sel_names = {self.car_listbox.get(i) for i in sel_idx}
            rows = [r for r in self.all_rows if r["차량명"] in sel_names]
        else:
            rows = list(self.all_rows)

        reverse = self.q_sort_var.get() == "desc"
        rows_sorted = sorted(rows, key=lambda r: _to_num(r["_q_val"]), reverse=reverse)
        top_n = max(1, self.top_n_var.get())
        rows_final = rows_sorted[:top_n]

        self.filtered_rows = rows_final

        # 트리뷰 갱신 — 원본 헤더 순서대로 값 삽입
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        for r in rows_final:
            values = tuple(r.get(h, "") for h in self.visible_headers)
            self.result_tree.insert("", tk.END, values=values)

        self.count_label.config(text=f"선택: {len(rows_final)}건")
        self._log(
            f"필터 적용 → {len(rows_final)}건  "
            f"(모델 {len(sel_idx) if sel_idx else '전체'} 종류 / Q열 상위 {top_n}개)"
        )

    # ── 업로드 ───────────────────────────────────────────────────────────────

    def _start_upload(self):
        if not self.filtered_rows:
            messagebox.showwarning("경고", "먼저 [필터 적용 및 미리보기]를 실행하세요.")
            return
        if not messagebox.askyesno(
            "업로드 확인",
            f"선택된 차량 {len(self.filtered_rows)}건을\n비포워드에 업로드하시겠습니까?",
        ):
            return

        self.upload_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._upload_thread, daemon=True).start()

    def _upload_thread(self):
        try:
            import os
            os.environ["BEFORWARD_USERNAME"] = self.bf_user_var.get()
            os.environ["BEFORWARD_PASSWORD"] = self.bf_pass_var.get()

            from mango_to_beforward import upload_to_beforward

            self.root.after(0, lambda: self._log(
                f"업로드 시작: {len(self.filtered_rows)}건… (계정: {self.bf_user_var.get()})"))
            total, success = upload_to_beforward(self.filtered_rows)
            msg = f"업로드 완료: {success}/{total}건 성공"
            self.root.after(0, lambda: self._log(msg))
            self.root.after(0, lambda: messagebox.showinfo(
                "완료", f"{msg}\n\n성공: {success}건 / 전체: {total}건"))
        except Exception as e:
            msg = str(e)
            err = traceback.format_exc()
            self.root.after(0, lambda m=msg: self._log(f"[오류] 업로드 실패: {m}"))
            self.root.after(0, lambda m=msg, t=err: messagebox.showerror(
                "오류", f"업로드 중 오류 발생:\n{m}\n\n{t}"))
        finally:
            self.root.after(0, lambda: self.upload_btn.config(state=tk.NORMAL))


# ── 실행 ──────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    MangoUploadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
