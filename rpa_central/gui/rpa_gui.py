"""RPA Central GUI — 등록된 자동화 작업을 한 창에서 관리.

데이터:
  ~/.rpa_central/jobs/*.json   (각 작업의 메타데이터)
  ~/.rpa_central/notifications.log  (최근 알림 기록)

스케줄: Windows Task Scheduler 와 연동.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

HOME = Path(os.path.expanduser("~"))
JOBS_DIR = HOME / ".rpa_central" / "jobs"
NOTIFY_LOG = HOME / ".rpa_central" / "notifications.log"
RPA_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = RPA_ROOT / "bin"

# ──────────────────────────────────────────────────────────────────
# 데이터 헬퍼
# ──────────────────────────────────────────────────────────────────


def load_jobs() -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    out: list[dict] = []
    for f in sorted(JOBS_DIR.glob("*.json")):
        try:
            with f.open(encoding="utf-8") as fp:
                j = json.load(fp)
                j["_file"] = str(f)
                out.append(j)
        except Exception as exc:
            print(f"[WARN] load {f}: {exc}", file=sys.stderr)
    return out


def run_powershell(*args: str) -> tuple[int, str]:
    """동기 실행. (return_code, combined_output)."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return -1, str(exc)


def fire_and_forget(*args: str) -> None:
    """비동기 실행 (응답 안 기다림)."""
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def get_task_info(task_name: str) -> dict | None:
    """Windows Task Scheduler 작업 정보 조회."""
    if not task_name:
        return None
    ps = (
        f"$t=Get-ScheduledTask -TaskName '{task_name}' -EA Stop;"
        f"$i=Get-ScheduledTaskInfo -TaskName '{task_name}';"
        "[ordered]@{State=[string]$t.State;NextRunTime=$i.NextRunTime.ToString('yyyy-MM-dd HH:mm');"
        "LastRunTime=$i.LastRunTime.ToString('yyyy-MM-dd HH:mm');"
        "LastResult=$i.LastTaskResult}|ConvertTo-Json -Compress"
    )
    rc, out = run_powershell("-Command", ps)
    if rc != 0 or not out.strip():
        return None
    try:
        return json.loads(out.strip())
    except Exception:
        return None


def count_processes() -> tuple[int, int]:
    rc, out = run_powershell(
        "-Command",
        "$p=Get-Process|Where-Object{$_.Name -like 'python*' -or $_.Name -like 'chrome*'};"
        "$py=($p|Where-Object{$_.Name -like 'python*'}).Count;"
        "$ch=($p|Where-Object{$_.Name -like 'chrome*'}).Count;"
        "Write-Host \"$py,$ch\""
    )
    try:
        py, ch = out.strip().split(",")
        return int(py), int(ch)
    except Exception:
        return 0, 0


# ──────────────────────────────────────────────────────────────────
# GUI
# ──────────────────────────────────────────────────────────────────


class RpaGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("RPA Central")
        root.geometry("900x600")
        try:
            root.iconbitmap(default="")
        except Exception:
            pass

        # 폰트 — Windows 기본 한글 폰트
        self.default_font = ("Malgun Gothic", 10)
        style = ttk.Style()
        try:
            style.theme_use("vista")  # Windows 기본
        except Exception:
            pass
        style.configure("Treeview", rowheight=28, font=self.default_font)
        style.configure("Treeview.Heading", font=("Malgun Gothic", 10, "bold"))

        self._build_widgets()
        self.refresh()
        # 30초마다 자동 새로고침
        self._schedule_auto_refresh()

    def _build_widgets(self) -> None:
        # 상단 타이틀 + 상태바
        title_frame = ttk.Frame(self.root, padding=(10, 10, 10, 5))
        title_frame.pack(fill="x")
        ttk.Label(title_frame, text="RPA Central", font=("Malgun Gothic", 14, "bold")).pack(side="left")
        self.status_label = ttk.Label(title_frame, text="", foreground="gray")
        self.status_label.pack(side="right")

        # 작업 테이블
        table_frame = ttk.Frame(self.root, padding=(10, 5))
        table_frame.pack(fill="both", expand=True)

        cols = ("name", "display", "schedule", "next_run", "last_result")
        self.tree = ttk.Treeview(
            table_frame, columns=cols, show="headings", selectmode="browse",
        )
        widths = {"name": 140, "display": 200, "schedule": 130, "next_run": 140, "last_result": 200}
        headings = {
            "name": "이름", "display": "표시 이름", "schedule": "스케줄",
            "next_run": "다음 실행", "last_result": "마지막 결과",
        }
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", lambda e: self._show_logs())

        # 액션 버튼 행
        btn_frame = ttk.Frame(self.root, padding=(10, 5))
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="▶ 실행",   command=self._run_selected).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="■ 중단",   command=self._stop_selected).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="📄 로그",  command=self._show_logs).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="🔔 알림",  command=self._show_notifications).pack(side="left", padx=2)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(btn_frame, text="✓ 스케줄 켜기", command=lambda: self._toggle_schedule(True)).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="✗ 스케줄 끄기", command=lambda: self._toggle_schedule(False)).pack(side="left", padx=2)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(btn_frame, text="+ 추가",   command=self._add_job).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="✎ 수정",   command=self._edit_job).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="- 삭제",   command=self._remove_job).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="↻ 새로고침", command=self.refresh).pack(side="right", padx=2)

        # 하단 정보 패널 (선택 작업 상세)
        detail_frame = ttk.LabelFrame(self.root, text="선택 작업 상세", padding=10)
        detail_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.detail_label = ttk.Label(detail_frame, text="(작업을 선택하세요)", justify="left", font=self.default_font)
        self.detail_label.pack(anchor="w")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_detail())

        # 푸터 / 상태바
        footer = ttk.Frame(self.root, relief="sunken", padding=(8, 4))
        footer.pack(side="bottom", fill="x")
        self.footer_label = ttk.Label(footer, text="", font=("Malgun Gothic", 9))
        self.footer_label.pack(side="left")

    # ── 선택 작업 가져오기 ─────────────────────────────────────
    def _selected_job(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("선택 필요", "먼저 작업을 선택해주세요.")
            return None
        idx = self.tree.index(sel[0])
        return self.jobs[idx]

    # ── 리프레시 ──────────────────────────────────────────────
    def refresh(self) -> None:
        self.jobs = load_jobs()
        # 테이블 클리어
        for row in self.tree.get_children():
            self.tree.delete(row)
        for j in self.jobs:
            ti = get_task_info(j.get("task_scheduler_name", ""))
            next_run = ti["NextRunTime"] if ti else "-"
            last_result = ""
            if j.get("last_result"):
                last_result = f"{j['last_result'].get('status', '?')} · {j['last_result'].get('detail', '')[:30]}"
            elif ti and ti.get("LastRunTime"):
                last_result = f"task last: {ti['LastRunTime']}"
            self.tree.insert("", "end", values=(
                j.get("name", ""), j.get("display_name", ""),
                j.get("schedule_human", "-"), next_run, last_result,
            ))
        # 푸터 정보
        py, ch = count_processes()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.footer_label.config(
            text=f"등록 작업: {len(self.jobs)}개  |  Python: {py}  |  Chrome: {ch}  |  새로고침: {ts}"
        )
        if self.jobs and not self.tree.selection():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
        self._update_detail()

    def _schedule_auto_refresh(self) -> None:
        self.root.after(30_000, self._auto_tick)

    def _auto_tick(self) -> None:
        try:
            self.refresh()
        finally:
            self._schedule_auto_refresh()

    # ── 상세 패널 갱신 ────────────────────────────────────────
    def _update_detail(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.detail_label.config(text="(작업을 선택하세요)")
            return
        idx = self.tree.index(sel[0])
        j = self.jobs[idx]
        ti = get_task_info(j.get("task_scheduler_name", ""))
        lines = [
            f"설명           : {j.get('description', '-')}",
            f"프로젝트       : {j.get('project_dir', '-')}",
            f"로그 디렉토리  : {j.get('log_dir', '-')}",
            f"Task Scheduler : {j.get('task_scheduler_name') or '(없음 — 수동 실행)'}",
        ]
        if ti:
            lines.append(f"  상태         : {ti.get('State', '-')}")
            lines.append(f"  다음 실행    : {ti.get('NextRunTime', '-')}")
            lines.append(f"  마지막 실행  : {ti.get('LastRunTime', '-')}  (exit={ti.get('LastResult', '?')})")
        if j.get("last_result"):
            lr = j["last_result"]
            lines.append(f"마지막 알림    : {lr.get('status', '?')} — {lr.get('detail', '')}")
        self.detail_label.config(text="\n".join(lines))

    # ── 액션 핸들러 ───────────────────────────────────────────
    def _run_selected(self) -> None:
        j = self._selected_job()
        if not j: return
        task = j.get("task_scheduler_name")
        if not task:
            messagebox.showwarning("불가", "이 작업은 Task Scheduler 등록이 없어 즉시 실행할 수 없습니다.")
            return
        if not messagebox.askyesno("실행 확인", f"'{j['display_name']}' 을 지금 실행할까요?"):
            return
        rc, out = run_powershell("-Command", f"Start-ScheduledTask -TaskName '{task}'")
        if rc == 0:
            messagebox.showinfo("실행 시작", f"'{task}' 시작되었습니다.")
        else:
            messagebox.showerror("실패", out[:500])
        self.refresh()

    def _stop_selected(self) -> None:
        j = self._selected_job()
        if not j: return
        task = j.get("task_scheduler_name")
        if task:
            run_powershell("-Command", f"Stop-ScheduledTask -TaskName '{task}' -EA SilentlyContinue")
        # 추가로 실행 중인 Python/Chrome 도 종료할지
        py, ch = count_processes()
        if py + ch > 0:
            if messagebox.askyesno(
                "프로세스 정리",
                f"현재 Python {py}개, Chrome {ch}개 실행 중입니다.\n전부 종료할까요?"
            ):
                run_powershell(
                    "-Command",
                    "Get-Process | Where-Object { $_.Name -like 'python*' -or $_.Name -like 'chrome*' } | Stop-Process -Force"
                )
        self.refresh()

    def _show_logs(self) -> None:
        j = self._selected_job()
        if not j: return
        log_dir = j.get("log_dir")
        if not log_dir or not Path(log_dir).exists():
            messagebox.showinfo("로그 없음", f"로그 디렉토리 없음: {log_dir}")
            return
        log_files = sorted(Path(log_dir).glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not log_files:
            messagebox.showinfo("로그 없음", "로그 파일이 아직 없습니다.")
            return
        latest = log_files[0]
        self._open_log_window(latest)

    def _open_log_window(self, path: Path) -> None:
        win = tk.Toplevel(self.root)
        win.title(f"로그 — {path.name}")
        win.geometry("1000x600")
        text = scrolledtext.ScrolledText(win, font=("Consolas", 9), wrap="none")
        text.pack(fill="both", expand=True)
        try:
            with path.open(encoding="utf-8", errors="replace") as fp:
                content = fp.read()
            # 마지막 5000줄만 (긴 로그 대비)
            lines = content.splitlines()
            if len(lines) > 5000:
                text.insert("end", f"... (앞 {len(lines)-5000}줄 생략) ...\n")
                lines = lines[-5000:]
            text.insert("end", "\n".join(lines))
            text.see("end")
        except Exception as exc:
            text.insert("end", f"로그 읽기 실패: {exc}")
        text.configure(state="disabled")

    def _show_notifications(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("최근 알림")
        win.geometry("800x400")
        text = scrolledtext.ScrolledText(win, font=("Consolas", 9), wrap="word")
        text.pack(fill="both", expand=True)
        if NOTIFY_LOG.exists():
            try:
                with NOTIFY_LOG.open(encoding="utf-8") as fp:
                    text.insert("end", fp.read())
                text.see("end")
            except Exception as exc:
                text.insert("end", f"읽기 실패: {exc}")
        else:
            text.insert("end", "(알림 기록 없음)")
        text.configure(state="disabled")

    def _toggle_schedule(self, enable: bool) -> None:
        j = self._selected_job()
        if not j: return
        task = j.get("task_scheduler_name")
        if not task:
            messagebox.showwarning("불가", "이 작업은 Task Scheduler 등록이 없습니다.")
            return
        cmd = "Enable-ScheduledTask" if enable else "Disable-ScheduledTask"
        rc, out = run_powershell("-Command", f"{cmd} -TaskName '{task}'")
        if rc == 0:
            messagebox.showinfo("완료", f"스케줄 {'활성화' if enable else '비활성화'}: {task}")
        else:
            messagebox.showerror("실패", out[:500])
        self.refresh()

    def _add_job(self) -> None:
        JobEditorDialog(self.root, on_done=self.refresh)

    def _edit_job(self) -> None:
        j = self._selected_job()
        if not j: return
        JobEditorDialog(self.root, on_done=self.refresh, existing=j)

    def _remove_job(self) -> None:
        j = self._selected_job()
        if not j: return
        if not messagebox.askyesno("삭제 확인",
            f"'{j['display_name']}' 등록을 해제할까요?\n"
            f"(Task Scheduler 항목도 같이 삭제됩니다)"):
            return
        task = j.get("task_scheduler_name")
        if task:
            run_powershell("-Command",
                f"Unregister-ScheduledTask -TaskName '{task}' -Confirm:$false -EA SilentlyContinue")
        try:
            Path(j["_file"]).unlink()
        except Exception as exc:
            messagebox.showerror("삭제 실패", str(exc))
            return
        messagebox.showinfo("완료", f"등록 해제: {j['name']}")
        self.refresh()


# ──────────────────────────────────────────────────────────────────
# 새 작업 등록 다이얼로그
# ──────────────────────────────────────────────────────────────────


class JobEditorDialog:
    """새 작업 등록 / 기존 작업 수정 다이얼로그.

    existing=None 이면 등록 모드, existing=<job dict> 이면 수정 모드.
    수정 모드에선 'name' 필드(파일명) 는 읽기 전용 — 다른 모든 필드는 자유롭게 수정 가능.
    """

    def __init__(self, parent: tk.Tk, on_done, existing: dict | None = None) -> None:
        self.on_done = on_done
        self.existing = existing
        is_edit = existing is not None

        self.win = tk.Toplevel(parent)
        self.win.title("RPA 작업 수정" if is_edit else "새 RPA 작업 등록")
        self.win.geometry("600x420")
        self.win.transient(parent)
        self.win.grab_set()

        frm = ttk.Frame(self.win, padding=15)
        frm.pack(fill="both", expand=True)

        self.entries: dict[str, tk.Entry] = {}
        fields = [
            ("name",        "내부 이름 (영문/숫자/_, 예: my_uploader)"),
            ("display",     "표시 이름 (예: 내 업로드 프로그램)"),
            ("description", "설명 (선택)"),
            ("project_dir", "프로젝트 디렉토리 (절대경로)"),
            ("log_dir",     "로그 디렉토리 (선택, 절대경로)"),
            ("task_name",   "Windows Task Scheduler 작업명 (선택)"),
            ("schedule",    "스케줄 표시 문구 (예: 매일 10:30)"),
        ]
        existing_values = {}
        if is_edit:
            existing_values = {
                "name":        existing.get("name", ""),
                "display":     existing.get("display_name", ""),
                "description": existing.get("description", ""),
                "project_dir": existing.get("project_dir", ""),
                "log_dir":     existing.get("log_dir", ""),
                "task_name":   existing.get("task_scheduler_name", ""),
                "schedule":    existing.get("schedule_human", ""),
            }

        for i, (key, label) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=4)
            e = ttk.Entry(frm, width=60)
            e.grid(row=i, column=1, sticky="we", padx=5, pady=4)
            self.entries[key] = e
            if key in existing_values:
                e.insert(0, existing_values[key])
            # 수정 모드에선 내부 이름(name) 만 잠금
            if is_edit and key == "name":
                e.configure(state="readonly")
            if key in ("project_dir", "log_dir"):
                ttk.Button(frm, text="찾기...", command=lambda k=key: self._browse(k)).grid(row=i, column=2, padx=2)

        frm.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=len(fields), column=0, columnspan=3, pady=15)
        submit_label = "저장" if is_edit else "등록"
        ttk.Button(btn_frame, text=submit_label, command=self._submit).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="취소", command=self.win.destroy).pack(side="left", padx=5)

    def _browse(self, key: str) -> None:
        d = filedialog.askdirectory()
        if d:
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, d)

    def _submit(self) -> None:
        # 읽기 전용 필드도 .get() 으로 값 가져올 수 있음
        name = self.entries["name"].get().strip()
        if not name:
            messagebox.showerror("입력 오류", "내부 이름은 필수입니다.")
            return
        proj = self.entries["project_dir"].get().strip()
        if not proj:
            messagebox.showerror("입력 오류", "프로젝트 디렉토리는 필수입니다.")
            return

        # 등록 모드에서 이름 충돌 방지
        out_file = JOBS_DIR / f"{name}.json"
        if self.existing is None and out_file.exists():
            messagebox.showerror("중복", f"이미 존재하는 이름: {name}")
            return

        # 기존 메타데이터 보존 (registered_at, last_run, last_result 등)
        job = dict(self.existing) if self.existing else {}
        job.pop("_file", None)
        job.update({
            "name": name,
            "display_name": self.entries["display"].get().strip() or name,
            "description": self.entries["description"].get().strip(),
            "project_dir": proj,
            "log_dir": self.entries["log_dir"].get().strip(),
            "task_scheduler_name": self.entries["task_name"].get().strip(),
            "schedule_human": self.entries["schedule"].get().strip(),
        })
        if "registered_at" not in job:
            job["registered_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        with out_file.open("w", encoding="utf-8") as fp:
            json.dump(job, fp, ensure_ascii=False, indent=2)
        action = "저장" if self.existing else "등록"
        messagebox.showinfo(f"{action} 완료", f"{action}됨: {name}")
        self.win.destroy()
        self.on_done()


def main() -> int:
    root = tk.Tk()
    RpaGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
