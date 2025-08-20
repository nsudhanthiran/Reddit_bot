import os
import time
import threading
import queue
import logging
import sqlite3
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

# Import your existing bot class
from reddit_bot_template import RedditBot

# ---------------------------
# GUI Log Handler
# ---------------------------
class QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q
        fmt = '%(asctime)s - %(levelname)s - %(message)s'
        self.setFormatter(logging.Formatter(fmt))

    def emit(self, record):
        try:
            self.q.put(self.format(record))
        except Exception:
            pass


# ---------------------------
# Main GUI Application
# ---------------------------
class BotApp:
    def __init__(self):
        # Theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Window
        self.root = ctk.CTk()
        self.root.title("Reddit Bot Controller")
        self.root.geometry("1000x720")

        # State
        self.bot: RedditBot | None = None
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.log_q: queue.Queue[str] = queue.Queue()
        self.is_running = False

        # Attach queue log handler to root logger
        self.queue_handler = QueueLogHandler(self.log_q)
        logging.getLogger().addHandler(self.queue_handler)
        logging.getLogger().setLevel(logging.INFO)

        # Top banner
        header = ctk.CTkLabel(self.root, text="Reddit Bot Controller", font=ctk.CTkFont(size=24, weight="bold"))
        header.pack(pady=14)

        # Config frame
        cfg = ctk.CTkFrame(self.root)
        cfg.pack(fill="x", padx=16, pady=10)

        # Subreddit selection
        row1 = ctk.CTkFrame(cfg, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(row1, text="Subreddit:", width=120, anchor="w").pack(side="left")
        self.subreddit_var = tk.StringVar(value="both")
        self.sub_combo = ctk.CTkComboBox(row1, values=["india", "AskReddit", "both"], variable=self.subreddit_var, width=180)
        self.sub_combo.pack(side="left", padx=8)

        # Timing mode
        row2 = ctk.CTkFrame(cfg, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(row2, text="Scan Mode:", width=120, anchor="w").pack(side="left")
        self.mode_var = tk.StringVar(value="hourly")
        self.rb_hourly = ctk.CTkRadioButton(row2, text="Hourly", variable=self.mode_var, value="hourly")
        self.rb_weekly = ctk.CTkRadioButton(row2, text="Weekly", variable=self.mode_var, value="weekly")
        self.rb_hourly.pack(side="left", padx=6)
        self.rb_weekly.pack(side="left", padx=6)

        # Test interval
        row3 = ctk.CTkFrame(cfg, fg_color="transparent")
        row3.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(row3, text="Test Interval (sec):", width=120, anchor="w").pack(side="left")
        self.interval_var = tk.StringVar(value="120")
        self.interval_entry = ctk.CTkEntry(row3, textvariable=self.interval_var, width=100)
        self.interval_entry.pack(side="left", padx=8)
        ctk.CTkLabel(row3, text="(Overrides Hourly/Weekly for development)").pack(side="left", padx=6)

        # Keywords
        row4 = ctk.CTkFrame(cfg, fg_color="transparent")
        row4.pack(fill="x", padx=10, pady=(6, 12))
        ctk.CTkLabel(row4, text="Keywords (comma-separated):", width=220, anchor="w").pack(side="left")
        self.kw_text = ctk.CTkTextbox(row4, height=60, width=600)
        self.kw_text.pack(side="left", padx=8)
        self.kw_text.insert("1.0", "help, advice, question, how to, need help, confused, stuck, problem, issue, guidance")

        # Buttons + status
        controls = ctk.CTkFrame(self.root)
        controls.pack(fill="x", padx=16, pady=8)
        self.btn_start = ctk.CTkButton(controls, text="Start", command=self.start_bot, width=120)
        self.btn_stop = ctk.CTkButton(controls, text="Stop", command=self.stop_bot, width=120, state="disabled")
        self.btn_start.pack(side="left", padx=6, pady=10)
        self.btn_stop.pack(side="left", padx=6, pady=10)
        self.status_lbl = ctk.CTkLabel(controls, text="Status: Stopped", text_color="red")
        self.status_lbl.pack(side="right", padx=10)

        # Tabs
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=10)

        # Logs tab
        self.tab_logs = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_logs, text="Live Logs")
        self.txt_logs = tk.Text(self.tab_logs, wrap="word", bg="#1e1e1e", fg="#e0e0e0", insertbackground="#e0e0e0")
        self.txt_logs.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(self.tab_logs, command=self.txt_logs.yview)
        self.txt_logs.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")

        # DB tab
        self.tab_db = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_db, text="Database")
        top_db = tk.Frame(self.tab_db)
        top_db.pack(fill="x", padx=6, pady=6)
        ttk.Button(top_db, text="Refresh", command=self.refresh_db).pack(side="left", padx=4)
        ttk.Button(top_db, text="Clear", command=self.clear_db).pack(side="left", padx=4)

        cols = ("ID", "Time", "Subreddit", "Post ID", "Keywords", "Success")
        self.tree = ttk.Treeview(self.tab_db, columns=cols, show="headings", height=14)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=140 if c != "Keywords" else 280)
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)

        # Start periodic UI tasks
        self.root.after(100, self.drain_logs)
        self.root.after(2000, self.refresh_db)

        # Current working dir for sanity
        self.log_line(f"Working directory: {os.getcwd()}")

    # ------------- UI helpers -------------
    def log_line(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.txt_logs.insert("end", f"{ts} - INFO - {msg}\n")
        self.txt_logs.see("end")

    def set_status(self, msg: str, color="green"):
        self.status_lbl.configure(text=f"Status: {msg}", text_color=color)

    def drain_logs(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.txt_logs.insert("end", line + "\n")
                self.txt_logs.see("end")
        except queue.Empty:
            pass
        self.root.after(100, self.drain_logs)

    # ------------- DB operations -------------
    def refresh_db(self):
        try:
            conn = sqlite3.connect("reddit_bot.db")
            cur = conn.cursor()
            cur.execute("""
                SELECT id, timestamp, subreddit, post_id, keywords_found, success
                FROM interactions
                ORDER BY id DESC LIMIT 150
            """)
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            messagebox.showerror("DB Error", str(e))
            return

        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in rows:
            # Format time
            tval = r[1]
            try:
                tval = datetime.fromisoformat(tval).strftime("%m-%d %H:%M")
            except Exception:
                pass
            kw = r[1] if r[1] is not None else ""
            if len(kw) > 45:
                kw = kw[:42] + "..."
            self.tree.insert("", "end", values=(r, tval, r[2], r[3], kw, "✓" if r[4] else "✗"))

    def clear_db(self):
        if not messagebox.askyesno("Confirm", "Delete all rows from database?"):
            return
        try:
            conn = sqlite3.connect("reddit_bot.db")
            cur = conn.cursor()
            cur.execute("DELETE FROM interactions")
            cur.execute("DELETE FROM performance_metrics")
            conn.commit()
            conn.close()
            self.refresh_db()
            messagebox.showinfo("Done", "Database cleared.")
        except Exception as e:
            messagebox.showerror("DB Error", str(e))

    # ------------- Bot control -------------
    def start_bot(self):
        if self.is_running:
            messagebox.showwarning("Running", "Bot is already running.")
            return

        # Collect settings
        sub_choice = self.subreddit_var.get().strip()
        kw_text = self.kw_text.get("1.0", "end").strip()
        keywords = [k.strip() for k in kw_text.split(",") if k.strip()]
        mode = self.mode_var.get().strip()
        interval_str = self.interval_var.get().strip()

        if not keywords:
            messagebox.showerror("Input Error", "Please provide at least one keyword.")
            return

        # Compute cycle delay
        cycle_delay = None
        if interval_str.isdigit() and int(interval_str) > 0:
            cycle_delay = int(interval_str)
        else:
            cycle_delay = 3600 if mode == "hourly" else 7 * 24 * 3600

        try:
            # Create bot instance
            self.bot = RedditBot()

            # Update bot config
            if sub_choice == "both":
                self.bot.config["subreddits"] = ["india", "AskReddit"]
            else:
                self.bot.config["subreddits"] = [sub_choice]
            self.bot.config["keywords"] = keywords
            self.bot.config.setdefault("rate_limits", {})
            self.bot.config["rate_limits"]["cycle_delay"] = cycle_delay

            # Start worker thread
            self.stop_event.clear()
            self.worker = threading.Thread(target=self._run_loop, daemon=True)
            self.worker.start()

            # UI state
            self.is_running = True
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.set_status("Running", "green")
            self.log_line("Bot started successfully! "
                          f"Subreddits={self.bot.config['subreddits']}, "
                          f"cycle_delay={cycle_delay}s")

        except Exception as e:
            messagebox.showerror("Start Error", str(e))

    def _run_loop(self):
        """
        Our own continuous loop:
        - Runs one scan cycle
        - Sleeps in 1-second steps so Stop is responsive
        """
        try:
            while not self.stop_event.is_set():
                self.bot.logger.info("Starting hourly scan cycle (GUI-managed loop)...")
                self.bot.run_hourly_scan()
                self.bot.logger.info("Scan cycle finished.")

                delay = int(self.bot.config["rate_limits"].get("cycle_delay", 3600))
                for _ in range(delay):
                    if self.stop_event.is_set():
                        break
                    if _ % 60 == 0:  # heartbeat every 60s
                        self.bot.logger.info("Heartbeat: waiting until next cycle...")
                    time.sleep(1)

        except Exception as e:
            logging.getLogger().error(f"Worker error: {e}")
        finally:
            try:
                if self.bot:
                    self.bot.cleanup()
            except Exception:
                pass
            self.is_running = False
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.set_status("Stopped", "red")
            self.log_line("Bot stopped.")

    def stop_bot(self):
        if not self.is_running:
            return
        self.log_line("Stopping bot...")
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=8)
        # UI updates handled in _run_loop finally

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = BotApp()
    app.run()
