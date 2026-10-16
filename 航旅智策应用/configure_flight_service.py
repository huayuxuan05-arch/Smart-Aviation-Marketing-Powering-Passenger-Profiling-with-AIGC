"""User-operated local credential dialog; never echoes the API key."""
def main():
    import tkinter as tk
    from tkinter import messagebox
    import flight_provider_settings as config
    root=tk.Tk();root.title('配置航班服务');root.geometry('470x240');root.resizable(False,False)
    tk.Label(root,text='SerpApi 航班查询',font=('Microsoft YaHei',14)).pack(pady=(18,8))
    tk.Label(root,text='将 API Key 粘贴到下方；密钥只加密保存在当前 Windows 用户本机。',wraplength=420).pack(padx=20)
    entry=tk.Entry(root,show='●',width=48);entry.pack(padx=22,pady=16);entry.focus_set()
    def save():
        try:config.save_key(entry.get())
        except ValueError as error:messagebox.showerror('请检查密钥',str(error));return
        entry.delete(0,'end');messagebox.showinfo('配置完成','密钥已加密保存。刷新航班即可使用第三方查询，无需重新注册网站账号。');root.destroy()
    tk.Button(root,text='加密保存并启用',command=save,width=22).pack()
    tk.Label(root,text='初次查询采用本机地区与币种配置，网页统一显示人民币。',wraplength=420).pack(pady=12)
    root.mainloop()


if __name__=='__main__':main()
