import psycopg # library for database
from sshtunnel import SSHTunnelForwarder
import tkinter as tk # library for graphics

# credentials
username = "YOUR_CS_USERNAME"
password = "YOUR_CS_PASSWORD"
dbName = "YOUR_DB_NAME"


try:
    with SSHTunnelForwarder(('starbug.cs.rit.edu', 22),
                            ssh_username=username,
                            ssh_password=password,
                            remote_bind_address=('127.0.0.1', 5432)) as server:
        server.start()
        print("SSH tunnel established")
        params = {
            'dbname': dbName,
            'user': username,
            'password': password,
            'host': 'localhost',
            'port': server.local_bind_port
        }


        conn = psycopg.connect(**params)
        curs = conn.cursor()
        print("Database connection established")

        #DB work here....

        conn.close()
except:
    print("Connection failed")

class MyApp(tk.Tk):
    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        self.title("Video Games")
        self.geometry("1024x600") # screen resolution

root = MyApp()
root.mainloop()