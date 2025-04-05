import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkinter.simpledialog import Dialog
import subprocess
import os
import sys
import threading
import queue
import re

class PackagerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.source_file = ""
        self.output_format = ""
        self.output_dir = ""
        self.progress_window = None
        self.log_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        
        # 预编译正则表达式
        self.stage_regex = [
            (re.compile(r'Analyzing\s.+', re.I), '分析依赖', 'analyzing'),
            (re.compile(r'collecting\s.+', re.I), '收集文件', 'collecting'),
            (re.compile(r'generating\s.+', re.I), '生成中间文件', 'generating'),
            (re.compile(r'writing\s.+', re.I), '写入数据', 'writing'),
            (re.compile(r'building\s.+', re.I), '构建可执行文件', 'building'),
            (re.compile(r'completed\s.+', re.I), '完成打包', 'completed'),
            (re.compile(r'(\d+)/(\d+)\s+steps'), '动态进度', 'dynamic')
        ]
        
        # 进度配置
        self.stage_weights = {
            'analyzing': 15,
            'collecting': 25,
            'generating': 15,
            'writing': 20,
            'building': 20,
            'completed': 5
        }
        self.current_progress = 0
        self.active_stages = set()

    def select_source_file(self):
        self.source_file = filedialog.askopenfilename(
            title="选择要打包的代码文件",
            filetypes=[("Python文件", "*.py"), ("所有文件", "*.*")]
        )
        if not self.source_file:
            messagebox.showerror("错误", "必须选择一个代码文件")
            sys.exit(1)

    def select_output_format(self):
        class FormatDialog(Dialog):
            def body(self, master):
                tk.Label(master, text="请选择打包格式：").grid(row=0, pady=5)
                self.format_var = tk.StringVar(value="exe")
                formats = [("EXE 文件", "exe"), ("APK 文件", "apk"), ("其他格式", "other")]
                for i, (text, value) in enumerate(formats, 1):
                    tk.Radiobutton(master, text=text, variable=self.format_var,
                                  value=value).grid(row=i, sticky=tk.W)
                return None

            def apply(self):
                self.result = self.format_var.get()

        dialog = FormatDialog(self.root, "选择打包格式")
        self.output_format = dialog.result

    def select_output_dir(self):
        self.output_dir = filedialog.askdirectory(
            title="选择保存路径",
            mustexist=True
        )
        if not self.output_dir:
            messagebox.showerror("错误", "必须选择保存路径")
            sys.exit(1)

    def create_progress_window(self):
        self.progress_window = tk.Toplevel(self.root)
        self.progress_window.title("打包进度")
        self.progress_window.geometry("600x400")
        
        # 进度条
        self.progress_bar = ttk.Progressbar(
            self.progress_window,
            orient=tk.HORIZONTAL,
            length=500,
            mode='determinate',
            maximum=100
        )
        self.progress_bar.pack(pady=10)
        
        # 阶段标签
        self.stage_label = tk.Label(self.progress_window, text="当前阶段：初始化")
        self.stage_label.pack()
        
        # 日志区域
        self.log_area = scrolledtext.ScrolledText(
            self.progress_window,
            wrap=tk.WORD,
            height=15
        )
        self.log_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        self.log_area.config(state='disabled')

    def update_progress(self):
        # 处理日志
        while not self.log_queue.empty():
            log = self.log_queue.get_nowait()
            self.log_area.config(state='normal')
            self.log_area.insert(tk.END, log + "\n")
            self.log_area.config(state='disabled')
            self.log_area.see(tk.END)
        
        # 处理进度
        while not self.progress_queue.empty():
            progress, stage = self.progress_queue.get_nowait()
            self.current_progress = min(progress, 100)
            self.progress_bar['value'] = self.current_progress
            if stage:
                self.stage_label.config(text=f"当前阶段：{stage}")
        
        if self.packaging_thread.is_alive():
            self.root.after(100, self.update_progress)
        else:
            self.progress_bar['value'] = 100
            self.progress_window.destroy()

    def package(self):
        self.create_progress_window()
        self.packaging_thread = threading.Thread(target=self._package)
        self.packaging_thread.start()
        self.root.after(100, self.update_progress)

    def _package(self):
        if self.output_format == "exe":
            self.package_to_exe()
        elif self.output_format == "apk":
            self.log_queue.put("APK打包需要Android环境支持")
            messagebox.showinfo("提示", "APK打包暂不可用")
        else:
            self.log_queue.put("不支持的打包格式")
            messagebox.showinfo("错误", "选择的格式不支持")

    def package_to_exe(self):
        try:
            # 验证pyinstaller
            subprocess.run(
                ["pyinstaller", "--version"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            self.log_queue.put(f"错误：{str(e)}")
            messagebox.showerror("错误", "请先安装pyinstaller\npip install pyinstaller")
            return

        try:
            process = subprocess.Popen(
                ["pyinstaller", "--onefile",
                 "--distpath", self.output_dir,
                 "--workpath", os.path.join(self.output_dir, "build"),
                 "--specpath", os.path.join(self.output_dir, "spec"),
                 "--clean", self.source_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    self.log_queue.put(output.strip())
                    
                    # 进度计算
                    for regex, display_name, stage_key in self.stage_regex:
                        if regex.search(output):
                            if stage_key == 'dynamic':
                                current = int(regex.search(output).group(1))
                                total = int(regex.search(output).group(2))
                                progress = (current / total) * 20  # 假设属于building阶段
                                self.current_progress += progress
                            elif stage_key not in self.active_stages:
                                self.active_stages.add(stage_key)
                                self.current_progress += self.stage_weights.get(stage_key, 0)
                            
                            self.progress_queue.put((
                                min(self.current_progress, 95),
                                display_name
                            ))
                            break

            if process.returncode == 0:
                messagebox.showinfo("成功", f"文件已生成到：\n{self.output_dir}")
            else:
                messagebox.showerror("失败", f"错误代码：{process.returncode}")

        except Exception as e:
            self.log_queue.put(f"打包异常：{str(e)}")
            messagebox.showerror("错误", str(e))
        finally:
            self.progress_queue.put((100, "完成"))

    def run(self):
        try:
            self.select_source_file()
            self.select_output_format()
            self.select_output_dir()
            self.package()
            self.root.mainloop()
        except Exception as e:
            messagebox.showerror("错误", str(e))
        finally:
            if self.root:
                self.root.destroy()

if __name__ == "__main__":
    app = PackagerApp()
    app.run()