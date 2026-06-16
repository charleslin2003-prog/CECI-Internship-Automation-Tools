import os
import shutil
import configparser
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import re

# =========================================================
#                    *** 內部參數設定 ***
# =========================================================
FOLDER_SCAN_IMAGES = "初調掃描"
FOLDER_ADJUSTED_PHOTOS = "初調照片"
SUFFIX_NO_PHOTOS = "__無"
EXT_JGW = '.jgw'
EXT_JPG = ['.jpg', '.jpeg']


# =========================================================
#                    *** 核心邏輯區 ***
# =========================================================

def get_classification_name(filename):
    name, _ = os.path.splitext(filename)
    if '-' in name:
        return name.split('-')[0]
    elif len(name) >= 4 and name[:4].isdigit():
        return name[:4]
    return None


def parse_depth_setting(setting_str):
    if "所有" in setting_str: return -1
    if "僅當前" in setting_str: return 0
    match = re.search(r'\d+', setting_str)
    return int(match.group()) if match else -1


def core_process(scan_dirs, jgw_dirs, photo_dirs, target_dir, depth_setting, log_func):
    max_depth = parse_depth_setting(depth_setting)
    log_func(f"設定搜尋深度: {depth_setting}")

    # --- 步驟一：處理掃描檔 ---
    log_func("--- 步驟一：處理掃描檔 (.jpg) 及建立基礎結構 ---")
    processed_maps = set()
    processed_scan_bases = set()

    for root_dir in scan_dirs:
        if not os.path.isdir(root_dir): continue
        log_func(f"  > 搜尋掃描檔: {root_dir}")
        base_d = root_dir.rstrip(os.path.sep).count(os.path.sep)
        for dirpath, dirs, filenames in os.walk(root_dir):
            curr_d = dirpath.rstrip(os.path.sep).count(os.path.sep) - base_d
            if max_depth != -1 and curr_d >= max_depth: del dirs[:]

            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                name_base = os.path.splitext(f)[0]
                c_name = get_classification_name(f)
                if c_name and ext in EXT_JPG and len(name_base.split('-')) == 2:
                    processed_scan_bases.add(name_base)
                    t_map_path = os.path.join(target_dir, c_name)
                    os.makedirs(os.path.join(t_map_path, FOLDER_SCAN_IMAGES), exist_ok=True)
                    processed_maps.add(c_name)
                    shutil.copy2(os.path.join(dirpath, f), os.path.join(t_map_path, FOLDER_SCAN_IMAGES, f))

    # --- 步驟二：處理定位檔 ---
    log_func("\n--- 步驟二/三：歸檔定位檔 (.jgw) (嚴格配對) ---")
    for root_dir in jgw_dirs:
        if not os.path.isdir(root_dir): continue
        base_d = root_dir.rstrip(os.path.sep).count(os.path.sep)
        for dirpath, dirs, filenames in os.walk(root_dir):
            curr_d = dirpath.rstrip(os.path.sep).count(os.path.sep) - base_d
            if max_depth != -1 and curr_d >= max_depth: del dirs[:]
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                name_base = os.path.splitext(f)[0]
                if ext == EXT_JGW and name_base in processed_scan_bases:
                    c_name = get_classification_name(f"{name_base}.jgw")
                    t_path = os.path.join(target_dir, c_name, FOLDER_SCAN_IMAGES, f)
                    shutil.copy2(os.path.join(dirpath, f), t_path)

    # --- 步驟四：處理調繪照片 (多路徑搜尋) ---
    log_func("\n--- 步驟四：處理調繪照片歸檔 (多路徑搜尋) ---")
    for map_name in processed_maps:
        photo_count = 0
        t_map_folder = os.path.join(target_dir, map_name)
        t_photo_folder = os.path.join(t_map_folder, FOLDER_ADJUSTED_PHOTOS)
        os.makedirs(t_photo_folder, exist_ok=True)

        for p_root in photo_dirs:
            # 在每個照片來源中尋找名為 map_name 的資料夾
            # 我們同樣根據深度設定來搜尋這些資料夾
            base_d = p_root.rstrip(os.path.sep).count(os.path.sep)
            for dirpath, dirs, filenames in os.walk(p_root):
                curr_d = dirpath.rstrip(os.path.sep).count(os.path.sep) - base_d
                if max_depth != -1 and curr_d >= max_depth: del dirs[:]

                # 如果當前資料夾名稱剛好是分幅號 (XXXX)
                if os.path.basename(dirpath) == map_name:
                    for f in filenames:
                        if os.path.splitext(f)[1].lower() in EXT_JPG:
                            shutil.copy2(os.path.join(dirpath, f), os.path.join(t_photo_folder, f))
                            photo_count += 1

        if photo_count == 0:
            os.rename(t_map_folder, t_map_folder + SUFFIX_NO_PHOTOS)
            log_func(f"  [無照片] 分幅 {map_name} 已標記為無")

    log_func("\n=== 全部任務完成！ ===")


# =========================================================
#                    *** GUI 介面類別 ***
# =========================================================

class DataOrganizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("自動資料整理工具 Pro (多來源照片版)")
        self.root.geometry("750x750")

        if getattr(sys, 'frozen', False):
            self.app_path = os.path.dirname(sys.executable)
        else:
            self.app_path = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(self.app_path, 'config.ini')

        self.scan_dirs_var = tk.StringVar()
        self.jgw_dirs_var = tk.StringVar()
        self.photo_dirs_var = tk.StringVar()  # 改為多選
        self.target_dir_var = tk.StringVar()
        self.depth_var = tk.StringVar(value="所有子資料夾")

        self.create_widgets()
        self.load_config()

    def create_widgets(self):
        # 深度設定
        f_depth = tk.Frame(self.root);
        f_depth.pack(fill="x", padx=10, pady=5)
        tk.Label(f_depth, text="搜尋深度設定:", font=("Arial", 10)).pack(side="left")
        depth_opts = ["所有子資料夾", "僅當前資料夾"] + [f"{i} 層" for i in range(1, 11)]
        ttk.Combobox(f_depth, textvariable=self.depth_var, values=depth_opts, state="readonly", width=15).pack(
            side="left", padx=5)

        # 1. 掃描檔
        f1 = tk.LabelFrame(self.root, text="1. 掃描檔資料夾 (多選)", padx=10, pady=5);
        f1.pack(fill="x", padx=10, pady=5)
        tk.Entry(f1, textvariable=self.scan_dirs_var, state='readonly').pack(fill="x", side="left", expand=True, padx=5)
        tk.Button(f1, text="添加", command=lambda: self.add_dir(self.scan_dirs_var)).pack(side="left")
        tk.Button(f1, text="清空", command=lambda: self.scan_dirs_var.set("")).pack(side="left")

        # 2. 定位檔
        f2 = tk.LabelFrame(self.root, text="2. 定位檔資料夾 (多選)", padx=10, pady=5);
        f2.pack(fill="x", padx=10, pady=5)
        tk.Entry(f2, textvariable=self.jgw_dirs_var, state='readonly').pack(fill="x", side="left", expand=True, padx=5)
        tk.Button(f2, text="添加", command=lambda: self.add_dir(self.jgw_dirs_var)).pack(side="left")
        tk.Button(f2, text="清空", command=lambda: self.jgw_dirs_var.set("")).pack(side="left")

        # 3. 調繪照片 (修正為多選)
        f3 = tk.LabelFrame(self.root, text="3. 調繪照片來源資料夾 (多選)", padx=10, pady=5);
        f3.pack(fill="x", padx=10, pady=5)
        tk.Entry(f3, textvariable=self.photo_dirs_var, state='readonly').pack(fill="x", side="left", expand=True,
                                                                              padx=5)
        tk.Button(f3, text="添加", command=lambda: self.add_dir(self.photo_dirs_var)).pack(side="left")
        tk.Button(f3, text="清空", command=lambda: self.photo_dirs_var.set("")).pack(side="left")

        # 4. 目標
        f4 = tk.LabelFrame(self.root, text="4. 最終輸出目標資料夾 (單選)", padx=10, pady=5);
        f4.pack(fill="x", padx=10, pady=5)
        tk.Entry(f4, textvariable=self.target_dir_var).pack(fill="x", side="left", expand=True, padx=5)
        tk.Button(f4, text="選擇", command=lambda: self.select_single_dir(self.target_dir_var)).pack(side="left")

        self.btn_run = tk.Button(self.root, text="開始整理", command=self.start_processing, bg="#66cc66",
                                 font=("Arial", 12, "bold"), height=2)
        self.btn_run.pack(fill="x", padx=20, pady=10)

        self.log_text = scrolledtext.ScrolledText(self.root, height=15);
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

    def add_dir(self, var):
        path = filedialog.askdirectory()
        if path:
            curr = var.get()
            var.set(curr + ";" + path if curr else path)

    def select_single_dir(self, var):
        path = filedialog.askdirectory()
        if path: var.set(path)

    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n");
        self.log_text.see(tk.END)

    def save_config(self):
        config = configparser.ConfigParser()
        config['PATHS'] = {
            'SCAN': self.scan_dirs_var.get(), 'JGW': self.jgw_dirs_var.get(),
            'PHOTO': self.photo_dirs_var.get(), 'TARGET': self.target_dir_var.get(),
            'DEPTH': self.depth_var.get()
        }
        with open(self.config_file, 'w', encoding='utf-8') as f: config.write(f)

    def load_config(self):
        if os.path.exists(self.config_file):
            config = configparser.ConfigParser()
            config.read(self.config_file, encoding='utf-8')
            if 'PATHS' in config:
                p = config['PATHS']
                self.scan_dirs_var.set(p.get('SCAN', ''));
                self.jgw_dirs_var.set(p.get('JGW', ''))
                self.photo_dirs_var.set(p.get('PHOTO', ''));
                self.target_dir_var.set(p.get('TARGET', ''))
                self.depth_var.set(p.get('DEPTH', '所有子資料夾'))

    def start_processing(self):
        s = self.scan_dirs_var.get();
        j = self.jgw_dirs_var.get();
        p = self.photo_dirs_var.get();
        t = self.target_dir_var.get()
        if not all([s, j, p, t]):
            messagebox.showwarning("欄位未填", "請確保 1~4 項路徑皆已選擇！");
            return
        self.btn_run.config(state="disabled", text="整理中...");
        self.log_text.delete(1.0, tk.END)
        self.save_config()
        s_list = s.split(';');
        j_list = j.split(';');
        p_list = p.split(';')
        threading.Thread(target=self.run_thread, args=(s_list, j_list, p_list, t, self.depth_var.get()),
                         daemon=True).start()

    def run_thread(self, s, j, p, t, d):
        try:
            core_process(s, j, p, t, d, self.log); messagebox.showinfo("完成", "資料整理完成！")
        except Exception as e:
            self.log(f"[錯誤] {e}"); messagebox.showerror("錯誤", str(e))
        finally:
            self.btn_run.config(state="normal", text="開始整理")


if __name__ == "__main__":
    root = tk.Tk();
    app = DataOrganizerApp(root);
    root.mainloop()