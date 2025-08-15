import tkinter as tk
from tkinter import ttk, messagebox
import requests
import time
import threading
import json

# --- 配置信息 ---
CLIENT_KEY = "awbeykzyos7kbidv"
CLIENT_SECRET = "4575440b156ecbe144284e4f69d284a2"
ACCOUNT_ID = "7241078611527075855"

# 用于缓存 access_token
token_cache = {
    "access_token": None,
    "expires_at": 0
}

def get_douyin_access_token():
    """获取或刷新抖音的 client_access_token"""
    now = time.time()
    if token_cache["access_token"] and token_cache["expires_at"] > now + 60:
        return token_cache["access_token"]

    url = "https://open.douyin.com/oauth/client_token/"
    headers = {"Content-Type": "application/json"}
    payload = {
        "grant_type": "client_credential",
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", {})
        
        if data.get("error_code") == 0:
            access_token = data.get("access_token")
            expires_in = data.get("expires_in")
            token_cache["access_token"] = access_token
            token_cache["expires_at"] = now + expires_in
            return access_token
        else:
            error_msg = f"获取Token失败: {data.get('description')}"
            messagebox.showerror("API错误", error_msg)
            return None
    except requests.exceptions.RequestException as e:
        error_msg = f"网络请求错误: {e}"
        messagebox.showerror("网络错误", error_msg)
        return None

def get_product_by_id(product_ids_str):
    """根据商品ID直接查询商品数据"""
    access_token = get_douyin_access_token()
    if not access_token:
        return {"error": "无法获取 access_token"}

    # --- 核心修改：使用新的API接口 ---
    api_url = "https://open.douyin.com/goodlife/v1/goods/product/online/get/"
    headers = {"access-token": access_token}
    
    # --- 核心修改：使用 product_ids 参数 ---
    # 将输入的字符串（可能包含逗号）直接传递
    params = {
        "account_id": ACCOUNT_ID,
        "product_ids": product_ids_str,
    }
    
    try:
        response = requests.get(api_url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        api_data = response.json()

        if api_data.get("BaseResp", {}).get("StatusCode") != 0:
             return {"error": api_data.get("BaseResp", {}).get("StatusMessage"), "raw_json": api_data}

        # --- 核心修改：解析 product_onlines 字段 ---
        products = api_data.get("data", {}).get("product_onlines", [])
        
        processed_results = []
        for product_info in products:
            product_data = product_info.get("product", {})
            poi_list = product_data.get("pois", [])
            poi_ids = [poi.get("poi_id") for poi in poi_list if poi.get("poi_id")]

            processed_results.append({
                "product_id": product_data.get("product_id"),
                "product_name": product_data.get("product_name"),
                "poi_ids": poi_ids
            })
        
        return {"success": processed_results, "raw_json": api_data}

    except requests.exceptions.RequestException as e:
        return {"error": f"查询商品时网络错误: {e}", "raw_json": {"error": str(e)}}


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("抖音商品ID查询POI工具 (精确版)")
        self.root.geometry("800x650")

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        paned_window = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(paned_window, padding=5)
        paned_window.add(top_frame, weight=1)

        search_frame = ttk.Frame(top_frame)
        search_frame.pack(fill=tk.X, pady=5)
        
        # --- 界面文本优化 ---
        ttk.Label(search_frame, text="输入商品ID (多个请用英文逗号,隔开):").pack(side=tk.LEFT, padx=(0, 5))
        self.search_entry = ttk.Entry(search_frame)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<Return>", self.start_search)

        self.search_button = ttk.Button(search_frame, text="查询", command=self.start_search)
        self.search_button.pack(side=tk.LEFT, padx=(5, 0))

        results_frame = ttk.Labelframe(top_frame, text="查询结果", padding=5)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.results_text = tk.Text(results_frame, wrap=tk.WORD, state="disabled", height=10)
        scrollbar_res = ttk.Scrollbar(results_frame, command=self.results_text.yview)
        self.results_text.config(yscrollcommand=scrollbar_res.set)
        
        scrollbar_res.pack(side=tk.RIGHT, fill=tk.Y)
        self.results_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        bottom_frame = ttk.Frame(paned_window, padding=5)
        paned_window.add(bottom_frame, weight=1)
        
        json_frame = ttk.Labelframe(bottom_frame, text="完整的API返回结果 (JSON)", padding=5)
        json_frame.pack(fill=tk.BOTH, expand=True)

        self.json_text = tk.Text(json_frame, wrap=tk.WORD, state="disabled", height=10)
        scrollbar_json = ttk.Scrollbar(json_frame, command=self.json_text.yview)
        self.json_text.config(yscrollcommand=scrollbar_json.set)

        scrollbar_json.pack(side=tk.RIGHT, fill=tk.Y)
        self.json_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.status_var = tk.StringVar()
        self.status_var.set("准备就绪")
        ttk.Label(main_frame, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    def start_search(self, event=None):
        query = self.search_entry.get().strip()
        if not query:
            messagebox.showwarning("输入错误", "请输入要查询的商品ID。")
            return

        self.search_button.config(state="disabled")
        self.status_var.set(f"正在查询ID: {query}...")
        self.update_text_widget(self.results_text, "正在查询中，请稍候...\n")
        self.update_text_widget(self.json_text, "")

        thread = threading.Thread(target=self.run_search_in_thread, args=(query,))
        thread.daemon = True
        thread.start()

    def run_search_in_thread(self, query):
        # 使用新的函数
        results_data = get_product_by_id(query)
        self.root.after(0, self.display_results, results_data)

    def display_results(self, results_data):
        self.search_button.config(state="normal")
        
        raw_json = results_data.get("raw_json", {"info": "无返回内容"})
        formatted_json = json.dumps(raw_json, indent=2, ensure_ascii=False)
        self.update_text_widget(self.json_text, formatted_json)
        
        if "error" in results_data:
            self.status_var.set("查询失败")
            self.update_text_widget(self.results_text, f"查询失败: {results_data['error']}\n")
            return

        results = results_data.get("success", [])
        if not results:
            self.status_var.set("查询完成，未找到该ID对应的商品。")
            self.update_text_widget(self.results_text, "查询成功，但未返回任何商品信息。请检查ID是否正确，或该商品是否属于可查询范围。\n")
            return
            
        self.status_var.set(f"查询完成，找到 {len(results)} 条结果。")
        
        display_text = ""
        for item in results:
            display_text += f"商品名称: {item['product_name']}\n"
            display_text += f"商品ID: {item['product_id']}\n"
            if item['poi_ids']:
                display_text += f"关联门店ID (POI IDs) - 共 {len(item['poi_ids'])} 家:\n"
                display_text += "\n".join([f"  - {pid}" for pid in item['poi_ids']]) + "\n"
            else:
                display_text += "关联门店ID (POI IDs): 未找到\n"
            display_text += "="*50 + "\n"
        
        self.update_text_widget(self.results_text, display_text)

    def update_text_widget(self, text_widget, content):
        text_widget.config(state="normal")
        text_widget.delete("1.0", tk.END)
        text_widget.insert(tk.END, content)
        text_widget.config(state="disabled")

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
