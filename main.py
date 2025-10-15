import tkinter as tk

class MyApp(tk.Tk):
    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        self.title("Video Games")
        self.geometry("1024x600")

root = MyApp()
root.mainloop()