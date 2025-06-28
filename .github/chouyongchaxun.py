import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import queue
import logging
import json
import os
import time
import datetime
import asyncio
import traceback
import concurrent.futures
import re
import sys

# 尝试导入必要的库，如果失败则给出提示
try:
    import openpyxl
    from playwright.async_api import async_playwright, expect, Error as PlaywrightError
    import pandas as pd
    import requests
    from playwright.sync_api import sync_playwright
    import lark_oapi as lark
    # 确保从 bitable v1 导入所有必要的类，如 FilterInfo, Condition, AppTableRecord 等
    from lark_oapi.api.bitable.v1 import *
except ImportError as e:
    # 细化错误提示
    missing_lib = e.name
    messagebox.showerror("库缺失", f"致命错误: 缺少 '{missing_lib}' 库。\n请运行 'pip install {missing_lib}' 后重试。")
    print(f"致命错误: 缺少 '{missing_lib}' 库。请通过 'pip install {missing_lib}' 安装后再运行程序。")
    exit()

# --- 全局配置 ---
CONFIG_FILE = "config.json"
COOKIE_FILE = "林客.json"
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# --- 日志设置 ---
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

# --- 主应用程序 ---
class MainApplication(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("抖音&林客一体化工具箱 V3.4.1") # 版本号微调
        self.geometry("850x750")

        self.configs = self.load_configs()
        self.task_running = False
        self.douyin_access_token = None
        self.feishu_client = None 

        log_filename = os.path.join(LOG_DIR, f"tool_log_{datetime.date.today().strftime('%Y-%m-%d')}.log")
        file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        self.queue_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(file_handler)
        logging.getLogger().addHandler(self.queue_handler)

        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.create_widgets()
        self.after(100, self.process_log_queue)

    def load_configs(self):
        default_configs = {
            "feishu_poi_excel": "门店ID.xlsx",
            "douyin_key": "awbeykzyos7kbidv",
            "douyin_secret": "4575440b156ecbe144284e4f69d284a2",
            "douyin_account_id": "7241078611527075855",
            "feishu_app_id": "",
            "feishu_app_secret": "",
            "feishu_app_token": "MslRbdwPca7P6qsqbqgcvpBGnRh",
            "feishu_table_id": "tbl0ErHhu8L4fAbN",
            "feishu_field_name": "商品ID",
            "poi_batch_size": 20,
            "feishu_max_workers": 5,
            "get_commission_source_field": "商品ID",
            "get_commission_target_field": "抽佣比例",
            "max_concurrent_pages": 5,
            "max_retries": 3,
            "retry_delay": 2,
            "headless_get": False,
            "set_commission_excel": "需设抽佣ID.xlsx",
            "commission_online": "10",
            "commission_offline": "10",
            "commission_zengliang": "0",
            "commission_zhiren": "0",
            "headless_set": False,
        }
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded_configs = json.load(f)
                    default_configs.update(loaded_configs)
            if "feishu_user_token" in default_configs:
                del default_configs["feishu_user_token"]
            return default_configs
        except (json.JSONDecodeError, IOError):
            return default_configs

    def save_configs(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, indent=4, ensure_ascii=False)
        except IOError as e:
            logging.error(f"无法保存配置文件: {e}")

    def create_widgets(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)
        tabs = {
            "第1步: 登录 | 获取Cookie": self.create_login_tab,
            "第2步: 飞书 | 同步商品ID": self.create_feishu_sync_tab,
            "第3步: 查询 | 获取佣金": self.create_get_commission_tab,
            "第4步: 设置 | 修改佣金": self.create_set_commission_tab,
        }
        for text, creation_func in tabs.items():
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=text)
            creation_func(frame)

    def create_login_tab(self, parent_frame):
        ttk.Label(parent_frame, text="第一步: 获取网站登录凭证 (Cookie)", font=("Arial", 16, "bold")).pack(pady=20)
        info_text = (
            f"本功能用于通过浏览器手动登录林客网站，并将登录状态保存到 `{COOKIE_FILE}` 文件中。\n\n"
            "操作流程:\n"
            "1. 点击下方的“启动浏览器登录”按钮。\n"
            "2. 在弹出的浏览器窗口中【手动完成扫码登录】操作。\n"
            f"3. 登录成功后，关闭浏览器，程序会自动保存登录状态。"
        )
        ttk.Label(parent_frame, text=info_text, justify=tk.LEFT, wraplength=750).pack(pady=10, padx=20)
        ttk.Button(parent_frame, text="启动浏览器登录", command=self.run_task_thread).pack(pady=20)

    def create_feishu_sync_tab(self, parent_frame):
        config_frame = ttk.LabelFrame(parent_frame, text="配置", padding=10)
        config_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        log_frame = ttk.LabelFrame(parent_frame, text="日志", padding=10)
        log_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(config_frame, text="门店ID文件:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.feishu_poi_excel_entry = ttk.Entry(config_frame, width=35)
        self.feishu_poi_excel_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW)
        self.feishu_poi_excel_entry.insert(0, self.configs.get("feishu_poi_excel", "门店ID.xlsx"))
        ttk.Button(config_frame, text="...", width=3, command=lambda: self.select_file(self.feishu_poi_excel_entry)).grid(row=0, column=3, padx=2)

        self.douyin_api_entries = self._create_api_entries(config_frame, "抖音API凭证", 1, {"抖音 Client Key": "douyin_key", "抖音 Client Secret": "douyin_secret", "抖音 Account ID": "douyin_account_id"})
        
        feishu_labels = {
            "飞书 App ID": "feishu_app_id", 
            "飞书 App Secret": "feishu_app_secret", 
            "飞书 App Token": "feishu_app_token", 
            "飞书 Table ID": "feishu_table_id", 
            "商品ID写入列名": "feishu_field_name"
        }
        self.feishu_api_entries = self._create_api_entries(config_frame, "飞书API凭证 (所有飞书功能共用)", 2, feishu_labels)

        perf_frame = ttk.LabelFrame(config_frame, text="性能参数", padding=5)
        perf_frame.grid(row=3, column=0, columnspan=4, sticky=tk.EW, pady=5)
        ttk.Label(perf_frame, text="POI批处理大小:").grid(row=0, column=0, sticky=tk.W, pady=2, padx=5)
        self.poi_batch_size_spinbox = ttk.Spinbox(perf_frame, from_=1, to=100, width=8)
        self.poi_batch_size_spinbox.grid(row=0, column=1, sticky=tk.W, pady=2, padx=5)
        self.poi_batch_size_spinbox.set(self.configs.get("poi_batch_size", 20))
        ttk.Label(perf_frame, text="查询线程数:").grid(row=1, column=0, sticky=tk.W, pady=2, padx=5)
        self.feishu_max_workers_spinbox = ttk.Spinbox(perf_frame, from_=1, to=20, width=8)
        self.feishu_max_workers_spinbox.grid(row=1, column=1, sticky=tk.W, pady=2, padx=5)
        self.feishu_max_workers_spinbox.set(self.configs.get("feishu_max_workers", 5))

        ttk.Button(config_frame, text="🚀 开始同步", command=self.run_task_thread).grid(row=4, column=0, columnspan=4, pady=20, sticky=tk.EW)
        
        self.feishu_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state='disabled')
        self.feishu_log.pack(fill=tk.BOTH, expand=True)

    def _create_api_entries(self, parent, title, grid_row, labels_keys):
        frame = ttk.LabelFrame(parent, text=title, padding=5)
        frame.grid(row=grid_row, column=0, columnspan=4, sticky=tk.EW, pady=5)
        entries = {}
        for i, (label, key) in enumerate(labels_keys.items()):
            ttk.Label(frame, text=f"{label}:").grid(row=i, column=0, sticky=tk.W, pady=2, padx=5)
            entry = ttk.Entry(frame, width=35)
            entry.grid(row=i, column=1, sticky=tk.EW, pady=2, padx=5)
            entry.insert(0, self.configs.get(key, ""))
            entries[key] = entry
        return entries

    def create_get_commission_tab(self, parent_frame):
        config_frame = ttk.LabelFrame(parent_frame, text="配置", padding=10)
        config_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        log_frame = ttk.LabelFrame(parent_frame, text="日志", padding=10)
        log_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        feishu_frame = ttk.LabelFrame(config_frame, text="飞书多维表格列名", padding=5)
        feishu_frame.grid(row=0, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        ttk.Label(feishu_frame, text="商品ID来源列:").grid(row=0, column=0, sticky=tk.W, pady=2, padx=5)
        self.get_commission_source_field_entry = ttk.Entry(feishu_frame, width=30)
        self.get_commission_source_field_entry.grid(row=0, column=1, sticky=tk.EW, pady=2, padx=5)
        self.get_commission_source_field_entry.insert(0, self.configs.get("get_commission_source_field", "商品ID"))

        ttk.Label(feishu_frame, text="佣金比例写入列:").grid(row=1, column=0, sticky=tk.W, pady=2, padx=5)
        self.get_commission_target_field_entry = ttk.Entry(feishu_frame, width=30)
        self.get_commission_target_field_entry.grid(row=1, column=1, sticky=tk.EW, pady=2, padx=5)
        self.get_commission_target_field_entry.insert(0, self.configs.get("get_commission_target_field", "抽佣比例"))

        # [GUI MODIFICATION] Removed the "Performance Parameters" frame.
        # These values will now be read directly from config.json.

        self.headless_get_var = tk.BooleanVar(value=self.configs.get("headless_get", False))
        # Adjusting grid row since the performance frame was removed
        ttk.Checkbutton(config_frame, text="无头模式 (后台运行)", variable=self.headless_get_var).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=10)

        # Adjusting grid row since the performance frame was removed
        ttk.Button(config_frame, text="从飞书查询并回写佣金", command=self.run_task_thread).grid(row=2, column=0, columnspan=3, pady=20, sticky=tk.EW)

        self.get_commission_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state='disabled')
        self.get_commission_log.pack(fill=tk.BOTH, expand=True)

    def create_set_commission_tab(self, parent_frame):
        config_frame = ttk.LabelFrame(parent_frame, text="配置", padding=10)
        config_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        log_frame = ttk.LabelFrame(parent_frame, text="日志", padding=10)
        log_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(config_frame, text="需设抽佣ID文件:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.set_commission_excel_entry = ttk.Entry(config_frame, width=30)
        self.set_commission_excel_entry.grid(row=0, column=1, sticky=tk.EW, columnspan=2)
        self.set_commission_excel_entry.insert(0, self.configs.get("set_commission_excel", "需设抽佣ID.xlsx"))
        ttk.Button(config_frame, text="...", width=3, command=lambda: self.select_file(self.set_commission_excel_entry)).grid(row=0, column=3, padx=2)

        ttk.Label(config_frame, text="佣金比例 (%)", font=("Arial", 10, "bold")).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(10,0))
        
        self.commission_entries = {}
        commission_labels = {'线上经营': 'commission_online', '线下扫码': 'commission_offline', '增量宝': 'commission_zengliang', '职人账号': 'commission_zhiren'}
        row_idx = 2
        for label, key in commission_labels.items():
            ttk.Label(config_frame, text=f"{label}:").grid(row=row_idx, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(config_frame, width=10)
            entry.grid(row=row_idx, column=1, sticky=tk.W, pady=2, columnspan=2)
            entry.insert(0, self.configs.get(key, "0"))
            self.commission_entries[key] = entry
            row_idx += 1
            
        self.headless_set_var = tk.BooleanVar(value=self.configs.get("headless_set", False))
        ttk.Checkbutton(config_frame, text="无头模式 (后台运行)", variable=self.headless_set_var).grid(row=row_idx, column=0, columnspan=3, sticky=tk.W, pady=10)
        row_idx += 1

        ttk.Button(config_frame, text="开始执行", command=self.run_task_thread).grid(row=row_idx, column=0, columnspan=4, pady=20, sticky=tk.EW)

        self.set_commission_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state='disabled')
        self.set_commission_log.pack(fill=tk.BOTH, expand=True)

    def get_current_log_widget(self):
        selected_tab_text = self.notebook.tab(self.notebook.select(), "text")
        if "飞书" in selected_tab_text: return self.feishu_log
        elif "查询" in selected_tab_text: return self.get_commission_log
        elif "设置" in selected_tab_text: return self.set_commission_log
        return None

    def log_to_gui(self, message):
        log_widget = self.get_current_log_widget()
        if not log_widget: print(message); return
        log_widget.config(state='normal')
        log_widget.insert(tk.END, message + '\n')
        log_widget.see(tk.END)
        log_widget.config(state='disabled')
        self.update_idletasks()

    def process_log_queue(self):
        try:
            while True: self.log_to_gui(self.log_queue.get_nowait())
        except queue.Empty: pass
        finally: self.after(100, self.process_log_queue)
            
    def set_ui_state(self, is_running):
        self.task_running = is_running
        state = tk.DISABLED if is_running else tk.NORMAL
        for tab_id in self.notebook.tabs():
            for widget in self.nametowidget(tab_id).winfo_children(): self._set_widget_state(widget, state)
    
    def _set_widget_state(self, widget, state):
        try:
            if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Spinbox, ttk.Checkbutton)) and 'readonly' not in str(widget.cget('state')):
                 widget.configure(state=state)
        except tk.TclError: pass
        for child in widget.winfo_children(): self._set_widget_state(child, state)

    def select_file(self, entry_widget):
        filepath = filedialog.askopenfilename(title="选择Excel文件", filetypes=(("Excel files", "*.xlsx"), ("All files", "*.*")))
        if filepath:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, filepath)

    def run_task_thread(self):
        if self.task_running: messagebox.showwarning("提示", "已有任务在运行，请稍候。"); return
        self.update_and_save_configs()
        selected_tab_text = self.notebook.tab(self.notebook.select(), "text")
        target_task_func = None
        if "登录" in selected_tab_text: target_task_func = self.task_get_cookie
        elif "飞书" in selected_tab_text: target_task_func = self.task_sync_feishu_ids
        elif "查询" in selected_tab_text:
            if not os.path.exists(COOKIE_FILE): messagebox.showerror("错误", f"`{COOKIE_FILE}` 文件不存在。\n请先在第1步中获取登录状态。"); return
            target_task_func = self.task_get_commission
        elif "设置" in selected_tab_text:
            if not os.path.exists(COOKIE_FILE): messagebox.showerror("错误", f"`{COOKIE_FILE}` 文件不存在。\n请先在第1步中获取登录状态。"); return
            target_task_func = self.task_set_commission
        if target_task_func:
            self.set_ui_state(is_running=True)
            log_widget = self.get_current_log_widget()
            if log_widget:
                log_widget.config(state='normal')
                log_widget.delete('1.0', tk.END)
                log_widget.config(state='disabled')
            if asyncio.iscoroutinefunction(target_task_func):
                thread = threading.Thread(target=lambda: asyncio.run(target_task_func()), daemon=True)
            else:
                thread = threading.Thread(target=target_task_func, daemon=True)
            thread.start()

    def update_and_save_configs(self):
        def get_stripped(widget): return widget.get().strip()
        def update_config_if_not_empty(widget, config_key):
            value = get_stripped(widget)
            if value: self.configs[config_key] = value

        if hasattr(self, 'feishu_poi_excel_entry'): self.configs["feishu_poi_excel"] = get_stripped(self.feishu_poi_excel_entry)
        if hasattr(self, 'set_commission_excel_entry'): self.configs["set_commission_excel"] = get_stripped(self.set_commission_excel_entry)
        if hasattr(self, 'douyin_api_entries'):
            for key, entry in self.douyin_api_entries.items():
                if entry: update_config_if_not_empty(entry, key)
        if hasattr(self, 'feishu_api_entries'):
            for key, entry in self.feishu_api_entries.items():
                if entry: update_config_if_not_empty(entry, key)
        if hasattr(self, 'poi_batch_size_spinbox'): self.configs["poi_batch_size"] = int(self.poi_batch_size_spinbox.get())
        if hasattr(self, 'feishu_max_workers_spinbox'): self.configs["feishu_max_workers"] = int(self.feishu_max_workers_spinbox.get())
        if hasattr(self, 'get_commission_source_field_entry'): update_config_if_not_empty(self.get_commission_source_field_entry, "get_commission_source_field")
        if hasattr(self, 'get_commission_target_field_entry'): update_config_if_not_empty(self.get_commission_target_field_entry, "get_commission_target_field")
        
        # [GUI MODIFICATION] Removed saving from widgets that were deleted
        # if hasattr(self, 'max_pages_spinbox'): self.configs["max_concurrent_pages"] = int(self.max_pages_spinbox.get())
        # if hasattr(self, 'max_retries_get_spinbox'): self.configs["max_retries"] = int(self.max_retries_get_spinbox.get())
        # if hasattr(self, 'retry_delay_get_spinbox'): self.configs["retry_delay"] = int(self.retry_delay_get_spinbox.get())
        
        if hasattr(self, 'headless_get_var'): self.configs["headless_get"] = self.headless_get_var.get()
        if hasattr(self, 'headless_set_var'): self.configs["headless_set"] = self.headless_set_var.get()
        if hasattr(self, 'commission_entries'):
            # This complex logic can be simplified. Let's map keys directly.
            key_map = {
                '线上经营': 'commission_online',
                '线下扫码': 'commission_offline',
                '增量宝': 'commission_zengliang',
                '职人账号': 'commission_zhiren'
            }
            for label, key in key_map.items():
                 # Check if the entry widget exists for this key before accessing
                if key in self.commission_entries and self.commission_entries[key]:
                    self.configs[key] = get_stripped(self.commission_entries[key])

        self.save_configs()

    def _on_closing(self):
        if self.task_running:
            if messagebox.askokcancel("退出确认", "任务仍在运行中，确定要强制退出吗？"): self.destroy()
        else:
            self.update_and_save_configs()
            self.destroy()

    # ==============================================================================
    # 任务逻辑 (Task Logics)
    # ==============================================================================
    def task_get_cookie(self):
        logging.info("启动获取Cookie任务...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://www.life-partner.cn/")
                messagebox.showinfo("等待手动登录", "请在打开的浏览器中完成扫码登录，然后【关闭该浏览器窗口】以继续。")
                closed_event = threading.Event()
                page.on('close', lambda p: closed_event.set())
                closed_event.wait() 
                context.storage_state(path=COOKIE_FILE)
                logging.info(f"登录状态已成功保存到: {COOKIE_FILE}")
                messagebox.showinfo("成功", f"登录状态已成功保存到: {COOKIE_FILE}")
        except Exception as e:
            logging.error(f"获取Cookie时发生错误: {e}", exc_info=True)
            messagebox.showerror("错误", f"获取Cookie时发生错误: {e}")
        finally:
            self.set_ui_state(is_running=False)

    def task_sync_feishu_ids(self):
        logging.info("启动同步商品ID到飞书任务...")
        try:
            if not self._init_feishu_client(): return
            douyin_configs = {"douyin_key": self.configs.get("douyin_key"), "douyin_secret": self.configs.get("douyin_secret"), "douyin_account_id": self.configs.get("douyin_account_id")}
            if not self._get_douyin_client_token(douyin_configs): return

            # 新增步骤1: 调用新函数，首先获取飞书中所有已存在的商品ID
            existing_feishu_ids = self._get_all_existing_product_ids_from_feishu()
            if existing_feishu_ids is None:
                # 如果获取失败（比如网络或权限问题），则终止任务
                logging.error("无法从飞书获取现有数据，任务中止。")
                self.set_ui_state(is_running=False)
                return

            poi_excel_path = self.configs['feishu_poi_excel']
            if not os.path.exists(poi_excel_path):
                messagebox.showerror("文件错误", f"找不到门店ID文件: {poi_excel_path}"); return
            poi_ids = self._load_poi_ids_from_excel(poi_excel_path)
            if not poi_ids: return

            poi_batch_size = self.configs['poi_batch_size']
            total_poi_batches = (len(poi_ids) + poi_batch_size - 1) // poi_batch_size
            for i in range(0, len(poi_ids), poi_batch_size):
                poi_chunk = poi_ids[i:i + poi_batch_size]
                current_batch_num = i // poi_batch_size + 1
                logging.info(f"\n--- 开始处理POI批次 {current_batch_num}/{total_poi_batches} ({len(poi_chunk)}个POI) ---")
                all_product_ids_for_chunk = set()
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.configs['feishu_max_workers']) as executor:
                    future_to_poi = {executor.submit(self._get_all_product_ids_for_poi, poi, douyin_configs['douyin_account_id']): poi for poi in poi_chunk}
                    for future in concurrent.futures.as_completed(future_to_poi):
                        product_ids_set = future.result()
                        if product_ids_set: all_product_ids_for_chunk.update(product_ids_set)

                # 修改/新增步骤2: 在这里进行去重逻辑判断
                # 使用集合的差集运算，高效地找出本次需要新增的ID
                ids_to_add = all_product_ids_for_chunk - existing_feishu_ids

                if not ids_to_add:
                    logging.info(f"--- POI批次 {current_batch_num} 未查询到任何【新的】商品ID可写入，跳过。 ---")
                    logging.info(f"  (本次从抖音查询到 {len(all_product_ids_for_chunk)} 个, 但均已存在于飞书)")
                    continue

                logging.info(f"POI批次 {current_batch_num} 查询结束，共收集到 {len(all_product_ids_for_chunk)} 个ID，其中 {len(ids_to_add)} 个是新ID，准备写入飞书...")
                
                # 修改: 只为新ID创建飞书记录
                records_to_create = [AppTableRecord.builder().fields({self.configs['feishu_field_name']: str(pid)}).build() for pid in ids_to_add]

                for j in range(0, len(records_to_create), 500):
                    record_batch = records_to_create[j:j+500]
                    logging.info(f"  向飞书写入数据... (部分 {j//500 + 1})")
                    add_result = self._add_records_to_feishu_table(record_batch, self.configs['feishu_app_token'], self.configs['feishu_table_id'])
                    if not add_result["success"]:
                        logging.error(f"  写入飞书失败: {add_result.get('message')}"); break
                    else:
                        # 新增步骤3: 写入成功后，更新内存中的ID集合，防止同一任务内的重复添加
                        existing_feishu_ids.update(ids_to_add)

            logging.info("\n所有POI批次处理完成！")
            messagebox.showinfo("任务完成", "所有POI批次处理完成！")
        except Exception as e:
            logging.error(f"同步飞书任务主线程出错: {e}", exc_info=True)
        finally:
            self.set_ui_state(is_running=False)
            self.feishu_client = None
            

    def _get_douyin_client_token(self, douyin_configs):
        url = "https://open.douyin.com/oauth/client_token/"
        payload = {"client_key": douyin_configs['douyin_key'], "client_secret": douyin_configs['douyin_secret'], "grant_type": "client_credential"}
        headers = {"Content-Type": "application/json"}
        logging.info("开始获取抖音 Client Token...")
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("data") and "access_token" in data["data"]:
                self.douyin_access_token = data["data"]["access_token"]; return True
            else:
                error_msg = data.get("data", {}).get("description", "获取Token失败")
                messagebox.showerror("API错误", f"获取抖音Token失败: {error_msg}"); logging.error(f"获取抖音Token失败: {error_msg}"); return False
        except requests.RequestException as e:
            messagebox.showerror("网络错误", f"请求抖音Token时出错: {e}"); logging.error(f"请求抖音Token时出错: {e}"); return False

    def _load_poi_ids_from_excel(self, file_path):
        try:
            df = pd.read_excel(file_path, header=0, usecols=[0], dtype=str)
            poi_ids = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
            if not poi_ids: messagebox.showerror("文件错误", f"未能从Excel文件 '{file_path}' 的第一列读取到任何POI ID。"); return []
            logging.info(f"成功从 '{file_path}' 加载 {len(poi_ids)} 个POI ID。")
            return poi_ids
        except Exception as e:
            messagebox.showerror("文件读取错误", f"读取Excel '{file_path}' 时出错: {e}"); return []

    def _query_douyin_online_products(self, params):
        if not self.douyin_access_token: return {"success": False, "message": "抖音 Access Token 缺失"}
        url = "https://open.douyin.com/goodlife/v1/goods/product/online/query/"
        headers = {'Content-Type': 'application/json', 'access-token': self.douyin_access_token}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            response_json = response.json()
            if response_json.get("BaseResp", {}).get("StatusCode") == 0:
                return {"success": True, **response_json.get("data", {})}
            else:
                error_message = response_json.get("BaseResp", {}).get("StatusMessage", "未知API错误")
                logging.error(f"查询抖音API返回错误: {error_message}. 完整响应: {response_json}"); return {"success": False, "message": f"API错误: {error_message}"}
        except Exception as e:
            logging.error(f"查询抖音线上商品时发生严重错误: {e}", exc_info=True); return {"success": False, "message": f"请求错误: {e}"}

    def _get_all_product_ids_for_poi(self, poi_id, account_id):
        all_product_ids = set()
        current_cursor, page = "", 1
        while True:
            logging.info(f"    查询POI[{poi_id}] 第 {page} 页...")
            params = {"account_id": account_id, "poi_ids": [poi_id], "count": 50, "cursor": current_cursor}
            result = self._query_douyin_online_products(params)
            if result.get("success"):
                for p_info in result.get("products", []):
                    if product_id_val := p_info.get("product", {}).get("product_id"):
                        all_product_ids.add(str(product_id_val))
                if result.get("has_more"): current_cursor, page = result.get("next_cursor", ""), page + 1; time.sleep(0.2)
                else: break
            else:
                logging.error(f"    错误：查询POI[{poi_id}]失败: {result.get('message')}"); return set()
        logging.info(f"    POI[{poi_id}]查询完成，找到 {len(all_product_ids)} 个商品ID。")
        return all_product_ids

    def _init_feishu_client(self):
        app_id = self.configs.get("feishu_app_id")
        app_secret = self.configs.get("feishu_app_secret")
        if not app_id or not app_secret:
            messagebox.showerror("飞书配置错误", "请在“飞书 | 同步商品ID”选项卡中填写飞书 App ID 和 App Secret。")
            return False
        logging.info("正在初始化飞书客户端...")
        self.feishu_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).log_level(lark.LogLevel.WARNING).build()
        logging.info("飞书客户端初始化成功。")
        return True

    def _add_records_to_feishu_table(self, records_to_add, app_token, table_id):
        if not records_to_add: return {"success": True}
        if not self.feishu_client: return {"success": False, "message": "飞书客户端未初始化"}
        try:
            request_body = BatchCreateAppTableRecordRequestBody.builder().records(records_to_add).build()
            req = BatchCreateAppTableRecordRequest.builder().app_token(app_token).table_id(table_id).request_body(request_body).build()
            res = self.feishu_client.bitable.v1.app_table_record.batch_create(req)
            if not res.success():
                error_details = f"Code={res.code}, Msg={res.msg}, LogID={res.get_log_id()}"
                logging.error(f"新增记录到飞书失败: {error_details}"); return {"success": False, "message": f"新增失败: {res.msg} (Code: {res.code})"}
            logging.info(f"成功向飞书表格新增 {len(res.data.records)} 条记录。")
            return {"success": True}
        except Exception as e:
            logging.error(f"写入飞书时发生未知错误: {e}", exc_info=True); return {"success": False, "message": f"未知错误: {e}"}

    def _get_all_existing_product_ids_from_feishu(self):
        """从飞书分页查询并获取指定表格中已存在的所有商品ID。"""
        field_name = self.configs['feishu_field_name']
        logging.info(f"开始从飞书获取已存在的商品ID，目标列: '{field_name}'...")
        existing_ids = set()
        page_token = None

        while True:
            try:
                # 仅请求我们需要的商品ID列
                request_body = SearchAppTableRecordRequestBody.builder() \
                    .field_names([field_name]) \
                    .build()
                
                # 构建请求，如果 page_token 存在，则用于翻页
                request_builder = SearchAppTableRecordRequest.builder() \
                    .app_token(self.configs['feishu_app_token']) \
                    .table_id(self.configs['feishu_table_id']) \
                    .page_size(500) \
                    .request_body(request_body)# 使用API允许的最大分页数量以提高效率

                if page_token:
                    request_builder.page_token(page_token)
                
                request = request_builder.build()
                response = self.feishu_client.bitable.v1.app_table_record.search(request)

                if not response.success():
                    logging.error(f"查询飞书现有记录失败: Code={response.code}, Msg={response.msg}")
                    messagebox.showerror("飞书API错误", f"查询现有记录失败: {response.msg}")
                    return None # 返回None表示操作失败

                items = response.data.items or []
                for item in items:
                    # 从返回的记录中提取商品ID文本
                    if field_name in item.fields and item.fields[field_name]:
                        product_id_text = item.fields[field_name][0].get('text', '')
                        if product_id_text:
                            existing_ids.add(product_id_text.strip())

                # 判断是否还有更多页
                if response.data.has_more:
                    page_token = response.data.page_token
                else:
                    break # 如果没有更多页，则退出循环
            except Exception as e:
                logging.error(f"查询飞书现有记录时发生异常: {e}", exc_info=True)
                messagebox.showerror("程序异常", f"查询飞书记录时出错: {e}")
                return None # 返回None表示操作失败
        
        logging.info(f"成功从飞书获取到 {len(existing_ids)} 个已存在的商品ID。")
        return existing_ids
    

    #第3部分函数实现

    async def task_get_commission(self):
        logging.info("启动从飞书查询并回写佣金任务...")
        if not self._init_feishu_client():
            self.set_ui_state(False); return
        try:
            tasks_to_process = await self._get_empty_commission_records_from_feishu()
            if tasks_to_process is None:
                messagebox.showerror("错误", "从飞书获取待处理记录失败，请检查日志。")
                return
            if not tasks_to_process:
                logging.info("未在飞书中找到需要处理的记录。")
                messagebox.showinfo("任务提示", "未在飞书中找到“抽佣比例”为空的记录。")
                return
            logging.info(f"共从飞书获取到 {len(tasks_to_process)} 条待处理记录。")
            await self.async_get_commission_worker(tasks_to_process)
        except Exception as e:
            logging.error(f"获取佣金任务主线程出错: {e}", exc_info=True)
        finally:
            self.set_ui_state(is_running=False)
            self.feishu_client = None

    async def _get_empty_commission_records_from_feishu(self):
        source_field = self.configs["get_commission_source_field"]
        target_field = self.configs["get_commission_target_field"]
        logging.info(f"开始从飞书查询 '{target_field}' 为空的记录...")
        all_records = []
        page_token = None
        while True:
            try:
                filter_condition = Condition.builder() \
                    .field_name(target_field) \
                    .operator("isEmpty") \
                    .value([]) \
                    .build()
                
                filter_obj = FilterInfo.builder().conjunction("and").conditions([filter_condition]).build()
                
                request_body = SearchAppTableRecordRequestBody.builder() \
                    .field_names([source_field]) \
                    .filter(filter_obj) \
                    .build()

                # [BUG FIX] 动态构建请求，仅在 page_token 有效时才添加
                request_builder = SearchAppTableRecordRequest.builder() \
                    .app_token(self.configs['feishu_app_token']) \
                    .table_id(self.configs['feishu_table_id']) \
                    .page_size(500) \
                    .request_body(request_body)

                if page_token:
                    request_builder.page_token(page_token)

                request = request_builder.build()
                
                response = self.feishu_client.bitable.v1.app_table_record.search(request)

                if not response.success():
                    logging.error(f"查询飞书记录失败: Code={response.code}, Msg={response.msg}, LogId={response.get_log_id()}")
                    return None
                    
                items = response.data.items or []
                for item in items:
                    if source_field in item.fields and item.fields[source_field]:
                        # 假设商品ID是文本类型字段
                        product_id_text = item.fields[source_field][0].get('text', '')
                        if product_id_text:
                           all_records.append({"id": product_id_text, "record_id": item.record_id})

                if response.data.has_more:
                    page_token = response.data.page_token
                else: 
                    break
            except Exception as e:
                logging.error(f"查询飞书记录时发生异常: {traceback.format_exc()}")
                messagebox.showerror("飞书查询错误", f"查询飞书记录时出错: {e}")
                return None
        return all_records

    async def _update_feishu_record(self, record_id, commission_info):
        target_field = self.configs["get_commission_target_field"]
        try:
            record = AppTableRecord.builder().fields({target_field: str(commission_info)}).build()
            req = UpdateAppTableRecordRequest.builder().app_token(self.configs['feishu_app_token']).table_id(self.configs['feishu_table_id']).record_id(record_id).request_body(record).build()
            response = self.feishu_client.bitable.v1.app_table_record.update(req)
            if not response.success():
                logging.error(f"更新飞书记录 {record_id} 失败: Code={response.code}, Msg={response.msg}")
                return False
            return True
        except Exception as e:
            logging.error(f"更新飞书记录 {record_id} 时发生异常: {e}", exc_info=True)
            return False

    async def async_get_commission_worker(self, tasks_to_process):
        max_pages = self.configs["max_concurrent_pages"]
        headless = self.configs["headless_get"]
        max_retries = self.configs["max_retries"]
        retry_delay = self.configs["retry_delay"]
        base_url = f"https://www.life-partner.cn/vmok/order-detail?from_page=order_management&merchantId={self.configs['douyin_account_id']}&orderId=7494097018429261839&queryScene=0&skuOrderId=1829003050957856&tabName=ChargeSetting"
        task_queue = asyncio.Queue()
        for task in tasks_to_process: await task_queue.put(task)
        total_tasks_count = len(tasks_to_process)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(storage_state=COOKIE_FILE)
            processed_count = 0
            async def worker(worker_id):
                nonlocal processed_count
                logging.info(f"[工 {worker_id}] 已启动...")
                page = await context.new_page()
                try:
                    await page.goto(base_url, timeout=120000, wait_until="domcontentloaded")
                    logging.info(f"[工作者 {worker_id}] 页面加载完成。")
                    await page.wait_for_timeout(3000)
                    while not task_queue.empty():
                        task = await task_queue.get()
                        product_id, record_id = task["id"], task["record_id"]
                        logging.info(f"[工作者 {worker_id}] 处理 ID: {product_id} (飞书记录: {record_id})")
                        status, commission_info = await self._process_id_on_page(page, product_id, max_retries, retry_delay)
                        if status == "已设置":
                            logging.info(f"  -> ID {product_id} 查询到佣金: {commission_info}，回写飞书...")
                            success = await self._update_feishu_record(record_id, commission_info)
                            if success: logging.info(f"  ✔ 回写记录 {record_id} 成功。")
                            else: logging.error(f"  ❌ 回写记录 {record_id} 失败。")
                        else:
                            logging.info(f"  -> ID {product_id} 未查询到佣金，跳过回写。")
                        processed_count += 1
                        logging.info(f"-> [进度 {processed_count}/{total_tasks_count}]")
                        task_queue.task_done()
                except Exception as e_page_setup:
                    logging.error(f"!!! [工作者 {worker_id}] 失败: {e_page_setup}", exc_info=True)
                finally:
                    logging.info(f"[工作者 {worker_id}] 关闭页面...")
                    await page.close()
            workers = [asyncio.create_task(worker(i + 1)) for i in range(max_pages)]
            await task_queue.join()
            await asyncio.gather(*workers, return_exceptions=True)
            await context.close()
            await browser.close()
        logging.info("\n所有任务处理完成！")
        messagebox.showinfo("任务完成", "所有佣金查询及回写任务处理完成！")

    async def _process_id_on_page(self, page, product_id, max_retries, retry_delay):
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0: logging.info(f"    -> [ID: {product_id}] 第 {attempt + 1}/{max_retries + 1} 次尝试...")
                input_field = page.get_by_role("textbox", name="商品名称/ID")
                await expect(input_field).to_be_visible(timeout=20000)
                await input_field.clear()
                await input_field.fill(str(product_id))
                await page.get_by_test_id("查询").click()
                id_in_result_locator = page.locator(".okee-lp-Table-Body .okee-lp-Table-Row").first.get_by_text(str(product_id), exact=True)
                await expect(id_in_result_locator).to_be_visible(timeout=30000)
                commission_status_locator = page.locator(".okee-lp-Table-Cell > .lp-flex > .okee-lp-tag").first
                await expect(commission_status_locator).to_be_visible(timeout=15000)
                status_text = (await commission_status_locator.text_content() or "").strip()
                status_result = "已设置" if status_text == "已设置" else f"未设置 ({status_text})"
                commission_info = "未找到"
                if status_result == "已设置":
                    channel_info_locator = page.locator("div.lp-flex.lp-items-center:has-text('%')").first
                    if await channel_info_locator.is_visible(timeout=5000):
                        commission_info = (await channel_info_locator.text_content() or "").strip().replace('"', '')
                return status_result, commission_info
            except Exception as e:
                if attempt < max_retries: logging.warning(f"    ! [ID: {product_id}] 查询超时 (尝试 {attempt + 1})。"); await asyncio.sleep(retry_delay)
                else: logging.error(f"    !! [ID: {product_id}] 所有重试失败。"); error_msg = str(e).splitlines()[0]; return "查询超时", f"超时: {error_msg}"
        return "查询失败", "未知错误"
    
    #第4部分函数实现
    
    async def task_set_commission(self):
        logging.info("启动设置佣金任务...")
        excel_file = self.configs["set_commission_excel"]
        if not os.path.exists(excel_file):
            logging.error(f"文件未找到: {excel_file}"); self.set_ui_state(is_running=False); return
        try:
            workbook = openpyxl.load_workbook(excel_file)
            sheet = workbook.active
            tasks = [{"id": str(c.value).strip(), "row": c.row} for c in sheet['A'] if c.value and c.row > 1]
        except Exception as e:
            logging.error(f"加载Excel '{excel_file}' 失败: {e}"); self.set_ui_state(is_running=False); return
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=self.configs["headless_set"])
                context = await browser.new_context(storage_state=COOKIE_FILE)
                page = await context.new_page()
                base_url = "https://www.life-partner.cn/vmok/order-detail?from_page=order_management&merchantId=7241078611527075855&orderId=7494097018429261839&queryScene=0&skuOrderId=1829003050957856&tabName=ChargeSetting"
                await page.goto(base_url, timeout=90000)
                for i, task in enumerate(tasks):
                    pid, row = task["id"], task["row"]
                    logging.info(f"--- [{i+1}/{len(tasks)}] 处理商品ID: {pid} ---")
                    commission_values = {'线上经营': self.configs.get('commission_online', '0'),'线下扫码': self.configs.get('commission_offline', '0'),'增量宝': self.configs.get('commission_zengliang', '0'),'职人账号': self.configs.get('commission_zhiren', '0')}
                    success = await self._set_single_commission(page, pid, commission_values)
                    sheet.cell(row=row, column=2).value = "设置成功" if success else "设置失败"
                    try:
                        await asyncio.to_thread(workbook.save, excel_file)
                    except PermissionError:
                        messagebox.showerror("文件占用", f"保存Excel失败，文件 '{excel_file}' 被占用。请关闭后重试。"); break
                await browser.close()
                logging.info("\n所有佣金设置任务处理完成！")
                messagebox.showinfo("任务完成", "所有佣金设置任务处理完成！")
            except Exception as e:
                logging.error(f"设置佣金时发生严重错误: {e}", exc_info=True)
                messagebox.showerror("严重错误", f"设置佣金时发生严重错误: {e}")
            finally:
                self.set_ui_state(is_running=False)

    async def _set_single_commission(self, page, product_id, commission_values):
        try:
            logging.info(f"  - 步骤1: 搜索 {product_id}...")
            input_field = page.get_by_role("textbox", name="商品名称/ID")
            await expect(input_field).to_be_visible(timeout=20000)
            await input_field.clear(); await input_field.fill(str(product_id))
            await page.get_by_test_id("查询").click()
            set_commission_button = page.get_by_role("button", name="设置佣金")
            await expect(set_commission_button).to_be_visible(timeout=15000)
            logging.info("  - 步骤2: 打开弹窗...")
            await set_commission_button.click()
            popup_title = page.get_by_text("设置佣金比例", exact=True)
            await expect(popup_title).to_be_visible(timeout=10000)
            logging.info("  - 步骤3: 填写佣金...")
            for label, value in commission_values.items():
                regex_pattern = re.compile(f"^{label}%$")
                input_locator = page.locator("div").filter(has_text=regex_pattern).get_by_placeholder("请输入")
                await expect(input_locator).to_be_visible(timeout=5000)
                await input_locator.fill(str(value))
                logging.info(f"    - '{label}' 已设置为 '{value}%'")
            logging.info("  - 步骤4: 提交...")
            submit_button = page.get_by_role("button", name="提交审核")
            await submit_button.click()
            await expect(popup_title).to_be_hidden(timeout=15000)
            logging.info(f"  ✔ [成功] ID: {product_id} 设置成功。")
            return True
        except Exception as e:
            error_msg = str(e).split('\n')[0]
            logging.error(f"  ❌ [失败] 为ID {product_id} 设置佣金时出错: {error_msg}", exc_info=False)
            try:
                screenshot_path = os.path.join(LOG_DIR, f"error_set_commission_{product_id}_{int(time.time())}.png")
                await page.screenshot(path=screenshot_path)
                logging.info(f"  - 错误截图已保存至: {screenshot_path}")
            except Exception as screenshot_error:
                logging.error(f"  - 尝试保存错误截图失败: {screenshot_error}")
            return False

# ==============================================================================
# 程序主入口
# ==============================================================================
if __name__ == "__main__":
    app = MainApplication()
    app.mainloop()
